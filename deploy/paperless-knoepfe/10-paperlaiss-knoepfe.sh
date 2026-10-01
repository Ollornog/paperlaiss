#!/usr/bin/env bash
# paperlaiss — hängt KI-Knopf, Export und Korrespondenten-Abschnitt in Paperless-ngx ein.
#
# Läuft über den offiziellen Weg /custom-cont-init.d bei JEDEM Start des Paperless-Containers,
# also auch nach jedem Update — kein Fork, nichts zu mergen. Idempotent.
#
#   1. paperlaiss-knoepfe.js (Namen aus der Umgebung eingesetzt) → Static-Verzeichnis
#   2. eine <script>-Zeile vor </head> der Startseite (documents/templates/index.html) — im Kopf,
#      damit sie VOR Paperless' eigenem main.js läuft (defer und module laufen in Dokumentreihenfolge):
#      das Skript hört die Listenantworten mit, und die erste kommt gleich nach dem Start.
#      Eine Zeile aus früheren Fassungen (vor </body>) wird dorthin umgezogen.
#
# Findet es die Stelle nicht (Paperless hat die Seite umgebaut), meldet es das und endet mit 0:
# Paperless startet dann ohne Knöpfe, statt gar nicht.
set -euo pipefail

quelle="${PAPERLAISS_KNOEPFE_JS:-/paperlaiss-knoepfe/paperlaiss-knoepfe.js}"
static="${PAPERLESS_STATICDIR:-/usr/src/paperless/static}"
vorlage="${PAPERLESS_INDEX_HTML:-/usr/src/paperless/src/documents/templates/index.html}"   # Umgebung nur für Tests
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

if ! grep -q '</head>' "$vorlage"; then
  echo "$p WARNUNG: kein </head> in $vorlage — Paperless hat die Seite umgebaut, Knöpfe fehlen"
  exit 0
fi
# Steht die Zeile schon im Kopf, ist nichts zu tun; sonst jede alte Zeile entfernen und neu setzen.
if grep -qF "paperlaiss-knoepfe.js" <<<"$(sed -n '1,/<\/head>/p' "$vorlage")"; then
  echo "$p schon eingehängt"
else
  sed -i '/paperlaiss-knoepfe\.js/d' "$vorlage"
  sed -i "s#</head>#\t${zeile}\n</head>#" "$vorlage"
  echo "$p eingehängt (Panel: ${url})"
fi
exit 0
