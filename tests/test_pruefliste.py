#!/usr/bin/env python3
"""Fachtest: panel/pruefliste.py — flagged documents with their reason, probably own identifiers (T-9 items 1, 7).

The routes around it (`/api/pruefen`, `/api/pruefen/kennung`) run in the panel image: `tests/abbild_pruefen.py`.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))

import pruefliste as pl  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — panel/pruefliste.py")

# ---- keys: the spellings a store and a document use must meet
r.check("Schlüssel: IBAN gruppiert und kompakt gleich",
        pl.schluessel("iban", "de02 1203 0000 0000 2020 51") == pl.schluessel("iban", "DE02120300000000202051"))
r.check("Schlüssel: Telefon mit Klammer-Null und mit 00 gleich",
        pl.schluessel("telefon", "+49 (0) 30 123456") == pl.schluessel("telefon", "0049 30 123456"))
r.check("Schlüssel: Mail ohne Groß/klein", pl.schluessel("email", "Info@Example.com") == "info@example.com")

# ---- flagged documents
NAMEN = {"correspondent": {"3": "Muster GmbH"}, "document_type": {"2": "Lohnabrechnung"}}
doks = [{"id": 1, "title": "A", "correspondent": 3, "document_type": 2, "tags": [5]},
        {"id": 2, "title": "B", "correspondent": None, "document_type": None, "tags": [5]},
        {"id": 3, "title": "C", "correspondent": 3, "document_type": None, "tags": [5]}]
traces = {1: {"ts_utc": "2026-11-01T10:00:00+00:00", "pruefen": {"datum": "kein Datum im Text", "leer_x": ""}},
          3: {"ts": "2026-11-05 10:00:00", "pruefen": None}}
z = pl.dokumente(doks, traces, NAMEN)
r.check("Dokumente: neuester Lauf zuerst, ohne Lauf hinten", [x["doc"] for x in z] == [3, 1, 2], str(z))
r.check("Dokumente: Grund aus dem Trace, leere Befunde fallen weg, Namen statt IDs",
        z[1]["gruende"] == [{"art": "datum", "text": "kein Datum im Text"}] and z[1]["korrespondent"] == "Muster GmbH"
        and z[1]["typ"] == "Lohnabrechnung")
r.check("Dokumente: ohne Befund im Trace oder ohne Trace steht das da",
        z[0]["gruende"][0]["text"] == pl.OHNE_GRUND and z[2]["gruende"][0]["text"] == pl.OHNE_GRUND)

# ---- identifiers
IBAN_EIGEN = "DE02 1203 0000 0000 2020 51"
STORE = {"3": {"iban": [IBAN_EIGEN, "DE89 3704 0044 0532 0130 00"], "aliase": ["M"],
               "erfasst": {"iban": {IBAN_EIGEN: "KI", "DE89 3704 0044 0532 0130 00": "KI"}}},
         "4": {"telefon": "+4930123456", "erfasst": {"telefon": "KI · Dokument 9"}},
         "7": {"iban": ["DE02120300000000202051"]},
         "8": "kaputt"}
EIGENE = {"iban": [IBAN_EIGEN], "namen": ["Erika Muster"]}
VOR = {"telefon:+4930123456": {"feld": "telefon", "wert": "+4930123456", "korrespondenten": 4, "dokumente": [11]},
       "iban:X": {"feld": "iban", "wert": "AT611904300234573201", "korrespondenten": 3, "verworfen": True},
       "iban:Y": {"feld": "iban", "wert": "DE02120300000000202051", "korrespondenten": 5},
       "kaputt": "x"}
kz = {(k["feld"], pl.schluessel(k["feld"], k["wert"])): k for k in pl.kennungen(VOR, STORE, EIGENE)}
r.check("Kennungen: offener Vorschlag mit Fundstellen im Store",
        kz.get(("telefon", "+4930123456"), {}).get("bei") == ["4"] and not kz[("telefon", "+4930123456")]["schon_eigen"])
r.check("Kennungen: verworfener Vorschlag fehlt", ("iban", "AT611904300234573201") not in kz)
r.check("Kennungen: eigene IBAN in zwei Schreibweisen bei zwei Korrespondenten, einmal gelistet und zum Räumen",
        kz.get(("iban", "DE02120300000000202051"), {}).get("bei") == ["3", "7"]
        and kz[("iban", "DE02120300000000202051")]["schon_eigen"] is True
        and len([k for k in kz if k[1] == "DE02120300000000202051"]) == 1, str(kz))
r.check("Kennungen: schon eigen und nirgends gespeichert → nicht mehr gezeigt",
        pl.kennungen({"a": {"feld": "iban", "wert": IBAN_EIGEN, "korrespondenten": 3}}, {}, EIGENE) == [])
r.check("Kennungen: kaputte Einträge stören nicht", isinstance(pl.kennungen({"x": 1}, {"1": []}, None), list))

neu, weg = pl.store_raeumen(STORE, "iban", "de02120300000000202051")
r.check("Räumen: aus allen Einträgen, beide Schreibweisen", weg == ["3", "7"], str(weg))
r.check("Räumen: fremde IBAN, Aliase und deren Herkunft bleiben",
        neu["3"] == {"iban": ["DE89 3704 0044 0532 0130 00"], "aliase": ["M"],
                     "erfasst": {"iban": {"DE89 3704 0044 0532 0130 00": "KI"}}}, str(neu["3"]))
r.check("Räumen: letzter Wert weg → Feld weg, leerer Eintrag bleibt als Eintrag", neu["7"] == {})
r.check("Räumen: der alte Store bleibt unverändert (rein)", STORE["3"]["iban"][0] == IBAN_EIGEN)
neu, weg = pl.store_raeumen(STORE, "telefon", "+49 30 123456")
r.check("Räumen: Einzelwert samt Herkunftsvermerk als Text", weg == ["4"] and neu["4"] == {}, str(neu["4"]))
r.check("Räumen: nichts gefunden → nichts geändert", pl.store_raeumen(STORE, "email", "a@b.de") == (STORE, []))

e = pl.eigene_ergaenzen(EIGENE, "telefon", "+49 30 123456")
r.check("Ergänzen: neue Telefonnummer normiert, Rest bleibt",
        e["telefon"] == ["+4930123456"] and e["iban"] == [IBAN_EIGEN] and e["namen"] == ["Erika Muster"], str(e))
r.check("Ergänzen: schon vorhanden → nicht doppelt",
        pl.eigene_ergaenzen(EIGENE, "iban", "DE02120300000000202051")["iban"] == [IBAN_EIGEN])
r.check("Ergänzen: aus einer Komma-Liste wird eine Liste",
        pl.eigene_ergaenzen({"email": "a@b.de, c@d.de"}, "email", "E@F.de")["email"] == ["a@b.de", "c@d.de", "e@f.de"])

sys.exit(r.done())
