# Security policy

## Reporting a vulnerability

Do not open a public issue for a suspected vulnerability, exposed credential, private route, or
personal travel detail. Use GitHub's private vulnerability reporting for this repository instead:

<https://github.com/atos-og/flyclub/security/advisories/new>

Include the affected version or commit, a concise reproduction, the expected impact, and any safe
mitigation you already identified. Do not include real tokens, connection strings, chat IDs,
healthcheck URLs, private route configuration, or personal itinerary data in the report.

This is a personal open-source project maintained on a best-effort basis. Reports will be
acknowledged as soon as practical. A fix may be developed privately and released before technical
details are published.

## Supported version

Security fixes target the latest commit on `main`. Older commits and forks are not maintained.

## Deployment responsibility

Fly Club does not need credentials at build time. Operators are responsible for keeping runtime
values in an ignored local `.env`, a secrets manager, or GitHub Repository Secrets. Never place
credentials or personal routes in issues, pull requests, Actions inputs, logs, screenshots, or
example files.

If a credential may have been disclosed, revoke or rotate it immediately. Removing it from the
latest commit is not sufficient because Git history, caches, forks, logs, and pull-request refs may
retain the original value.
