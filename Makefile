SERVICES := gateway sourcing logistics geo trust rfq messaging tracking notifications assistant demand payments media feed freight
.PHONY: venv test lint contract-examples dev down compose-e2e e2e e2e-extended e2e-scenarios e2e-privacy smoke audit compose-check $(addprefix test-,$(SERVICES))
venv:
	python3 -m venv .venv && .venv/bin/pip install -q fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy aiosqlite greenlet pyjwt bcrypt email-validator websockets pytest pytest-asyncio respx ruff pyyaml pillow python-multipart
test:
	@set -e; for s in $(SERVICES); do echo "== $$s"; (cd services/$$s && ../../.venv/bin/python -m pytest -q); done
$(addprefix test-,$(SERVICES)): test-%:
	cd services/$* && ../../.venv/bin/python -m pytest -q
lint:
	.venv/bin/ruff check services scripts
contract-examples:  # every example/examples in contracts/openapi validates against its schema (offline)
	.venv/bin/python scripts/contract_examples.py
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
e2e-scenarios:  # 5 focused edge scenarios: landed-cost labels + geo avoid, tracking typo, concurrent invoice, freight dup, feed hidden unlike
	.venv/bin/python scripts/e2e_scenarios.py
e2e-privacy:  # account export + erasure across services (retention, tokens, bystander isolation)
	.venv/bin/python scripts/e2e_privacy.py
smoke:  # post-deploy read-only checks: FF_E2E_BASE_URL=https://api.example.com make smoke
	.venv/bin/python scripts/smoke_prod.py
audit:  # dependency vulnerability scan; non-fatal and skipped if pip-audit is not installed
	@if [ -x .venv/bin/pip-audit ]; then PA=.venv/bin/pip-audit; elif command -v pip-audit >/dev/null 2>&1; then PA=pip-audit; else echo "pip-audit not installed; skipping (pip install pip-audit)"; exit 0; fi; \
	for d in packages/py-common $(addprefix services/,$(SERVICES)); do echo "== $$d"; timeout 60 $$PA --progress-spinner off $$d || echo "audit: findings or offline for $$d (non-fatal)"; done; exit 0
compose-check:  # static, offline: compose files, prod secrets vs fail-closed guards, .env.example, Makefile, workflows
	.venv/bin/python scripts/check_compose.py
