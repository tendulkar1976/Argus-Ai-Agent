from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, SecretStr, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class FunctionCall(Strict):
    name: str = Field(min_length=1, max_length=64)
    arguments: str = Field(max_length=32000)


class ToolCall(Strict):
    id: str = Field(min_length=1, max_length=200)
    type: Literal["function"] = "function"
    function: FunctionCall


class FunctionSpec(Strict):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=4000)
    parameters: dict = Field(default_factory=dict)


class ToolSpec(Strict):
    type: Literal["function"] = "function"
    function: FunctionSpec


class Message(Strict):
    role: Literal["system", "developer", "user", "assistant", "tool"]
    content: str | None = Field(default=None, max_length=100000)
    tool_calls: list[ToolCall] | None = Field(default=None, max_length=32)

    @model_validator(mode="after")
    def check_content(self):
        if self.tool_calls and self.role != "assistant":
            raise ValueError("Only assistant messages can include tool calls")
        if self.content is None and not self.tool_calls:
            raise ValueError("Supply message text or assistant tool calls")
        if (self.role == "tool") != bool(self.tool_call_id):
            raise ValueError("Tool responses require a tool_call_id")
        return self

    def measured_text(self):
        import json

        if not self.tool_calls:
            return self.content or ""
        return (self.content or "") + json.dumps(
            [c.model_dump() for c in self.tool_calls], ensure_ascii=False
        )

    tool_call_id: str | None = Field(default=None, max_length=200)


class Evidence(Strict):
    source: str = Field(min_length=1, max_length=160, pattern=r"^[\w .:/#-]+$")
    text: str = Field(min_length=1, max_length=60000)
    aliases: list[str] = Field(default_factory=list, max_length=100)
    critical: bool = False


class Chat(Strict):
    model: str = Field(min_length=1, max_length=256)
    messages: list[Message] = Field(min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int = Field(default=256, ge=1, le=32768)
    stream: bool = False
    tools: list[ToolSpec] = Field(default_factory=list, max_length=32)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)
    parent_trace_id: str | None = Field(default=None, max_length=64)
    policy_id: str | None = Field(default=None, max_length=64)
    cache_ttl_seconds: int = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def cache_mode(self):
        if self.cache_ttl_seconds and (
            self.stream or self.policy_id or self.temperature != 0
        ):
            raise ValueError(
                "Cache requires direct, nonstreaming execution with temperature zero"
            )
        return self


class Connection(Strict):
    provider: str
    secret: SecretStr = Field(min_length=1, max_length=4096)


class ModelSpec(Strict):
    connection: str
    name: str = Field(min_length=1, max_length=256)
    # Operator-verified upper limit for billable input (used for conservative reservation).
    input_limit: int = Field(ge=1, le=10000000)
    output_limit: int = Field(ge=1, le=32768)
    input_rate: float | None = Field(default=None, ge=0, le=10000)
    output_rate: float | None = Field(default=None, ge=0, le=10000)
    cached_rate: float | None = Field(default=None, ge=0, le=10000)
    tokenizer_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    supports_tools: bool = False
    stream_usage: bool = False
    output_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"


class Settings(Strict):
    day_calls: int = Field(ge=1, le=100000)
    day_micros: int | None = Field(default=None, ge=0, le=1000000000000)
    retention_days: int = Field(ge=1, le=365)


class KeySpec(Strict):
    role: Literal["reader", "runner"]
    label: str = Field(min_length=1, max_length=100)


class Check(Strict):
    method: Literal[
        "exact",
        "numeric",
        "json_fields",
        "citations",
        "integer_function",
        "rubric_judge",
        "json_schema",
    ]
    expected: str = Field(min_length=1, max_length=8000)
    tolerance: float = Field(default=0, ge=0, le=1000000)

    @model_validator(mode="after")
    def valid_check(self):
        import json, math

        if not self.expected.strip():
            raise ValueError("Expected answer is empty")
        if self.method == "numeric" and not math.isfinite(float(self.expected)):
            raise ValueError("Expected number must be finite")
        if self.method == "json_schema":
            from argus.evaluators import schema_check

            schema_check(self.expected)
        if self.method == "integer_function":
            from argus.evaluators import parse_suite

            parse_suite(self.expected)
        if self.method == "json_fields":
            obj = json.loads(self.expected)
            if not isinstance(obj, dict) or not obj:
                raise ValueError("Supply a nonempty JSON object")
        return self


class Case(Strict):
    request: Chat
    check: Check


class CostAssumptions(Strict):
    host_usd_per_hour: float = Field(ge=0, le=1e6)
    other_micros_per_request: float = Field(ge=0, le=1e10)
    other_study_micros: float = Field(ge=0, le=1e12)
    rollout_calls: int = Field(ge=1, le=1000000000)


class Experiment(Strict):
    trace_id: str
    strategy: Literal["deduplicate", "select_evidence", "route_model", "combined"]
    objective: Literal["tokens", "inference_cost", "latency", "net_cost"] = "tokens"
    cost_assumptions: CostAssumptions | None = None
    candidate_model: str | None = None
    cases: list[Case] = Field(min_length=1, max_length=20)
    repeats: int = Field(default=1, ge=1, le=5)
    min_accuracy: float = Field(default=1, gt=0, le=1)
    max_latency_ms: int | None = Field(default=None, ge=1)
    approve_calls: int = Field(ge=2, le=400)

    @model_validator(mode="after")
    def controls(self):
        if self.objective == "net_cost" and self.cost_assumptions is None:
            raise ValueError("Net-cost experiments require a complete cost scenario")
        if self.approve_calls != 2 * self.repeats * sum(
            1 + int(c.check.method == "rubric_judge") for c in self.cases
        ):
            raise ValueError("Approval must equal the exact number of planned calls")
        if self.strategy in ("route_model", "combined") and not self.candidate_model:
            raise ValueError("Select a candidate model")
        return self
