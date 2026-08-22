# Contributing to PhantomCurl

Thanks for your interest in the project! Any help is welcome.

## Getting Started

1. Fork the repository.
2. Clone it locally: `git clone https://github.com/your_username/phantom-curl.git`
3. Create a virtual environment: `python -m venv .venv`.
4. Activate it. On PowerShell: `.venv\Scripts\Activate.ps1`; on POSIX shells: `source .venv/bin/activate`.
5. Install development dependencies: `python -m pip install -e ".[dev]"`.
6. Create a new branch for your feature or fix: `git checkout -b feature/my-cool-stuff`.

## Code Standards

- We use `ruff` for linting and formatting.
- Follow PEP 8.
- Type hints are mandatory (at least for the public API).
- All public methods must have docstrings in Google or Sphinx format.

## Testing

Before pushing, run:

```bash
python -m pytest -p no:cacheprovider
ruff check .
mypy phantom_curl
git diff --check
```

Write tests against the local HTTP server fixtures whenever networking behavior
is involved. Do not make the test suite depend on a live third-party website.

When a change adds or changes public behavior, update the README and the
relevant file in `docs/` in the same pull request.
