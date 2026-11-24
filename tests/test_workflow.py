from concurrent.futures import ThreadPoolExecutor
from argus.db import create_workspace


def chat(m, prompt):
    return {
        "model": m,
        "messages": [{"role": "user", "content": prompt}],
        "evidence": [
            {"source": "A", "text": "The result is 7."},
            {"source": "B", "text": "The result is 7."},
        ],
        "temperature": 0,
    }


def study(c, m, expected="7"):
    original = c.post("/v1/chat/completions", json=chat(m, "Discovery")).headers[
        "x-argus-trace"
    ]
    inv = c.post("/api/investigations/" + original).json()
    assert "deduplicate" in inv["strategies"]
    spec = {
        "trace_id": original,
        "strategy": "deduplicate",
        "cases": [
            {
                "request": chat(m, "Held out"),
                "check": {"method": "exact", "expected": expected},
            }
        ],
        "approve_calls": 2,
    }
    result = c.post("/api/experiments", json=spec)
    assert result.status_code == 200, result.text
    return original, spec, result.json()


def test_end_to_end(api):
    c, m, calls = api
    _, _, r = study(c, m)
    assert (
        r["status"] == "eligible"
        and r["inference_saving_micros"] > 0
        and r["net_system_savings"] is None
    )
    p = c.post("/api/experiments/" + r["id"] + "/approve").json()["id"]
    result = c.post(
        "/v1/chat/completions", json={**chat(m, "Held out"), "policy_id": p}
    )
    assert result.status_code == 200, result.text
    detail = c.get("/api/traces/" + result.headers["x-argus-trace"]).json()
    assert detail["monitor"]["quality"]["passed"] and len(calls) == 4
    c.post("/api/policies/" + p + "/rollback")
    assert (
        c.post(
            "/v1/chat/completions", json={**chat(m, "Held out"), "policy_id": p}
        ).status_code
        == 409
    )


def test_quality_gate_and_leakage(api):
    c, m, calls = api
    source, spec, r = study(c, m, "wrong")
    assert r["status"] == "rejected"
    assert c.post("/api/experiments/" + r["id"] + "/approve").status_code == 409
    spec["cases"][0]["request"] = chat(m, "Discovery")
    assert c.post("/api/experiments", json=spec).status_code == 422
    assert len(calls) == 3


def test_stream_and_failure(api):
    c, m, _ = api
    r = c.post("/v1/chat/completions", json={**chat(m, "ask"), "stream": True})
    assert "[DONE]" in r.text
    t = c.get("/api/traces/" + r.headers["x-argus-trace"]).json()
    assert t["usage_source"] == "provider" and t["output"] == "7"
    r = c.post("/v1/chat/completions", json={**chat(m, "FAIL"), "evidence": []})
    assert r.status_code == 502
    assert (
        c.get("/api/traces/" + r.headers["x-argus-trace"]).json()["status"] == "error"
    )


def test_access_and_isolation(api):
    c, m, _ = api
    source = c.post("/v1/chat/completions", json=chat(m, "ask")).headers[
        "x-argus-trace"
    ]
    reader = c.post("/api/keys", json={"label": "read", "role": "reader"}).json()["key"]
    assert (
        c.post(
            "/v1/chat/completions",
            json=chat(m, "ask"),
            headers={"Authorization": "Bearer " + reader},
        ).status_code
        == 403
    )
    other = {"Authorization": "Bearer " + create_workspace("Other")}
    assert c.get("/api/traces/" + source, headers=other).status_code == 404
    assert c.get("/api/traces", headers=other).json() == []
    assert (
        c.post("/v1/chat/completions", json=chat(m, "ask"), headers=other).status_code
        == 404
    )
    assert c.get("/api/workspace", headers={"Authorization": ""}).status_code == 401
    assert "fixture-secret" not in c.get("/api/workspace").text


def test_budget_concurrent(api):
    c, m, calls = api
    c.put("/api/settings", json={"day_calls": 1, "day_micros": 0, "retention_days": 7})
    assert c.post("/v1/chat/completions", json=chat(m, "ask")).status_code == 402
    c.put(
        "/api/settings", json={"day_calls": 1, "day_micros": None, "retention_days": 7}
    )
    with ThreadPoolExecutor(4) as pool:
        codes = list(
            pool.map(
                lambda _: (
                    c.post("/v1/chat/completions", json=chat(m, "ask")).status_code
                ),
                range(4),
            )
        )
    assert sorted(codes) == [200, 429, 429, 429] and len(calls) == 1


def test_input_limits(api):
    c, m, _ = api
    assert (
        c.post(
            "/api/connections", json={"provider": "unlisted", "secret": "private"}
        ).status_code
        == 422
    )
    assert c.post("/v1/chat/completions", content=b"a" * 512001).status_code == 413
    assert (
        c.post(
            "/v1/chat/completions", json={**chat(m, "ask"), "max_tokens": 501}
        ).status_code
        == 422
    )


