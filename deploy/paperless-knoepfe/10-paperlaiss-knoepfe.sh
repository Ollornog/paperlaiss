#!/usr/bin/env bash
# paperlaiss — hängt KI-Knopf und Korrespondenten-Abschnitt in Paperless-ngx ein.
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

# Adresse des Panels aus Sicht des Browsers. Hinter demselben Reverse-Proxy genügt ein Pfad
# ("/paperlaiss"); im Testbett mit getrenntem Port die volle Adresse. Nur Zeichen einer URL
# zulassen — der Wert landet in einem JavaScript-String.
url="${PAPERLAISS_URL:-/paperlaiss}"
if [[ ! "$url" =~ ^(https?://[A-Za-z0-9.:-]+)?(/[A-Za-z0-9._/-]*)?$ ]]; then
  echo "$p unzulässige PAPERLAISS_URL '$url' — Knöpfe NICHT eingehängt"
  exit 0
fi
sed -e "s#%%PAPERLAISS_URL%%#${url}#" "$quelle" > "$static/paperlaiss-knoepfe.js"
chmod 644 "$static/paperlaiss-knoepfe.js"

if grep -qF "paperlaiss-knoepfe.js" "$vorlage"; then
  echo "$p schon eingehängt"
elif grep -q '</body>' "$vorlage"; then
  sed -i "s#</body>#\t${zeile}\n</body>#" "$vorlage"
  echo "$p eingehängt (Panel: ${url})"
else
  echo "$p WARNUNG: kein </body> in $vorlage — Paperless hat die Seite umgebaut, Knöpfe fehlen"
fi
exit 0
