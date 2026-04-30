# AI Security Control Plane

Local deterministic control plane for healthcare AI request prechecks, routing decisions, output validation, and audit logging.

## Local Docker Setup

Build the API image:

```powershell
docker compose build
```

Run the FastAPI app on port 8000:

```powershell
docker compose up
```

Run in the background:

```powershell
docker compose up -d
```

Stop the local stack:

```powershell
docker compose down
```

## Local Python Tests

Using the Codex bundled runtime:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'; & 'C:\Users\vinod rai\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests -p 'test_*.py'
```

Using a project environment with dependencies installed:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

## Local App Setup

Install or sync dependencies first:

```powershell
uv sync
```

Configure OpenRouter for real LLM calls:

```powershell
$env:OPENAI_API_KEY="your-openrouter-key"
$env:OPENAI_BASE_URL="https://openrouter.ai/api/v1"
$env:OPENAI_MODEL="openai/gpt-4o-mini"
```

Run the FastAPI backend:

```powershell
uvicorn main:app --reload
```

Or through uv:

```powershell
uv run uvicorn main:app --reload
```

Run the Streamlit UI in a second terminal:

```powershell
streamlit run ui/app.py
```

Or through uv:

```powershell
uv run streamlit run ui/app.py
```

The UI calls the local demo endpoint at `http://127.0.0.1:8000/analyze`.

On Windows, you can also use the included launchers:

```cmd
run_api.bat
run_ui.bat
```

If `streamlit` is not recognized, use `uv run streamlit run ui/app.py`; the bare
`streamlit` command is only available after the virtual environment has been
synced and its Scripts directory is on PATH.

## Manual API Checks

`/health` is not implemented yet in the application code. Until that route is added, use OpenAPI as a container liveness check:

```powershell
curl http://localhost:8000/openapi.json
```

Expected current `/health` behavior:

```powershell
curl http://localhost:8000/health
```

This returns `404 Not Found` until the health endpoint task is implemented.

Test `/analyze`:

```powershell
curl -X POST http://localhost:8000/analyze `
  -H "Content-Type: application/json" `
  -d '{
    "request_id": "11111111-1111-4111-8111-111111111111",
    "session_id": "22222222-2222-4222-8222-222222222222",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "query": "Please explain this lab result reference range.",
    "domain": "lab_interpretation",
    "metadata": {
      "source": "manual_test"
    }
  }'
```

Test canonical `/v1/analyze`:

```powershell
curl -X POST http://localhost:8000/v1/analyze `
  -H "Content-Type: application/json" `
  -d '{
    "request_id": "11111111-1111-4111-8111-111111111111",
    "session_id": "22222222-2222-4222-8222-222222222222",
    "user_id": "33333333-3333-4333-8333-333333333333",
    "query": "Please explain this lab result reference range.",
    "domain": "lab_interpretation",
    "metadata": {
      "source": "manual_test"
    }
  }'
```

The response should be a deterministic placeholder analysis with no real LLM call.
