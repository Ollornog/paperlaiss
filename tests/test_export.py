#!/usr/bin/env python3
"""Fachtest: die reine Logik des Export-Knopfs (panel/exportlogik.py).

Auftrag prüfen, Leserechte, Größengrenze, Paperless-Adresse, Variablen, Dateinamen aus der Vorlage
(entschärft, eindeutig), Sortierung, Aufbau des Inhaltsverzeichnisses. Stdlib-only — das Zeichnen
und Zusammenfügen mit pypdf/reportlab prüft `tests/abbild_export.py` im gebauten Panel-Abbild.
Dazu statisch (AST): jeder Export-Endpunkt in app.py fragt die Paperless-Sitzung.
"""
from __future__ import annotations

import ast
import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))

import exportlogik as el  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Fachtest — panel/exportlogik.py (Export-Knopf)")

# ---- export_auftrag(): was der Knopf schickt
_a, _f = el.export_auftrag({"docs": [5, "3", 5, "x", -1, 0, 7], "art": "ein", "seitenzahlen": "true"})
r.check("Auftrag: Reihenfolge der Auswahl bleibt, Doppelte und Unsinn fallen weg", _a["docs"] == [5, 3, 7] and not _f, str(_a["docs"]))
r.check("Auftrag: Wahrheitswerte aus Text", _a["seitenzahlen"] is True and _a["zip"] is False)
_a, _f = el.export_auftrag({"docs": list(range(1, 12))}, max_dokumente=10)
r.check("Auftrag: zu viele Dokumente ist ein Fehler mit Zahlen, keine stille Kürzung",
        any("10" in x and "11" in x for x in _f), str(_f))
r.check("Auftrag: ohne Dokumente ein Fehler", el.export_auftrag({"docs": []})[1])
_f = [("a", 100, 4), ("b", 300, 4), ("c", 200, 4)]          # Auftrag, Ende, Bytes
r.check("Speicher: unter der Grenze bleibt alles", el.speicher_ueberlauf(_f, 12) == [])
r.check("Speicher: über der Grenze fallen die ältesten zuerst, nur so viele wie nötig",
        el.speicher_ueberlauf(_f, 8) == ["a"] and el.speicher_ueberlauf(_f, 4) == ["a", "c"], str(el.speicher_ueberlauf(_f, 4)))
r.check("Vorgabe: bis 1000 Dokumente je Export", not el.export_auftrag({"docs": list(range(1, 1001))})[1]
        and el.export_auftrag({"docs": list(range(1, 1002))})[1])
r.check("Auftrag: unbekannte Art ein Fehler", el.export_auftrag({"docs": [1], "art": "fax"})[1])
r.check("Auftrag: Einzel-Export prüft die Vorlage",
        el.export_auftrag({"docs": [1], "art": "einzeln", "vorlage": "{gibtsnicht}"})[1])
r.check("Auftrag: leere Vorlage wird zur Standardvorlage",
        el.export_auftrag({"docs": [1], "art": "einzeln", "vorlage": "  "})[0]["vorlage"] == el.VORLAGE_STANDARD)
r.check("Auftrag: unbekannte Sortierung ein Fehler", el.export_auftrag({"docs": [1], "sortierung": "farbe"})[1])
r.check("Auftrag: Sortierung nach Feld ist erlaubt", not el.export_auftrag({"docs": [1], "sortierung": "feld:Betrag"})[1])

# ---- lese_rechte(): nur, was Paperless dem Nutzer zeigt
_ant = {"results": [{"id": 1}, {"id": 3}]}
r.check("Rechte: sichtbar = lesbar, unsichtbar = verweigert, Reihenfolge bleibt",
        el.lese_rechte(_ant, [3, 2, 1]) == ([3, 1], [2]), str(el.lese_rechte(_ant, [3, 2, 1])))
r.check("Rechte: leere Antwort verweigert alles", el.lese_rechte({}, [4, 5]) == ([], [4, 5]))
r.check("Rechte: Antwort ohne Ergebnisliste verweigert alles", el.lese_rechte(None, [4]) == ([], [4]))

