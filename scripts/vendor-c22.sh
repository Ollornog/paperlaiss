#!/usr/bin/env bash
# C22 (Aussehen) ins Panel vendorn — Kopie im Repo statt `pip install c22 @ git+…`.
#
# Warum: Die kompilierten Style-Packs sind in C22 Build-Outputs (gitignored); ein Paket aus dem
# Git-Tag hätte kein Stylesheet, und das Panel käme still ungestaltet heraus. Ein Tailwind-Lauf im
# Docker-Bau zöge eine große Binary aus dem Netz. Also: eine Kopie, reproduzierbar über dieses
# Skript, mit festgehaltener Herkunft in HERKUNFT — dasselbe Muster, mit dem C22 Basecoat vendort.
#
# Aufruf:  scripts/vendor-c22.sh [pfad-zum-c22-checkout] [pack]
set -euo pipefail
cd "$(dirname "$0")/.."

quelle="${1:-../C22}"
pack="${2:-vega}"
ziel="panel/static/c22"

[ -d "$quelle/.git" ] || { echo "Kein C22-Checkout unter $quelle" >&2; exit 1; }
css="$quelle/c22/static/css/c22-$pack.css"
[ -f "$css" ] || { echo "Pack '$pack' nicht gebaut ($css fehlt) — in C22 'scripts/build-gallery.sh'." >&2; exit 1; }
for q in "$quelle"/c22/static/css/{tokens,components,input}.css; do
  if [ "$q" -nt "$css" ]; then
    echo "$(basename "$q") ist neuer als das gebaute Pack — erst in C22 'scripts/build-gallery.sh'." >&2
    exit 1
  fi
done

mkdir -p "$ziel/css" "$ziel/js" "$ziel/fonts"
cp "$css" "$ziel/css/c22.css"
cp "$quelle/c22/static/js/basecoat.all.min.js" "$quelle/c22/static/js/c22.js" "$ziel/js/"
cp "$quelle/c22/static/fonts/inter.woff2" "$ziel/fonts/"

stand="$(git -C "$quelle" describe --tags --always)"
sha="$(git -C "$quelle" rev-parse HEAD)"
cat > "$ziel/HERKUNFT" <<HERKUNFT
C22 — geteiltes Design-System (Aussehen). Kopie, nicht bearbeiten.

Stand:   $stand
Commit:  $sha
Pack:    $pack
Bezogen: $(date -I) durch scripts/vendor-c22.sh

Enthalten: css/c22.css (Pack), js/basecoat.all.min.js, js/c22.js, fonts/inter.woff2
(Inter, SIL Open Font License 1.1 — Lizenztext in fonts/OFL.txt).

Änderungen am Aussehen gehören nach C22, nicht hierher: eine Korrektur in dieser Kopie
wäre beim nächsten Vendor-Lauf wieder weg.
HERKUNFT
echo "C22 $stand ($pack) vendort nach $ziel"
