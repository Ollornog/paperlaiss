#!/usr/bin/env python3
"""Fachtest: die reinen Hilfsfunktionen von classify.py.

Der Klassifizierer ist stdlib-only und spricht zur Laufzeit die Paperless- und Mistral-API —
das prüfen wir hier NICHT. Geprüft werden die Bausteine, die ohne Netz entscheiden, was
geschrieben wird: Normalisierung, Korrespondent-Tokens, OCR-Heuristik, Null-Erkennung,
Feld-Typumwandlung und die Namensauflösung. Reine Funktionen, kein I/O, wiederholbar.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

# classify.py leitet Log-/Trace-Pfade aus CLASSIFY_LOG ab. Vor dem Import auf ein Wegwerf-
# Verzeichnis zeigen lassen, damit ein Test-Import nie ins Repo schreibt (Wiederholbarkeit).
_TMP = tempfile.mkdtemp(prefix="paperlaiss-test-")
os.environ["CLASSIFY_LOG"] = str(Path(_TMP) / "classify.log")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

import classify  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — classify.py")

# ---- norm(): NFKD-Falte auf [a-z0-9 ], Umlaute/Sonderzeichen weg
r.check("norm faltet Umlaute und Sonderzeichen", classify.norm("Ärzte-Haus GmbH!") == "arzte haus gmbh")
r.check("norm auf None ist leer", classify.norm(None) == "")

# ---- ctoks(): Firmen-/Rechtsformwörter fallen raus, der Kern bleibt
r.check("ctoks entfernt Rechtsform (gmbh)", classify.ctoks("STRATO GmbH") == ["strato"])
r.check("ctoks behält den Markenkern", "hetzner" in classify.ctoks("Hetzner Online GmbH"))

# ---- bad_ocr(): kurz/leer oder tokenarm → OCR nötig; brauchbarer Text → nicht
r.check("bad_ocr: leerer Text", classify.bad_ocr("") is True)
r.check("bad_ocr: zu kurz", classify.bad_ocr("Rechnung Betrag 5 EUR") is True)
_gut = ("Sehr geehrte Frau Muster, anbei die Rechnung Nummer 4711 mit Datum und Betrag. "
        "Die Summe netto und brutto steht unten, gültig für die Lieferung an die genannte "
        "Strasse. Mit freundlichen Grüßen, die Buchhaltung der Firma. " * 4)
r.check("bad_ocr: brauchbarer Text ist nicht schlecht", classify.bad_ocr(_gut) is False)

# ---- is_null(): die vielen Schreibweisen von „leer"
r.check("is_null: None", classify.is_null(None) is True)
r.check("is_null: Leerstring", classify.is_null("  ") is True)
r.check("is_null: das Wort null", classify.is_null("NULL") is True)
r.check("is_null: kein", classify.is_null("kein") is True)
r.check("is_null: echter Wert", classify.is_null("Rechnung") is False)

# ---- coerce_field(): typgerechte Umwandlung, unparsebar → None
r.check("coerce integer aus Text", classify.coerce_field({"data_type": "integer"}, "1.234 km") == 1234)
r.check("coerce float mit Komma", classify.coerce_field({"data_type": "float"}, "1,5") == 1.5)
r.check("coerce monetary → EUR-Präfix", classify.coerce_field({"data_type": "monetary"}, "1234,56") == "EUR1234.56")
r.check("coerce boolean ja → True", classify.coerce_field({"data_type": "boolean"}, "ja") is True)
r.check("coerce boolean nein → False", classify.coerce_field({"data_type": "boolean"}, "nein") is False)
r.check("coerce date behält ISO-Kopf", classify.coerce_field({"data_type": "date"}, "2026-07-12T00:00") == "2026-07-12")
r.check("coerce date unparsebar → None", classify.coerce_field({"data_type": "date"}, "irgendwann") is None)

_sel = {"data_type": "select", "extra_data": {"select_options": [{"id": 7, "label": "Offen"}]}}
r.check("coerce select matcht Label auf ID", classify.coerce_field(_sel, "offen") == 7)
r.check("coerce select ohne Treffer → None", classify.coerce_field(_sel, "Storno") is None)

# ---- sel_label(): ID zurück auf Label
r.check("sel_label findet Label", classify.sel_label(_sel, 7) == "Offen")
r.check("sel_label ohne Treffer gibt Wert zurück", classify.sel_label(_sel, 99) == 99)

# ---- resolve_tag()/resolve_field(): Auflösung per normalisiertem Namen
_by_norm = {classify.norm("Ai-Processed"): 3, classify.norm("Offen"): 4}
r.check("resolve_tag matcht case-insensitiv", classify.resolve_tag(_by_norm, "AI-PROCESSED") == 3)
r.check("resolve_tag ohne Namen → None", classify.resolve_tag(_by_norm, "") is None)

_cfields = [{"id": 11, "name": "Bezahlt-Am"}, {"id": 12, "name": "Kennzeichen"}]
r.check("resolve_field matcht per Name", classify.resolve_field(_cfields, "kennzeichen") == 12)
r.check("resolve_field ohne Treffer → None", classify.resolve_field(_cfields, "Unbekannt") is None)

# ---- Der eingebaute Default-Prompt trägt keinen mandantenspezifischen Kontext mehr
_p = classify.DEFAULT_PROMPT.lower()
r.check("Default-Prompt ist mandantenneutral", not any(w in _p for w in ("salzburg", "autohaus")))
r.check("Default-Prompt behält die Platzhalter", "{TYPES}" in classify.DEFAULT_PROMPT and "{TAGBLOCK}" in classify.DEFAULT_PROMPT)

sys.exit(r.done())
