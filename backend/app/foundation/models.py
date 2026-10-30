"""L8 PostgreSQL schema for telemetry, workflow state, approvals, and audit."""

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    Vector = None

metadata = MetaData()
json_type = JSONB().with_variant(JSON(), "sqlite")

assets = Table(
    "assets",
    metadata,
    Column("asset_id", String(64), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("asset_class", String(80), nullable=False),
    Column("criticality_tier", Integer, nullable=False),
    Column("safety_critical", Boolean, nullable=True),
    Column("install_date", DateTime(timezone=True), nullable=False),
    Column("site_id", String(80), nullable=False),
    Column("location", String(255), nullable=False),
    Column("days_since_last_pm", Integer, nullable=False, server_default="0"),
)

sensor_readings = Table(
    "sensor_readings",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("asset_id", String(64), ForeignKey("assets.asset_id"), nullable=False),
    Column("sensor_id", String(100), nullable=False),
    Column("scenario_id", String(128)),
    Column("measurement_type", String(40), nullable=False),
    Column("ts", DateTime(timezone=True), nullable=False),
    Column("value", Float, nullable=False),
    Column("unit", String(24), nullable=False),
    Column("quality_flag", String(16), nullable=False),
)
Index(
    "ix_sensor_readings_asset_measurement_ts",
    sensor_readings.c.asset_id,
    sensor_readings.c.measurement_type,
    sensor_readings.c.ts,
)

anomalies = Table(
    "anomalies",
    metadata,
    Column("anomaly_id", String(64), primary_key=True),
    Column("asset_id", String(64), ForeignKey("assets.asset_id"), nullable=False),
    Column("detected_at", DateTime(timezone=True), nullable=False),
    Column("anomaly_type", String(80), nullable=False),
    Column("severity", Float, nullable=False),
    Column("shadow", Boolean, nullable=False),
    Column("evidence", json_type, nullable=False),
)

suppressed_alerts = Table(
    "suppressed_alerts",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("asset_id", String(64), nullable=False),
    Column("anomaly_type", String(80), nullable=False),
    Column("reason", String(80), nullable=False),
    Column("suppressed_at", DateTime(timezone=True), nullable=False),
)

workflows = Table(
    "workflows",
    metadata,
    Column("correlation_id", String(128), primary_key=True),
    Column("status", String(40), nullable=False),
    Column("asset_id", String(64), ForeignKey("assets.asset_id"), nullable=False),
    Column("anomaly_id", String(64), ForeignKey("anomalies.anomaly_id"), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

workflow_steps = Table(
    "workflow_steps",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("correlation_id", String(128), ForeignKey("workflows.correlation_id"), nullable=False),
    Column("node", String(80), nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("ended_at", DateTime(timezone=True), nullable=False),
    Column("model", String(120)),
    Column("prompt_tokens", Integer, nullable=False, server_default="0"),
    Column("completion_tokens", Integer, nullable=False, server_default="0"),
    Column("retries", Integer, nullable=False, server_default="0"),
    Column("outcome", String(40), nullable=False),
    Column("payload", json_type, nullable=False),
)

diagnoses = Table(
    "diagnoses",
    metadata,
    Column("correlation_id", String(128), ForeignKey("workflows.correlation_id"), primary_key=True),
    Column("result", json_type, nullable=False),
)

work_orders = Table(
    "work_orders",
    metadata,
    Column("correlation_id", String(128), ForeignKey("workflows.correlation_id"), primary_key=True),
    Column("work_order_id", String(80)),
    Column("status", String(40), nullable=False),
    Column("payload", json_type, nullable=False),
    Column("cmms_queued", Boolean, nullable=False, server_default="false"),
)

parts_inventory = Table(
    "parts_inventory",
    metadata,
    Column("part_number", String(80), primary_key=True),
    Column("description", String(255), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("unit_cost", Float, nullable=False),
    Column("storeroom", String(80), nullable=False),
    Column("lead_days", Integer, nullable=False, server_default="0"),
)

part_reservations = Table(
    "part_reservations",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("correlation_id", String(128), ForeignKey("workflows.correlation_id"), nullable=False),
    Column("part_number", String(80), ForeignKey("parts_inventory.part_number"), nullable=False),
    Column("quantity", Integer, nullable=False),
    Column("reserved_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

technicians = Table(
    "technicians",
    metadata,
    Column("technician_id", String(80), primary_key=True),
    Column("name", String(255), nullable=False),
    Column("skills", json_type, nullable=False),
    Column("available", Boolean, nullable=False),
)

approval_requests = Table(
    "approval_requests",
    metadata,
    Column("correlation_id", String(128), ForeignKey("workflows.correlation_id"), primary_key=True),
    Column("status", String(40), nullable=False),
    Column("required_approver_tier", Integer, nullable=False),
    Column("sla_deadline", DateTime(timezone=True), nullable=False),
    Column("package", json_type, nullable=False),
)

approval_decisions = Table(
    "approval_decisions",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("correlation_id", String(128), ForeignKey("workflows.correlation_id"), nullable=False),
    Column("decision", String(32), nullable=False),
    Column("approver", String(128), nullable=False),
    Column("reason", Text),
    Column("modifications", json_type, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("seq", Integer, primary_key=True),
    Column("correlation_id", String(128), nullable=False),
    Column("timestamp_utc", DateTime(timezone=True), nullable=False),
    Column("actor", String(128), nullable=False),
    Column("event_type", String(80), nullable=False),
    Column("payload", json_type, nullable=False),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False, unique=True),
)

feedback = Table(
    "feedback",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("correlation_id", String(128), nullable=False),
    Column("failure_mode", String(80)),
    Column("asset_class", String(80)),
    Column("feedback_type", String(40), nullable=False),
    Column("payload", json_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

llm_calls = Table(
    "llm_calls",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("correlation_id", String(128)),
    Column("model", String(120), nullable=False),
    Column("latency_seconds", Float, nullable=False),
    Column("prompt_tokens", Integer, nullable=False),
    Column("completion_tokens", Integer, nullable=False),
    Column("ok", Boolean, nullable=False),
    Column("error", Text),
    Column("fallback", Boolean, nullable=False),
)

manual_chunks = Table(
    "manual_chunks",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("asset_class", String(80), nullable=False),
    Column("fault_code", String(32), nullable=False),
    Column("document", String(255), nullable=False),
    Column("section", String(255), nullable=False),
    Column("content", Text, nullable=False),
    Column("embedding", Vector(384) if Vector else JSON),
)

kpi_snapshots = Table(
    "kpi_snapshots",
    metadata,
    Column("id", Integer, primary_key=True),
    Column("captured_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("metrics", json_type, nullable=False),
)