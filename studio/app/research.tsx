"use client";
import { useState } from "react";
import {
  ArrowRight,
  Check,
  Download,
  FlaskConical,
  ScanLine,
} from "lucide-react";
import {
  Api,
  Act,
  Chat,
  Detail,
  Evidence,
  Investigation,
  Report,
  Workspace,
  label,
  money,
} from "./types";
import { EvidenceEditor, Field } from "./forms";

export function TraceView({
  trace,
  investigate,
  canRun,
}: {
  trace: Detail;
  investigate: () => void;
  canRun: boolean;
}) {
  const maximum = Math.max(
    1,
    ...trace.analysis.blocks.map((b) => b.estimated_tokens),
  );
  return (
    <>
      <section className="card">
        <div className="row">
          <div>
            <small>TRACE {trace.id.slice(0, 8).toUpperCase()}</small>
            <h2>Context composition</h2>
          </div>
          <ScanLine className="symbol" />
        </div>
        <p>{trace.analysis.attribution}</p>
        {trace.analysis.blocks.map((b, i) => (
          <details key={i} className="block">
            <summary>
              <span>
                {b.source || b.category}
                {b.repeated && <em>Repeated</em>}
              </span>
              <i>
                <b
                  style={{ width: (100 * b.estimated_tokens) / maximum + "%" }}
                />
              </i>
              <code>~{b.estimated_tokens}</code>
            </summary>
            <pre>{b.text}</pre>
          </details>
        ))}
      </section>
      <section className="card">
        <h2>Optimization opportunities</h2>
        {trace.analysis.findings.length ? (
          trace.analysis.findings.map((f, i) => (
            <article key={i}>
              <strong>{f.category}</strong>
              <p>
                {f.evidence} {f.risk}
              </p>
              <small>
                {f.confidence} · ~{f.impact_tokens} tokens in this block
              </small>
            </article>
          ))
        ) : (
          <p>No repeated messages or low-overlap source passages detected.</p>
        )}
        {canRun && trace.status === "ok" && (
          <button onClick={investigate}>
            Investigate trace <ArrowRight size={15} />
          </button>
        )}
      </section>
      {trace.workflow && trace.workflow.spans.length > 1 && (
        <section className="card">
          <h2>Workflow timeline</h2>
          {trace.workflow.spans.map((s) => (
            <div className="record" key={s.trace_id}>
              <code>{s.trace_id.slice(0, 8)}</code>
              <span>
                {s.status} · {s.elapsed_ms ?? "—"} ms
              </span>
            </div>
          ))}
          {trace.workflow.findings.map((f, i) => (
            <p key={i}>
              {f.evidence} {f.risk}
            </p>
          ))}
        </section>
      )}
      <section className="card">
        <h2>Execution</h2>
        <div className="chips">
          <code>{trace.status}</code>
          <code>{trace.usage_source || "Unknown"} usage</code>
          <code>
            {trace.input_tokens ?? "—"} in / {trace.output_tokens ?? "—"} out
          </code>
          <code>{money(trace.cost)} estimated</code>
        </div>
        <details>
          <summary>Request sent to provider</summary>
          <pre>{JSON.stringify(trace.sent_messages, null, 2)}</pre>
        </details>
        <h3>Output</h3>
        <pre>{trace.output || "No text recorded."}</pre>
        {trace.monitor != null && (
          <>
            <h3>Policy monitoring</h3>
            <pre>{JSON.stringify(trace.monitor, null, 2)}</pre>
          </>
        )}
      </section>
    </>
  );
}

