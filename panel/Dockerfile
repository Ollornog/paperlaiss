# Per DIGEST gepinnt, nicht per Tag: `python:3.14-slim` zeigt heute hierhin und morgen woanders —
# zwei Bauläufe desselben Commits ergäben verschiedene Abbilder. Dependabot (docker, /panel) hebt
# den Digest; ein Basisabbild-Wechsel wird von Hand gemergt.
FROM python:3.14-slim@sha256:f85c5697265c178cc6887276c55fe16cf3d14ca35c3df6a5eab3b360534a55d2
# Schrift für das Inhaltsverzeichnis des Export-Knopfs: DejaVu Sans deckt Umlaute, €, Ost- und
# Südosteuropäisches, Griechisch und Kyrillisch ab (ohne sie fällt exportpdf.py auf Helvetica zurück,
# die nur Windows-1252 kann).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
# Genau, was requirements.txt festschreibt: jede Abhängigkeit mit Version UND Prüfsumme, die
# Unterabhängigkeiten eingeschlossen. `--require-hashes` macht jede Abweichung zum Bau-Abbruch.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt
# app.py (FastAPI) und die reine Logik in kern.py und exportlogik.py (ohne Abhaengigkeiten —
# getrennt, weil die stdlib-only-Testsuite sie importieren koennen muss); exportpdf.py baut die PDFs.
COPY app.py kern.py huelle.py seiten.py exportlogik.py exportpdf.py paperlaiss.png ./
# Aussehen: vendortes C22 (scripts/vendor-c22.sh)
COPY static ./static
EXPOSE 8400
# --root-path aus PANEL_PFAD: hinter einem Proxy, der den Pfad abschneidet (Caddy handle_path),
# braucht TinySesam ihn für Weiterleitungen und next=-Ziele (TinySesam T-15).
# --no-proxy-headers: die echte Client-IP bestimmt TinySesam selbst (PANEL_TRUSTED_PROXIES). Schriebe
# uvicorn sie vorher um, hätte TinySesams Prüfung nichts mehr zu prüfen (TinySesam-README).
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port 8400 --no-proxy-headers --root-path \"${PANEL_PFAD:-}\""]
