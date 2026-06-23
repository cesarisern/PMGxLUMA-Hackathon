# PMGxLUMA Hackathon Local UI

Local full-stack wizard for running the existing feed pipeline and AudioStack generation.

## Run locally

### Terminal 1 (API)

```bash
cd api && ../.venv/bin/uvicorn server:app --reload --port 8002
```

### Terminal 2 (UI)

```bash
cd ui && npm run dev
```

## Health check

`GET http://127.0.0.1:8002/health`
