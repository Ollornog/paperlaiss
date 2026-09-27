FROM python:3.14-slim
# Schrift für das Inhaltsverzeichnis des Export-Knopfs: DejaVu Sans deckt Umlaute, €, Ost- und
# Südosteuropäisches, Griechisch und Kyrillisch ab (ohne sie fällt exportpdf.py auf Helvetica zurück,
# die nur Windows-1252 kann).
RUN apt-get update \
 && apt-get install -y --no-install-recommends fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# app.py (FastAPI) und die reine Logik in kern.py und exportlogik.py (ohne Abhaengigkeiten —
# getrennt, weil die stdlib-only-Testsuite sie importieren koennen muss); exportpdf.py baut die PDFs.
COPY app.py kern.py huelle.py seiten.py exportlogik.py exportpdf.py paperlaiss.png ./
# Aussehen: vendortes C22 (scripts/vendor-c22.sh)
COPY static ./static
EXPOSE 8400
# --root-path aus PANEL_PFAD: hinter einem Proxy, der den Pfad abschneidet (Caddy handle_path),
# braucht TinySesam ihn für Weiterleitungen und next=-Ziele (TinySesam T-15).
CMD ["sh", "-c", "exec uvicorn app:app --host 0.0.0.0 --port 8400 --root-path \"${PANEL_PFAD:-}\""]
