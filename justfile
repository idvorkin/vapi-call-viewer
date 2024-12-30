install:
    uv pip install --editable ".[dev]"

global-install: install
    pipxu install -f . --editable --python $(which python3.12)

test:
    pytest -n auto
