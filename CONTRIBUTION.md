#### `CONTRIBUTING.md`
```markdown
# Contributing to PhantomCurl

Thanks for your interest in the project! Any help is welcome.

## Getting Started

1. Fork the repository.
2. Clone it locally: `git clone https://github.com/your_username/phantom-curl.git`
3. Create a virtual environment: `python -m venv venv && source venv/bin/activate`
4. Install dev dependencies: `pip install -e ".[dev]"`
5. Create a new branch for your feature/fix: `git checkout -b feature/my-cool-stuff`

## Code Standards

- We use `ruff` for linting and formatting.
- Follow PEP 8.
- Type hints are mandatory (at least for the public API).
- All public methods must have docstrings in Google or Sphinx format.

## Testing

Before pushing, make sure the tests pass:
```bash
pytest tests/