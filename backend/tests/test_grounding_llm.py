import asyncio

import pytest
from pydantic import BaseModel

from app.grounding.chunker import load_manual_corpus
from app.grounding.fault_codes import parse_fault_codes
from app.grounding.retriever import ManualRetriever
from app.grounding.validator import validate_diagnosis
from app.llm.groq_client import FakeGroqLLM, GroqClientError, GroqLLM, strictify
from app.schemas.domain import DiagnosisResult


def test_manual_parser_and_asset_class_filtered_keyword_search() -> None:
    chunks = load_manual_corpus()
    assert {chunk.fault_code for chunk in chunks} == {
        "WD-101",
        "WD-102",
        "TG-101",
        "TG-201",
        "IC-101",
        "IC-201",
    }
    results = ManualRetriever(chunks).retrieve("vibration bearing temperature", "wire_draw_motor")
    assert results and all(result.chunk.asset_class == "wire_draw_motor" for result in results)


def test_validator_rejects_bad_code_and_inexact_citation() -> None:
    fake = asyncio.run(FakeGroqLLM().structured(DiagnosisResult, "", "WD-001 vibration"))
    chunks = [
        result.chunk
        for result in ManualRetriever().retrieve("bearing vibration", "wire_draw_motor")
    ]
    validated = validate_diagnosis(fake, chunks, set(parse_fault_codes()))
    assert validated.candidates[0].verified is True
    uncited = fake.model_copy(
        update={
            "candidates": [
                fake.candidates[0].model_copy(
                    update={
                        "citations": [
                            fake.candidates[0]
                            .citations[0]
                            .model_copy(update={"passage": "invented"})
                        ]
                    }
                )
            ]
        }
    )
    rejected = validate_diagnosis(uncited, chunks, set(parse_fault_codes()))
    assert rejected.candidates[0].verified is False
    assert rejected.candidates[0].confidence <= 0.49


def test_strictify_recurses_into_defs_and_requires_every_property() -> None:
    schema = {
        "type": "object",
        "properties": {"outer": {"$ref": "#/$defs/Inner"}},
        "$defs": {"Inner": {"type": "object", "properties": {"value": {"type": "string"}}}},
    }
    strict = strictify(schema)
    assert strict["required"] == ["outer"]
    assert strict["additionalProperties"] is False
    assert strict["$defs"]["Inner"]["required"] == ["value"]
    assert strict["$defs"]["Inner"]["additionalProperties"] is False


def test_fake_llm_returns_schema_validated_diagnosis() -> None:
    result = asyncio.run(FakeGroqLLM().structured(DiagnosisResult, "system", "IC-001 alarm"))
    assert result.candidates[0].failure_mode == "IC-101"
    assert result.safety_flag is True


def test_groq_client_retries_then_uses_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GroqLLM()
    monkeypatch.setattr(client.settings, "groq_max_retries", 2)
    calls = 0

    def request(model, system, user, schema_name, schema, strict):
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("mock unavailable")
        return (
            '{"candidates":[{"failure_mode":"WD-101","confidence":0.8,"rationale":"ok",'
            '"citations":[],"verified":false}],"selected_index":0,"safety_flag":false}',
            12,
            8,
        )

    monkeypatch.setattr(client, "_request", request)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr("app.llm.groq_client.asyncio.sleep", no_sleep)
    result = asyncio.run(client.structured(DiagnosisResult, "system", "user"))
    assert result.candidates[0].failure_mode == "WD-101"
    assert client.stats[-1].fallback is True


class TinySchema(BaseModel):
    value: str


def test_groq_client_raises_typed_error_after_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = GroqLLM()
    monkeypatch.setattr(client.settings, "groq_max_retries", 1)
    monkeypatch.setattr(
        client, "_request", lambda *args: (_ for _ in ()).throw(ConnectionError("offline"))
    )
    with pytest.raises(GroqClientError):
        asyncio.run(client.structured(TinySchema, "system", "user"))
