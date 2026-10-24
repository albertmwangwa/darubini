.DEFAULT_GOAL := help
PY ?= python3
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help setup lint format typecheck security test check data data-extended datasets serve docker clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

setup: ## Create .venv, install dev deps and git hooks
	$(PY) -m venv $(VENV)
	$(BIN)/pip install -U pip
	$(BIN)/pip install -e ".[dev,notebooks]"
	$(BIN)/pre-commit install

lint: ## Ruff lint + format check
	$(BIN)/ruff check .
	$(BIN)/ruff format --check .

format: ## Auto-fix lint and format
	$(BIN)/ruff check --fix .
	$(BIN)/ruff format .

typecheck: ## Mypy strict
	$(BIN)/mypy

security: ## Bandit + pip-audit
	$(BIN)/bandit -c pyproject.toml -r src
	$(BIN)/pip freeze --exclude-editable > .audit-requirements.txt
	$(BIN)/pip-audit --strict -r .audit-requirements.txt
	rm -f .audit-requirements.txt

test: ## Pytest with coverage gate
	$(BIN)/pytest

check: lint typecheck security test ## Everything CI runs

datasets: ## List datasets in the manifest
	$(BIN)/darubini datasets

data: ## Download core datasets (~6.5 GB) into datasets/raw/
	$(BIN)/darubini download --tier core

data-extended: ## Core + extended datasets
	$(BIN)/darubini download --tier extended

serve: ## Run the API on http://127.0.0.1:8000 (docs at /docs)
	$(BIN)/darubini serve --reload

docker: ## Build the container image
	docker build -t darubini:local .

clean: ## Remove caches and build output
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov coverage.xml dist build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
