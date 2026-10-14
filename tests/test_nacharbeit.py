#!/usr/bin/env python3
"""Fachtest: Nacharbeit (panel/nacharbeit.py) — was Menschen nach einem KI-Lauf geändert haben.

Die Historie in den Fällen ist echten Einträgen des Paperless-Audit-Logs nachgebaut (Form von
`/api/documents/<id>/history/`, Paperless 3.2): neueste zuerst, Grundfelder als [alt, neu] mit IDs,
eigene Felder nur mit neuem Wert, Tags als m2m-Operation. Der Klassifizierer schreibt unter dem
Token-Benutzer — der kann ein Mensch sein; getrennt wird über die Zeit, nicht über den Namen.
"""
from __future__ import annotations

import datetime
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))

import nacharbeit as na  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — panel/nacharbeit.py")

TRACE = {
    "id": "1210", "_stage": "fertig", "ts": "2026-10-14 18:00:30", "ts_utc": "2026-10-14T16:00:30+00:00",
    "trigger": "KI-Knopf",
    "writeback": {"document_type": "Rechnung", "title": "Uniqa – Rechnung 4711", "tags": ["KFZ"],
                  "correspondent": "exakt='Uniqa'",
                  "fields_ki": {"Rechnungsnummer": "4711", "Fahrzeug": "Mercedes-Benz C 180",
                                "Polizze Nr.": "behalten", "IBAN": "geleert", "Betrag": "EUR12.50"}},
}


def e(ts, wer, changes, action="update"):
    return {"timestamp": ts, "action": action, "changes": changes,
            "actor": {"id": 4, "username": wer} if wer else None}


def cf(feld, wert):
    return {"custom_fields": {"type": "custom_field", "field": feld, "value": wert}}


HIST = [   # neueste zuerst, wie Paperless
    e("2026-10-14T16:09:00Z", "Meli", {"tags": {"type": "m2m", "objects": ["Inbox"], "operation": "delete"}}),
    e("2026-10-14T16:08:50Z", "Meli", {"tags": {"type": "m2m", "objects": ["KFZ"], "operation": "delete"}}),
    e("2026-10-14T16:08:48Z", "Meli", cf("Bezahlt-Am", "2026-08-03")),
    e("2026-10-14T16:08:47Z", "Meli", cf("Polizze Nr.", "")),
    e("2026-10-14T16:08:47Z", "Meli", cf("IBAN", "AT611904300234573201")),
    e("2026-10-14T16:08:46Z", "Meli", cf("Fahrzeug", "")),
    e("2026-10-14T16:08:45Z", "Meli", {"correspondent": ["12", "39"], "title": ["Uniqa – Rechnung 4711", "Post – Rechnung 4711"]}),
    e("2026-10-14T16:08:44Z", "Meli", cf("Betrag", "EUR99.00")),
    e("2026-10-14T16:08:43Z", "Meli", cf("Betrag", "EUR12.50")),       # hin …
    e("2026-10-14T16:08:42Z", "Meli", cf("Betrag", "EUR13.50")),       # … und wieder zurück (s. o. 99 → bleibt)
    e("2026-10-14T16:05:00Z", None, cf("Rechnungsnummer", "9999")),     # Workflow/Skript, kein Mensch
    e("2026-10-14T16:00:40Z", "Ollornog", cf("Rechnungsnummer", "4711")),  # noch der Lauf selbst (Gnadenfrist)
    e("2026-10-14T16:00:29Z", "Ollornog", {"title": ["alt", "Uniqa – Rechnung 4711"]}),   # Schreiben des Laufs
]
NAMEN = {"correspondent": {"12": "Uniqa", "39": "Österreichische Post AG"}, "document_type": {"21": "Rechnung"}}

erg = na.korrekturen(TRACE, HIST, NAMEN)
k = {x["feld"]: x for x in erg["korrekturen"]}

r.check("Lauf mit Writeback zählt, abgebrochener nicht",
        na.ki_lauf(TRACE) and not na.ki_lauf({**TRACE, "writeback": {"fehler": "x"}})
        and not na.ki_lauf({"id": "1"}) and not na.ki_lauf({**TRACE, "_stage": "Tags & Schreiben"}))
r.check("Felder des Laufs: vier Grundfelder, die KI-Felder, Tags",
        erg["felder"][:4] == ["Titel", "Korrespondent", "Dokumenttyp", "Datum"]
        and "Rechnungsnummer" in erg["felder"] and "Tags" in erg["felder"] and "Bezahlt-Am" not in erg["felder"])
