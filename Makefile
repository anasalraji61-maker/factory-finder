SERVICES := gateway sourcing logistics geo trust rfq messaging tracking notifications assistant demand payments media
.PHONY: venv test lint dev down compose-e2e e2e $(addprefix test-,$(SERVICES))
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
