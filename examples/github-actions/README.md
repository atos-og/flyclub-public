# Private deployment workflow templates

These files are intentionally named `*.example.yml` and stored outside `.github/workflows`, so
GitHub does not execute them in the public source repository.

To operate a personal Fly Club instance:

1. Create a separate private deployment repository.
2. Copy only the templates you need into its `.github/workflows` directory and remove the
   `.example` segment from each filename.
3. Add these private repository variables:
   - `FLYCLUB_SOURCE_REPOSITORY`, for example `OWNER/flyclub`;
   - `FLYCLUB_SOURCE_REF`, set to a reviewed immutable tag or full commit SHA.
4. Add the required Repository Secrets described in the root README. Never use variables for
   credentials or route YAML.
5. Review every trigger and permission, then run a manual validation before enabling schedules.

The checkout step reads public source at the pinned revision without persisting Git credentials.
The workflows' Actions logs, manual inputs, schedules, and secrets remain private. Updating public
`main` does not update production automatically: promotion requires changing
`FLYCLUB_SOURCE_REF` after tests and review.
