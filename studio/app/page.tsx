"use client";
import { useState, useEffect } from "react";
import {
  Activity,
  ArrowRight,
  ArrowUpRight,
  Box,
  ChevronRight,
  CircleCheck,
  Command,
  FlaskConical,
  Layers3,
  LayoutDashboard,
  LogOut,
  Moon,
  Orbit,
  PanelLeft,
  Play,
  Radar,
  ScanLine,
  Settings2,
  ShieldCheck,
  Sun,
  Workflow,
} from "lucide-react";
import {
  Workspace,
  Trace,
  Detail,
  Overview,
  Api,
  Investigation,
  Study,
  Report,
  Policy,
  when,
  label,
  money,
} from "./types";
import { Settings, Field, Composer } from "./forms";
import { ExperimentForm, Results, TraceView } from "./research";

const nav = [
  ["Overview", LayoutDashboard],
  ["Token Intelligence", ScanLine],
  ["Argus Intelligence", Orbit],
  ["Experiment Studio", FlaskConical],
  ["Integrations & Settings", Settings2],
] as const;
type Page = (typeof nav)[number][0];
const desc: Record<Page, string> = {
  Overview: "LLM execution, usage and quality across your workspace.",
  "Token Intelligence":
    "Inspect the context, output and accounting behind each request.",
  "Argus Intelligence": "Investigate a trace and choose a strategy to test.",
  "Experiment Studio":
    "Compare paired executions and manage approved policies.",
  "Integrations & Settings":
    "Manage provider access, model versions and workspace limits.",
};
function Brand() {
  return (
    <div className="brand">
      <Radar size={33} strokeWidth={1.6} />
      <strong>
        Argus<span>-AI</span>
      </strong>
    </div>
  );
}
export default function Studio() {
  const [token, setToken] = useState(""),
    [ws, setWs] = useState<Workspace | null>(null),
    [dark, setDark] = useState(false),
    [page, setPage] = useState<Page>("Overview"),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [menu, setMenu] = useState(false);
  const [ov, setOv] = useState<Overview | null>(null),
    [traces, setTraces] = useState<Trace[]>([]),
    [trace, setTrace] = useState<Detail | null>(null),
    [inv, setInv] = useState<Investigation | null>(null),
    [studies, setStudies] = useState<Study[]>([]),
    [report, setReport] = useState<Report | null>(null),
    [policies, setPolicies] = useState<Policy[]>([]),
    [search, setSearch] = useState(""),
    [compose, setCompose] = useState(false);
  const api: Api = async <T,>(
    path: string,
    method = "GET",
    body?: unknown,
    idempotencyKey?: string,
  ): Promise<T> => {
    const res = await fetch(path, {
      method,
      headers: {
        Authorization: "Bearer " + token,
        "Content-Type": "application/json",
        ...(idempotencyKey ? { "Idempotency-Key": idempotencyKey } : {}),
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      cache: "no-store",
    });
    const data = await res.json();
    if (!res.ok)
      throw Error(
        typeof data.detail === "string"
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail
                .map(
                  (v: { loc: string[]; msg: string }) =>
                    v.loc.join(".") + " " + v.msg,
                )
                .join("; ")
            : "Request failed",
      );
    return path === "/v1/chat/completions"
      ? ({ trace: res.headers.get("x-argus-trace") } as T)
      : data;
  };
  async function refresh() {
    const [w, o, t, s, p] = await Promise.all([
      api<Workspace>("/api/workspace"),
      api<Overview>("/api/overview"),
      api<Trace[]>("/api/traces"),
      api<Study[]>("/api/experiments"),
      api<Policy[]>("/api/policies"),
    ]);
    setWs(w);
    setOv(o);
    setTraces(t);
    setStudies(s);
    setPolicies(p);
  }
  async function act(fn: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    setDark(localStorage.getItem("argus-theme") === "dark");
  }, []);
  function theme() {
    setDark(!dark);
    localStorage.setItem("argus-theme", dark ? "light" : "dark");
  }
  function go(p: Page) {
    setPage(p);
    setMenu(false);
    setError("");
  }
  async function selectTrace(id: string) {
    const t = await api<Detail>("/api/traces/" + id);
    setTrace(t);
    setInv(null);
    setCompose(false);
    await refresh();
    go("Token Intelligence");
  }
  async function investigate(id: string) {
    setInv(await api<Investigation>("/api/investigations/" + id, "POST"));
    setTrace(await api<Detail>("/api/traces/" + id));
    go("Argus Intelligence");
  }
  function run() {
    go("Token Intelligence");
    setTrace(null);
    setCompose(true);
  }
  const canRun = ws?.role !== "reader";
  const themeButton = (
    <button className="icon" aria-label="Switch color theme" onClick={theme}>
      {dark ? <Sun size={17} /> : <Moon size={17} />}
    </button>
  );
  const notice = error ? (
    <div className="notice" role="alert">
      {error}
    </div>
  ) : null;
  const pending = busy ? (
    <div className="progress" role="status">
      Working…
    </div>
  ) : null;
  if (!ws)
    return (
      <main className="entrance" data-dark={dark}>
        <header>
          <Brand />
          {themeButton}
        </header>
        <div className="entry">
          <section className="entry-copy">
            <div className="identity">
              <span /> ARGUS-AI STUDIO
            </div>
            <h1>
              Understand every
              <br />
              <i>model call.</i>
            </h1>
            <p>
              Trace a request, identify redundant context, and test whether a
              change preserves answer quality.
            </p>
            <div className="journey">
              {[
                [ScanLine, "Inspect traces"],
                [FlaskConical, "Test candidates"],
                [ShieldCheck, "Approve policies"],
              ].map(([Icon, name]) => {
                const I = Icon as typeof Radar;
                return (
                  <div key={String(name)}>
                    <I size={19} />
                    {String(name)}
                  </div>
                );
              })}
            </div>
          </section>
          <section className="login card">
            <div className="tile">
              <Command size={25} />
            </div>
            <h2>Open your workspace</h2>
            <p>Enter the workspace key issued by your Argus Engine.</p>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                act(refresh);
              }}
            >
              <Field name="Workspace key">
                <input
                  autoComplete="off"
                  type="password"
                  required
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="argus_…"
                />
              </Field>
              <button disabled={busy}>
                Open Studio <ArrowRight size={17} />
              </button>
            </form>
            {notice}
            {pending}
            <details>
              <summary>Create a local workspace</summary>
              <p>
                In the project terminal, run this command and copy the owner
                key.
              </p>
              <pre>python -m argus.cli workspace "My workspace"</pre>
            </details>
          </section>
        </div>
        <footer>
          Argus Engine <span>Trace-aware LLM optimization</span>
        </footer>
      </main>
    );
  const empty = (title: string, body: string) => (
    <div className="empty">
      <Box size={25} />
      <h3>{title}</h3>
      <p>{body}</p>
    </div>
  );
  function traceTable(items: Trace[]) {
    return items.length ? (
      <div className="scroll">
        <table>
          <thead>
            <tr>
              <th>Trace</th>
              <th>Model</th>
              <th>Status</th>
              <th>Tokens</th>
              <th>Latency</th>
            </tr>
          </thead>
          <tbody>
            {items.map((t) => (
              <tr key={t.id}>
                <td>
                  <button
                    className="link"
                    onClick={() => act(() => selectTrace(t.id))}
                  >
                    {t.id.slice(0, 8)} <ArrowUpRight size={13} />
                  </button>
                  <small>{when(t.created)}</small>
                </td>
                <td>
                  {ws!.models.find((m) => m.id === t.model_id)?.name || "—"}
                </td>
                <td>
                  <span className="status">{t.status}</span>
                </td>
                <td>
                  {t.input_tokens == null
                    ? "—"
                    : t.input_tokens + (t.output_tokens || 0)}
                </td>
                <td>
                  {t.elapsed_ms == null
                    ? "—"
                    : Math.round(t.elapsed_ms) + " ms"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    ) : (
      empty(
        "No matching traces",
        "Execute a request to record its input, output and timing.",
      )
    );
  }
  return (
    <div className="shell" data-dark={dark}>
      <aside className={menu ? "open" : ""}>
        <Brand />
        <div className="workspace">
          <div className="tile">
            <Layers3 size={19} />
          </div>
          <div>
            <strong>{ws.name}</strong>
            <small>{ws.role} workspace</small>
          </div>
        </div>
        <nav>
          {nav.map(([n, I]) => (
            <button
              key={n}
              className={n === page ? "selected" : ""}
              onClick={() => go(n)}
            >
              <I size={18} />
              {n}
            </button>
          ))}
        </nav>
        <div className="aside-foot">
          <button className="quiet" onClick={() => location.reload()}>
            <LogOut size={16} />
            Close workspace
          </button>
        </div>
      </aside>
      <main>
        <header className="bar">
          <div>
            <button
              className="icon mobile"
              onClick={() => setMenu(!menu)}
              aria-label="Toggle navigation"
            >
              <PanelLeft size={17} />
            </button>
            Studio <ChevronRight size={13} /> <b>{page}</b>
          </div>
          {themeButton}
        </header>
        <div className="content">
          <div className="heading">
            <div className="identity">
              <span /> WORKSPACE
            </div>
            <h1>{page}</h1>
            <p>{desc[page]}</p>
          </div>
          {notice}
          {pending}
          <fieldset disabled={busy}>
            {page === "Overview" && (
              <>
                {!ov?.requests ? (
                  <section className="card setup">
                    <div className="tile">
                      <Workflow size={24} />
                    </div>
                    <h2>Start your first trace</h2>
                    <p>
                      Connect a provider, choose a model, then send a task
                      through Argus Engine.
                    </p>
                    <div className="steps">
                      {[
                        "Verify provider",
                        "Configure model",
                        "Run first request",
                      ].map((s, i) => (
                        <div key={s}>
                          {(i === 0 && ws.connections.length > 0) ||
                          (i === 1 && ws.models.length > 0) ? (
                            <CircleCheck size={18} />
                          ) : (
                            <b>{i + 1}</b>
                          )}
                          {s}
                        </div>
                      ))}
                    </div>
                    {canRun && (
                      <button
                        onClick={() =>
                          ws.models.length
                            ? run()
                            : go("Integrations & Settings")
                        }
                      >
                        {ws.models.length
                          ? "Run first request"
                          : "Configure provider"}
                        <ArrowRight size={16} />
                      </button>
                    )}
                  </section>
                ) : (
                  <>
                    <div className="metrics">
                      {[
                        ["Requests", ov.requests],
                        [
                          "Input / output tokens",
                          ov.input_tokens + " / " + ov.output_tokens,
                        ],
                        [
                          "P95 latency",
                          ov.p95_ms == null
                            ? "—"
                            : Math.round(ov.p95_ms) + " ms",
                        ],
                        [
                          "Estimated inference cost",
                          ov.priced_requests
                            ? money(ov.estimated_micros)
                            : "Unknown",
                        ],
                      ].map(([n, v]) => (
                        <div key={n}>
                          <small>{n}</small>
                          <strong>{v}</strong>
                        </div>
                      ))}
                    </div>
                    <p>
                      {ov.priced_requests} of {ov.requests} calls priced ·{" "}
                      {ov.estimated_usage_requests} calls with estimated tokens
                      · {ov.errors} errors
                    </p>
                    <section className="card">
                      <div className="row">
                        <h2>Recent executions</h2>
                        {canRun && (
                          <button onClick={run}>
                            <Play size={15} />
                            Run request
                          </button>
                        )}
                      </div>
                      {traceTable(traces.slice(0, 8))}
                    </section>
                    <section className="card">
                      <h2>Model utilization</h2>
                      {Object.entries(ov.model_utilization).map(([id, n]) => (
                        <div className="record" key={id}>
                          <span>
                            {ws.models.find((m) => m.id === id)?.name}
                          </span>
                          <code>{n} calls</code>
                        </div>
                      ))}
                      <p>
                        {studies.length} experiments ·{" "}
                        {studies.filter((s) => s.status === "eligible").length}{" "}
                        eligible for approval
                      </p>
                    </section>
                  </>
                )}
              </>
            )}
            {page === "Token Intelligence" && (
              <>
                {canRun && ws.models.length > 0 && (
                  <div className="actions">
                    <button
                      className="quiet"
                      onClick={() => {
                        setCompose(!compose);
                        setTrace(null);
                      }}
                    >
                      {compose ? "Show trace history" : "New request"}
                    </button>
                  </div>
                )}
                {compose && ws.models.length > 0 ? (
                  <Composer
                    ws={ws}
                    api={api}
                    act={act}
                    onTrace={selectTrace}
                    policies={policies}
                  />
                ) : (
                  <>
                    {trace && (
                      <TraceView
                        trace={trace}
                        canRun={canRun}
                        investigate={() => act(() => investigate(trace.id))}
                      />
                    )}
                    <section className="card">
                      <div className="row">
                        <h2>Execution traces</h2>
                        <input
                          className="search"
                          placeholder="Search trace or model"
                          aria-label="Search traces"
                          value={search}
                          onChange={(e) => setSearch(e.target.value)}
                        />
                      </div>
                      {traceTable(
                        traces.filter((t) =>
                          (
                            t.id +
                            " " +
                            t.status +
                            " " +
                            ws.models.find((m) => m.id === t.model_id)?.name
                          )
                            .toLowerCase()
                            .includes(search.toLowerCase()),
                        ),
                      )}
                    </section>
                  </>
                )}
              </>
            )}
            {page === "Argus Intelligence" && (
              <>
                {!inv ? (
                  <section className="card">
                    <h2>Select a discovery trace</h2>
                    <p>
                      Investigate a successful request to find testable context
                      or routing changes.
                    </p>
                    {canRun &&
                      traces
                        .filter((t) => t.status === "ok")
                        .map((t) => (
                          <button
                            className="record choice"
                            key={t.id}
                            onClick={() => act(() => investigate(t.id))}
                          >
                            {t.id.slice(0, 8)} · {when(t.created)}
                            <ArrowRight size={15} />
                          </button>
                        ))}
                    {!traces.length &&
                      empty(
                        "Waiting for a trace",
                        "Run a request from Token Intelligence.",
                      )}
                  </section>
                ) : (
                  <>
                    <section className="card">
                      <h2>Investigation activity</h2>
                      {inv.activity.map((a) => (
                        <div className="record" key={a.tool}>
                          <span>{label(a.tool)}</span>
                          <code>
                            {typeof a.result === "string"
                              ? a.result
                              : JSON.stringify(a.result)}
                          </code>
                        </div>
                      ))}
                    </section>
                    {trace && (
                      <ExperimentForm
                        key={inv.trace_id}
                        inv={inv}
                        trace={trace}
                        ws={ws}
                        api={api}
                        act={act}
                        finish={async (r) => {
                          setReport(r);
                          await refresh();
                          go("Experiment Studio");
                        }}
                      />
                    )}
                  </>
                )}
              </>
            )}
            {page === "Experiment Studio" && (
              <>
                {report && (
                  <Results
                    key={report.id}
                    r={report}
                    api={api}
                    act={act}
                    ws={ws}
                    reload={refresh}
                  />
                )}
                <section className="card">
                  <div className="row">
                    <h2>Experiment history</h2>
                    {canRun && (
                      <button
                        className="quiet"
                        onClick={() => go("Argus Intelligence")}
                      >
                        New experiment
                      </button>
                    )}
                  </div>
                  {studies.length
                    ? studies.map((s) => (
                        <button
                          key={s.id}
                          className="record choice"
                          onClick={() =>
                            act(async () =>
                              setReport(await api("/api/experiments/" + s.id)),
                            )
                          }
                        >
                          <code>{s.id.slice(0, 8)}</code>
                          <span>
                            {s.status} · {when(s.created)}
                          </span>
                        </button>
                      ))
                    : empty(
                        "No experiments yet",
                        "Investigate a trace to compare a candidate with its baseline.",
                      )}
                </section>
                <section className="card">
                  <h2>Policy versions</h2>
                  {policies.length ? (
                    policies.map((p) => (
                      <div className="record" key={p.id}>
                        <code>{p.id.slice(0, 8)}</code>
                        <span>
                          {p.active ? "Available for requests" : "Rolled back"}
                        </span>
                        {p.active && ws.role === "owner" && (
                          <button
                            className="quiet"
                            onClick={() =>
                              act(async () => {
                                await api(
                                  "/api/policies/" + p.id + "/rollback",
                                  "POST",
                                );
                                await refresh();
                              })
                            }
                          >
                            Roll back
                          </button>
                        )}
                      </div>
                    ))
                  ) : (
                    <p>
                      Approved experiments appear here as selectable policies.
                    </p>
                  )}
                </section>
              </>
            )}
            {page === "Integrations & Settings" && (
              <Settings ws={ws} api={api} act={act} refresh={refresh} />
            )}
          </fieldset>
        </div>
      </main>
    </div>
  );
}
