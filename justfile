install:
    uv venv
    . .venv/bin/activate
    uv pip install --editable .

global-install: install
    uv tool install --force --editable --python $(which python3.12) .

test:
    pytest -n auto
