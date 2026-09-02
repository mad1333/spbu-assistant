# Contributing

Thank you for helping improve SPbU Assistant.

## Development setup

Use Python 3.12 or newer. Create a virtual environment and install the project
with development dependencies:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
```

Run the checks before submitting a change:

```bash
ruff format --check .
ruff check .
pytest
```

## Pull requests

- Keep each pull request focused on one change.
- Add or update tests for changed behaviour.
- Do not commit credentials, tokens, private calendar links, email content, or
  production configuration.
- Describe user-visible changes and any migration or deployment requirements.
- Preserve backward compatibility unless the change clearly documents why it
  cannot be maintained.

By contributing, you agree that your contribution is licensed under the MIT
License included in this repository.
