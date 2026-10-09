# Runner API v1

Base: `https://filsat.odehit.com/api/runner`. HTTPS is mandatory except loopback development. Authenticate every call with `Authorization: Bearer <runner:work token>`. Token must belong to an eligible merchant. No cookie-only authentication. Provider keys never enter this protocol.

| Method and path | Request | Result |
|---|---|---|
| GET `/services` | No body | Owned local service definitions, work schedules, server time and `in_hours` |
| POST `/presence` | `{"ready_product_ids":[123]}` | Ready bindings for this token; expires after 90 seconds |
| POST `/claim` | `{"product_ids":[123]}` | `{"job":null,"poll_after_seconds":30}` or a claimed job |
| POST `/orders/{id}/heartbeat` | `{}` or `{"stage":"thinking"}` | Renews the 3-minute lease within the fixed deadline |
| GET `/orders/{id}/files/{file_id}` | No body | Authorized clean input/prior revision file bytes |
| POST `/orders/{id}/files` | Multipart `file` | `file_id` and `scan_status=clean` only after scanning |
| POST `/orders/{id}/complete` | `{"output":"Result text"}` | Completes and credits seller once; retries are idempotent |
| POST `/orders/{id}/fail` | `{}` | Refund wallet or route direct DOGE to refund review |

All order endpoints require `X-Job-Lease: <lease from claim>`, bound to the claiming token and seller. Never put the lease in a URL or provider prompt. Claim returns `id`, `product_id`, `lease`, `prompt`, `requirements`, `input`, `history`, `locale`, `output_kind`, `timeout_seconds`, `files`. Files include `id`, `name`, `size`, `sha256`, `mime`. They contain no storage path or other customer's details.

Only paid queued seller-local jobs for owned bound products are claimable. Row locks make claims exclusive. A claim response lost in transit is not recoverable in v1; the job expires and is refunded/reviewed rather than executing twice. A revoked token immediately prevents further work. A lost completion response can be retried with the same token/lease even after successful completion; it cannot credit twice.

Purchase, revision and claim also require current presence and working hours. Presence belongs to a single token, so independent seller machines may advertise different service IDs; revoking a token removes its presence. Refresh the service list and presence every 30 seconds, even while all execution slots are busy. Return an empty ready list on graceful shutdown. Readiness is reported by the seller-owned runner, not a remote security attestation; provider outages can still happen after a successful check.

Heartbeat stages: `connected`, `sending_inputs`, `thinking`, `searching`, `creating_tools`, `generating`, `uploading`. The server owns `scanning`, `ready`, `failed`. It stores stage transitions without provider logs. API limits are shared per authenticated user (120 requests/minute), so do not poll faster than specified.

Each uploaded output is private and clean, but still inaccessible to the customer until the whole order completes. Partial outputs from failed orders are not delivered. File service completion checks for required artifacts; image services require recognized image MIME, ZIP services require a ZIP artifact. File download expires after 30 days. The delivery email points to an authenticated order page, not a public bearer download URL.
