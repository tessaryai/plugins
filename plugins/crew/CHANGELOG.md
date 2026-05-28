# Changelog

All notable changes to the `crew` plugin are documented here. This project
follows [semantic versioning](https://semver.org/).

## [0.1.0] — unreleased

Initial local-first release.

### Added

- **Orchestrator** (`/crew:run`) — goal-driven conductor that surveys repo state,
  plans a bounded sequence of primitives via the lifecycle state machine, dispatches
  them, and loops until the goal is met or a guardrail stops it. Runs unattended,
  supports `--dry-run`, and never merges (ceiling = review-ready PR).
- **Triage** — `/crew:triage-bug` and `/crew:triage-task` enrich issues with
  codebase context and apply the `triaged` label.
- **Implementation** — `/crew:implement-issue` convenes a deliberative team
  (architect, pragmatist, perf-analyst, visionary, product-advocate) and opens a PR.
- **Review** — `/crew:review-pr` posts a structured review; `/crew:respond-to-review`
  addresses feedback with a capped iteration loop.
- **Docs & knowledge** — `/crew:update-docs` and `/crew:manage-knowledge`.
- **Maintenance** — `/crew:process-backlog` and `/crew:spring-cleaning`.
- **Configuration** — `/crew:init-config`, layered `crew.config.yaml` →
  `AGENTS.md`/`CLAUDE.md` → built-in defaults, resolved by `lib/load_config.py`.

### Not yet included

- GitHub Actions packaging (workflow templates + `/crew:install-ci`) — planned for
  a later release. This version is local-only.
