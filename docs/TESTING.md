# Verification record — 2026-10-09

This is an early preview. Adapter preparation is not a claim that every provider or operating system was exercised.

| Component | Evidence |
|---|---|
| Runner | 15 Python tests passed on Windows / Python 3.13, including output-directory symlinks, path traversal, checksums, environment isolation, readiness cache and process containment |
| Storefront | 52 PHP feature tests / 247 assertions on SQLite and isolated MySQL; 5 browser-script tests |
| Codex CLI 0.125 | Actual authenticated readiness probe and complete isolated order: downloaded input, generated receipt file, uploaded it, passed ClamAV and completed delivery |
| DeepSeek Harness | Actual complete isolated order using installed Harness; receipt contents and clean scan verified |
| OpenCode 1.14.33 | Actual local file-generation smoke test with an authenticated OpenRouter model; process-tree cleanup verified |
| OpenRouter direct | Adapter implemented; direct API adapter has not had a separate end-to-end order test |
| Claude Code | Headless adapter prepared from official documentation / CLI; not executed because no active subscription was available |
| Pi | Adapter checked against installed CLI help; not executed end to end |
| n8n | Webhook adapter and importable example prepared; local runtime update/testing pending Windows Docker administrator approval |

The two complete orders used an isolated database and synthetic balances. Both returned the expected artifact bytes. Two 100-cent sales credited the test seller 140 cents total. No real buyer balance was used. Automated tests cover duplicate completion, authorization boundaries, lease expiration/refund, offline purchases, presence expiration/revocation and timezone/overnight schedules.

The server's real antivirus rejected the standard EICAR test signature. Email job construction and deduplication were tested with an array mail transport; arrival in an external inbox was not verified.

Re-run `python -m unittest discover -s tests -v` after changes. Before offering a paid service, test the exact installed provider, model, permissions and promised output type. CI additionally defines Linux/Windows Python 3.11/3.13 jobs; a workflow definition alone is not evidence those remote jobs passed.
