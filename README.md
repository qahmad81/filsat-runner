# Filsat Runner

Run your **seller local services** from a computer you control. Filsat reviews the customer's request before payment, then your runner claims paid jobs, executes your chosen agent or workflow, and returns text and files for scanning and delivery.

This repository is the public Python client, not the private Filsat storefront. Python 3.11+; no runtime dependencies. Windows, Linux and macOS are supported. Release: **0.1.0 — early preview**.

[العربية](docs/README.ar.md) · [Creating services with an agent](docs/CREATING-SERVICES.md) · [Execution contract](docs/EXECUTING-SERVICES.md) · [Protocol](docs/PROTOCOL.md)

## Quick start

1. Complete a paid service on [Filsat](https://filsat.odehit.com) to unlock merchant access. Use the [MCP guide](https://filsat.odehit.com/mcp-guide) to create an approved service with `execution_kind: "seller_local"`.
2. Create a separate account token with **only `runner:work`**. Product management uses a different token. Do not put either token in product descriptions or prompts.
3. Clone and install:

```sh
git clone https://github.com/qahmad81/filsat-runner.git
cd filsat-runner
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
python -m pip install -e .
python -m filsat_runner doctor
```

4. Copy `config.example.json` to `runner.json`, replace service ID `123` with your approved service ID, and sign in to the provider CLI on this computer (for Codex, run `codex login`). The runner reuses local authentication; it never copies your login to the site.
5. Set `FILSAT_TOKEN` in your terminal environment to the runner token. Then start:

```sh
python -m filsat_runner run --config runner.json
# For one poll and at most one job:
python -m filsat_runner run --config runner.json --once
```

Keep this terminal running. It polls every **30 seconds**, with **15-second heartbeats** while working. `concurrency` defaults to 1 and can be 1–4. Map multiple IDs in `services` to serve multiple products. Ctrl+C stops the worker; interrupted leases expire and are reconciled by the server. The program does not install an autostart service.

The runner authenticates with the token, downloads the owned service definitions and work schedules, then checks each distinct runtime before reporting it ready. CLI/API adapters make one small real provider request on startup, cached for ten minutes; a failed execution invalidates that readiness. These probes may consume provider credit. n8n uses `/healthz` (or a configured `health_url`) and requires `workflow_ready: true` after you have published and tested the selected workflow.

Only ready services **inside working hours** accept new purchases. The site expires presence after **90 seconds** without an update. Green = online and ready; orange = offline during scheduled hours; gray = outside scheduled hours. The seller is responsible for keeping the machine, runtime, login and provider balance available. Existing jobs may finish after closing time.

Configure hours through MCP as `work_schedule: {"timezone":"Asia/Jerusalem","days":[1,2,3,4,5],"start":"09:00","end":"17:00"}`. ISO weekdays are Monday=1 through Sunday=7. Overnight windows are supported. Equal start/end means 24 hours on the selected days; all seven days with equal times means continuous availability while the runner is connected. The server clock and IANA timezone determine the schedule, including daylight-saving time.

## Runtime adapters

| `kind` | Local configuration | Behavior |
|---|---|---|
| `codex` | Sign in using `codex login`; optional `model` | `codex exec`, JSON events, workspace-write sandbox, isolated job working directory; global user config is not loaded |
| `claude` | Sign in using Claude Code; optional `model` | Headless streaming mode with Read/Write/Edit/Glob/Grep tools; no blanket permission bypass |
| `opencode` | Configure your OpenCode provider; optional `model` | `opencode run --pure --format json`; dedicated account/container required |
| `pi` | Configure Pi authentication; optional `model` | Print mode, JSON, no session persistence or extension discovery; dedicated account/container required |
| `deepseek` | Install `dsh`, configure its credentials; optional `profile` | Harness headless JSON events, stdin prompt; dedicated account/container required |
| `openrouter` | `model`, `key_env` (default `OPENROUTER_API_KEY`) | Direct API **text output**, text/image inputs; no shell tools. Use another adapter for generated files |
| `n8n` | `url`, optional `token_env` and `token_header` | Calls your published webhook once; expects a final JSON response including text and optional base64 files |

Example bindings (IDs are placeholders):

```json
{
  "site_url": "https://filsat.odehit.com",
  "token_env": "FILSAT_TOKEN",
  "concurrency": 2,
  "services": {
    "123": {"kind": "codex"},
    "124": {"kind": "deepseek", "isolated_environment": true},
    "125": {"kind": "n8n", "url": "http://127.0.0.1:5678/webhook/filsat-service", "workflow_ready": true, "token_env": "N8N_WEBHOOK_SECRET", "token_header": "X-Filsat-Webhook"},
    "126": {"kind": "openrouter", "model": "YOUR_MODEL_ID", "key_env": "OPENROUTER_API_KEY"}
  }
}
```

Environment values are never embedded in this repository. n8n URLs and commands are **seller-owned local settings**; requests from the website cannot replace them. A custom `command` is an array, e.g. `["node", "/opt/harness/apps/cli/lib/bin.js"]`; no shell is used. `args` adds static seller-approved arguments. `env_names` explicitly allows provider environment variables into a CLI subprocess, e.g. `["DEEPSEEK_API_KEY"]`; the site token is stripped.

Set `isolated_environment: true` only after you have arranged the isolation. It is an acknowledgement, not a sandbox implementation. OpenCode, Pi and Harness do not share Codex's sandbox. A fresh folder does **not** prevent an agent from reading other files on the operating system. Use a dedicated low-privilege OS account or container without unrelated secrets. The seller remains responsible for provider terms, usage charges and the capabilities promised by the service.

## n8n

Import [examples/n8n-workflow.json](examples/n8n-workflow.json) into your own n8n, inspect it, then publish it. The included workflow is a harmless echo demonstration, not an AI service. Replace its Code node with the work your service actually performs. Use **Respond to Webhook**, not an immediate acknowledgement. Add header authentication before exposing the webhook beyond loopback. Example request:

```json
{"prompt":"Service contract and request...","files":[{"name":"uuid.png","base64":"..."}]}
```

Example response:

```json
{"text":"Your report is ready.","files":[{"name":"report.txt","base64":"SGVsbG8="}]}
```

The runner does not accept arbitrary result download URLs. Files are returned inline; the same limits apply. Docker n8n accesses attachments from the webhook body, so no host workspace mount is necessary. The request is not retried automatically: a lost response may mean the workflow already ran. Configure the webhook/reverse-proxy timeout to accommodate the service. Long-running workflows beyond that timeout should be split into shorter services; asynchronous n8n callback jobs are not implemented in this release.

## Delivery, billing and failure handling

- Customer requests are checked by the site's configured reviewer against the service rules. Rejections ask for clarification and do not charge the wallet. Approval is followed by customer confirmation in the web checkout.
- Every job gets a new `temporary/job-.../` directory. Inputs are checksum verified and stored under generated filenames. They are never automatically extracted or executed.
- Agents write `result.json` and explicit files in `outputs/`. Raw logs, reasoning and credentials are not deliverables.
- The server scans every input/output file with ClamAV, validates ZIP structure, rejects encrypted ZIPs, nested archives and executable binaries in ZIPs, and fails closed if scanning is unavailable. Antivirus reduces risk; it cannot guarantee that a file is harmless.
- Downloads require the buyer's authenticated account. Output files are hidden until the complete result is accepted. The site queues a delivery email containing an account-protected order link.
- Files expire after 30 days. Temporary local job folders are removed after each attempt. Provider CLIs may retain their own logs; configure their retention separately.
- A queued job times out after 30 minutes. A claimed job has a 3-minute renewable lease and an immutable 1–60 minute execution deadline. Lost/expired executions are not automatically run again. Wallet payment is refunded on failure; direct DOGE needs refund review.
- After successful delivery, the merchant receives **70%** as internal spendable balance; the site retains **30%**, including revisions. Withdrawals are not yet offered.
- Output uploads and completion can be retried without double merchant credit. Claim or provider execution is deliberately not automatically retried after an ambiguous response.

The provider must actually produce the advertised result. File services reject a text-only response. Tool limitations and denied permissions must fail the job, not be disguised as successful delivery. Progress is generated from real tool events or a validated `progress.json`; not every runtime exposes every stage, and reasoning text is never sent to the buyer.

## Development

```sh
python -m unittest discover -s tests -v
```

Tests cover path traversal, symlinks, manifests, secret isolation, input checksums, sandbox arguments and transport configuration. Integration results are documented in [docs/TESTING.md](docs/TESTING.md). Never test payments against a customer's balance or commit `runner.json`, `.env`, provider authentication, temporary workspaces or customer files.

Sources: [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive), [Claude Code headless](https://code.claude.com/docs/en/headless), [n8n Webhook](https://docs.n8n.io/integrations/builtin/core-nodes/n8n-nodes-base.webhook/). Harness, OpenCode and Pi adapters were also checked against installed CLI help/source; versions differ, so run a small private test before publishing a paid service.
