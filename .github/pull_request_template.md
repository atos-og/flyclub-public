## What changed

Describe the problem and the smallest change that solves it.

## Validation

List the checks you ran and their results.

## Public-safety checklist

- [ ] I did not add credentials, tokens, private keys, connection strings, chat IDs, account IDs,
      private healthcheck URLs, or production logs.
- [ ] I did not add a real `.env`, private configuration file, full personal itinerary, passenger
      details, or operational GitHub Actions input.
- [ ] Example dates, routes, prices, identifiers, and URLs are synthetic or intentionally public.
- [ ] New environment variables appear in `.env.example` with empty values only.
- [ ] Deployment workflows remain inert examples outside `.github/workflows`.
- [ ] I ran `python scripts/check_public_boundary.py`, tests, lint, and formatting checks.

If any credential may have been exposed, do not merge the pull request. Revoke or rotate the
credential and report the incident privately according to `SECURITY.md`.