r.check("angefasst: ein Mensch hat nach dem Lauf geändert", erg["angefasst"] is True)
r.check("Fahrzeug von der KI gesetzt, von Hand geleert → Korrektur „geleert“",
        k.get("Fahrzeug", {}).get("art") == "geleert" and k["Fahrzeug"]["ki"] == "Mercedes-Benz C 180"
        and k["Fahrzeug"]["wer"] == "Meli")
r.check("IBAN von der KI geleert, von Hand ergänzt → „ergänzt“",
        k.get("IBAN", {}).get("art") == "ergänzt" and k["IBAN"]["neu"] == "AT611904300234573201")
r.check("Behaltener Wert: KI-Wert unbekannt (None), Leeren zählt als „geleert“",
        k.get("Polizze Nr.", {}).get("ki", "x") is None and k["Polizze Nr."]["art"] == "geleert")
r.check("Korrespondent: IDs werden zu Namen, KI-Wert = Wert vor der ersten Änderung",
        k.get("Korrespondent", {}).get("ki") == "Uniqa" and k["Korrespondent"]["neu"] == "Österreichische Post AG")
r.check("Titel nach dem Lauf geändert → Korrektur", k.get("Titel", {}).get("neu") == "Post – Rechnung 4711")
r.check("Betrag: letzter Stand zählt (12.50 → 13.50 → 12.50 → 99.00 ist eine Korrektur)",
        k.get("Betrag", {}).get("ki") == "EUR12.50" and k["Betrag"]["neu"] == "EUR99.00")
r.check("Feld, das die KI nicht gesetzt hat (Bezahlt-Am), ist keine Korrektur", "Bezahlt-Am" not in k)
r.check("Änderung ohne Benutzer (Workflow) ist keine Korrektur", "Rechnungsnummer" not in k)
r.check("KI-Tag entfernt → „entfernt“, Workflow-Tag (Inbox) zählt nicht",
        k.get("Tags", {}).get("ki") == "KFZ" and k["Tags"]["art"] == "entfernt"
        and not any(x["ki"] == "Inbox" for x in erg["korrekturen"]))

# Hin und zurück: kein Fehler der KI.
_hz = na.korrekturen(TRACE, [e("2026-10-14T16:10:00Z", "Meli", cf("Rechnungsnummer", "4711")),
                             e("2026-10-14T16:09:00Z", "Meli", cf("Rechnungsnummer", "4712"))])
r.check("Hin und zurück geändert → keine Korrektur, aber angefasst",
        _hz["korrekturen"] == [] and _hz["angefasst"])
_tag = na.korrekturen(TRACE, [e("2026-10-14T16:10:00Z", "Meli", {"tags": {"type": "m2m", "objects": ["KFZ"], "operation": "add"}}),
                              e("2026-10-14T16:09:00Z", "Meli", {"tags": {"type": "m2m", "objects": ["KFZ"], "operation": "delete"}})])
r.check("KI-Tag entfernt und wieder gesetzt → keine Korrektur", _tag["korrekturen"] == [])

# Gnadenfrist: Schreiben des Laufs selbst (unter dem Token-Benutzer) direkt um den Zeitstempel.
_nah = na.korrekturen(TRACE, [e("2026-10-14T16:00:44Z", "Ollornog", cf("Fahrzeug", ""))])
r.check(f"Änderung bis {na.GNADE_S} s nach dem Lauf gehört noch zum Lauf", _nah["korrekturen"] == [] and not _nah["angefasst"])

# Alte Traces: nur `ts` in Ortszeit der Installation.
_alt = {k2: v for k2, v in TRACE.items() if k2 != "ts_utc"}
r.check("Alter Trace: ts in Europe/Berlin wird zu UTC",
        na.lauf_zeit(_alt, "Europe/Berlin") == datetime.datetime(2026, 10, 14, 16, 0, 30, tzinfo=datetime.timezone.utc))
r.check("Alter Trace: ohne Zone gilt UTC, unbekannte Zone auch",
        na.lauf_zeit(_alt, "") == na.lauf_zeit(_alt, "Mars/Olympus")
        == datetime.datetime(2026, 10, 14, 18, 0, 30, tzinfo=datetime.timezone.utc))
r.check("Alter Trace mit Zone: gleiche Korrekturen wie mit ts_utc",
        na.korrekturen(_alt, HIST, NAMEN, "Europe/Berlin")["korrekturen"] == erg["korrekturen"])
r.check("Trace ohne Zeit: keine Korrekturen statt Absturz",
        na.korrekturen({"writeback": {}}, HIST)["korrekturen"] == [])

