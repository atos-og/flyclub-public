# Public release and private operation

Fly Club separates portfolio source code from the owner's personal deployment. Public visibility
must never make private routes, workflow inputs, logs, credentials, or retained Git references
public.

## Repository model

- During public preview, `flyclub-public` is the canonical source for application code, tests,
  synthetic examples, architecture, and public CI. It may be renamed to `flyclub` during the final
  V1 migration.
- A separate private deployment repository owns enabled schedules, personal manual runs, private
  Actions logs, and Repository Secrets. It consumes a reviewed public Fly Club release or commit.
- Neither repository versions credentials or real route configuration.

This boundary keeps normal open-source development public while preserving the confidentiality of
the owner's operational data.

## Visibility and release timing

Public visibility and the V1 release are separate milestones. A sanitized source repository may be
made visible as a **public preview** once its complete reachable history is scanned, production
workflows and data are absent, public CI passes, and the private operational repository remains
private. A preview is not a claim that the V1 scoring review is complete.

The V1 release remains gated on the 30-day `daily-median-v2` shadow review, whose earliest valid
review date is 2026-09-14. If that review causes a scoring or alert-policy change, the new behavior
must pass CI and run stably in the private deployment before a V1 tag is created. The preferred V1
release window is 2026-09-21 through 2026-09-30; reaching a calendar date never overrides a failed
security or reliability gate.

## One-time migration

1. Build a new private public-release candidate from the clean `main` branch only. Never mirror
   pull-request refs, remote branches, Actions artifacts, or old repository metadata.
2. Remove enabled production schedules and workflows that accept personal inputs. Keep public CI
   and sanitized deployment examples only.
3. Scan every reachable candidate commit and file for credentials and personal configuration.
4. Create the private deployment repository and validate it against an immutable candidate commit.
5. Rotate the database credential, Telegram bot token, healthcheck URL, and external scheduler
   token; configure only the private deployment repository with their replacements.
6. Confirm one complete monitor cycle, one health heartbeat, and safe aggregate-only logs.
7. Enable branch protection, required CI, Dependabot, secret scanning, push protection, code
   scanning, and private vulnerability reporting on the public candidate.
8. Review README, license, acknowledgements, screenshots, issues, releases, Actions artifacts, and
   repository metadata manually.
9. Rename repositories only after both sides pass the go/no-go checklist. Keep any historical
   repository with private operational refs permanently private.

## Public-preview go/no-go checklist

Public visibility is allowed only when all answers are yes:

- Is the candidate built without historical production pull-request refs?
- Do automated and manual scans find no real secrets or personal itinerary data?
- Are production workflows, configuration, credentials, logs, and artifacts absent?
- Do tests, lint, formatting, dependency checks, and the full-history secret scan pass?
- Are the MIT license, security policy, contribution guide, acknowledgements, README, and preview
  status current?
- Does the private production repository remain private and operationally independent?

## V1 release go/no-go checklist

Creating the V1 release/tag is allowed only when all answers are yes:

- Is the 30-day Deal Score v2 review complete and documented?
- Is the candidate built without historical PR refs or non-main branches?
- Do automated and manual scans find no real secrets or personal itinerary data?
- Are every production credential and private endpoint rotated after the split?
- Are production workflows and logs private while public workflows use only synthetic data?
- Do tests, lint, formatting, dependency checks, and code scanning pass?
- Are the MIT license, security policy, contribution guide, acknowledgements, and README current?
- Has a clean-room installation succeeded using only public documentation?
- Has the private deployment completed a real cycle from the exact public candidate revision?

After public visibility, normal development continues through public branches and pull requests. A
secret accidentally committed to a public branch is considered compromised and must be rotated;
deleting it in a later commit is not remediation.