# ---- groesse_fehler(): Grenze für die Summe der heruntergeladenen PDFs
_mb = 1024 * 1024
r.check("Größe: genau an der Grenze geht noch", el.groesse_fehler(5 * _mb, 5 * _mb) is None)
_g = el.groesse_fehler(5 * _mb + 1, 5 * _mb)
r.check("Größe: darüber gibt es eine klare Meldung mit Grenze", bool(_g) and "5 MB" in _g, str(_g))

# ---- pdf_quelle(): Archiv, sonst Original-PDF, sonst überspringen
r.check("Quelle: Archiv-PDF zuerst", el.pdf_quelle({"archived_file_name": "x.pdf", "mime_type": "image/png"}) == ("archiv", None))
r.check("Quelle: ohne Archiv das Original, wenn es ein PDF ist",
        el.pdf_quelle({"archived_file_name": None, "mime_type": "application/pdf"}) == ("original", None))
_q = el.pdf_quelle({"archived_file_name": None, "mime_type": "text/plain"})
r.check("Quelle: kein PDF → übersprungen, mit Grund", _q[0] is None and "text/plain" in _q[1], str(_q))

# ---- paperless_basis(): keine Adresse im Code, nichts Fremdes aus dem Browser
_pb = el.paperless_basis
r.check("Basis: Konfiguration gewinnt", _pb("https://dms.example.com/", "http://x.example.com", "http://x.example.com/") == "https://dms.example.com")
r.check("Basis: Vorschlag vom selben Ursprung (mit Unterpfad)",
        _pb("", "https://dms.example.com", "https://dms.example.com/paperless/") == "https://dms.example.com/paperless")
r.check("Basis: Vorschlag von fremdem Ursprung zählt nicht, der Ursprung schon",
        _pb("", "https://dms.example.com", "https://boese.example.net/") == "https://dms.example.com")
r.check("Basis: nur http(s) — javascript:, ftp:, file: fallen durch",
        _pb("", "", "javascript:alert(1)") == "" and _pb("ftp://dms.example.com", "", "") == ""
        and _pb("", "", "file://dms.example.com/x") == "")
r.check("Basis: Zugangsdaten in der Adresse fallen durch", _pb("https://a:b@dms.example.com", "", "") == "")
r.check("Basis: nichts bekannt → keine Links", _pb("", "", "") == "")
r.check("Link: Dokumentansicht in Paperless", el.paperless_link("https://dms.example.com", 42) == "https://dms.example.com/documents/42/details"
        and el.paperless_link("", 42) == "")

# ---- dokument_variablen(): was die Vorlage einsetzen kann
_namen = {"korrespondenten": {1: "Muster GmbH"}, "typen": {2: "Rechnung"},
          "felder": {7: {"name": "Betrag", "data_type": "monetary"},
                     8: {"name": "Status", "data_type": "select",
                         "extra_data": {"select_options": [{"id": "a1", "label": "offen"}, {"id": "b2", "label": "bezahlt"}]}},
                     9: {"name": "Geprüft", "data_type": "boolean"},
                     10: {"name": "Verwandt", "data_type": "documentlink"}}}
_dok = {"id": 12, "title": "Rechnung 2025/26", "correspondent": 1, "document_type": 2, "created": "2026-03-04",
        "added": "2026-03-05T10:00:00+01:00", "archive_serial_number": 77, "page_count": 3,
        "original_file_name": "scan.final.pdf",
        "custom_fields": [{"field": 7, "value": "EUR42.50"}, {"field": 8, "value": "b2"}, {"field": 9, "value": True},
                          {"field": 10, "value": [3, 4]}, {"field": 99, "value": "?"}]}