# ---- Auswertung über mehrere Läufe
JETZT = datetime.datetime(2026, 10, 15, tzinfo=datetime.timezone.utc)


def lauf(doc, ts, korr, feld_k=(), felder=("Titel", "Korrespondent", "Dokumenttyp", "Datum", "Rechnungsnummer"),
         angefasst=None):
    return {"doc": doc, "ts": ts, "quelle": "automatisch", "korrespondent": korr, "typ": "Rechnung",
            "felder": list(felder), "angefasst": bool(feld_k) if angefasst is None else angefasst,
            "korrekturen": [{"feld": f, "ki": "a", "neu": "b", "art": "geändert", "wer": "Meli",
                             "wann": ts} for f in feld_k]}


LAEUFE = [lauf(1, "2026-10-14T10:00:00+00:00", "Uniqa", ["Titel", "Rechnungsnummer"]),
          lauf(2, "2026-10-13T10:00:00+00:00", "Uniqa", ["Titel"]),
          lauf(3, "2026-10-12T10:00:00+00:00", "Post"),
          lauf(4, "2026-10-11T10:00:00+00:00", "Post", angefasst=True),
          lauf(5, "2026-01-01T10:00:00+00:00", "Alt", ["Titel"])]
a = na.auswertung(LAEUFE, JETZT, tage=90)
f = {z["feld"]: z for z in a["je_feld"]}
r.check("Zeitraum: Lauf älter als 90 Tage fällt heraus", a["laeufe"] == 4 and a["alle_laeufe"] == 4)
r.check("Nachgearbeitet und Quote je Lauf", a["nachgearbeitet"] == 2 and a["quote"] == 50.0 and a["korrekturen"] == 3)
r.check("angefasst zählt auch Läufe ohne Korrektur", a["angefasst"] == 3)
r.check("Quote je Feld: Titel 2 von 4, Rechnungsnummer 1 von 4",
        f["Titel"]["korrigiert"] == 2 and f["Titel"]["basis"] == 4 and f["Titel"]["quote"] == 50.0
        and f["Rechnungsnummer"]["quote"] == 25.0 and f["Datum"]["quote"] == 0.0)
r.check("Je Feld: höchste Quote zuerst", a["je_feld"][0]["feld"] == "Titel")
r.check("Je Korrespondent: Uniqa 2/2 vor Post 0/2",
        [(z["name"], z["nachgearbeitet"]) for z in a["je_korrespondent"]] == [("Uniqa", 2), ("Post", 0)])
r.check("Je Woche: ISO-Woche mit Läufen und Quote",
        {z["woche"]: z["nachgearbeitet"] for z in a["je_woche"]} == {"2026-W41": 0, "2026-W42": 2})
r.check("Fälle: neueste zuerst, mit Dokument und Korrespondent",
        [x["doc"] for x in a["faelle"]] == [1, 1, 2] and a["faelle"][0]["korrespondent"] == "Uniqa")
r.check("Filter Feld: nur diese Fälle, Kennzahlen bleiben",
        [x["feld"] for x in na.auswertung(LAEUFE, JETZT, feld="Rechnungsnummer")["faelle"]] == ["Rechnungsnummer"])
r.check("Filter Korrespondent: Kennzahlen nur für ihn",
        na.auswertung(LAEUFE, JETZT, korrespondent="Post")["laeufe"] == 2)
r.check("tage=0: alles", na.auswertung(LAEUFE, JETZT, tage=0)["laeufe"] == 5)
r.check("Leere Liste: Nullen statt Teilen durch null",
        na.auswertung([], JETZT)["quote"] == 0.0 and na.auswertung([], JETZT)["je_feld"] == [])

# ---- Speichern: ein überschriebener Trace darf seinen alten Lauf nicht mitnehmen
_alt_l = {"1@2026-10-01T00:00:00+00:00": {"ts": "2026-10-01T00:00:00+00:00", "korrekturen": [{"feld": "Titel"}]}}
_neu_l = {"1@2026-10-14T00:00:00+00:00": {"ts": "2026-10-14T00:00:00+00:00", "korrekturen": []}}
m = na.zusammenfuehren(_alt_l, _neu_l)
r.check("Zusammenführen: alter Lauf desselben Dokuments bleibt stehen", len(m) == 2)
r.check("Zusammenführen: Obergrenze wirft die ältesten weg",
        list(na.zusammenfuehren(_alt_l, _neu_l, behalten=1)) == ["1@2026-10-14T00:00:00+00:00"])

sys.exit(r.done())