type Entry = {
  task: string;
  expected: string;
  method: string;
  evidence: Evidence[];
};
const empty = (): Entry => ({
  task: "",
  expected: "",
  method: "exact",
  evidence: [],
});
export function ExperimentForm({
  inv,
  trace,
  ws,
  api,
  act,
  finish,
}: {
  inv: Investigation;
  trace: Detail;
  ws: Workspace;
  api: Api;
  act: Act;
  finish: (r: Report) => Promise<void>;
}) {
  const [cases, setCases] = useState<Entry[]>([empty()]),
    [strategy, setStrategy] = useState(inv.strategies[0] || ""),
    [repeats, setRepeats] = useState(1),
    [objective, setObjective] = useState("tokens");
  function edit(i: number, patch: Partial<Entry>) {
    setCases(cases.map((v, j) => (i === j ? { ...v, ...patch } : v)));
  }
  const callCount =
    2 *
    repeats *
    cases.reduce((n, c) => n + (c.method === "rubric_judge" ? 2 : 1), 0);
  if (!strategy)
    return (
      <div className="card">
        <h2>No candidate identified</h2>
        <p>
          Inspect another trace, supply separate evidence passages, or configure
          a lower-priced model.
        </p>
      </div>
    );
  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        act(async () => {
          const items = cases.map((c) => ({
            request: {
              ...trace.request,
              policy_id: null,
              parent_trace_id: null,
              cache_ttl_seconds: 0,
              stream: false,
              messages: [
                ...trace.request.messages.filter(
                  (m) => m.role === "system" || m.role === "developer",
                ),
                { role: "user", content: c.task },
              ],
              evidence: c.evidence,
            },
            check: { method: c.method, expected: c.expected },
          }));
          const config = {
            trace_id: trace.id,
            strategy,
            objective,
            cost_assumptions:
              objective === "net_cost"
                ? {
                    host_usd_per_hour: Number(f.get("host")),
                    other_micros_per_request: Number(f.get("other")),
                    other_study_micros: Number(f.get("study")),
                    rollout_calls: Number(f.get("volume")),
                  }
                : null,
            candidate_model: f.get("candidate") || null,
            repeats,
            cases: items,
            min_accuracy: Number(f.get("accuracy")) / 100,
            max_latency_ms: f.get("latency") ? Number(f.get("latency")) : null,
            approve_calls: callCount,
          };
          // Keep only a digest and nonce in this tab. A lost response can be retried
          // after reload without storing prompts, reference answers or credentials.
          const hash = await crypto.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(JSON.stringify(config)),
          );
          const slot =
            "argus.pending." +
            Array.from(new Uint8Array(hash), (b) =>
              b.toString(16).padStart(2, "0"),
            ).join("");
          const key = sessionStorage.getItem(slot) || crypto.randomUUID();
          sessionStorage.setItem(slot, key);
          const result = await api<Report>(
            "/api/experiments",
            "POST",
            config,
            key,
          );
          await finish(result);
          if (result.status !== "running") sessionStorage.removeItem(slot);
        });
      }}
    >
      <h2>Configure a paired experiment</h2>
      <p>
        Each trial runs the original and candidate on the same held-out case.
        Use cases separate from the discovery trace.
      </p>
      <div className="grid">
        <Field name="Optimization objective">
          <select
            value={objective}
            onChange={(e) => setObjective(e.target.value)}
          >
            <option value="tokens">Reduce total tokens</option>
            <option value="inference_cost">
              Reduce estimated inference cost
            </option>
            <option value="latency">Reduce P95 latency</option>
            <option value="net_cost">Reduce projected rollout cost</option>
          </select>
        </Field>
        <Field name="Candidate strategy">
          <select
            value={strategy}
            onChange={(e) => setStrategy(e.target.value)}
          >
            {inv.strategies.map((s) => (
              <option key={s} value={s}>
                {label(s)}
              </option>
            ))}
          </select>
        </Field>
        {["combined", "route_model"].includes(strategy) && (
          <Field name="Candidate model">
            <select name="candidate">
              {inv.alternative_models.map((id) => (
                <option value={id} key={id}>
                  {ws.models.find((m) => m.id === id)?.name} · {id.slice(0, 6)}
                </option>
              ))}
            </select>
          </Field>
        )}
      </div>
      {objective === "net_cost" && (
        <article>
          <h3>Rollout cost assumptions</h3>
          <p>
            Allocate host occupancy including provider wait. Include storage,
            analysis and any remaining expense in the extra costs. Enter zero
            explicitly where appropriate.
          </p>
          <div className="grid">
            {[
              ["host", "Host USD per hour"],
              ["other", "Extra microdollars per request"],
              ["study", "Other study microdollars"],
              ["volume", "Expected rollout calls"],
            ].map(([k, n]) => (
              <Field key={k} name={n}>
                <input
                  name={k}
                  type="number"
                  required
                  min={k === "volume" ? 1 : 0}
                  step={k === "volume" ? 1 : "any"}
                />
              </Field>
            ))}
          </div>
        </article>
      )}
      {cases.map((c, i) => (
        <article key={i}>
          <div className="row">
            <h3>Held-out case {i + 1}</h3>
            {cases.length > 1 && (
              <button
                type="button"
                className="quiet"
                onClick={() => setCases(cases.filter((_, j) => j !== i))}
              >
                Remove
              </button>
            )}
          </div>
          <Field name="Held-out task">
            <textarea
              required
              value={c.task}
              onChange={(e) => edit(i, { task: e.target.value })}
            />
          </Field>
          <EvidenceEditor
            value={c.evidence}
            change={(v) => edit(i, { evidence: v })}
          />
          <div className="grid">
            <Field name="Quality check">
              <select
                value={c.method}
                onChange={(e) => edit(i, { method: e.target.value })}
              >
                <option value="exact">Exact answer</option>
                <option value="numeric">Numeric answer</option>
                <option value="json_fields">Expected JSON fields</option>
                <option value="json_schema">JSON schema validity</option>
                <option value="rubric_judge">Calibrated judge version</option>
                <option value="citations">Required source IDs</option>
                <option value="integer_function">
                  Integer function test vectors
                </option>
              </select>
            </Field>
            <Field
              name={
                c.method === "rubric_judge"
                  ? "Qualified judge version ID"
                  : "Expected answer or fields"
              }
            >
              <input
                required
                value={c.expected}
                onChange={(e) => edit(i, { expected: e.target.value })}
              />
            </Field>
          </div>
        </article>
      ))}
      <button
        type="button"
        className="quiet"
        onClick={() => setCases([...cases, empty()])}
        disabled={cases.length >= 20}
      >
        Add evaluation case
      </button>
      <div className="grid">
        <Field name="Trials per case">
          <input
            type="number"
            min="1"
            max="5"
            required
            value={repeats}
            onChange={(e) => setRepeats(Number(e.target.value))}
          />
        </Field>
        <Field name="Required pass rate (%)">
          <input
            name="accuracy"
            type="number"
            defaultValue={100}
            required
            min="1"
            max="100"
          />
        </Field>
        <Field name="P95 limit (ms)">
          <input name="latency" type="number" min="1" placeholder="Optional" />
        </Field>
      </div>
      <button>
        <FlaskConical size={16} />
        Approve and run {callCount} calls
      </button>
    </form>
  );
}