def test_exact_cache_and_accounting(api):
    c, m, calls = api
    q = {**chat(m, "Repeat"), "cache_ttl_seconds": 60, "temperature": 0}
    r1 = c.post("/v1/chat/completions", json=q)
    r2 = c.post("/v1/chat/completions", json=q)
    assert len(calls) == 1 and r2.json()["usage"]["total_tokens"] == 0
    trace = c.get("/api/traces/" + r2.headers["x-argus-trace"]).json()
    assert trace["cache_origin"] == r1.headers["x-argus-trace"] and trace["cost"] == 0
    assert (
        c.post("/v1/chat/completions", json={**q, "temperature": 1}).status_code == 422
    )


def test_workflow_scoping(api):
    c, m, calls = api
    q = chat(m, "Follow up")
    root = c.post("/v1/chat/completions", json=q).headers["x-argus-trace"]
    response = c.post("/v1/chat/completions", json={**q, "parent_trace_id": root})
    detail = c.get("/api/traces/" + response.headers["x-argus-trace"]).json()
    assert detail["workflow"]["id"] == root and len(detail["workflow"]["spans"]) == 2
    assert (
        c.post(
            "/v1/chat/completions", json={**q, "parent_trace_id": "missing"}
        ).status_code
        == 404
    )
    assert len(calls) == 2


def test_net_cost_accounts_for_experiment(api):
    c, m, _ = api
    _, spec, _ = study(c, m)
    spec.update(
        objective="net_cost",
        cost_assumptions={
            "host_usd_per_hour": 0,
            "other_micros_per_request": 0,
            "other_study_micros": 0,
            "rollout_calls": 1,
        },
    )
    r = c.post("/api/experiments", json=spec).json()
    assert (
        r["inference_saving_micros"] > 0
        and r["rollout_cost_scenario"]["projected_net_saving_micros"] < 0
    )
    assert r["status"] == "rejected"


def test_calibrated_judge_and_overhead(api):
    c, m, calls = api
    spec = {
        "model": m,
        "rubric": "Value must be seven.",
        "min_agreement": 1,
        "approve_calls": 4,
        "examples": [
            {
                "task": f"Calibration {i}",
                "answer": "7" if i % 2 else "8",
                "passes": bool(i % 2),
            }
            for i in range(4)
        ],
    }
    j = c.post("/api/judges", json=spec).json()
    assert j["status"] == "qualified" and j["agreement"] == 1
    source = c.post("/v1/chat/completions", json=chat(m, "Discovery")).headers[
        "x-argus-trace"
    ]
    study_spec = {
        "trace_id": source,
        "strategy": "deduplicate",
        "cases": [
            {
                "request": chat(m, "Unseen rubric task"),
                "check": {"method": "rubric_judge", "expected": j["id"]},
            }
        ],
        "approve_calls": 4,
    }
    r = c.post("/api/experiments", json=study_spec).json()
    assert r["status"] == "eligible" and r["overhead"]["external_evaluation_calls"] == 2
    assert r["overhead"]["evaluation_inference_micros"] > 0 and len(calls) == 9
    study_spec["cases"][0]["request"] = chat(m, "Calibration 1")
    assert c.post("/api/experiments", json=study_spec).status_code == 422


def test_tool_transcript_requires_configured_capability(api):
    c, m, calls = api
    workspace = c.get("/api/workspace").json()
    original = workspace["models"][0]
    chat_body = {
        "model": m,
        "messages": [
            {"role": "user", "content": "Review the result"},
            {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call_a",
                        "type": "function",
                        "function": {"name": "lookup", "arguments": "{}"},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "call_a", "content": "Seven records."},
        ],
    }
    assert c.post("/v1/chat/completions", json=chat_body).status_code == 422
    model = c.post(
        "/api/models",
        json={
            **original["config"],
            "name": original["name"],
            "connection": original["connection"],
            "supports_tools": True,
        },
    ).json()["id"]
    response = c.post("/v1/chat/completions", json={**chat_body, "model": model})
    assert response.status_code == 200
    detail = c.get("/api/traces/" + response.headers["x-argus-trace"]).json()
    assert calls[-1]["messages"][1]["tool_calls"][0]["id"] == "call_a"
    assert detail["analysis"]["blocks"][-1]["category"] == "Tool output"


def test_experiment_approval_survives_concurrent_retries(api):
    c, model, calls = api
    _, spec, _ = study(c, model)
    start_count = len(calls)
    headers = {"Idempotency-Key": "concurrent-approval"}

    def retry(_):
        return c.post("/api/experiments", json=spec, headers=headers)

    with ThreadPoolExecutor(4) as pool:
        responses = list(pool.map(retry, range(4)))
    assert all(r.status_code == 200 for r in responses)
    assert len({r.json()["id"] for r in responses}) == 1
    assert len(calls) == start_count + spec["approve_calls"]
    finished = retry(None).json()
    assert finished["status"] == "eligible" and finished["pairs"]
    conflict = c.post(
        "/api/experiments", json={**spec, "min_accuracy": 0.5}, headers=headers
    )
    assert conflict.status_code == 409 and len(calls) == start_count + 2


def test_rejected_experiment_is_replayed_without_new_calls(api):
    c, model, calls = api
    _, spec, _ = study(c, model, "wrong")
    headers = {"Idempotency-Key": "review-rejected"}
    first = c.post("/api/experiments", json=spec, headers=headers).json()
    call_count = len(calls)
    assert first["status"] == "rejected"
    assert c.post("/api/experiments", json=spec, headers=headers).json() == first
    assert len(calls) == call_count