_v = el.dokument_variablen(_dok, _namen)
_w = _v["werte"]
r.check("Variablen: Grunddaten", (_w["titel"], _w["korrespondent"], _w["typ"], _w["datum"], _w["jahr"], _w["monat"],
                                  _w["hinzugefuegt"], _w["id"], _w["asn"], _w["seiten"], _w["original"]) ==
        ("Rechnung 2025/26", "Muster GmbH", "Rechnung", "2026-03-04", "2026", "03", "2026-03-05", "12", "77", "3", "scan.final"), str(_w))
r.check("Variablen: jede angebotene Variable hat einen Wert-Schlüssel", set(_w) == set(el.VARIABLEN_NAMEN))
r.check("Variablen: Felder typgerecht (Betrag, Auswahl, ja/nein, Verweise)",
        _v["felder"] == {"Betrag": "42.50 EUR", "Status": "bezahlt", "Geprüft": "ja", "Verwandt": "3,4"}, str(_v["felder"]))
r.check("Variablen: Korrespondent ohne Leserecht bleibt leer",
        el.dokument_variablen({**_dok, "correspondent": 5}, _namen)["werte"]["korrespondent"] == "")
r.check("Variablen: Datum mit Uhrzeit (ältere API) wird aufs Datum gekürzt",
        el.dokument_variablen({"id": 1, "created": "2024-01-02T00:00:00+01:00"}, {})["werte"]["datum"] == "2024-01-02")

# ---- vorlage_fehler(): klare Meldung statt leerer Dateinamen
r.check("Vorlage: gültig", el.vorlage_fehler("{datum} {titel} {feld:Betrag}", ["Betrag"]) == [])
r.check("Vorlage: unbekannte Variable", el.vorlage_fehler("{farbe}"))
r.check("Vorlage: Klammer ohne Gegenstück", el.vorlage_fehler("{titel"))
r.check("Vorlage: {feld:} ohne Namen", el.vorlage_fehler("{feld:}"))
r.check("Vorlage: unbekanntes Feld, wenn der Bestand bekannt ist", el.vorlage_fehler("{feld:Farbe}", ["Betrag"]))
r.check("Vorlage: Feldname ohne Rücksicht auf Groß-/Kleinschreibung", el.vorlage_fehler("{feld:betrag}", ["Betrag"]) == [])
r.check("Vorlage: zu lang", el.vorlage_fehler("x" * (el.VORLAGE_MAX + 1)))

# ---- sicherer_name(): kein Pfad, keine Steuerzeichen, begrenzte Länge
_s = el.sicherer_name
r.check("Name: Pfadtrenner werden Bindestriche (kein Unterordner)", _s("a/b\\c") == "a-b-c")
r.check("Name: kein Weg nach oben", _s("../../etc/passwd") == "-..-etc-passwd" and _s("..") == "dokument" and _s(".") == "dokument")
r.check("Name: keine versteckte Datei, kein Punkt am Ende", _s(".bashrc") == "bashrc" and _s("Rechnung.") == "Rechnung")
r.check("Name: Steuerzeichen und Zeilenumbrüche weg", _s("a\x00b\x1fc\nd\te") == "abc d e", repr(_s("a\x00b\x1fc\nd\te")))
r.check("Name: Richtungsumkehr (U+202E) und Nullbreite weg", _s("Rechnung\u202efdp.exe\u200b") == "Rechnungfdp.exe")
r.check("Name: unter Windows verbotene Zeichen ersetzt", _s('a<b>c:d"e|f?g*h') == "a_b_c_d_e_f_g_h")
r.check("Name: reservierte Windows-Namen entschärft", _s("CON") == "_CON" and _s("lpt1.txt") == "_lpt1.txt" and _s("CONTO") == "CONTO")
r.check("Name: NFC (zerlegtes ä wird eins)", _s("a\u0308") == "ä")
_lang = _s("ä" * 200)
r.check("Name: Länge in Bytes begrenzt, kein halbes Zeichen",
        len(_lang.encode()) <= el.MAX_STAMM_BYTES and set(_lang) == {"ä"}, str(len(_lang.encode())))
