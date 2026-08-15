# External scheduling

Fly Club keeps GitHub's native `schedule` as a fallback, but can use cron-job.org as the primary
90-minute trigger through GitHub's `workflow_dispatch` API. GitHub documents that scheduled runs
can be delayed or even dropped during high load, while the dispatch endpoint directly creates a
workflow run.

References:

- [GitHub workflow dispatch API](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event)
- [GitHub scheduled workflow delays](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows#scheduled-workflows-running-at-unexpected-times)
- [cron-job.org custom requests](https://cron-job.org/EN/)

## Security model

Create a fine-grained personal access token named `FLYCLUB_GITHUB_ACTIONS_TOKEN` in your password
manager. The label is documentation only: never add its value to this repository, `.env`, route
configuration, GitHub Actions logs, or a GitHub Repository Secret. The external scheduler must hold
the credential because GitHub Secrets cannot be read outside a running workflow.

Use these token settings:

1. GitHub → Settings → Developer settings → Personal access tokens → Fine-grained tokens.
2. Resource owner: `atos-og`.
3. Repository access: **Only select repositories** → `flyclub`.
4. Repository permissions: **Actions: Read and write**; leave every other permission at its
   minimum/default value.
5. Set a finite expiration and add a calendar reminder to rotate it.

GitHub requires `Actions: write` for the workflow-dispatch endpoint. Revoking this token disables
only the external trigger; the native fallback remains available.

## cron-job.org setup

Create a free cron-job.org account, enable MFA, and create two grouped jobs. Together they generate
the same 16 daily triggers as sixteen individual jobs and take less time to maintain.

Both jobs use:

- URL: `https://api.github.com/repos/atos-og/flyclub/actions/workflows/monitor.yml/dispatches`
- Method: `POST`
- Timezone: `America/Sao_Paulo`
- Days/months/weekdays: every value
- Request body: `{"ref":"main"}`
- Save response body: disabled

Custom headers:

```text
Accept: application/vnd.github+json
Authorization: Bearer <FLYCLUB_GITHUB_ACTIONS_TOKEN>
Content-Type: application/json
X-GitHub-Api-Version: 2022-11-28
```

Schedules in Brasília time:

| Job | Minute | Hours |
|---|---:|---|
| Fly Club primary A | 17 | 00, 03, 06, 09, 12, 15, 18, 21 |
| Fly Club primary B | 47 | 01, 04, 07, 10, 13, 16, 19, 22 |

If the console cannot select several hours in one job, create sixteen jobs instead, one for each
displayed time. Do not paste the token into the URL or request body.

## Validation and fallback

1. Use cron-job.org's test-run function on one job.
2. Confirm a new `workflow_dispatch` run appears in GitHub Actions.
3. Confirm the monitor succeeds and Healthchecks records a normal start/completion pair.
4. Enable both cron jobs.

The native GitHub schedules run 30 minutes after each desired external time. Before doing real
work, a scheduled fallback checks for a recent successful, queued, or running external dispatch.
It exits without provider calls, database writes, Telegram delivery, or Healthchecks pings when
the primary already ran. If the GitHub API check itself fails, the fallback runs to favor
availability.

Expected native fallback times in Brasília are 00:47, 02:17, 03:47, 05:17, 06:47, 08:17, 09:47,
11:17, 12:47, 14:17, 15:47, 17:17, 18:47, 20:17, 21:47, and 23:17.
