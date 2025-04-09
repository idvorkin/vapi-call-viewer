install:
    uv venv
    . .venv/bin/activate
    uv pip install --editable .

global-install: install
    uv tool install --force --editable .

test:
    pytest -n auto
