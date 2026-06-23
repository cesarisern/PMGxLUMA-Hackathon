# PMGxLUMA Hackathon Local UI

Local full-stack wizard for running the existing feed pipeline and AudioStack generation.

## Run locally

### Terminal 1 (API)

```bash
cd api && ../.venv/bin/uvicorn server:app --reload --port 8000
```

### Terminal 2 (UI)

```bash
cd ui && npm run dev
```

## Health check

`GET http://localhost:8000/health`
