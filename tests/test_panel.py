#!/usr/bin/env python3
"""Fachtest: die reine Logik des Panels (panel/kern.py).

`app.py` braucht FastAPI und ist damit in dieser stdlib-only-Suite nicht importierbar. Alles,
was eine Entscheidung trifft und ohne Netz auskommt, steht deshalb in `kern.py` — und wird hier
geprüft. Bis 2026-09-21 war am Panel nichts getestet.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))

import kern  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — panel/kern.py")

# ---- doc_id_aus_webhook(): Paperless sendet je nach Einstellung drei verschiedene Formen.
# Die doppelt kodierte ist die Falle: as_json=true PLUS body ergibt JSON, das JSON enthält.
r.check("Webhook: sauberes Objekt (use_params)",
        kern.doc_id_aus_webhook('{"doc_id": "919"}') == 919)
r.check("Webhook: doppelt kodiert (as_json + body)",
        kern.doc_id_aus_webhook('"{\\"doc_id\\": \\"919\\"}"') == 919)
r.check("Webhook: nur doc_url, ID steckt im Pfad",
        kern.doc_id_aus_webhook('{"doc_url": "https://example.com/documents/919/details"}') == 919)
r.check("Webhook: ID als Zahl statt Text",
        kern.doc_id_aus_webhook('{"doc_id": 42}') == 42)
r.check("Webhook: alternative Feldnamen",
        kern.doc_id_aus_webhook('{"document_id": "7"}') == 7)
r.check("Webhook: roher Text ohne JSON",
        kern.doc_id_aus_webhook('Dokument /documents/123/ wurde geaendert') == 123)
r.check("Webhook: ohne ID ergibt None",
        kern.doc_id_aus_webhook('{"was": "anderes"}') is None)
r.check("Webhook: leerer Rumpf ergibt None", kern.doc_id_aus_webhook("") is None)
r.check("Webhook: Unsinn ergibt None statt Absturz",
        kern.doc_id_aus_webhook("{{{ kaputt") is None)

# ---- doc_hat_sich_geaendert(): schützt davor, dass ein alter Vorschlag eine zwischenzeitliche
# Handkorrektur stillschweigend überschreibt.
_V = {"stand": {"modified": "2026-09-21T01:00:00Z", "title": "Rechnung",
                "correspondent": 5, "document_type": 2, "created": "2026-05-02", "tags": [1, 2]}}

r.check("Abgleich: gleicher Zeitstempel = unverändert",
        kern.doc_hat_sich_geaendert(_V, {"modified": "2026-09-21T01:00:00Z"}) is False)
r.check("Abgleich: anderer Zeitstempel = geändert",
        kern.doc_hat_sich_geaendert(_V, {"modified": "2026-09-21T02:00:00Z"}) is True)

# Ohne modified-Zeitstempel wird inhaltlich verglichen.
_ohne = {"stand": {k: v for k, v in _V["stand"].items() if k != "modified"}}
_gleich = {"title": "Rechnung", "correspondent": 5, "document_type": 2,
           "created": "2026-05-02T00:00:00Z", "tags": [2, 1]}
r.check("Abgleich ohne Zeitstempel: gleicher Inhalt (Tag-Reihenfolge egal)",
        kern.doc_hat_sich_geaendert(_ohne, _gleich) is False)
r.check("Abgleich ohne Zeitstempel: anderer Korrespondent = geändert",
        kern.doc_hat_sich_geaendert(_ohne, {**_gleich, "correspondent": 9}) is True)
r.check("Abgleich ohne Zeitstempel: neuer Tag = geändert",
        kern.doc_hat_sich_geaendert(_ohne, {**_gleich, "tags": [1, 2, 3]}) is True)

# Ein Vorschlag ohne Stand ist nicht vertrauenswürdig — im Zweifel „geändert".
r.check("Abgleich: Vorschlag ohne Stand gilt als geändert",
        kern.doc_hat_sich_geaendert({}, _gleich) is True)

sys.exit(r.done())
