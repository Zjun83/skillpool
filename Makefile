# ── SkillPool v4.1.0 Makefile ─────────────────────────────────────
# Quick commands: make help | make dev | make test | make build
# ──────────────────────────────────────────────────────────────────

.PHONY: help dev run test lint fmt build docker up down clean

# ── Defaults ──────────────────────────────────────────────────────
PYTHON      ?= python3
VENV        := .venv
PIP         := $(VENV)/bin/pip
PYTHON_VENV := $(VENV)/bin/python
PORT        ?= 8000

# ── Help ──────────────────────────────────────────────────────────
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# ── Setup ─────────────────────────────────────────────────────────
venv: ## Create virtual environment
	$(PYTHON) -m venv $(VENV)
	$(PIP) install --upgrade pip

install: venv ## Install dependencies
	$(PIP) install -e ".[dev]"

# ── Development ───────────────────────────────────────────────────
dev: install ## Install + run dev server
	$(PYTHON_VENV) -m skillpool serve --reload --port $(PORT)

run: ## Run production server
	$(PYTHON_VENV) -m skillpool serve --port $(PORT)

# ── Testing ───────────────────────────────────────────────────────
test: ## Run all tests
	$(PYTHON_VENV) -m pytest tests/ -v --tb=short

test-cov: ## Run tests with coverage
	$(PYTHON_VENV) -m pytest tests/ -v --cov=skillpool --cov-report=term-missing

# ── Code Quality ──────────────────────────────────────────────────
lint: ## Run linters
	$(PYTHON_VENV) -m ruff check src/ tests/
	$(PYTHON_VENV) -m mypy src/

fmt: ## Auto-format code
	$(PYTHON_VENV) -m ruff format src/ tests/
	$(PYTHON_VENV) -m ruff check --fix src/ tests/

# ── Docker ────────────────────────────────────────────────────────
build: ## Build Docker image
	docker build -t skillpool:4.1.0 .

docker: build ## Build + run in Docker
	docker run -d --name skillpool -p $(PORT):8000 -v skillpool-data:/data skillpool:4.1.0

up: ## Start via docker-compose
	docker compose -f deploy/docker-compose.yml up -d

down: ## Stop docker-compose
	docker compose -f deploy/docker-compose.yml down

# ── Cleanup ───────────────────────────────────────────────────────
clean: ## Remove build artifacts
	rm -rf build/ dist/ *.egg-info .pytest_cache .mypy_cache .ruff_cache
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

clean-all: clean ## Remove venv + data too
	rm -rf $(VENV) .data/ data/
