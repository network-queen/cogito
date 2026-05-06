#!/usr/bin/env sh
set -eu

cd "$(dirname "$0")/.."

python3 -m venv .venv
.venv/bin/pip install -e .

if command -v docker >/dev/null 2>&1; then
  docker compose up -d ollama
  OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
  export OLLAMA_URL
  .venv/bin/python - <<'PY'
from cogito.local_extractor import ensure_ollama
ensure_ollama("qwen3:0.6b")
ensure_ollama("nomic-embed-text")
PY
else
  echo "Docker not found. Cogito installed; install Docker or Ollama for local models." >&2
fi

echo "Run: .venv/bin/cogito"
