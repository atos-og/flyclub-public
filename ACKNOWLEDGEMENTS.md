# Acknowledgements

Fly Club is built with open-source software. Each dependency remains governed by its own license.

## Runtime dependencies

- [fli](https://github.com/punitarani/fli) — MIT; the primary unofficial Google Flights provider,
  pinned to a reviewed commit.
- [Psycopg](https://github.com/psycopg/psycopg) — LGPL-3.0; PostgreSQL connectivity.
- [Pydantic](https://github.com/pydantic/pydantic) — MIT; configuration validation.
- [python-dotenv](https://github.com/theskumar/python-dotenv) — BSD-3-Clause; ignored local
  environment loading.
- [PyYAML](https://github.com/yaml/pyyaml) — MIT; YAML configuration parsing.

## Development and automation

- [pytest](https://github.com/pytest-dev/pytest),
  [pytest-cov](https://github.com/pytest-dev/pytest-cov), and
  [Ruff](https://github.com/astral-sh/ruff) support testing, coverage, linting, and formatting.
- [actions/checkout](https://github.com/actions/checkout) and
  [actions/setup-python](https://github.com/actions/setup-python) support CI and deployment.
- [Gitleaks](https://github.com/gitleaks/gitleaks) — MIT; scans reachable public history for
  accidental credentials after its release checksum is verified.

Fly Club is not affiliated with or endorsed by Google, Google Flights, Telegram, Supabase,
Healthchecks.io, GitHub, or the maintainers of the projects listed above.