r.check("Name: leer wird zum Ersatz", _s("  \x00 ") == "dokument" and _s("", ersatz="x") == "x")
_boese = ["../x", "/abs", "a/../../b", "\u202e", "C:\\Windows", "nul", "..\\..", "\n", "a" * 400]
r.check("Name: nie ein Pfadtrenner, nie leer, nie „.“/„..“",
        all(os.sep not in _s(b) and "/" not in _s(b) and "\\" not in _s(b) and _s(b) not in ("", ".", "..") for b in _boese))

# ---- vorlage_fuellen(), nummer(), eindeutig(), dateinamen()
r.check("Füllen: Titel mit Schrägstrich legt keinen Ordner an",
        el.vorlage_fuellen("{datum} {titel}", _v) == "2026-03-04 Rechnung 2025-26")
r.check("Füllen: benutzerdefiniertes Feld", el.vorlage_fuellen("{feld:status}_{id}", _v) == "bezahlt_12")
r.check("Füllen: alles leer → dokument-<id>",
        el.vorlage_fuellen("{korrespondent}", el.dokument_variablen({"id": 5}, {})) == "dokument-5")
r.check("Nummer: dreistellig, bei mehr als 999 breiter", el.nummer(7, 12) == "007_" and el.nummer(7, 1200) == "0007_")
r.check("Eindeutig: zweiter und dritter bekommen (2), (3)",
        el.eindeutig(["a.pdf", "a.pdf", "a.pdf"]) == ["a.pdf", "a (2).pdf", "a (3).pdf"])
r.check("Eindeutig: Groß-/Kleinschreibung zählt als gleich (Windows, macOS)",
        el.eindeutig(["Rechnung.pdf", "rechnung.pdf"]) == ["Rechnung.pdf", "rechnung (2).pdf"])
r.check("Eindeutig: ein erzeugter Name kollidiert nicht mit einem vorhandenen",
        el.eindeutig(["a (2).pdf", "a.pdf", "a.pdf"]) == ["a (2).pdf", "a.pdf", "a (3).pdf"])
r.check("Eindeutig: belegte Namen (Inhaltsverzeichnis) werden umgangen",
        el.eindeutig(["Inhaltsverzeichnis.pdf"], belegt=["Inhaltsverzeichnis.pdf"]) == ["Inhaltsverzeichnis (2).pdf"])
r.check("Eindeutig: NFC — zerlegtes und fertiges ä sind derselbe Name",
        el.eindeutig(["ä.pdf", "a\u0308.pdf"])[1] == "a\u0308 (2).pdf")
_e3 = [el.dokument_variablen({"id": i, "title": "Gleich"}, {}) for i in (1, 2, 3)]
_dn = el.dateinamen(_e3, "{titel}", True, el.inhalt_dateiname(True, 3))
r.check("Dateinamen: nummeriert, Verzeichnis 000_ vorn, alle verschieden",
        _dn == ["001_Gleich.pdf", "002_Gleich.pdf", "003_Gleich.pdf"] and el.inhalt_dateiname(True, 3) == "000_Inhaltsverzeichnis.pdf", str(_dn))
r.check("Dateinamen: ohne Nummer eindeutig gemacht",
        el.dateinamen(_e3, "{titel}", False) == ["Gleich.pdf", "Gleich (2).pdf", "Gleich (3).pdf"])
r.check("Dateinamen: jeder Name endet auf .pdf und ist entschärft",
        all(n.endswith(".pdf") and "/" not in n for n in el.dateinamen(
            [el.dokument_variablen({"id": 1, "title": "../../x\u202e"}, {})], "{titel}", False)))
_zn = el.export_dateiname("zip", 3, "2026-09-27 1530")
r.check("Downloadname: Datum, Anzahl, Endung", _zn == "Export 2026-09-27 1530 (3 Dokumente).zip"
        and el.export_dateiname("pdf", 1, "2026-09-27 1530").endswith("(1 Dokument).pdf"), _zn)

