.PHONY: help backend frontend test fmt lint

help: ## list available targets
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "%-12s %s\n", $$1, $$2}'

backend: ## run FastAPI on :8000 with reload
	cd backend && uvicorn api.server:app --reload --port 8000

frontend: ## run Vite on :5173
	cd frontend && npm run dev

install: ## install backend (editable) + frontend deps
	cd backend && pip install -e .
	cd frontend && npm install

test: ## run pytest
	cd backend && pytest -q

prune: ## drop seen-store rows older than 90 days
	cd backend && python -c "from core import dedup; dedup.init_db(); print(dedup.prune_seen(90), 'rows pruned')"
