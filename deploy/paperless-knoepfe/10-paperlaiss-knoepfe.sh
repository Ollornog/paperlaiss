#!/usr/bin/env bash
# paperlaiss — hängt die KI-/OCR-Knöpfe in die Dokumentansicht von Paperless-ngx ein.
#
# Läuft über den offiziellen Weg /custom-cont-init.d bei JEDEM Start des Paperless-Containers,
# also auch nach jedem Update — kein Fork, nichts zu mergen. Idempotent.
#
#   1. paperlaiss-knoepfe.js (Namen aus der Umgebung eingesetzt) → Static-Verzeichnis
#   2. eine <script>-Zeile vor </body> der Startseite (documents/templates/index.html)
#
# Findet es die Stelle nicht (Paperless hat die Seite umgebaut), meldet es das und endet mit 0:
# Paperless startet dann ohne Knöpfe, statt gar nicht.
set -euo pipefail

quelle="${PAPERLAISS_KNOEPFE_JS:-/paperlaiss-knoepfe/paperlaiss-knoepfe.js}"
static="${PAPERLESS_STATICDIR:-/usr/src/paperless/static}"
vorlage="/usr/src/paperless/src/documents/templates/index.html"
zeile="<script src=\"{% static 'paperlaiss-knoepfe.js' %}\" defer></script>"
p="[paperlaiss-knoepfe]"

if [ ! -f "$quelle" ]; then
  echo "$p $quelle fehlt — Knöpfe NICHT eingehängt (Volume prüfen)"
  exit 0
fi

# Namen einsetzen. Nur Buchstaben, Ziffern, Leer, Punkt, Binde- und Unterstrich zulassen:
# die Werte landen in einem JavaScript-String.
wert() {
  local v="${1:-$2}"
  if [[ ! "$v" =~ ^[[:alnum:]\ ._äöüÄÖÜß-]+$ ]]; then
    echo "$p unzulässiger Name '$v' — nehme '$2'" >&2
    v="$2"
  fi
  printf '%s' "$v"
}
redo="$(wert "${PAPERLAISS_REDO_TAG:-}" "KI-neu")"
ocr="$(wert "${PAPERLAISS_OCR_TAG:-}" "KI-OCR")"
feld="$(wert "${PAPERLAISS_HINWEIS_FELD:-}" "KI-Hinweis")"
sed -e "s/%%REDO_TAG%%/${redo}/" -e "s/%%OCR_TAG%%/${ocr}/" -e "s/%%HINWEIS_FELD%%/${feld}/" \
  "$quelle" > "$static/paperlaiss-knoepfe.js"
chmod 644 "$static/paperlaiss-knoepfe.js"

if grep -qF "paperlaiss-knoepfe.js" "$vorlage"; then
  echo "$p schon eingehängt"
elif grep -q '</body>' "$vorlage"; then
  sed -i "s#</body>#\t${zeile}\n</body>#" "$vorlage"
  echo "$p eingehängt (Tag '${redo}', OCR-Tag '${ocr}', Feld '${feld}')"
else
  echo "$p WARNUNG: kein </body> in $vorlage — Paperless hat die Seite umgebaut, Knöpfe fehlen"
fi
exit 0