# ---- sortieren()
def _e(i, **w):
    d = el.dokument_variablen({"id": i}, {})
    d["werte"].update(w)
    return d


_liste = [_e(1, titel="Rechnung 10", datum="2026-02-01", asn="9"), _e(2, titel="Rechnung 9", datum=""),
          _e(3, titel="Äpfel", datum="2025-12-31", asn="10"), _e(4, titel="birne", datum="2026-01-15", asn="")]
_ids = lambda xs: [int(x["werte"]["id"]) for x in xs]  # noqa: E731
r.check("Sortierung: ohne Schlüssel die Reihenfolge der Auswahl", _ids(el.sortieren(_liste)) == [1, 2, 3, 4])
r.check("Sortierung: ohne Schlüssel absteigend = umgedreht", _ids(el.sortieren(_liste, "", True)) == [4, 3, 2, 1])
r.check("Sortierung: Datum aufsteigend, ohne Datum hinten", _ids(el.sortieren(_liste, "datum")) == [3, 4, 1, 2])
r.check("Sortierung: Datum absteigend, ohne Datum trotzdem hinten", _ids(el.sortieren(_liste, "datum", True)) == [1, 4, 3, 2])
r.check("Sortierung: Titel natürlich (9 vor 10), Ä wie A, ohne Groß-/Kleinschreibung",
        _ids(el.sortieren(_liste, "titel")) == [3, 4, 2, 1], str(_ids(el.sortieren(_liste, "titel"))))
r.check("Sortierung: ASN als Zahl (9 vor 10)", _ids(el.sortieren(_liste, "asn")) == [1, 3, 2, 4])
_gleich = [_e(5, typ="Rechnung"), _e(6, typ="Rechnung"), _e(7, typ="Angebot")]
r.check("Sortierung: bei Gleichstand bleibt die Auswahl-Reihenfolge (auch absteigend)",
        _ids(el.sortieren(_gleich, "typ")) == [7, 5, 6] and _ids(el.sortieren(_gleich, "typ", True)) == [5, 6, 7])
_betrag = [el.dokument_variablen({"id": i, "custom_fields": [{"field": 7, "value": v}]}, _namen)
           for i, v in ((1, "EUR100.00"), (2, "EUR9.50"), (3, None))]
r.check("Sortierung: Geldfeld als Zahl, leeres Feld hinten", _ids(el.sortieren(_betrag, "feld:Betrag")) == [2, 1, 3])

# ---- Inhaltsverzeichnis: Seiten, Sprungziele, Zeilen
_stimmt = all(len(el.toc_verteilen(list(range(n)))) == el.toc_seiten(n)
              and sum(el.toc_verteilen(list(range(n))), []) == list(range(n)) for n in range(0, 400))
r.check("Verzeichnis: Seitenzahl vorab = tatsächliche Verteilung, keine Zeile verloren (0–399 Zeilen)", _stimmt)
r.check("Verzeichnis: Grenzen der ersten und der Folgeseiten",
        el.toc_seiten(el.ZEILEN_ERSTE) == 1 and el.toc_seiten(el.ZEILEN_ERSTE + 1) == 2
        and el.toc_seiten(el.ZEILEN_ERSTE + el.ZEILEN_FOLGE + 1) == 3)
r.check("Verzeichnis: passt auf A4 (Zeilen × Höhe + Kopf + Ränder)",
        el.ZEILEN_ERSTE * el.ZEILE_HOEHE + el.KOPF_HOEHE + 2 * el.RAND <= el.SEITE_HOEHE
        and el.ZEILEN_FOLGE * el.ZEILE_HOEHE + 2 * el.RAND <= el.SEITE_HOEHE)
