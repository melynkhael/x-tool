# Contributing to X-Tool

Thanks for your interest in contributing! Here's how to get started.

## Development Setup

```bash
git clone https://github.com/melynkhael/x-tool.git
cd x-tool
python -m pip install -e ".[dev]"
```

## Running Tests

```bash
pytest -x --tb=short
```

All tests must pass before submitting a PR.

## Code Style

- Python 3.9+ compatible.
- Use type hints where practical.
- Follow existing patterns in the codebase.
- Keep imports sorted (stdlib, third-party, local).

## Pull Requests

1. Fork the repo and create a feature branch.
2. Make focused, incremental changes.
3. Add tests for new functionality.
4. Update CHANGELOG.md.
5. Open a PR with a clear description of what and why.

## Reporting Issues

- Check existing issues first.
- Include: Python version, OS (Termux/Linux/macOS), error output.
- For X API changes: include the HTTP status code and (sanitized) response body.

## Security

If you find a security vulnerability, please report it privately.
See [SECURITY.md](SECURITY.md).

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
