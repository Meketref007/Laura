.PHONY: test test-quick lint format typecheck clean install dev docker docker-build pre-commit help

help:
	@echo "Laura — Comandos disponiveis:"
	@echo "  make install     Instalar dependencias (editable)"
	@echo "  make dev         Instalar dev extras (test, lint)"
	@echo "  make test        Rodar todos os testes"
	@echo "  make test-quick  Rodar testes rapidos (exceto lentos)"
	@echo "  make lint        Rodar ruff lint"
	@echo "  make format      Rodar ruff format"
	@echo "  make typecheck   Rodar mypy (se instalado)"
	@echo "  make clean       Limpar caches Python"
	@echo "  make docker      Build + run Docker Compose"
	@echo "  make docker-build Build imagem Docker"
	@echo "  make pre-commit  Instalar pre-commit hooks"

install:
	pip install -e .

dev:
	pip install -e ".[dev]"

test:
	python -m pytest tests/ -q --tb=short --ignore=tests/_archive -k "not test_memory_summary_command"

test-quick:
	python -m pytest tests/ -q --tb=short --ignore=tests/_archive -k "not test_memory_summary_command" --timeout=30 -x

lint:
	ruff check shopee_agent/ --line-length=120

format:
	ruff format shopee_agent/ --line-length=120

typecheck:
	mypy shopee_agent/ --ignore-missing-imports || true

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	rm -rf .pytest_cache/ .ruff_cache/ 2>/dev/null || true

docker-build:
	docker build -t laura:latest .

docker:
	docker-compose up --build -d

pre-commit:
	pre-commit install
	pre-commit install --hook-type pre-push
