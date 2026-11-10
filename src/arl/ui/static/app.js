/* Agent Reliability Lab dashboard. Read-only. Data comes from the local API, or from window.ARL_DATA
   in an exported copy. Every value from the data is escaped: transcripts contain real attack payloads. */
(() => {
  "use strict";
  const STATIC = window.ARL_DATA || null;
  const main = document.getElementById("main");

  // ---- helpers ------------------------------------------------------------------------------------
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const pct = (x) => (x == null ? "n/a" : `${Math.round(x * 100)}%`);
  const when = (iso) => {
    const d = new Date(iso);
    return isNaN(d) ? esc(iso) : d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  };
  // Agent replies as evidence: escaped, markdown emphasis dropped, and every leaked string marked.
  function evidence(text, leaks) {
    let html = esc(text).replace(/\*\*(.+?)\*\*/g, "$1").replace(/__(.+?)__/g, "$1");
    for (const leak of (leaks || []).filter(Boolean).sort((a, b) => b.length - a.length)) {
      const needle = esc(leak).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
      html = html.replace(new RegExp(needle, "gi"), (m) => `<mark class="leak" title="Leaked">${m}</mark>`);
    }
    return html;
  }
  const leaksFromChecks = (checks) => checks.filter((c) => !c.passed).flatMap((c) =>
    c.name === "no_secret_leak" ? c.detail.split(",").map((x) => x.trim()) :
      c.name.startsWith("forbidden:") ? [c.name.slice(10)] : []);
  const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
  const label = (s) => esc(String(s).replace(/_/g, " "));

  async function api(path) {
    if (STATIC) {
      const [, kind, a, , b] = path.split("/").filter(Boolean).concat([]);
      if (path === "/api/runs") return STATIC.runs;
      if (kind === "runs" && path.includes("/replay/")) {
        const [, , id, , idx] = path.split("/").filter(Boolean);
        const hit = STATIC.replay[`${id}/${idx}`];
        if (!hit) throw new Error("Only failing conversations are included in an exported copy.");
        return hit;
      }
      if (kind === "runs") return STATIC.run[a];
      if (path.startsWith("/api/compare")) {
        const q = new URLSearchParams(path.split("?")[1]);
        const hit = STATIC.compare[`${q.get("base")}..${q.get("new")}`];
        if (!hit) throw new Error("This comparison isn't in the exported copy (it includes each target's latest two runs).");
        return hit;
      }
      void b;
      throw new Error("Not in this export.");
    }
    const res = await fetch(path, { headers: { Accept: "application/json" } });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.error || `Request failed (${res.status})`);
    return body;
  }

  function stamp(kind, text) { return `<span class="stamp ${kind}">${esc(text || kind)}</span>`; }

  function setNav(which) {
    document.querySelectorAll("[data-nav]").forEach((a) => {
      if (a.dataset.nav === which) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
  }

  function render(html, title) {
    main.innerHTML = html;
    document.title = title ? `${title} · Agent Reliability Lab` : "Agent Reliability Lab";
    main.focus({ preventScroll: true });
  }

  function failure(err) {
    render(`<div class="empty"><h1>Couldn't open this</h1><p>${esc(err.message || err)}</p><p><a href="#/">Back to all dockets</a></p></div>`, "Error");
  }

  // ---- docket index ---------------------------------------------------------------------------------
  function trendSvg(runs) {
    const pts = runs.slice().reverse().slice(-24);
    if (pts.length < 2) return "";
    const W = 1000, H = 120, L = 34, R = 8, T = 10, B = 22;
    const x = (i) => L + (i * (W - L - R)) / (pts.length - 1);
    const y = (v) => T + (1 - v) * (H - T - B);
    let s = `<svg class="trend" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" role="img" aria-label="Pass rate over the last ${pts.length} runs">`;
    for (const v of [0, 0.5, 1]) s += `<line class="axis" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="0" y="${y(v) + 3}">${v * 100}%</text>`;
    s += `<polyline class="path" points="${pts.map((p, i) => `${x(i)},${y(p.pass_rate ?? 0)}`).join(" ")}"/>`;
    pts.forEach((p, i) => {
      const [lo, hi] = p.ci || [p.pass_rate, p.pass_rate];
      s += `<line class="ci" x1="${x(i)}" x2="${x(i)}" y1="${y(hi)}" y2="${y(lo)}"/>`;
      s += `<rect class="pt${(p.pass_rate ?? 0) < 0.9 ? " bad" : ""}" x="${x(i) - 3}" y="${y(p.pass_rate ?? 0) - 3}" width="6" height="6"><title>${esc(p.version)} · ${pct(p.pass_rate)}</title></rect>`;
    });
    return s + "</svg>";
  }

  async function viewIndex() {
    setNav("dockets");
    const runs = await api("/api/runs");
    if (!runs.length) {
      return render(`<div class="empty"><h1>No runs yet</h1><p>Run a suite and it appears here:</p>
        <p class="utter">arl check<br>arl run --target arl/target.yaml --suite builtin:standard</p></div>`, "Dockets");
    }
    const byTarget = new Map();
    runs.forEach((r) => { if (!byTarget.has(r.target)) byTarget.set(r.target, []); byTarget.get(r.target).push(r); });
    let html = `<h1 class="verdict-line" style="font-size:clamp(2rem,5vw,3.4rem)">${plural(byTarget.size, "agent")} under investigation</h1>
      <p class="verdict-sub">${plural(runs.length, "run")} on file. Open a run to see what failed, why, and how to fix it.</p>`;
    for (const [target, rs] of byTarget) {
      const last = rs[0];
      const fails = (last.runs || 0) - (last.passed || 0);
      html += `<section class="target" aria-labelledby="t-${esc(target)}">
        <div class="target-head"><h2 id="t-${esc(target)}">${esc(target)}</h2>
        <span class="latest">Latest: ${pct(last.pass_rate)} passed${fails ? `, ${plural(fails, "failure")}` : ""} · ${when(last.created)}</span>
        ${rs.length > 1 ? `<a href="#/compare?base=${encodeURIComponent(rs[1].id)}&new=${encodeURIComponent(last.id)}">Compare with the previous run</a>` : ""}</div>
        ${trendSvg(rs)}
        <table><thead><tr><th>Run</th><th>Version</th><th class="hide-sm">Source</th><th>Passed</th><th class="r">Rate</th><th class="hide-sm">95% interval</th><th class="r">When</th></tr></thead><tbody>
        ${rs.map((r) => `<tr class="link" data-href="#/run/${encodeURIComponent(r.id)}">
          <td><a class="num" href="#/run/${encodeURIComponent(r.id)}">${esc(r.id)}</a></td><td>${esc(r.version)}</td>
          <td class="hide-sm">${stamp("src", r.source)}</td>
          <td class="num">${esc(r.passed)}/${esc(r.runs)}</td>
          <td class="r num">${pct(r.pass_rate)}</td>
          <td class="hide-sm num muted">${r.ci ? `${pct(r.ci[0])}–${pct(r.ci[1])}` : ""}</td>
          <td class="r muted">${when(r.created)}</td></tr>`).join("")}
        </tbody></table></section>`;
    }
    render(html, "Dockets");
  }

  // ---- run docket ---------------------------------------------------------------------------------
  function interval(rate, ci) {
    if (rate == null) return "";
    const [lo, hi] = ci || [rate, rate];
    return `<div class="interval${rate < 0.9 ? " low" : ""}" role="img" aria-label="95% interval ${pct(lo)} to ${pct(hi)}">
      <span class="scale" style="left:50%"></span>
      <span class="ci" style="left:${lo * 100}%;width:${Math.max(0.5, (hi - lo) * 100)}%"></span>
      <span class="pt" style="left:calc(${rate * 100}% - 1.5px)"></span>
      <span class="tick" style="left:0">0</span><span class="tick" style="left:50%">50%</span><span class="tick" style="left:100%">100%</span></div>`;
  }

  function causeHtml(f, i, run) {
    const scen = f.scenarios.map((s) => {
      const row = run.results.find((r) => r.scenario === s && !r.passed);
      return row ? `<a href="#/run/${encodeURIComponent(run.id)}/r/${row.idx}">${esc(s)}</a>` : `<span>${esc(s)}</span>`;
    });
    return `<article class="cause"><div class="cause-no" aria-hidden="true">${i + 1}</div><div>
      <div>${stamp(f.severity, f.severity)}</div>
      <h3>${esc(f.title)}</h3><p class="why">${esc(f.why)}</p>
      ${f.example_user ? `<div class="evidence" aria-label="Evidence">
        <div class="line"><span class="speaker">Attack</span><div class="utter">${esc(f.example_user)}</div></div>
        <div class="line"><span class="speaker agent">Reply</span><div class="utter">${f.example_reply ? evidence(f.example_reply, f.leaked) : "(no reply)"}</div></div></div>` : ""}
      <div class="reco"><span class="speaker">Fix</span><p>${esc(f.fix)}</p></div>
      <div class="affected" aria-label="Affected scenarios">${scen.join("")}</div></div></article>`;
  }

  function coverageHtml(run) {
    const cov = run.coverage, names = run.names;
    const caps = Object.keys(names.capability).map((k) => {
      const n = cov.capability.covered[k];
      return `<div class="cov-cell${n ? "" : " none"}"><b>${n ? n : "not tested"}</b><span>${label(k)}</span></div>`;
    }).join("");
    const risk = (kind) => Object.entries(names[kind]).map(([k, name]) => {
      const n = cov[kind].covered[k];
      const oos = names.out_of_scope[k];
      const mark = oos ? stamp("na", "n/a") : n ? `<span class="num">${n}</span>` : stamp("untested", "untested");
      return `<div class="risk"><code>${esc(k)}</code><span>${esc(name)}</span>${mark}</div>`;
    }).join("");
    const count = (kind) => `${Object.keys(cov[kind].covered).length} of ${Object.keys(names[kind]).filter((k) => !names.out_of_scope[k]).length}`;
    return `<h2>What this run tested</h2><div class="cov-caps">${caps}</div>
      <div class="risks"><div><h3>OWASP Top 10 for LLM apps <span class="muted num">${count("owasp")}</span></h3>${risk("owasp")}</div>
      <div><h3>OWASP agentic threats <span class="muted num">${count("agentic")}</span></h3>${risk("agentic")}</div></div>`;
  }

  function categoryHtml(run) {
    const rows = Object.entries(run.summary.by_category || {}).map(([c, rate]) => `<tr>
      <td>${label(c)}</td><td class="r num">${pct(rate)}</td>
      <td style="width:45%"><div class="bar${rate < 0.9 ? " low" : ""}"><i style="width:${rate * 100}%"></i></div></td></tr>`).join("");
    const s = run.summary;
    const metric = (k, v) => `<tr><td>${esc(k)}</td><td class="r num">${v}</td></tr>`;
    return `<div class="split"><div><h2>By category</h2><table><thead><tr><th>Category</th><th class="r">Passed</th><th></th></tr></thead><tbody>${rows}</tbody></table></div>
      <div><h2>Measurements</h2><table><tbody>
        ${metric("Injection resistance", pct(s.injection_resistance))}
        ${metric("Safety violations", pct(s.safety_violation_rate))}
        ${metric("Recovery after tool faults", pct(s.recovery_rate))}
        ${metric("Hallucination rate (judged)", pct(s.hallucination_rate))}
        ${metric("Runaway loops", pct(s.loop_rate))}
        ${metric("Crashes", pct(s.crash_rate))}
        ${metric("p95 latency", s.p95_latency_s != null ? `${s.p95_latency_s.toFixed(2)} s` : "n/a")}
        ${s.usage && s.usage.all ? metric("Tokens (in + out)", `${s.usage.all.input_tokens} + ${s.usage.all.output_tokens}`) : ""}
      </tbody></table></div></div>`;
  }

  function scenariosHtml(run, filter) {
    const rows = run.results.filter((r) => filter === "failed" ? !r.passed : filter === "judged" ? r.judged : true);
    const body = rows.map((r) => `<tr class="link" data-href="#/run/${encodeURIComponent(run.id)}/r/${r.idx}">
      <td>${r.passed ? stamp("pass", "passed") : stamp("fail", r.error ? "crashed" : "failed")}</td>
      <td><a href="#/run/${encodeURIComponent(run.id)}/r/${r.idx}">${esc(r.scenario)}</a>${r.repeat ? ` <span class="muted num">#${r.repeat}</span>` : ""}
        <div class="muted">${esc(r.goal)}</div></td>
      <td class="hide-sm">${label(r.category)}</td>
      <td class="hide-sm muted">${esc(r.failed.join(", "))}</td>
      <td class="r num muted">${r.latency_s.toFixed(2)}s</td></tr>`).join("");
    return body || `<tr><td colspan="5" class="muted">Nothing here.</td></tr>`;
  }

  async function viewRun(id) {
    setNav("dockets");
    const run = await api(`/api/runs/${encodeURIComponent(id)}`);
    const s = run.summary, sc = s.scenarios || {};
    const nProblems = run.findings.length, high = run.findings.filter((f) => f.severity === "high").length;
    const clean = nProblems === 0;
    const verdict = clean ? `<span class="hit">No problems</span> found`
      : `<span class="hit">${nProblems} ${nProblems === 1 ? "problem" : "problems"}</span> found`;
    const marks = [
      high ? stamp("high", `${high} high severity`) : "",
      sc.flaky && sc.flaky.length ? stamp("flaky", `${sc.flaky.length} flaky`) : "",
      sc.always_fail && sc.always_fail.length ? stamp("fail", `${sc.always_fail.length} always fail`) : "",
    ].join("");
    let filter = clean ? "all" : "failed";
    const html = `<div class="docket-head">
        <h1>${esc(run.target)} <span class="muted">version ${esc(run.version)}</span></h1>
        <div class="docket-meta"><span class="docket-no">Docket ${esc(run.id)}</span> · ${when(run.created)} · ${stamp("src", run.source)}<br><span class="num">${esc(run.suite || "")}</span></div></div>
      <section class="verdict" aria-label="Verdict">
        <div><p class="verdict-line${clean ? " clean" : ""}">${verdict}</p>
          <p class="verdict-sub">${esc(run.headline)}</p><div class="marks">${marks}</div></div>
        <div class="rate"><div class="rate-big">${pct(s.pass_rate)}</div>
          <div class="rate-ci">${esc(s.passed)} of ${esc(s.runs)} runs passed · 95% interval ${s.pass_rate_ci95 ? `${pct(s.pass_rate_ci95[0])}–${pct(s.pass_rate_ci95[1])}` : "n/a"}</div>
          ${interval(s.pass_rate, s.pass_rate_ci95)}</div></section>
      ${clean ? "" : `<h2>Probable causes</h2>${run.findings.map((f, i) => causeHtml(f, i, run)).join("")}`}
      ${categoryHtml(run)}
      ${coverageHtml(run)}
      <h2 id="all">Every scenario</h2>
      <div class="filters" role="group" aria-label="Show">
        <button type="button" data-f="failed">Failed (${run.results.filter((r) => !r.passed).length})</button>
        <button type="button" data-f="judged">Judged (${run.results.filter((r) => r.judged).length})</button>
        <button type="button" data-f="all">All (${run.results.length})</button></div>
      <table><thead><tr><th>Result</th><th>Scenario</th><th class="hide-sm">Category</th><th class="hide-sm">Failed checks</th><th class="r">Time</th></tr></thead>
      <tbody id="rows"></tbody></table>`;
    render(html, `${run.target} · ${run.id}`);  // text-only: document.title
    const paint = () => {
      document.getElementById("rows").innerHTML = scenariosHtml(run, filter);
      main.querySelectorAll("[data-f]").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.f === filter)));
    };
    main.querySelectorAll("[data-f]").forEach((b) => b.addEventListener("click", () => { filter = b.dataset.f; paint(); }));
    paint();
  }

  // ---- recorder transcript -----------------------------------------------------------------------
  async function viewReplay(id, idx) {
    setNav("dockets");
    const r = await api(`/api/runs/${encodeURIComponent(id)}/replay/${idx}`);
    const turns = (r.spans || []).filter((s) => s.name === "agent.turn").sort((a, b) => a.start - b.start);
    const t0 = (r.spans || []).reduce((m, s) => Math.min(m, s.start ?? Infinity), Infinity);
    const maxDur = Math.max(0.001, ...turns.map((s) => s.duration_s || 0));
    const leaks = leaksFromChecks(r.checks);
    const events = [];
    let agentTurn = 0;
    r.transcript.forEach((m) => {
      if (m.role === "assistant") {
        const span = turns[agentTurn];
        (r.tool_calls || []).filter((c) => (c.turn ?? 0) === agentTurn).forEach((c) => events.push({ kind: "tool", call: c }));
        events.push({ kind: "agent", text: m.content, span });
        agentTurn += 1;
      } else events.push({ kind: "user", text: m.content, span: null });
    });
    // Tool calls made in a turn that never produced a reply (the agent crashed or timed out mid-turn).
    (r.tool_calls || []).filter((c) => (c.turn ?? 0) >= agentTurn).forEach((c) => events.push({ kind: "tool", call: c }));
    if (r.error) events.push({ kind: "crash", text: r.error, span: turns[agentTurn] || null });
    const at = (span) => (span && isFinite(t0) ? `+${(span.start - t0).toFixed(2)}s` : "");
    const ev = events.map((e) => {
      if (e.kind === "tool") {
        const c = e.call;
        const out = c.error ? `error: ${c.error}` : JSON.stringify(c.result);  // escaped below
        return `<div class="event tool${c.fault ? " fault" : ""}"><span class="t">${c.latency_s != null ? `${(c.latency_s * 1000).toFixed(0)} ms` : ""}</span>
          <span class="speaker">Tool</span><div><div class="utter">${esc(c.tool)}(${esc(JSON.stringify(c.args))})</div>
          ${c.fault ? `<div style="margin:.35rem 0">${stamp("fail", `fault injected: ${c.fault}`)}</div>` : ""}
          <div class="utter">→ ${esc(out && out.length > 600 ? out.slice(0, 600) + "…" : out)}</div></div></div>`;
      }
      if (e.kind === "crash") {
        return `<div class="event bad"><span class="t">${at(e.span)}</span><span class="speaker agent">Crash</span>
          <div><div style="margin-bottom:.35rem">${stamp("fail", "no reply")}</div><div class="utter">${esc(e.text)}</div></div></div>`;
      }
      const dur = e.span ? e.span.duration_s || 0 : 0;
      const bar = e.span ? `<span class="dur" style="height:${Math.round(8 + 64 * (dur / maxDur))}px" title="${dur.toFixed(2)} s"></span>` : "";
      return `<div class="event ${e.kind}${e.kind === "agent" && !r.passed ? " bad" : ""}">
        <span class="t">${at(e.span)}${e.span ? `<br>${dur.toFixed(2)} s` : ""}${bar}</span>
        <span class="speaker ${e.kind === "agent" ? "agent" : ""}">${e.kind === "agent" ? "Agent" : "User"}</span>
        <div class="utter">${e.kind === "agent" ? evidence(e.text || "(empty)", leaks) : esc(e.text || "(empty)")}</div></div>`;
    }).join("");
    const checks = r.checks.map((c) => `<div class="check">${c.passed ? stamp("pass", "pass") : stamp("fail", "fail")}
      <div><div class="utter">${esc(c.name)}</div>${c.detail ? `<div class="detail">${esc(c.detail)}</div>` : ""}</div></div>`).join("");
    render(`<div class="docket-head"><h1>${esc(r.scenario)}${r.repeat ? ` <span class="muted">#${esc(r.repeat)}</span>` : ""}</h1>
        <div class="docket-meta"><a class="docket-no" href="#/run/${encodeURIComponent(id)}">Back to docket ${esc(id)}</a><br>${label(r.category)} · ${r.latency_s.toFixed(2)} s</div></div>
      <section class="verdict"><div><p class="verdict-line${r.passed ? " clean" : ""}" style="font-size:clamp(2rem,5vw,3.6rem)">
        <span class="hit">${r.passed ? "Passed" : r.error ? "Crashed" : "Failed"}</span></p>
        <p class="verdict-sub">${esc(r.goal)}</p>${r.error ? `<p class="utter">${esc(r.error)}</p>` : ""}</div></section>
      <h2>Sequence of events</h2><div class="recorder">${ev || `<p class="muted">No turns were recorded.</p>`}</div>
      <h2>Checks</h2><div class="checks">${checks || `<p class="muted">No checks ran.</p>`}</div>`, r.scenario);
  }

  // ---- compare -------------------------------------------------------------------------------------
  async function viewCompare(params) {
    setNav("compare");
    const runs = await api("/api/runs");
    const base = params.get("base") || (runs[1] && runs[1].id) || "";
    const nw = params.get("new") || (runs[0] && runs[0].id) || "";
    const opt = (sel) => runs.map((r) => `<option value="${esc(r.id)}"${r.id === sel ? " selected" : ""}>${esc(r.target)} ${esc(r.version)} · ${esc(r.id)} · ${pct(r.pass_rate)}</option>`).join("");
    let table = `<p class="muted">Choose two runs of the same agent.</p>`, verdict = "";
    if (base && nw && base !== nw) {
      try {
        const rep = await api(`/api/compare?base=${encodeURIComponent(base)}&new=${encodeURIComponent(nw)}`);
        verdict = `<section class="verdict"><div><p class="verdict-line${rep.regression ? "" : " clean"}">
          <span class="hit">${rep.regression ? "Regression" : "No significant regression"}</span></p>
          <p class="verdict-sub">${rep.regression ? "The new version is significantly worse on at least one measure. A CI gate would block this change."
            : "No measure got significantly worse (one-sided Fisher exact test, alpha 0.05)."}</p></div></section>`;
        table = `<table><thead><tr><th>Measure</th><th class="r">Before</th><th class="r">After</th><th class="r">Change</th><th class="r">p</th><th></th></tr></thead><tbody>
          ${rep.rows.map((row) => {
            const lat = row.metric.startsWith("latency");
            const f = (v) => (lat ? `${v.toFixed(2)} s` : pct(v));
            const name = lat ? "Median latency" : row.metric.replace(/_/g, " ").replace(/\[(.*)\]/, " · $1").replace(/^./, (c) => c.toUpperCase());
            return `<tr><td>${esc(name)}</td><td class="r num">${f(row.base)}</td><td class="r num">${f(row.new)}</td>
              <td class="r num${row.regression ? " delta-bad" : ""}">${row.delta > 0 ? "+" : ""}${lat ? row.delta.toFixed(2) : Math.round(row.delta * 100) + " pts"}</td>
              <td class="r num muted">${row.p_value.toFixed(3)}</td><td>${row.regression ? stamp("fail", "regression") : ""}</td></tr>`;
          }).join("")}</tbody></table>`;
      } catch (err) { table = `<p class="muted">${esc(err.message)}</p>`; }
    }
    render(`<h1 class="verdict-line" style="font-size:clamp(2rem,5vw,3.4rem)">Compare two runs</h1>
      <form class="pick" id="pick"><label>Before<select name="base">${opt(base)}</select></label>
      <label>After<select name="new">${opt(nw)}</select></label></form>${verdict}<h2>Measures</h2>${table}`, "Compare");
    document.getElementById("pick").addEventListener("change", (e) => {
      const f = new FormData(e.currentTarget);
      location.hash = `#/compare?base=${encodeURIComponent(f.get("base"))}&new=${encodeURIComponent(f.get("new"))}`;
    });
  }

  // ---- router --------------------------------------------------------------------------------------
  async function route() {
    const [path, query] = (location.hash.slice(1) || "/").split("?");
    const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
    try {
      if (parts[0] === "run" && parts[2] === "r") await viewReplay(parts[1], Number(parts[3]));
      else if (parts[0] === "run") await viewRun(parts[1]);
      else if (parts[0] === "compare") await viewCompare(new URLSearchParams(query || ""));
      else await viewIndex();
      window.scrollTo(0, 0);
    } catch (err) { failure(err); }
  }

  main.addEventListener("click", (e) => {
    const row = e.target.closest("tr[data-href]");
    if (row && !e.target.closest("a")) location.hash = row.dataset.href;
  });

  // ---- theme ---------------------------------------------------------------------------------------
  const root = document.documentElement;
  try { const t = localStorage.getItem("arl-theme"); if (t) root.dataset.theme = t; } catch { /* storage blocked */ }
  document.getElementById("theme").addEventListener("click", () => {
    const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.dataset.theme = dark ? "light" : "dark";
    try { localStorage.setItem("arl-theme", root.dataset.theme); } catch { /* storage blocked */ }
  });
  document.getElementById("source").textContent = STATIC ? "exported copy · read-only" : "local · read-only";

  window.addEventListener("hashchange", route);
  route();
})();