export function Results({
  r,
  api,
  act,
  ws,
  reload,
}: {
  r: Report;
  api: Api;
  act: Act;
  ws: Workspace;
  reload: () => Promise<void>;
}) {
  const [replay, setReplay] = useState<Detail[]>([]);
  function download() {
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(r, null, 2)], { type: "application/json" }),
    );
    const a = document.createElement("a");
    a.href = url;
    a.download = "argus-experiment-" + r.id + ".json";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return (
    <section className="card">
      <div className="row">
        <h2>Experiment results</h2>
        <button className="quiet" onClick={download}>
          <Download size={15} />
          Export JSON
        </button>
      </div>
      <p>
        {label(r.strategy)} · {r.status}
      </p>
      {r.error && <p role="alert">{r.error}</p>}
      {r.baseline && r.candidate && (
        <>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th>Metric</th>
                  <th>Baseline</th>
                  <th>Candidate</th>
                </tr>
              </thead>
              <tbody>
                {[
                  [
                    "Pass rate",
                    100 * r.baseline.accuracy + "%",
                    100 * r.candidate.accuracy + "%",
                  ],
                  [
                    "Input tokens",
                    r.baseline.input_tokens,
                    r.candidate.input_tokens,
                  ],
                  [
                    "Output tokens",
                    r.baseline.output_tokens,
                    r.candidate.output_tokens,
                  ],
                  [
                    "Usage source",
                    r.baseline.usage_source,
                    r.candidate.usage_source,
                  ],
                  [
                    "Estimated inference cost",
                    money(r.baseline.inference_micros),
                    money(r.candidate.inference_micros),
                  ],
                  ["P95 latency (ms)", r.baseline.p95_ms, r.candidate.p95_ms],
                ].map((row) => (
                  <tr key={row[0]}>
                    {row.map((x, i) => (
                      <td key={i}>{x}</td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p>
            Timed local transformation and checks took{" "}
            {r.overhead.local_processing_ms.toFixed(2)} ms.{" "}
            {r.rollout_cost_scenario
              ? "Projected savings include study amortization."
              : "Infrastructure cost and net system savings are unknown."}
          </p>
          {r.rollout_cost_scenario && (
            <p>
              <strong>
                Projected net saving{" "}
                {money(r.rollout_cost_scenario.projected_net_saving_micros)}
              </strong>{" "}
              over {r.rollout_cost_scenario.rollout_calls} calls, including{" "}
              {money(r.rollout_cost_scenario.discovery_and_study_micros)} for
              discovery and testing.
            </p>
          )}
          <div className="chips">
            {Object.entries(r.conditions || {}).map(([k, v]) => (
              <code key={k}>
                {label(k)} · {v ? "pass" : "fail"}
              </code>
            ))}
          </div>
        </>
      )}
      {r.pairs.map((p, i) => (
        <div className="record" key={i}>
          <span>
            Case {p.case} · trial {p.repeat}
          </span>
          {p.baseline && p.candidate && (
            <button
              className="quiet"
              onClick={() =>
                act(async () =>
                  setReplay(
                    await Promise.all(
                      [p.baseline!, p.candidate!].map((s) =>
                        api<Detail>("/api/traces/" + s.trace),
                      ),
                    ),
                  ),
                )
              }
            >
              Replay pair
            </button>
          )}
        </div>
      ))}
      {replay.length > 0 && (
        <div className="grid replay">
          {replay.map((t, i) => (
            <article key={t.id}>
              <h3>{i ? "Candidate" : "Baseline"}</h3>
              <pre>{JSON.stringify(t.sent_messages, null, 2)}</pre>
              <h3>Output</h3>
              <pre>{t.output}</pre>
            </article>
          ))}
        </div>
      )}
      {r.status === "eligible" && ws.role === "owner" && (
        <button
          onClick={() =>
            act(async () => {
              await api("/api/experiments/" + r.id + "/approve", "POST");
              await reload();
            })
          }
        >
          <Check size={16} />
          Approve policy version
        </button>
      )}
    </section>
  );
}
