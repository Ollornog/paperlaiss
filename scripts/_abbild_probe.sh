#!/usr/bin/env bash
# Startprobe des Panel-Abbilds (PO 2026-10-11: Updates mergen selbst, wenn ein Test sie abnimmt).
#
# Ein Abbild, das baut, kann trotzdem nicht starten: ein Basis-Abbild mit anderer Python-Fassung,
# eine Abhängigkeit, die erst beim Import bricht. Der Bau allein nimmt deshalb weder das
# Basis-Abbild (Dependabot `docker`) noch panel/requirements.txt (Dependabot `uv`) ab. Diese Probe
# startet das Abbild im Betriebsmodus mit Anmeldung über TinySesam (lädt also die schwerste
# Abhängigkeit), ohne Netz nach draußen, und verlangt `/health` mit 200.
#
# Außerdem: das Panel läuft nicht als root (PO 2026-10-11), und die TinySesam-DB entsteht im /auth
# des Abbilds — ohne tmpfs davor, damit die Probe die Rechte des Abbilds prüft und nicht die eines
# frischen tmpfs (1777).
#
# Aufruf: scripts/_abbild_probe.sh [abbild]   (ohne Argument wird ./panel gebaut)
set -euo pipefail

abbild="${1:-}"
name="paperlaiss-probe-$$"
gebaut=""
if [ -z "$abbild" ]; then
  abbild="paperlaiss-panel:probe-$$"
  gebaut="$abbild"
  docker build -q -t "$abbild" ./panel >/dev/null
fi

aufraeumen() {
  docker rm -f "$name" >/dev/null 2>&1 || true
  [ -z "$gebaut" ] || docker image rm "$gebaut" >/dev/null 2>&1 || true
}
trap aufraeumen EXIT

# Nur Werte, die das Starten braucht; kein Anbieter ist erreichbar (--network none). Die App darf
# beim Start nicht nach draußen müssen — täte sie es, wäre das ein Befund.
docker run -d --name "$name" --network none \
  -e PANEL_AUTH=tinysesam \
  -e PANEL_BASE_URL=http://localhost:8400 \
  -e PANEL_OIDC_ISSUER=https://id.example.com \
  -e PANEL_OIDC_CLIENT_ID=startprobe \
  -e PANEL_OIDC_CLIENT_SECRET=nur-fuer-die-startprobe \
  "$abbild" >/dev/null

# Frist 60 s. /health von innen (ohne Netz gibt es kein Außen).
antwort=""
for _ in $(seq 1 60); do
  [ "$(docker inspect -f '{{.State.Running}}' "$name" 2>/dev/null)" = "true" ] \
    || { echo "Container läuft nicht mehr"; docker logs "$name" 2>&1 | tail -30; exit 1; }
  antwort="$(docker exec "$name" python -c "import urllib.request; r=urllib.request.urlopen('http://127.0.0.1:8400/health', timeout=3); print(r.status, r.read().decode().strip())" 2>/dev/null || true)"
  [ -n "$antwort" ] && break
  sleep 1
done
echo "/health: ${antwort:-keine Antwort}"
[ "${antwort%% *}" = "200" ] || { docker logs "$name" 2>&1 | tail -30; exit 1; }
uid="$(docker exec "$name" id -u)"
gid="$(docker exec "$name" id -g)"
[ "$uid" != "0" ] || { echo "Panel läuft als root (uid 0) — USER im Dockerfile fehlt"; exit 1; }
docker exec "$name" test -s /auth/tinysesam.db \
  || { echo "/auth/tinysesam.db fehlt — /auth im Abbild für uid $uid nicht schreibbar?"; docker logs "$name" 2>&1 | tail -30; exit 1; }
echo "Startprobe bestanden: $abbild antwortet, läuft als $uid:$gid."
