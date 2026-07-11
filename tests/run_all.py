#!/usr/bin/env python3
"""Sammellauf: führt jede tests/test_*.py aus und meldet eine Bilanz.

  python tests/run_all.py                # alles
  python tests/run_all.py --no-browser   # ohne Browser-Test (kurze Schleife)

Exit 0 nur, wenn jede Suite grün ist. Übersprungene Suiten sind kein Fehler.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
skip_browser = "--no-browser" in sys.argv

suiten = sorted(HERE.glob("test_*.py"))
if skip_browser:
    suiten = [s for s in suiten if s.name != "test_browser.py"]

rot: list[str] = []
for suite in suiten:
    print(f"\n\033[1m▸ {suite.name}\033[0m", flush=True)
    code = subprocess.run([sys.executable, str(suite)], cwd=HERE.parent).returncode
    if code != 0:
        rot.append(suite.name)

print("\n" + "─" * 60)
if rot:
    print(f"\033[31m✗ {len(rot)} von {len(suiten)} Suiten rot: {', '.join(rot)}\033[0m")
    sys.exit(1)
print(f"\033[32m✓ {len(suiten)} Suiten grün\033[0m")
