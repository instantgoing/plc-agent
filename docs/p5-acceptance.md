# P4/P5 acceptance (2026-09-22)

The P4 human entrypoint is `python main.py chat`. It uses one in-process
`PLCSession` across turns, streams phase events, and prints the final ST,
verification plan, and observed expected/actual values. `/json` exposes the
unchanged complete result contract; `python main.py agent --json` remains the
non-interactive automation entrypoint. `/metrics` shows in-process counters.
Ctrl+C during a turn requests cancellation and waits for cleanup. The CLI does
not persist sessions or call Runtime adapters directly.

P5 was exercised with the configured real `deepseek-flash` endpoint, real
MatIEC, and real OpenPLC. Scripted model sequences are used only where a
specific *first* fault or cancellation point must be forced; they still call
the real checker and Runtime. This distinction matters: a scripted sequence
does not prove the real model will spontaneously make and repair that fault.

| Scenario | Evidence and result |
| --- | --- |
| 1. Clear simple requirement | Real LLM; explicit `Motor = Start AND NOT Stop`, no latch; one Runtime attempt accepted with real behavior assertions. `test_m5_integration.py`. |
| 2. Incomplete requirement | Real LLM asked for missing I/O/polarity without a Runtime attempt; same `PLCSession` resumed after user clarification and verified behavior. `test_p5_real_llm_integration.py`. |
| 3. MatIEC syntax repair | A forced invalid ST candidate produced real MatIEC diagnostics; the corrected candidate passed and used one Runtime attempt. The real LLM multi-turn run also repaired an initial located-variable declaration error during preflight. `test_p5_runtime_integration.py`. |
| 4. Behavioral repair | A syntactically valid wrong Boolean expression compiled but failed expected/actual assertions; the corrected expression passed on Runtime attempt 2. Scripted model, real Runtime. `test_p5_runtime_integration.py`. |
| 5. Verified-program edit | Real LLM changed Start from `%IX0.0` to `%IX0.2` in the same session and reverified. A separate real Runtime test changed a TON delay from 10 s to 5 s and asserted before/after timing. `test_p5_real_llm_integration.py`, `test_m5_runtime_integration.py`. |
| 6. Authentication failure | The actual model endpoint rejected an intentionally invalid API key during preflight; no PLC status call or Runtime attempt occurred. `test_p5_real_llm_integration.py`. |
| 7. Runtime busy | With a test program already RUNNING, the host rejected a new candidate without consuming an attempt or stopping the existing program. The test then stopped only the program it started. `test_p5_runtime_integration.py`. |
| 8. Cancellation cleanup | A live verification was cancelled; forced Start/Stop inputs were released and Runtime returned to STOPPED. Scripted cancellation point, real Runtime. `test_m5_runtime_integration.py`. |

Run all eight opt-in checks only against an available, STOPPED test Runtime:

```powershell
python run_p5_acceptance.py
```

The runner loads `.env.local`/`.env` without printing credentials, refuses a
busy or unavailable Runtime, and returns nonzero on a failure or skip. The
ordinary `python -m unittest discover -s tests -q` suite keeps these external
checks skipped by default.

Metric definitions (`PLCSession.metrics_dict()` or chat `/metrics`):

- First progress latency: start of a turn to its first emitted event, in ms;
  the report includes the last value and the mean of the latest 100 turns.
- Clarification questions: `waiting_for_user` events.
- Meaningless tool calls: host-rejected calls, including wrong order or
  schema; `schema_errors` is the narrower argument-validation subset.
- Runtime attempts: accepted-for-evaluation candidates, not syntax retries.
- Repair success rate: successful turns that had a `repair_started` event /
  all turns with such an event.
- Continuation success rate: accepted `resume()` turns / all `resume()` turns.
- Cleanup success rate: successful stop and any required force release /
  `cleanup_completed` events. Unobserved rates are `null`, never assumed 100%.

These are per-process diagnostic counters, not benchmark claims about model
reliability. Repeated trials are needed before comparing models or prompts.
