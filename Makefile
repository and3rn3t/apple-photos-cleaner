# Makefile for apple-photos-cleaner skill

PYTHON := python3
PYTEST := $(PYTHON) -m pytest
PIP := $(PYTHON) -m pip

.PHONY: help test coverage lint clean install

help:
	@echo "Apple Photos Cleaner - Makefile targets:"
	@echo "  make test       - Run tests"
	@echo "  make coverage   - Run tests with coverage report"
	@echo "  make lint       - Run code linting (if available)"
	@echo "  make clean      - Remove test artifacts"
	@echo "  make install    - Install test dependencies"

install:
	$(PIP) install -r requirements.txt

test:
	$(PYTEST) tests/ -v

coverage:
	$(PYTEST) tests/ -v --cov=scripts --cov-report=term-missing --cov-report=html

lint:
	@echo "Linting Python files..."
	@$(PYTHON) -m py_compile scripts/*.py tests/*.py || true

clean:
	rm -rf __pycache__ tests/__pycache__ scripts/__pycache__
	rm -rf .pytest_cache .coverage htmlcov
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete

.DEFAULT_GOAL := help
