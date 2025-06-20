install:
    uv sync

global-install:
    uv tool install --force --editable .

test:
    uv run pytest -n auto

dev:
    uv sync --dev

lock:
    uv lock

clean:
    rm -rf .venv
    rm -f uv.lock

format:
    uv run ruff format .
    uv run ruff check --fix .

lint:
    uv run ruff check .
