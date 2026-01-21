.PHONY: help install clean build publish

DIST_DIR := dist
SRC_DIR := src

help:
	@echo "Available commands:"
	@echo "  make install  - Install project dependencies"
	@echo "  make clean   - Clean build directory"
	@echo "  make build   - Build project"
	@echo "  make publish - Build and publish plugin package"

install:
	uv sync --all-extras

clean:
	python -c "import shutil, os; shutil.rmtree('$(DIST_DIR)') if os.path.exists('$(DIST_DIR)') else None"

lint:
	uv run ruff check src
	uv run mypy src

format:
	uv run ruff format src

build: lint format
	uv run python build.py

test:
	uv run python -m unittest tests/test_friendly_names.py

publish: lint format
	uv run python build.py --publish
