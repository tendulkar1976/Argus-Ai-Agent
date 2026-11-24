"""Run a bounded, explicitly approved live study against an existing workspace."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import httpx


def run(url, key, model, dataset, repeats, approve_calls, output, max_tokens):
    raw = Path(dataset).read_bytes()
    spec = json.loads(raw)
    calls = 1 + 2 * repeats * len(spec["cases"])
    if approve_calls != calls:
        raise SystemExit(
            f"Study requires explicit approval for {calls} provider calls including discovery"
        )
    with httpx.Client(
        base_url=url,
        headers={"Authorization": "Bearer " + key},
        timeout=None,
        trust_env=False,
    ) as client:

        def post(path, payload=None):
            res = client.post(path, json=payload)
            res.raise_for_status()
            return res

        def chat(case):
            return {
                "model": model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": case["task"]}],
                "evidence": case.get("evidence", []),
            }

        trace = post("/v1/chat/completions", chat(spec["discovery"])).headers[
            "X-Argus-Trace"
        ]
        investigation = post("/api/investigations/" + trace).json()
        if spec["strategy"] not in investigation["strategies"]:
            raise SystemExit("Investigation did not identify the requested candidate")
        cases = [{"request": chat(c), "check": c["check"]} for c in spec["cases"]]
        report = post(
            "/api/experiments",
            {
                "trace_id": trace,
                "strategy": spec["strategy"],
                "objective": spec["objective"],
                "candidate_model": spec.get("candidate_model"),
                "cases": cases,
                "repeats": repeats,
                "min_accuracy": 1,
                "approve_calls": calls - 1,
            },
        ).json()
        report.update(
            dataset_sha256=hashlib.sha256(raw).hexdigest(),
            dataset_name=spec["name"],
            workloads=[c["workload"] for c in spec["cases"]],
            discovery_trace=trace,
        )
        details = {}
        for pair in report["pairs"]:
            for arm in ("baseline", "candidate"):
                if arm in pair:
                    id = pair[arm]["trace"]
                    res = client.get("/api/traces/" + id)
                    res.raise_for_status()
                    t = res.json()
                    details[id] = {
                        k: t[k]
                        for k in (
                            "requested_model",
                            "provider_metadata",
                            "raw_usage",
                            "sent_messages",
                            "output",
                            "elapsed_ms",
                        )
                    }
        report["replay"] = details
        Path(output).write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default="http://127.0.0.1:8000")
    p.add_argument("--model", required=True, help="Workspace model version ID")
    p.add_argument("--dataset", default="benchmarks/starter.json")
    p.add_argument("--repeats", type=int, default=1)
    p.add_argument("--approve-calls", type=int, required=True)
    p.add_argument("--max-tokens", type=int, default=64)
    p.add_argument("--output", required=True)
    a = p.parse_args()
    result = run(
        a.url,
        os.environ["ARGUS_WORKSPACE_KEY"],
        a.model,
        a.dataset,
        a.repeats,
        a.approve_calls,
        a.output,
        a.max_tokens,
    )
    print(result["status"], result["id"])
