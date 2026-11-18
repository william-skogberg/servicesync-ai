# ServiceSync AI – complete project

**Local portfolio demo:** a service inquiry is validated, saved to SQLite, optionally analyzed by an OpenAI model, sent over HTTP to a separate mock CRM, and displayed in a browser dashboard. Includes mismatch warnings, retry of failed CRM delivery and automated tests. Use **fictional data only**.

## Technologies

Python 3.12 · FastAPI · SQLite · Pydantic · HTTPX · OpenAI Responses API · HTML/CSS/JavaScript · Pytest · GitHub Actions.

## Quick start (Windows PowerShell + VS Code)

1. Unzip the archive. In VS Code choose **File → Open Folder** and open `servicesync-ai` (the folder containing `requirements.txt`).
2. In VS Code choose **Terminal → New Terminal**, then run:

```powershell
uv python install 3.12
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
Copy-Item .env.example .env
```

If you already have a project-specific `.venv` and dependencies installed, you can skip the first three commands. If `uv` is not found, restart the VS Code terminal or use `& "$env:USERPROFILE\.local\bin\uv.exe"` instead of `uv`.

3. Open **`.env`** in VS Code. Insert your own API key into `OPENAI_API_KEY=...`. The provided `.env.example` uses `AI_MODE=openai` and `OPENAI_MODEL=gpt-6-luna` (the model you successfully tested). **Never share or commit your `.env` file.** To use the no-cost rule-based demo instead, set `AI_MODE=demo`.
4. Run tests (they do not send any real AI requests):

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

5. Start **two separate terminals** in the `servicesync-ai` folder:

**Terminal 1: mock CRM**

```powershell
.\.venv\Scripts\python.exe -m uvicorn servicesync.mock_crm:app --host 127.0.0.1 --port 8001
```

**Terminal 2: inquiry API + dashboard**

```powershell
$env:AI_MODE = 'openai'
.\.venv\Scripts\python.exe -m uvicorn servicesync.inquiry_api:app --host 127.0.0.1 --port 8000
```

The explicit `AI_MODE` above avoids an old PowerShell variable set to `demo` taking priority over your `.env`. Alternatively, remove that environment variable from Terminal 2 with `Remove-Item Env:AI_MODE -ErrorAction SilentlyContinue` to use the value from `.env`.

6. Open **http://127.0.0.1:8000/** for the dashboard, **http://127.0.0.1:8000/docs** for API documentation, and **http://127.0.0.1:8001/leads** to inspect the mock CRM.

## Test the dashboard

Click **New inquiry** and enter fictional details. Select `Home cleaning`, but write a message like `I need move-out cleaning for an 85 m2 apartment next Friday.` The AI may classify this as `move_out_cleaning`; the dashboard should flag a **service mismatch** while leaving the original selected service unchanged. The inquiry should show CRM status **synced** if the CRM server is running.

For the failure/retry demonstration, stop Terminal 1 (CRM) with Ctrl+C, send a new inquiry, start Terminal 1 again, and click **Retry failed** in the dashboard.

## Project layout

```text
servicesync-ai/
├── servicesync/
│   ├── inquiry_api.py       # Main API, local SQLite, CRM sync, dashboard routes
│   ├── ai_service.py        # Real OpenAI analysis or deterministic demo fallback
│   ├── models.py            # Validation contracts
│   ├── mock_crm.py          # Simulated second system
│   ├── storage.py           # SQLite and local .env loader
│   └── static/
│       ├── index.html       # Dashboard
│       ├── style.css
│       └── app.js
├── tests/
│   ├── test_integration.py
│   └── test_dashboard.py
├── .github/workflows/tests.yml
├── .env.example             # Template: no secrets
├── .gitignore
├── requirements.txt
└── README.md
```

## Existing inquiries from the older project

This archive intentionally does **not** contain your old databases or API key. If you want to preserve earlier local requests, stop both servers and copy the **`data/` folder from the old project** into this `servicesync-ai/` folder. Existing SQLite schemas are compatible with the app's included local migration. Copy your own `.env` separately if preferred; do not overwrite it accidentally.

## Important limitations

- **Local demo only:** endpoints for listing inquiry data are not authenticated. Do not expose these services publicly or insert real customer information.
- AI category, summary and requested date are **suggestions**, not confirmed bookings. Relative dates are not converted into calendar dates.
- Failed AI requests are recorded as `unavailable` and do not block sending the underlying inquiry to the mock CRM.
- The project uses synchronous request-time processing, not a production background job system. Automated CRM retries are not scheduled; the user triggers them.
- API calls to OpenAI may cost money, charged separately from ChatGPT Plus.
