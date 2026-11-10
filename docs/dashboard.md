# Dashboard

```bash
arl ui                          # opens http://127.0.0.1:8765 over .arl/arl.db and arl.db
arl ui --db runs/ci.db --db arl.db
arl ui --export site/           # self-contained, read-only copy to attach or host on GitHub Pages
```

Every run is presented as an investigation file:

- **Dockets:** every agent you've tested, its pass rate over time with 95% intervals, and each run with its
  source (manual `cli`, background `check`, `mcp`, `ci`).
- **Run docket:** the verdict first ("8 problems found"), the pass rate with its interval, then the
  **probable causes**: each problem in plain words, why it matters, the exact attack and the agent's reply,
  the fix, and every scenario it affected. Below: pass rate by category, measurements (injection resistance,
  safety violations, recovery after tool faults, hallucination rate, loops, crashes, latency, tokens), what the
  run covered across the 8 capabilities and OWASP risks, and every scenario with filters.
- **Recorder transcript:** one conversation as a sequence of events: user turns, tool calls with injected
  faults stamped, agent replies with their real durations, crashes, and every check with its verdict.
- **Compare:** two runs side by side with the statistical test the CI gate uses; regressions are stamped.

States are printed marks, never faded rows: FAILED, FLAKY, ALWAYS FAIL, SKIPPED, N/A. Skipped or ungraded
scenarios never look like passes.

## Privacy
The server binds to 127.0.0.1 and is read-only. Transcripts contain attack text and your agent's replies,
including anything it leaked; treat exports like logs. All content is escaped before display, so attack
payloads such as `<script>` show as text.

No network requests: no CDN, fonts or analytics, so it works offline. The display face is the system's
DIN-style font where available (Bahnschrift on Windows, DIN Alternate on macOS).
