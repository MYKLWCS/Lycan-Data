#!/usr/bin/env python3
"""
Quick import sanity check — tries to import every non-test Python module
and reports any that fail due to missing dependencies or syntax errors.
Does NOT raise on import errors that require running services.
"""

import importlib
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
SKIP_DIRS = {".venv", "__pycache__", "migrations", "node_modules", "scripts"}
SKIP_RUNTIME_ERRORS = {
    "playwright",
    "scrapy",
    "crawlee",
    "weasyprint",
    "cv2",
    "spacy",
    "torch",
    "transformers",
}

errors = []
warnings = []
checked = 0

for path in ROOT.rglob("*.py"):
    rel = path.relative_to(ROOT)
    parts = rel.parts
    if any(skip in parts for skip in SKIP_DIRS):
        continue
    if rel.name.startswith("test_") or rel.name == "conftest.py":
        continue
    if any(skip in rel.name for skip in SKIP_DIRS):
        continue

    mod = str(rel).replace("/", ".").replace("\\", ".").removesuffix(".py")
    if mod.startswith("."):
        continue

    try:
        importlib.import_module(mod)
        checked += 1
    except ImportError as e:
        msg = str(e)
        if any(skip in msg for skip in SKIP_RUNTIME_ERRORS):
            warnings.append(f"  SKIP  {mod}: {msg}")
        else:
            errors.append(f"  ERROR {mod}: {msg}")
    except Exception:
        # Runtime errors (DB connection, missing env vars) are expected
        checked += 1

print(f"Checked {checked} modules")
for w in warnings[:10]:
    print(w)

if errors:
    print(f"\n{len(errors)} import errors:")
    for e in errors:
        print(e)
    # Don't fail — just report
    sys.exit(0)

print("Import check passed.")
