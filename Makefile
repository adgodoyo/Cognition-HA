PYTHON ?= $(shell command -v python3.12 || command -v python3.11 || command -v python3)
VENV := .venv
BIN := $(VENV)/bin
HOST ?= 127.0.0.1
PORT ?= 8000

.PHONY: dev demo reset test token

$(BIN)/activate: requirements.txt
	@$(PYTHON) -m venv $(VENV)
	@$(BIN)/pip install -q --disable-pip-version-check -r requirements.txt
	@touch $(BIN)/activate

dev: $(BIN)/activate  ## serve with auto-reload (DEMO_MODE on)
	DEMO_MODE=1 $(BIN)/uvicorn app_main:create_app --factory --reload --host $(HOST) --port $(PORT)

demo: $(BIN)/activate reset  ## reset demo data, then serve on http://localhost:8000
	DEMO_MODE=1 $(BIN)/uvicorn app_main:create_app --factory --host $(HOST) --port $(PORT)

reset: $(BIN)/activate  ## rebuild data/platform.db and data/ledger.db from seed/
	@$(BIN)/python app_main.py reset

test: $(BIN)/activate
	$(BIN)/pytest

token: $(BIN)/activate  ## make -s token user=<username>
	@$(BIN)/python app_main.py token $(user)
