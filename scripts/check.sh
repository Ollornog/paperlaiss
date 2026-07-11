#!/usr/bin/env bash
# Das Tor vor jedem Push: Fach- und Hygiene-Tests.
#
#   scripts/check.sh            # alles
#   scripts/check.sh --fast     # (hier gleichbedeutend — es gibt keinen Browser-Test)
#
# Der pre-push-Hook (.githooks/pre-push) ruft dieses Skript. Einmalig pro Klon:
#   git config core.hooksPath .githooks
#
# Der Klassifizierer ist stdlib-only; die Suite braucht kein installiertes Paket und kein Netz.
set -euo pipefail

cd "$(dirname "$0")/.."
FAST=0
[[ "${1:-}" == "--fast" ]] && FAST=1

step() { printf '\n\033[1m▸ %s\033[0m\n' "$1"; }
fail() { printf '\n\033[31m✗ %s\033[0m\n' "$1" >&2; exit 1; }

PY="${PYTHON:-$(command -v python3 || true)}"
[[ -n "$PY" && -x "$PY" ]] || fail "Kein python3 gefunden."
step "Interpreter: $("$PY" -c 'import sys; print(sys.executable)')"

if [[ $FAST -eq 1 ]]; then
    step "Suiten (--fast) — Fach- und Hygiene-Test"
    "$PY" tests/run_all.py --no-browser || fail "Testsuite"
else
    step "Alle Suiten — Fach- und Hygiene-Test"
    "$PY" tests/run_all.py || fail "Testsuite"
fi

step "Beispiel-Config ist gültiges JSON"
"$PY" -c "import json; json.load(open('classify-config.json'))" || fail "classify-config.json"

printf '\n\033[32m✓ Alles grün\033[0m\n'
