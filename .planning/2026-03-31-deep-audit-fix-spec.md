## Objective

Close the remaining deep-audit gaps in Lycan by removing dormant paid execution paths, surfacing silent runtime failures, and making the audit script verify against the repo's actual Python environment.

## Acceptance Criteria

- `scripts/audit.py` uses the project virtualenv when available and reports real pytest collection results.
- Silent `except ...: pass` paths in startup/shutdown and enrichment code are replaced with explicit logging or equivalent non-silent control flow.
- Paid-only crawler execution paths are disabled so the runtime no longer uses ATTOM API or DeHashed credentials.
- Breach aggregation metadata no longer treats retired paid/legacy crawlers as active breach platforms.
- Targeted tests covering the touched runtime paths pass.
- A follow-up audit completes without surfacing the previously known residual gaps.

## Affected Files / Systems

- `/Users/michaelwolf/Documents/Lycan-Data/scripts/audit.py`
- `/Users/michaelwolf/Documents/Lycan-Data/api/main.py`
- `/Users/michaelwolf/Documents/Lycan-Data/modules/enrichers/genealogy_enricher.py`
- `/Users/michaelwolf/Documents/Lycan-Data/modules/enrichers/biographical.py`
- `/Users/michaelwolf/Documents/Lycan-Data/modules/crawlers/property/attom_gateway.py`
- `/Users/michaelwolf/Documents/Lycan-Data/modules/crawlers/email_dehashed.py`
- `/Users/michaelwolf/Documents/Lycan-Data/modules/pipeline/aggregator.py`
- `/Users/michaelwolf/Documents/Lycan-Data/shared/config.py`
- related targeted tests under `/Users/michaelwolf/Documents/Lycan-Data/tests/`

## Verification Plan

- `python3 -m py_compile` on all touched Python files
- `.venv/bin/python -m pytest` on targeted crawler, pipeline, and audit-adjacent tests
- `python3 scripts/audit.py`
- inspect `git status --short` before staging and commit

## Risk Notes

- ATTOM and DeHashed have broad existing test coverage, so disabling paid paths requires keeping compatibility surfaces stable enough for the rest of the repo.
- Date parsing fallback behavior in `biographical.py` must remain permissive even after removing silent `pass` branches.
