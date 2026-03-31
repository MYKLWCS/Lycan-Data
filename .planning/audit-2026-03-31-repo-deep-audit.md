# Repo Deep Audit Spec

## Objective

Perform a repo-wide failure audit of Lycan-Data to determine why the platform does not fully work in practice, with special focus on why crawler coverage, crawler execution, and crawler bypass behavior fail to deliver the promised results.

## Context

- The repo claims 150+ to 180+ crawlers, recursive search, SSE progress, anti-bot bypass, and government-grade reliability.
- The local planning docs already note unresolved crawler bypass issues and stale or mismatched documentation paths.
- The user request is not for a feature build. It is for a deep audit that traces surface failures down to architectural and implementation-level root causes.

## Acceptance Criteria

- Identify the highest-severity repo failures that prevent the platform from working as claimed.
- Identify crawler-specific blockers across registration, orchestration, anti-bot handling, proxies, Playwright/FlareSolverr/Tor usage, timeouts, and result persistence.
- Distinguish between:
  - broken code paths
  - missing or stubbed functionality
  - architecture mismatches
  - environment or operational prerequisites
  - documentation/spec drift
- Back findings with concrete file references and, where practical, verification evidence from tests or runtime commands.
- Produce a severity-ordered audit summary with residual risks and the next best remediation path.

## Affected Systems

- `api/`
- `modules/crawlers/`
- `modules/builder/`
- `modules/discovery/`
- `modules/enrichers/`
- `shared/`
- `worker.py`
- `lycan.py`
- `README.md`
- `.planning/`
- `docs/superpowers/specs/`

## Investigation Tracks

1. Contract drift
   - Compare repo claims, spec docs, and planning docs against actual file layout and behavior.
2. Crawler inventory integrity
   - Confirm whether crawlers register, import, expose a compatible interface, and are reachable from API, worker, and CLI entry points.
3. Orchestration and execution
   - Trace how crawlers are selected, run, timed out, retried, circuit-broken, and reported.
4. Anti-bot and bypass stack
   - Inspect Tor, proxy pool, FlareSolverr, Playwright, stealth wrappers, cookie handling, and fallbacks.
5. Result ingestion and user-visible completeness
   - Determine whether crawler results are persisted, indexed, deduplicated, and surfaced with correct failure reporting.
6. Verification reality
   - Run the strongest practical local verification available and use failures as audit signals.

## Verification Plan

- Read canonical planning and spec docs actually present in the repo.
- Inspect core crawler framework files and representative crawler implementations.
- Run targeted static checks:
  - registry and import path inspection
  - interface mismatch search
  - anti-bot dependency search
  - broad exception and silent failure search
- Run practical verification commands if the environment allows:
  - `pytest`
  - targeted `pytest` on crawler and search pipeline tests
  - `python -m compileall` or equivalent importability checks if needed
- Record what could not be verified due to environment or missing services.

## Risks

- Test results may be limited by missing local services or secrets.
- Some crawler failures may be operational rather than code defects, so the audit must separate configuration gaps from design flaws.
- Large repository size requires prioritization toward execution-critical paths instead of line-by-line review of every module.

## Suggested Model Split

- Tier 3: write the audit spec, cross-system reasoning, final audit synthesis.
- Tier 2 or below: not used here because delegation is not explicitly requested in this session.
