#!/usr/bin/env python3
"""Fachtest: eval.py — Vergleich und Bericht der Testsammlung (reine Funktionen, ohne Netz)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "tests"))
import eval as ev  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — eval.py")
r.check("Vergleich: Name ohne Schreibweise, Typ mit ä=ae, Datum genau",
        ev.vergleiche({"korrespondent": "Häuser", "typ": "Erklärung", "datum": "2026-08-16"},
                      {"korrespondent": "HAEUSER", "typ": "Erklaerung", "datum": "2026-08-16"})
        == {"korrespondent": True, "typ": True, "datum": True})
r.check("Vergleich: nur geprüfte Felder; null heißt „keiner erwartet“",
        ev.vergleiche({"korrespondent": None}, {"korrespondent": None, "typ": "X"}) == {"korrespondent": True}
        and ev.vergleiche({"korrespondent": None}, {"korrespondent": "Google"}) == {"korrespondent": False})
r.check("Auswertung: Ist aus der Trockenlauf-Ausgabe",
        ev.lauf_auswerten({"korrespondent_ergebnis": "O2", "document_type": "Rechnung", "document_date": "2026-06-11"})
        == {"korrespondent": "O2", "typ": "Rechnung", "datum": "2026-06-11"}
        and ev.lauf_auswerten({"document_date": None, "datum_bisher": "2017-04-17"})["datum"] == "2017-04-17")
_neu = [{"id": 1, "soll": {"typ": "A"}, "ist": {"typ": "A"}, "vergleich": {"typ": True}},
        {"id": 2, "soll": {"typ": "B"}, "ist": {"typ": "C"}, "vergleich": {"typ": False}}]
_alt = [{"id": 1, "vergleich": {"typ": False}}, {"id": 2, "vergleich": {"typ": True}}]
_b = ev.bericht(_neu, _alt)
r.check("Bericht: Quote, Abweichung, Verbesserung und Rückschritt gegenüber dem alten Lauf",
        _b["quote"]["typ"] == "1/2" and len(_b["abweichungen"]) == 1
        and _b["verbesserungen"] == ["1 typ: jetzt richtig ('A')"] and _b["rueckschritte"] == ["2 typ: war richtig, jetzt 'C'"], str(_b))
r.check("Wiederholen: immer richtig, immer falsch, schwankend",
        ev.zusammenfassen([{"typ": True, "datum": False}, {"typ": True, "datum": False}]) == {"typ": True, "datum": False}
        and ev.zusammenfassen([{"typ": True}, {"typ": False}]) == {"typ": "schwankend"})
_bs = ev.bericht([{"id": 3, "soll": {"typ": "A"}, "ist": {"typ": "A"}, "ist_alle": [{"typ": "A"}, {"typ": "B"}],
                   "vergleich": {"typ": "schwankend"}}], [{"id": 3, "vergleich": {"typ": True}}])
r.check("Bericht: schwankend ist kein Rückschritt, zählt aber nicht als Treffer",
        _bs["rueckschritte"] == [] and _bs["quote"]["typ"] == "0/1" and len(_bs["schwankend"]) == 1, str(_bs))

sys.exit(r.done())