r.check("Startseiten: hinter dem Verzeichnis, fortlaufend", el.startseiten(2, [3, 1, 4]) == [2, 5, 6])
_ein = [dict(_e(1, titel="A", datum="2026-01-01", korrespondent="K"), seitenzahl=2), dict(_e(2, titel=""), seitenzahl=1)]
_fehl = [dict(_e(9, titel="Text"), grund="kein PDF")]
_z = el.toc_zeilen(_ein, _fehl, "https://dms.example.com", sprungziele=[1, 3])
r.check("Zeilen (ein PDF): Nummer, Titel, Sprung und „Seite n“ (1-basiert)",
        (_z[0]["nr"], _z[0]["titel"], _z[0]["sprung"], _z[0]["rechts"]) == ("1.", "A", 1, "Seite 2"), str(_z[0]))
r.check("Zeilen: Titel fehlt → „Dokument <id>“", _z[1]["titel"] == "Dokument 2")
r.check("Zeilen: Link nach Paperless je Dokument", _z[0]["paperless"] == "https://dms.example.com/documents/1/details")
r.check("Zeilen: Angaben (Korrespondent, Datum, Seiten, ID)", _z[0]["meta"] == "K · 2026-01-01 · 2 Seiten · #1", _z[0]["meta"])
r.check("Zeilen: Übersprungene am Ende unter „Nicht enthalten“, mit Grund und Paperless-Link, ohne Sprung",
        _z[2]["art"] == "ueberschrift" and _z[3]["art"] == "fehlt" and _z[3]["sprung"] is None
        and "kein PDF" in _z[3]["meta"] and _z[3]["paperless"].endswith("/documents/9/details"))
_zd = el.toc_zeilen(_ein, [], "", dateien=["001_A.pdf", "002_x.pdf"])
r.check("Zeilen (einzeln): Datei als Ziel und in den Angaben, ohne Paperless-Adresse kein Link",
        _zd[0]["datei"] == "001_A.pdf" and _zd[0]["meta"].startswith("Datei: 001_A.pdf") and _zd[0]["paperless"] == ""
        and _zd[0]["sprung"] is None and len(_zd) == 2)
r.check("Lesezeichen: Titel mit Datum", el.lesezeichen(_ein[0]) == "A (2026-01-01)" and el.lesezeichen(_ein[1]) == "Dokument 2")
r.check("Relativer Link: kodiert, im selben Ordner",
        el.relativer_link("001_Rechnung März.pdf") == "./001_Rechnung%20M%C3%A4rz.pdf")

# ---- Statisch: jeder Export-Endpunkt fragt die Paperless-Sitzung (AST über panel/app.py)
# Wer einen Endpunkt ergänzt und die Prüfung vergisst, macht Dokumente ohne Leserecht abrufbar.
_app = ast.parse((ROOT / "panel" / "app.py").read_text(encoding="utf-8"))
_funks = {f.name: f for f in ast.walk(_app) if isinstance(f, ast.FunctionDef)}
_PRUEFER = {"als_nutzer", "export_lesbar", "_export_job", "_knopf_sitzung"}


def _ruft(fn, namen, tiefe=0):
    """Ruft die Funktion (direkt oder über eine Funktion dieses Moduls) einen der Prüfer?"""
    for k in ast.walk(fn):
        if not isinstance(k, ast.Call):
            continue
        name = k.func.id if isinstance(k.func, ast.Name) else k.func.attr if isinstance(k.func, ast.Attribute) else ""
        if name in namen:
            return True
        if (isinstance(k.func, ast.Name) and tiefe < 3 and name in _funks and name != fn.name
                and _ruft(_funks[name], namen, tiefe + 1)):
            return True
    return False


_export_routen = []
for f in _funks.values():
    for d in f.decorator_list:
        if (isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)
                and str(d.args[0].value).startswith("/knopf/export")):
            _export_routen.append((d.args[0].value, f))
r.check("Statisch: vier Export-Endpunkte gefunden (sonst prüft das Folgende nichts)", len(_export_routen) == 4,
        str([p for p, _ in _export_routen]))
