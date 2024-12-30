# Coding conventions used in this project

### Core Libraries

- Use Textual for TUI applications
- Use Pydantic for data models and validation
- Use SQLite for local caching
- Use loguru for logging
- Use icecream (`ic`) for debug printing

### Code Style

- Use Python 3.12+ features and type hints
- Prefer descriptive variable names over comments
- Avoid nested if statements, return early from functions
- Use Ruff for linting and formatting (configured in .pre-commit-config.yaml)

### Types

- Use type hints consistently
- Use Pydantic BaseModel for data structures
- Example from the codebase:
  ```python
  class Call(BaseModel):
      id: str
      Caller: str
      Transcript: str
      Summary: str
      Start: datetime
      End: datetime
      Cost: float = 0.0
      CostBreakdown: dict = {}
  ```

### TUI Conventions

- Use Textual's built-in styling system with CSS
- Standard key bindings:

  ```python
  BINDINGS = [
      Binding("q", "quit", "Quit"),
      Binding("j,down", "move_down", "Down"),
      Binding("k,up", "move_up", "Up"),
      Binding("g,g", "move_top", "Top"),
      Binding("G", "move_bottom", "Bottom"),
      Binding("tab", "focus_next", "Next Widget"),
      Binding("?", "help", "Help")
  ]
  ```

- Modal screens:

  - Inherit from `ModalScreen`
  - Use consistent styling:

    ```python
    CSS = """
    Screen {
        align: center middle;
        background: rgba(26, 27, 38, 0.85);
    }

    Container {
        background: #24283b;
        border: tall #414868;
        padding: 1;
    }
    """
    ```

- DataTable usage:
  - Add key parameter for row selection
  - Define columns explicitly
  - Example:
    ```python
    class CallTable(DataTable):
        def __init__(self):
            super().__init__(id="calls")
            self.cursor_type = "row"
            self.add_column("Time")
            self.add_column("Length")
            self.add_column("Cost")
    ```

### Testing

- Use pytest with pytest-xdist for parallel execution
- Use pytest-asyncio for async tests
- Test files should be named `test_*.py`
- Use async test fixtures with Textual:
  ```python
  @pytest.mark.asyncio
  async def test_something(app):
      async with app.run_test() as pilot:
          # Test code here
  ```

### Error Handling

- Use loguru for error logging
- Wrap main app entry points with `@logger.catch()`
- Use try/except blocks for external operations (file I/O, commands)

### Color Scheme

Use Tokyo Night theme colors:

- Background: #1a1b26
- Foreground: #c0caf5
- Accent: #7aa2f7
- Border: #414868
- Hover: #364a82
