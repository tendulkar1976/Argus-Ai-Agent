"use client";
import { useState } from "react";
import { ArrowRight, KeyRound, Play, Plus, X } from "lucide-react";
import { Workspace, Api, Act, Evidence, Policy } from "./types";

export function Field({
  name,
  children,
}: {
  name: string;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>{name}</span>
      {children}
    </label>
  );
}
export function EvidenceEditor({
  value,
  change,
}: {
  value: Evidence[];
  change: (v: Evidence[]) => void;
}) {
  function edit(i: number, p: Partial<Evidence>) {
    change(value.map((e, n) => (n === i ? { ...e, ...p } : e)));
  }
  return (
    <div className="sources">
      <div className="row">
        <h3>Source passages</h3>
        <button
          type="button"
          className="quiet"
          onClick={() => change([...value, { source: "", text: "" }])}
        >
          <Plus size={15} />
          Add passage
        </button>
      </div>
      {value.map((e, i) => (
        <div className="source" key={i}>
          <div className="row">
            <Field name="Source ID">
              <input
                required
                value={e.source}
                onChange={(v) => edit(i, { source: v.target.value })}
              />
            </Field>
            <button
              aria-label={"Remove passage " + (i + 1)}
              type="button"
              className="icon"
              onClick={() => change(value.filter((_, j) => i !== j))}
            >
              <X size={16} />
            </button>
          </div>
          <Field name="Passage">
            <textarea
              required
              value={e.text}
              onChange={(v) => edit(i, { text: v.target.value })}
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={!!e.critical}
              onChange={(v) => edit(i, { critical: v.target.checked })}
            />
            Always retain this passage
          </label>
        </div>
      ))}
    </div>
  );
}
type FormProps = {
  ws: Workspace;
  api: Api;
  act: Act;
  refresh: () => Promise<void>;
};
export function Settings({ ws, api, act, refresh }: FormProps) {
  const [secret, setSecret] = useState(""),
    [cid, setCid] = useState(ws.connections[0]?.id || ""),
    [newKey, setNewKey] = useState(""),
    [audit, setAudit] = useState<{ action: string; created: number }[]>([]);
  const conn = ws.connections.find((c) => c.id === cid) || ws.connections[0];
  if (ws.role !== "owner")
    return (
      <section className="card">
        Workspace owners manage credentials, budgets and access.
      </section>
    );
  return (
    <>
      <section className="card">
        <KeyRound className="symbol" />
        <h2>Connect a provider</h2>
        <p>
          Test a credential and discover the models available to your account.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            act(async () => {
              const c = await api<{ id: string }>("/api/connections", "POST", {
                provider: f.get("provider"),
                secret,
              });
              setSecret("");
              setCid(c.id);
              await refresh();
            });
          }}
        >
          <Field name="Provider">
            <select name="provider">
              {ws.catalog.map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </Field>
          <Field name="Provider API key">
            <input
              type="password"
              required
              autoComplete="off"
              value={secret}
              onChange={(e) => setSecret(e.target.value)}
            />
          </Field>
          <button>
            Test connection <ArrowRight size={16} />
          </button>
        </form>
      </section>
      {conn && (
        <section className="card">
          <h2>Configure a model</h2>
          <p>
            Each save creates a version. Enter provider limits and optional
            prices per million tokens.
          </p>
          <form
            key={conn.id}
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              const num = (k: string) => (f.get(k) ? Number(f.get(k)) : null);
              act(async () => {
                await api("/api/models", "POST", {
                  connection: conn.id,
                  name: f.get("name"),
                  input_limit: num("il"),
                  output_limit: num("ol"),
                  input_rate: num("ir"),
                  output_rate: num("or"),
                  cached_rate: num("cr"),
                  output_parameter: f.get("parameter"),
                  stream_usage: f.has("stream"),
                  supports_tools: f.has("tools"),
                  tokenizer_sha256: f.get("tokenizer") || null,
                });
                await refresh();
              });
            }}
          >
            <div className="grid">
              <Field name="Verified connection">
                <select
                  value={conn.id}
                  onChange={(e) => setCid(e.target.value)}
                >
                  {ws.connections.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.provider} · {c.id.slice(0, 6)}
                    </option>
                  ))}
                </select>
              </Field>
              <Field name="Provider model">
                <select name="name">
                  {conn.models.map((x) => (
                    <option key={x}>{x}</option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="grid">
              {[
                ["il", "Maximum input tokens"],
                ["ol", "Maximum output tokens"],
              ].map(([k, n]) => (
                <Field key={k} name={n}>
                  <input name={k} type="number" min="1" required />
                </Field>
              ))}
            </div>
            <div className="grid">
              {[
                ["ir", "Input USD / 1M"],
                ["or", "Output USD / 1M"],
                ["cr", "Cached input USD / 1M"],
              ].map(([k, n]) => (
                <Field key={k} name={n}>
                  <input
                    type="number"
                    min="0"
                    step="any"
                    name={k}
                    placeholder="Unknown"
                  />
                </Field>
              ))}
            </div>
            <Field name="Token attribution">
              <select name="tokenizer">
                <option value="">Byte-length estimate</option>
                {ws.tokenizers.map((t) => (
                  <option key={t} value={t}>
                    Tokenizer · {t.slice(0, 12)}
                  </option>
                ))}
              </select>
            </Field>
            <Field name="Output limit parameter">
              <select name="parameter">
                <option>max_tokens</option>
                <option>max_completion_tokens</option>
              </select>
            </Field>
            <label className="check">
              <input type="checkbox" name="stream" />
              Provider supports streaming usage reports
            </label>
            <label className="check">
              <input type="checkbox" name="tools" />
              Provider supports function tools
            </label>
            <button>Save model version</button>
          </form>
        </section>
      )}
      <section className="card">
        <h2>Workspace limits</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            act(async () => {
              await api("/api/settings", "PUT", {
                day_calls: Number(f.get("calls")),
                day_micros: f.get("usd")
                  ? Math.round(Number(f.get("usd")) * 1e6)
                  : null,
                retention_days: Number(f.get("days")),
              });
              await refresh();
            });
          }}
        >
          <div className="grid">
            <Field name="Calls per UTC day">
              <input
                required
                type="number"
                name="calls"
                min="1"
                defaultValue={ws.day_calls}
              />
            </Field>
            <Field name="Daily USD ceiling">
              <input
                type="number"
                step="0.000001"
                min="0"
                name="usd"
                defaultValue={ws.day_micros == null ? "" : ws.day_micros / 1e6}
                placeholder="Optional"
              />
            </Field>
            <Field name="Retention (days)">
              <input
                required
                type="number"
                name="days"
                min="1"
                max="365"
                defaultValue={ws.retention_days}
              />
            </Field>
          </div>
          <button>Save limits</button>
        </form>
      </section>
      <section className="card">
        <h2>API access</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            const f = new FormData(e.currentTarget);
            act(async () =>
              setNewKey(
                (
                  await api<{ key: string }>("/api/keys", "POST", {
                    label: f.get("label"),
                    role: f.get("role"),
                  })
                ).key,
              ),
            );
          }}
        >
          <Field name="Key label">
            <input name="label" required />
          </Field>
          <Field name="Access level">
            <select name="role">
              <option>reader</option>
              <option>runner</option>
            </select>
          </Field>
          <button>Issue workspace key</button>
          {newKey && (
            <Field name="Copy this key before leaving">
              <input
                readOnly
                value={newKey}
                onFocus={(e) => e.target.select()}
              />
            </Field>
          )}
        </form>
      </section>
      <section className="card">
        <div className="row">
          <h2>Audit log</h2>
          <button
            className="quiet"
            onClick={() => act(async () => setAudit(await api("/api/audit")))}
          >
            Load events
          </button>
        </div>
        {audit.map((a, i) => (
          <div className="record" key={i}>
            <code>{a.action}</code>
            <small>{new Date(a.created * 1000).toLocaleString()}</small>
          </div>
        ))}
      </section>
    </>
  );
}
function compactTask(task: string) {
  // Preserve quoted material, code, and structured multiline input verbatim.
  if (/[`"“”{}<>\n]/.test(task)) return task;
  const sentences = task.split(/(?<=[.!?])\s+/);
  return sentences
    .filter((sentence, i) => i === 0 || sentence !== sentences[i - 1])
    .join(" ")
    .replace(/^(?:(?:could you please|can you please|please)\s+)(?=(?:explain|list|summarize|describe|compare|write|give|translate|answer)\b)/i, "")
    .replace(/^I would like you to\s+(?=\w)/i, "");
}

export function Composer({
  ws,
  api,
  act,
  onTrace,
  policies,
}: {
  ws: Workspace;
  api: Api;
  act: Act;
  onTrace: (id: string) => Promise<void>;
  policies: Policy[];
}) {
  const [model, setModel] = useState(ws.models[0]?.id || ""),
    [ev, setEv] = useState<Evidence[]>([]);
  const [task, setTask] = useState("");
  const [useShorter, setUseShorter] = useState(true);
  const shorter = compactTask(task);
  const estimate = (value: string) => Math.ceil(new TextEncoder().encode(value).length / 4);
  const selected = ws.models.find((m) => m.id === model);
  return (
    <form
      className="card"
      onSubmit={(e) => {
        e.preventDefault();
        const f = new FormData(e.currentTarget);
        act(async () => {
          const r = await api<{ trace: string }>(
            "/v1/chat/completions",
            "POST",
            {
              model,
              messages: [{ role: "user", content: useShorter ? shorter : task }],
              evidence: ev,
              max_tokens: Number(f.get("max")),
              policy_id: f.get("policy") || null,
            },
          );
          await onTrace(r.trace);
        });
      }}
    >
      <h2>Run a request</h2>
      <div className="grid">
        <Field name="Model version">
          <select value={model} onChange={(e) => setModel(e.target.value)}>
            {ws.models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name} · {m.id.slice(0, 6)}
              </option>
            ))}
          </select>
        </Field>
        <Field name="Maximum output tokens">
          <input
            key={model}
            required
            name="max"
            type="number"
            min="1"
            max={selected?.config.output_limit}
            defaultValue={Math.min(256, selected?.config.output_limit || 256)}
          />
        </Field>
      </div>
      <Field name="Task or question">
        <textarea
          value={task}
          onChange={(e) => setTask(e.target.value)}
          name="prompt"
          rows={4}
          required
          placeholder="What should the model do?"
        />
      </Field>
      {task.trim() && (shorter !== task ? (
        <section aria-label="Prompt optimization">
          <strong>Shortened prompt</strong>
          <p>{shorter}</p>
          <p>Estimated task tokens: {estimate(task)} → {estimate(shorter)} ({estimate(task) - estimate(shorter)} saved if used).</p>
          <label><input type="checkbox" checked={useShorter} onChange={(e) => setUseShorter(e.target.checked)} /> Send shortened prompt</label>
        </section>
      ) : <p>No automatic shortening found.</p>)}
      <EvidenceEditor value={ev} change={setEv} />
      <Field name="Execution policy">
        <select name="policy">
          <option value="">Original request</option>
          {policies
            .filter((p) => p.active && p.model_id === model)
            .map((p) => (
              <option key={p.id} value={p.id}>
                Approved · {p.id.slice(0, 8)}
              </option>
            ))}
        </select>
      </Field>
      <button>
        <Play size={15} />
        Run 1 provider call
      </button>
    </form>
  );
}