_ohne = [p for p, f in _export_routen if not _ruft(f, _PRUEFER)]
r.check("Statisch: jeder Export-Endpunkt prüft die Paperless-Sitzung des Nutzers", not _ohne, str(_ohne))
_job = _funks.get("_export_job")
r.check("Statisch: Status und Download prüfen die Leserechte bei JEDEM Abruf erneut",
        _job is not None and _ruft(_job, {"export_lesbar"})
        and any(isinstance(k, ast.Raise) for k in ast.walk(_job)))
_start = _funks.get("export_starten")
_src_start = ast.get_source_segment((ROOT / "panel" / "app.py").read_text(encoding="utf-8"), _start) if _start else ""
_erste = next((k for k in (_start.body if _start else []) if not isinstance(k, ast.Expr) or not isinstance(k.value, ast.Constant)), None)
r.check("Statisch: Start prüft Kopf und Sitzung als Erstes (vor dem Auftrag)",
        _erste is not None and isinstance(_erste, ast.Expr) and isinstance(_erste.value, ast.Call)
        and getattr(_erste.value.func, "id", "") == "_knopf_sitzung")
_erste_job = next((k for k in (_job.body if _job else []) if not isinstance(k, ast.Expr) or not isinstance(k.value, ast.Constant)), None)
r.check("Statisch: Status und Download prüfen Kopf und Sitzung vor der Suche nach dem Auftrag",
        _erste_job is not None and isinstance(_erste_job, ast.Expr) and isinstance(_erste_job.value, ast.Call)
        and getattr(_erste_job.value.func, "id", "") == "_knopf_sitzung")
r.check("Statisch: Start lehnt ab, wenn ein Dokument nicht lesbar ist (nicht still weglassen)",
        "if verweigert:\n        raise HTTPException(403" in _src_start)
_laden = _funks.get("_pdf_laden")
r.check("Statisch: der Download prüft die Größengrenze je Block", _laden is not None and _ruft(_laden, {"groesse_fehler"}))

# ---- Unicode-Hygiene der eigenen Meldungen: echte Umlaute, keine Ersatzschreibung
_quelle = (ROOT / "panel" / "exportlogik.py").read_text(encoding="utf-8")
r.check("exportlogik.py ist NFC", unicodedata.is_normalized("NFC", _quelle))

# Verdrahtung: wer einen Export auf „fertig“ setzt, begrenzt danach den Speicher aller fertigen Exporte.
import ast as _ast
_baum = _ast.parse((ROOT / "panel" / "app.py").read_text(encoding="utf-8"))
def _ruft(fn, name):
    return any(isinstance(n, _ast.Call) and getattr(n.func, "id", None) == name for n in _ast.walk(fn))
def _setzt_fertig(fn):
    return any(isinstance(n, _ast.Call) and getattr(n.func, "id", None) == "_export"
               and any(k.arg == "status" and isinstance(k.value, _ast.Constant) and k.value.value == "fertig" for k in n.keywords)
               for n in _ast.walk(fn))
_fertig = [f for f in _ast.walk(_baum) if isinstance(f, _ast.FunctionDef) and _setzt_fertig(f)]
r.check("Verdrahtung: nach „fertig“ wird der Speicher aller Exporte begrenzt",
        _fertig and all(_ruft(f, "_export_speicher_begrenzen") for f in _fertig), str([f.name for f in _fertig]))

# Aufbewahrung: Vorgabe 20 Minuten (PO 2026-09-27) — gelesen aus der Zuweisung in app.py.
_aufb = [n.value for n in ast.walk(_app) if isinstance(n, ast.Assign)
         and any(getattr(t, "id", "") == "EXPORT_AUFBEWAHRUNG" for t in n.targets)]
_vorgabe = [c.args[1].value for v in _aufb for c in ast.walk(v)
            if isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_env_zahl" and len(c.args) == 2]
r.check("Vorgabe: Export 20 Minuten abrufbar (EXPORT_AUFBEWAHRUNG_MIN)", _vorgabe == [20], str(_vorgabe))

sys.exit(r.done())
