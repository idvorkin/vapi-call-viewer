# Calls App

A TUI (Text User Interface) application for managing and viewing call transcripts and summaries. Built with Python using Textual for the interface and SQLite for caching.

## Features

- View call transcripts and summaries
- Interactive TUI interface
- Call cost tracking and breakdown
- Local caching of call data
- Phone number formatting
- UTC to local time conversion

## Demo Video

[![Building a VAPI TUI to debug a 10$ API call](https://img.youtube.com/vi/hE-qimUbKdg/0.jpg)](https://www.youtube.com/watch?v=hE-qimUbKdg)

Watch a demonstration of the VAPI TUI application in action. This video shows how to use the interface to debug and analyze API calls.

Duration: 1:59

## Installation

### Using uv (Recommended)

```bash
uv pip install --editable .
```

## Usage

After installation, you can run the app using:

```bash
calls
```

### Key Bindings

- `q`: Quit the application
- `h`: Show help screen
- Arrow keys: Navigate through calls
- Enter: View call details
- `v`: View JSON and edit options

## Development

### Prerequisites

- Python 3.12+
- Development dependencies (install with `pip install -e ".[dev]"`)

### Running Tests

First install development dependencies:

```bash
uv pip install -e ".[dev]"
```

Run the test suite with:

```bash
pytest -n auto
```

This will run tests in parallel using pytest-xdist.

### Project Structure

- `calls.py`: Main application logic and TUI implementation
- `models.py`: Pydantic models for data structures
- `cache.py`: SQLite caching implementation
- `test_*.py`: Test files

## License

MIT License

## Contributing

1. Fork the repository
2. Create a feature branch
3. Commit your changes
4. Push to the branch
5. Create a Pull Request

## Cache Location

The application caches call data in:

```
{tempfile.gettempdir()}/vapi_calls.db
```

## Type Hints

This project uses Python 3.12+ type hints and follows strict typing conventions using Pydantic models for data structures.
