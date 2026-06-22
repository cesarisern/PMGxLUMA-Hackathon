#!/usr/bin/env bash
# Launch the Dynamic Voice API app using the project venv.
cd "$(dirname "$0")"
exec .venv/bin/streamlit run app.py "$@"
