SERVICES := gateway sourcing logistics geo trust rfq messaging tracking notifications assistant demand
.PHONY: venv test lint dev down $(addprefix test-,$(SERVICES))
venv:
	python3 -m venv .venv && .venv/bin/pip install -q fastapi "uvicorn[standard]" pydantic pydantic-settings httpx sqlalchemy aiosqlite greenlet pyjwt bcrypt email-validator websockets pytest pytest-asyncio respx ruff pyyaml
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
