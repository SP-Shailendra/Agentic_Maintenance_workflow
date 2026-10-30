"""Groq structured-output client with strict schemas, retries, and a deterministic fake."""

import asyncio
import json
import time
from dataclasses import dataclass
from typing import Any, TypeVar

from pydantic import BaseModel

from app.config import get_settings
from app.schemas.domain import DiagnosisResult

T = TypeVar("T", bound=BaseModel)


class GroqClientError(RuntimeError):
    """Raised after primary retries and fast-model fallback both fail."""


@dataclass(frozen=True)
class LLMCallStat:
    model: str
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    ok: bool
    error: str | None = None
    fallback: bool = False


def strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Return a recursively Groq-strict JSON schema, including definitions."""
    result = json.loads(json.dumps(schema))

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("type") == "object" or "properties" in value:
                properties = value.get("properties", {})
                value["additionalProperties"] = False
                value["required"] = list(properties)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(result)
    return result


class GroqLLM:
    def __init__(self, *, client: Any | None = None) -> None:
        self.settings = get_settings()
        self._client = client
        self.stats: list[LLMCallStat] = []

    async def structured(
        self,
        schema_model: type[T],
        system: str,
        user: str,
        model: str | None = None,
        strict: bool = True,
    ) -> T:
        primary = model or self.settings.groq_model_primary
        schema = (
            strictify(schema_model.model_json_schema())
            if strict
            else schema_model.model_json_schema()
        )
        for attempt in range(self.settings.groq_max_retries):
            try:
                return await self._call(schema_model, system, user, primary, schema, strict, False)
            except Exception as error:
                if attempt + 1 == self.settings.groq_max_retries:
                    break
                await asyncio.sleep(self._retry_delay(error, attempt))
        fast = self.settings.groq_model_fast
        try:
            return await self._call(schema_model, system, user, fast, schema, False, True)
        except Exception as error:
            raise GroqClientError(
                f"Groq primary and fast-model fallback failed: {error}"
            ) from error

    async def _call(
        self,
        schema_model: type[T],
        system: str,
        user: str,
        model: str,
        schema: dict[str, Any],
        strict: bool,
        fallback: bool,
    ) -> T:
        started = time.perf_counter()
        try:
            content, prompt_tokens, completion_tokens = await asyncio.to_thread(
                self._request, model, system, user, schema_model.__name__, schema, strict
            )
            parsed = schema_model.model_validate_json(content)
            self.stats.append(
                LLMCallStat(
                    model,
                    time.perf_counter() - started,
                    prompt_tokens,
                    completion_tokens,
                    True,
                    fallback=fallback,
                )
            )
            return parsed
        except Exception as error:
            self.stats.append(
                LLMCallStat(
                    model,
                    time.perf_counter() - started,
                    0,
                    0,
                    False,
                    str(error),
                    fallback,
                )
            )
            raise

    def _request(
        self,
        model: str,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        strict: bool,
    ) -> tuple[str, int, int]:
        if self._client is None:
            try:
                from groq import Groq
            except ImportError as error:
                raise GroqClientError("Install the groq package to use LLM_MODE=groq") from error
            self._client = Groq(
                api_key=self.settings.groq_api_key,
                timeout=self.settings.groq_timeout_seconds,
            )
        response_format = (
            {
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": strict, "schema": schema},
            }
            if strict
            else {"type": "json_object"}
        )
        result = self._client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format=response_format,
            temperature=0.1,
        )
        usage = result.usage
        return result.choices[0].message.content, usage.prompt_tokens, usage.completion_tokens

    @staticmethod
    def _retry_delay(error: Exception, attempt: int) -> float:
        response = getattr(error, "response", None)
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            try:
                return max(0.0, float(retry_after))
            except (TypeError, ValueError):
                pass
        return min(8.0, 0.5 * (2**attempt))


class FakeGroqLLM:
    """Schema-compatible deterministic diagnosis fixture for tests and offline demos."""

    def __init__(self) -> None:
        self.stats: list[LLMCallStat] = []

    async def structured(
        self,
        schema_model: type[T],
        system: str,
        user: str,
        model: str | None = None,
        strict: bool = True,
    ) -> T:
        del system, strict
        selected_model = model or "fake-deterministic"
        if schema_model is not DiagnosisResult:
            raise TypeError(f"FakeGroqLLM has no deterministic fixture for {schema_model.__name__}")
        asset_class = (
            "imaging_chiller"
            if "IC-" in user
            else "testcell_generator"
            if "TG-" in user
            else "wire_draw_motor"
        )
        code = {
            "imaging_chiller": (
                "IC-101",
                "imaging_chiller.md",
                "IC-101 | Chiller refrigerant pressure loss",
            ),
            "testcell_generator": (
                "TG-101",
                "testcell_generator.md",
                "TG-101 | Generator bearing wear",
            ),
            "wire_draw_motor": ("WD-101", "wire_draw_motor.md", "WD-101 | Bearing wear"),
        }[asset_class]
        content = {
            "imaging_chiller": (
                "Symptoms: falling refrigerant pressure with " "rising coolant temperature."
            ),
            "testcell_generator": (
                "Symptoms: vibration RMS increases with bearing temperature "
                "during a stable load."
            ),
            "wire_draw_motor": (
                "Symptoms: rising vibration RMS with a gradual bearing-housing "
                "temperature increase."
            ),
        }[asset_class]
        result = schema_model.model_validate(
            {
                "candidates": [
                    {
                        "failure_mode": code[0],
                        "confidence": 0.82,
                        "rationale": "The sensor trend matches the manual symptoms.",
                        "citations": [
                            {
                                "document": code[1],
                                "section": code[2],
                                "passage": content,
                            }
                        ],
                        "verified": False,
                    }
                ],
                "selected_index": 0,
                "safety_flag": asset_class == "imaging_chiller",
            }
        )
        self.stats.append(LLMCallStat(selected_model, 0.0, 0, 0, True))
        return result
