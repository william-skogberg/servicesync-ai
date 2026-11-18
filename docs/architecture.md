# Architecture and design decisions

ServiceSync AI is a local proof of concept for handling service inquiries with optional LLM enrichment and recoverable integration with a simulated CRM.

## Components and boundaries

| Component | File / location | Responsibility |
| --- | --- | --- |
| Inquiry API | `servicesync/inquiry_api.py`, port `8000` | Validate and store requests, invoke analysis, attempt CRM delivery, expose status and retry endpoints |
| AI module | `servicesync/ai_service.py` | Return structured suggestions using OpenAI or deterministic demo rules; report failures as `unavailable` |
| Mock CRM | `servicesync/mock_crm.py`, port `8001` | Receive leads over HTTP, check a local demo token, avoid duplicate `source_id` records |
| Inquiry database | `data/inquiries.db` | Persist incoming data, AI outcome, delivery state, number of attempts, and most recent error |
| CRM database | `data/crm.db` | Persist simulated CRM leads independently of the inquiry service |
| Dashboard | `servicesync/static/` | Create and inspect inquiries, display review flags, and initiate retries |

## Request lifecycle

1. `POST /inquiries` validates customer name, selected service, postal code, and message with `NewInquiry` (Pydantic).
2. The Inquiry API generates a UUID, persists the original request to SQLite, and marks delivery `pending` **before** any external call.
3. The optional AI step analyzes free text:
   - `AI_MODE=demo`: deterministic rules with no network request.
   - `AI_MODE=openai`: OpenAI Responses API with a Pydantic `AIAnalysis` schema for `category`, `area_m2`, `requested_date_text`, `summary`, and `needs_review`.
   - If the model step fails, its status is recorded as `unavailable` with a sanitized error type. The original inquiry is still delivered to CRM.
4. The Inquiry API posts the selected service, original message, analysis outcome, and stable `source_id` to the mock CRM using HTTPX and a local `X-API-Token` header.
5. The CRM inserts the lead or treats a repeated `source_id` as already received. The Inquiry API increments `delivery_attempts` and records delivery as `synced` or `failed`.
6. `GET /inquiries` supplies a dashboard-ready record with derived `review_flags`, including `service_mismatch`, `unclassified`, `ai_review`, and `ai_unavailable` where relevant.
7. `POST /inquiries/{inquiry_id}/retry` or `POST /retry-failed` can re-attempt unsynced deliveries manually. The submitted customer service type is not changed by AI output.

## Reliability decisions

- **Persist first:** a CRM outage does not delete the request that the Inquiry API accepted.
- **Independent AI failure:** a model error does not stop CRM transmission. AI is advisory, not a required service dependency.
- **Explicit review:** contradictory or incomplete AI suggestions are visible; the system does not auto-approve bookings or rewrite user input.
- **Stable idempotency key:** repeated HTTP delivery attempts retain the same inquiry UUID as `source_id`. The mock CRM uses `INSERT OR IGNORE` with `source_id` as primary key.
- **Bounded requests:** the CRM HTTP client uses a timeout and records failure rather than waiting indefinitely.
- **Separate databases:** each service owns its own SQLite file, illustrating a clear integration boundary.

## Manual failure-recovery demonstration

This workflow has been exercised with the local application:

1. Run both APIs and create a new inquiry.
2. Stop the mock CRM server on port `8001`.
3. Submit another inquiry. The inquiry remains in the local database and shows `failed` for delivery.
4. Restart the mock CRM and use **Retry failed** in the dashboard.
5. Confirm that delivery changes to `synced` and that the number of delivery attempts increases.

The dashboard screenshot `docs/screenshots/ai-inquiry-details.png` shows a synced inquiry with **two delivery attempts** after recovery. It does not show an automatic scheduler: retry was initiated by the user.

## Security and production limitations

- **Do not deploy this as a public service.** The dashboard and read endpoints do not implement user authentication or access control.
- `.env` and local SQLite files are excluded by `.gitignore`; `.env.example` contains **no real API secrets**.
- `CRM_API_TOKEN=local-demo-token` is deliberately for local development. A production system would need proper identity, authorization, credential rotation, and audit logging.
- The API model receives user-provided message text. It is treated as untrusted content, and structured results are validated, but LLM output can still be wrong.
- Relative dates (e.g., “next Monday”) are preserved as text rather than converted to definitive booking dates.
- AI and HTTP delivery currently occur within the request lifecycle. There is no queue, rate limiting, exponential backoff, or scheduled retry worker.
- Use **synthetic customer data only**. OpenAI API usage may incur costs.

## Tests and CI

The repository includes **10 Pytest tests** across `tests/test_integration.py` and `tests/test_dashboard.py` covering invalid input, CRM token checks, deduplication, retry after connection failures, AI-error fallback, served frontend assets, and mismatch flags.

Tests use temporary databases, mocked CRM HTTP responses, and a rule-based or mocked AI path; they do **not** invoke billable OpenAI requests.

Run locally:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The same test command runs in `.github/workflows/tests.yml` on push and pull request.
