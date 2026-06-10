# TenderScore development targets. See docs/BUILD_HANDOVER.md and
# docs/architecture.md Part I for the milestone plan.

.PHONY: dev dev-down test test-backend test-frontend lint lint-backend lint-frontend regression redteam

dev: ## Boot the full local stack (db, minio, api, worker, web)
	docker compose up --build

dev-down: ## Stop the local stack
	docker compose down

test: test-backend test-frontend ## Run all unit and integration tests

test-backend:
	cd backend && uv run pytest

test-frontend:
	cd frontend && npm test

lint: lint-backend lint-frontend ## All static checks (ruff, mypy --strict, tsc --noEmit)

lint-backend:
	cd backend && uv run ruff check . && uv run mypy

lint-frontend:
	cd frontend && npx tsc --noEmit

regression: ## Synthetic tender regression suite (fails loudly until M5 delivers it)
	@if ! ls backend/tests/regression/test_*.py >/dev/null 2>&1; then \
		echo "FAIL: the synthetic tender regression suite does not exist yet (built in M5)."; \
		echo "See backend/tests/regression/README.md."; \
		exit 1; \
	fi
	cd backend && uv run pytest tests/regression

redteam: ## Injection red-team suite (fails loudly until M2+ delivers it)
	@if ! ls backend/tests/redteam/test_*.py >/dev/null 2>&1; then \
		echo "FAIL: the injection red-team suite does not exist yet (built from M2, hardened in M9)."; \
		echo "See backend/tests/redteam/README.md."; \
		exit 1; \
	fi
	cd backend && uv run pytest tests/redteam
