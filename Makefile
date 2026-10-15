SERVICES := gateway sourcing logistics geo trust rfq messaging tracking notifications assistant demand payments media feed freight
.PHONY: venv test lint dev down compose-e2e e2e e2e-extended smoke audit $(addprefix test-,$(SERVICES))
venv:
	python3 -m venv .venv && .venv/bin/pip install -q fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy aiosqlite greenlet pyjwt bcrypt email-validator websockets pytest pytest-asyncio respx ruff pyyaml pillow python-multipart
test:
	@set -e; for s in $(SERVICES); do echo "== $$s"; (cd services/$$s && ../../.venv/bin/python -m pytest -q); done
$(addprefix test-,$(SERVICES)): test-%:
	cd services/$* && ../../.venv/bin/python -m pytest -q
lint:
	.venv/bin/ruff check services scripts
dev:
	docker compose up --build
down:
	docker compose down
compose-e2e:  # build + start the stack detached, run scripts/e2e.py against it, always tear down
	docker compose up --build -d --wait
	FF_E2E_BASE_URL=http://localhost:8000 .venv/bin/python scripts/e2e.py; rc=$$?; docker compose down -v; exit $$rc
e2e:
	.venv/bin/python scripts/e2e.py
e2e-extended:  # extra flows: moderation, media attachments, email verify, tracking relay, deals, assistant, reviews, prod guard
	.venv/bin/python scripts/e2e_extended.py
smoke:  # post-deploy read-only checks: FF_E2E_BASE_URL=https://api.example.com make smoke
	.venv/bin/python scripts/smoke_prod.py
audit:  # dependency vulnerability scan; non-fatal and skipped if pip-audit is not installed
	@if [ -x .venv/bin/pip-audit ]; then PA=.venv/bin/pip-audit; elif command -v pip-audit >/dev/null 2>&1; then PA=pip-audit; else echo "pip-audit not installed; skipping (pip install pip-audit)"; exit 0; fi; \
	for d in packages/py-common $(addprefix services/,$(SERVICES)); do echo "== $$d"; timeout 60 $$PA --progress-spinner off $$d || echo "audit: findings or offline for $$d (non-fatal)"; done; exit 0
