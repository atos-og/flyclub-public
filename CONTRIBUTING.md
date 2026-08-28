# Contributing to Fly Club

Thank you for helping improve Fly Club. Small, focused pull requests with deterministic tests are
preferred.

## Before opening an issue or pull request

- Never include real credentials, `.env` contents, chat IDs, database URLs, healthcheck URLs,
  private keys, account identifiers, or production logs.
- A destination name by itself may be discussed intentionally. Do not include a complete personal
  itinerary, private dates, passenger details, or operational configuration in public material.
- Reproduce route-related behavior with synthetic dates, destinations, and prices.
- Report security concerns privately as described in [SECURITY.md](SECURITY.md).
- Keep provider-specific types inside the provider adapter boundary.
- Use `Decimal` for money and preserve prior-only statistical baselines.

## Development

Use Python 3.12 or newer:

```bash
python -m venv .venv
python -m pip install -e ".[dev]"
pytest
ruff check .
ruff format --check .
python scripts/check_public_boundary.py
```

The public `config/routes.example.yaml` is synthetic. Copy it to the ignored
`config/routes.yaml` for local experiments and replace values only in that ignored file.

Use conventional-style commit subjects such as `feat:`, `fix:`, `docs:`, and `test:`. Explain
material product or architecture trade-offs in the pull request. All CI checks must pass before a
change is merged.

GitHub Secret Scanning with push protection is enabled, and Gitleaks scans the complete reachable
history on every branch push and pull request. These controls complement careful review; they do
not make a committed credential safe. If one is exposed, revoke or rotate it immediately.

## Scope

Fly Club is a personal opportunity radar, not a booking engine or travel agency. New dependencies,
providers, paid services, browser automation, machine learning, notification channels, or major
architecture changes should be discussed before implementation.
