"""Frozen initial schema, shared with migration 0001."""

from sqlalchemy import (
    MetaData,
    Table,
    Column,
    String,
    Integer,
    Float,
    ForeignKey,
    Text,
    BigInteger,
    Boolean,
    Index,
)

metadata = MetaData()


def pk():
    return Column("id", String(64), primary_key=True)


def workspace_fk():
    return Column("workspace", ForeignKey("workspaces.id"), nullable=False, index=True)


def t(name, *columns):
    return Table(name, metadata, *columns)


workspaces = t(
    "workspaces",
    pk(),
    Column("name", String(100), nullable=False),
    Column("day_calls", Integer, nullable=False),
    Column("day_micros", BigInteger),
    Column("retention_days", Integer, nullable=False),
)
keys = t(
    "access_keys",
    pk(),
    workspace_fk(),
    Column("role", String(22), nullable=False),
    Column("label", String(100), nullable=False),
)
connections = t(
    "connections",
    pk(),
    workspace_fk(),
    Column("provider", String(100), nullable=False),
    Column("secret", Text, nullable=False),
    Column("models", Text, nullable=False),
)
models = t(
    "model_versions",
    pk(),
    workspace_fk(),
    Column("connection", ForeignKey("connections.id"), nullable=False),
    Column("name", String(256), nullable=False),
    Column("config", Text, nullable=False),
    Column("created", Float, nullable=False),
)
traces = t(
    "traces",
    pk(),
    workspace_fk(),
    Column("model_id", ForeignKey("model_versions.id"), nullable=False),
    Column("created", Float, nullable=False),
    Column("status", String(30), nullable=False),
    Column("reserved", BigInteger),
    Column("cost", BigInteger),
    Column("elapsed_ms", Float),
    Column("input_tokens", Integer),
    Column("output_tokens", Integer),
    Column("usage_source", String(30)),
    Column("kind", String(30), nullable=False),
    Column("policy", String(64)),
    Column("payload", Text, nullable=False),
)
Index("trace_quota_clock", traces.c.workspace, traces.c.created)
experiments = t(
    "experiments",
    pk(),
    workspace_fk(),
    Column("trace", String(64), nullable=False),
    Column("created", Float, nullable=False),
    Column("status", String(30), nullable=False),
    Column("payload", Text, nullable=False),
)
policies = t(
    "policies",
    pk(),
    workspace_fk(),
    Column("experiment", ForeignKey("experiments.id"), unique=True, nullable=False),
    Column("model_id", ForeignKey("model_versions.id"), nullable=False),
    Column("created", Float, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("payload", Text, nullable=False),
)
events = t(
    "audit_events",
    pk(),
    workspace_fk(),
    Column("created", Float, nullable=False),
    Column("action", String(80), nullable=False),
    Column("resource", String(64), nullable=False),
)
