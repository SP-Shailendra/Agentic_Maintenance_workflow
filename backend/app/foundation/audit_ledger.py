"""L8 append-only in-memory hash-chain audit ledger used by tests and demo mode."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from app.schemas.domain import AuditEvent

GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    """Serialize audit values deterministically."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


class InMemoryAuditLedger:
    """Append-only ledger with an independently verifiable SHA-256 chain."""

    def __init__(self) -> None:
        self._events: list[AuditEvent] = []

    @property
    def events(self) -> tuple[AuditEvent, ...]:
        return tuple(self._events)

    def append(
        self,
        correlation_id: str,
        actor: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        timestamp_utc: datetime | None = None,
    ) -> AuditEvent:
        timestamp = timestamp_utc or datetime.now(UTC)
        previous = self._events[-1].hash if self._events else GENESIS_HASH
        body = {
            "seq": len(self._events) + 1,
            "correlation_id": correlation_id,
            "timestamp_utc": timestamp.isoformat(),
            "actor": actor,
            "event_type": event_type,
            "payload": payload,
        }
        digest = hashlib.sha256(f"{previous}{canonical_json(body)}".encode()).hexdigest()
        event = AuditEvent(**body, prev_hash=previous, hash=digest)
        self._events.append(event)
        return event

    def verify(self) -> tuple[bool, int | None]:
        previous = GENESIS_HASH
        for expected_seq, event in enumerate(self._events, start=1):
            body = {
                "seq": event.seq,
                "correlation_id": event.correlation_id,
                "timestamp_utc": event.timestamp_utc.isoformat(),
                "actor": event.actor,
                "event_type": event.event_type,
                "payload": event.payload,
            }
            expected_hash = hashlib.sha256(f"{previous}{canonical_json(body)}".encode()).hexdigest()
            if (
                event.seq != expected_seq
                or event.prev_hash != previous
                or event.hash != expected_hash
            ):
                return False, expected_seq
            previous = event.hash
        return True, None