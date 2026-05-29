---
uuid: "orgs-open-hax-archived-voxx-kanban-orgs-open-hax-archived-voxx-specs-drafts-deploy-on-main-md"
title: "Voxx deploy on main"
status: incoming
priority: P3
labels: ["specs", "migrated-spec"]
created_at: "2026-05-29T04:01:22.560Z"
source: "orgs/open-hax/archived/voxx/specs/drafts/deploy-on-main.md"
category: "specs"
---

> Source: `orgs/open-hax/archived/voxx/specs/drafts/deploy-on-main.md`
> Migrated-to-kanban: `orgs/open-hax/archived/voxx/kanban/drafts/deploy-on-main.md`

# Voxx deploy on main

## Status
Complete

## Goal
Create a CI/CD pipeline so merges or pushes to `main` in the Voxx source repo can automatically validate, publish, and deploy Voxx to the remote host.

## Constraints
- Source-of-truth repo is `orgs/open-hax/voxx`.
- Production runtime currently lives in `~/devel/services/voxx` on the remote host.
- Deploys should use a prebuilt container image, not rebuild on the host.
- Deployment must preserve the remote host's existing runtime secrets in its local `.env`.
- The deploy pipeline must be safe for repeated pushes to `main`.

## Plan
1. Add a GitHub Actions workflow that runs tests and a Docker build smoke on PRs and pushes.
2. On pushes to `main`, build and push a GHCR image tagged with both `main` and the commit SHA.
3. Over SSH, update a remote deploy-pin file with the immutable SHA image tag.
4. On the remote host, source existing `.env` plus the deploy-pin file, pull the pinned image, restart Voxx without rebuilding, and verify `/healthz`.
5. Document required GitHub secrets/vars and remote host expectations.

## Risks
- Missing GHCR read credentials on the host would break pull-based deploys if the package is private.
- The remote host must already have a valid `services/voxx` runtime and Docker Compose installed.
- Overwriting the remote `.env` would be unsafe; use a separate deploy pin file instead.

## Affected files
- `orgs/open-hax/voxx/.github/workflows/voxx-main.yml`
- `orgs/open-hax/voxx/README.md`
- `services/voxx/README.md`

## Definition of done
- Pushes to `main` have a documented CI/CD workflow.
- The deploy uses immutable image tags.
- The remote deployment does not rebuild on-host.
- Health verification is part of deploy.

## Implementation notes
- Added `.github/workflows/voxx-main.yml` with test/smoke, publish, and deploy jobs.
- Publish job builds from `Dockerfile.compose` and pushes `main` + immutable `sha-<commit>` tags to GHCR.
- Deploy job writes a remote `.env.deploy` image pin, preserves the host `.env`, and runs `docker compose pull` + `up -d --no-build`.
- Updated operator docs in both `orgs/open-hax/voxx/README.md` and `services/voxx/README.md`.

## Verification
- `cd orgs/open-hax/voxx && pnpm test`
- `cd orgs/open-hax/voxx && docker build -f Dockerfile.compose -t voxx-ci-local:main-pipeline .`
- `python3 -c "import yaml, pathlib; print(yaml.safe_load(pathlib.Path('orgs/open-hax/voxx/.github/workflows/voxx-main.yml').read_text())['name'])"`
