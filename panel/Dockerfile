FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Beide Module: app.py (FastAPI) und kern.py (reine Logik, ohne Abhaengigkeiten).
# Getrennt, weil die stdlib-only-Testsuite kern.py importieren koennen muss.
COPY app.py kern.py huelle.py seiten.py paperlaiss.png ./
# Aussehen: vendortes C22 (scripts/vendor-c22.sh)
COPY static ./static
EXPOSE 8400
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8400"]
