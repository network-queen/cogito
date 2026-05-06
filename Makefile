.PHONY: bootstrap install test smoke models-up models-pull

bootstrap:
	sh scripts/bootstrap.sh

install:
	python3 -m pip install -e .

models-up:
	docker compose up -d ollama

models-pull:
	.venv/bin/python -c "from cogito.local_extractor import ensure_ollama; ensure_ollama('qwen3:0.6b'); ensure_ollama('nomic-embed-text')"

test:
	PYTHONPATH=src python3 -m unittest discover -s tests

smoke:
	rm -f /tmp/cogito-smoke.db
	PYTHONPATH=src COGITO_DB=/tmp/cogito-smoke.db python3 -m cogito.cli init
	PYTHONPATH=src COGITO_DB=/tmp/cogito-smoke.db python3 -m cogito.cli remember "User is building Cogito Ergo Sum as local-first agent memory." --type goal --sensitivity professional --contexts coding,professional
	PYTHONPATH=src COGITO_DB=/tmp/cogito-smoke.db python3 -m cogito.cli context-pack "Cogito architecture" --lens coding --max-sensitivity professional
