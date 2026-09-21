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


# ---- build_cfs(): die Funktion, die entscheidet WAS geschrieben wird.
# Bis 2026-09-21 ungetestet — und genau dort steckten zwei Fehler, die der
# laengst laufende Produktivstand nicht hat. Die Faelle stehen hier, damit sie nicht
# wiederkommen. Aufbau: ein Zusammenfassungsfeld (38, longtext), ein Hinweisfeld
# (39, longtext), ein manuelles Feld (13, date) und ein normales KI-Feld (2, monetary).
_CF = [
    {"id": 38, "name": "Zusammenfassung", "data_type": "longtext"},
    {"id": 39, "name": "KI-Hinweis", "data_type": "longtext"},
    {"id": 13, "name": "Bezahlt-Am", "data_type": "date"},
    {"id": 2, "name": "Betrag", "data_type": "monetary"},
]
_SKIP = {38, 39, 13}


def _feld(cfs, fid):
    """Alle Einträge zu einem Feld — als Liste, denn genau die Anzahl ist der Testgegenstand."""
    return [c for c in cfs if c["field"] == fid]


# Die Zusammenfassung wird am Ende gesetzt. Stünde sie zusätzlich in der Schleife,
# enthielte die Liste dasselbe Feld zweimal — Paperless bekäme zwei Werte für ein Feld.
_cfs, _ = classify.build_cfs(
    _CF, {38: "ALTE Zusammenfassung", 2: "EUR10.00"}, {},
    "NEUE Zusammenfassung", 38, _SKIP)
r.check("build_cfs: Zusammenfassung steht genau einmal in der Liste",
        len(_feld(_cfs, 38)) == 1)
r.check("build_cfs: und zwar mit dem NEUEN Wert",
        _feld(_cfs, 38)[0]["value"] == "NEUE Zusammenfassung")

# Der Nutzer-Hinweis wird nach Gebrauch entfernt (Schleifenschutz: solange das Feld
# befüllt ist, feuert der Redo-Trigger erneut). Das Feld steht in skip_fids, damit die
# KI es nicht setzt — der Klassifizierer selbst muss es aber leeren dürfen.
_cfs, _flog = classify.build_cfs(
    _CF, {39: "Korrespondent war falsch", 2: "EUR10.00"}, {},
    "", None, _SKIP, {39: None})
r.check("build_cfs: geleertes Hinweisfeld ist NICHT mehr in der Liste",
        _feld(_cfs, 39) == [])
r.check("build_cfs: das Entfernen wird protokolliert",
        _flog.get("KI-Hinweis") == "entfernt")

# Gegenprobe: ohne Auftrag des Codes bleibt der Hinweis stehen.
_cfs, _ = classify.build_cfs(
    _CF, {39: "bleibt stehen"}, {}, "", None, _SKIP)
r.check("build_cfs: ohne Auftrag bleibt der Hinweis erhalten",
        _feld(_cfs, 39) == [{"field": 39, "value": "bleibt stehen"}])

# Ein geschütztes Feld bleibt geschützt, selbst wenn die KI seinen Namen halluziniert.
# (Die KI bekommt skip_fids gar nicht erst im Prompt — aber „bekommt es nicht" ist keine Zusage.)
_cfs, _ = classify.build_cfs(
    _CF, {13: "2026-01-01"}, {"Bezahlt-Am": "2026-09-21"}, "", None, _SKIP)
r.check("build_cfs: KI kann ein manuelles Feld nicht überschreiben",
        _feld(_cfs, 13) == [{"field": 13, "value": "2026-01-01"}])

# Eine LEERE Feldzuordnung ist ein Zustand, kein fehlendes Feld. Paperless loescht jede
# Zuordnung, die in der gesendeten Liste fehlt — ein manuelles Feld, das ein post-consume-Skript
# bewusst leer anlegt (damit es in der Maske erscheint), verschwand dadurch nach dem ersten Lauf.
# Aufgefallen 2026-09-21 an echten Dokumenten im Testbett.
_cfs, _ = classify.build_cfs(
    _CF, {13: None, 2: "EUR10.00"}, {}, "", None, _SKIP)
r.check("build_cfs: leere Zuordnung eines geschuetzten Feldes bleibt erhalten",
        _feld(_cfs, 13) == [{"field": 13, "value": None}])

_cfs, _ = classify.build_cfs(
    _CF, {2: None}, {}, "", None, set())
r.check("build_cfs: leere Zuordnung eines nicht erwaehnten Feldes bleibt erhalten",
        _feld(_cfs, 2) == [{"field": 2, "value": None}])

_cfs, _flog = classify.build_cfs(
    _CF, {2: None}, {"Betrag": "BEHALTEN"}, "", None, set())
r.check("build_cfs: BEHALTEN auf leerem Feld erhaelt die Zuordnung",
        _feld(_cfs, 2) == [{"field": 2, "value": None}] and _flog.get("Betrag") == "behalten")

# Gegenprobe: ein Feld, das gar keine Zuordnung hat, bekommt auch keine.
_cfs, _ = classify.build_cfs(_CF, {}, {}, "", None, _SKIP)
r.check("build_cfs: ohne bestehende Zuordnung wird keine erfunden", _cfs == [])

# Und der Unterschied zum Leeren auf Wunsch der KI bleibt bestehen.
_cfs, _flog = classify.build_cfs(
    _CF, {2: "EUR10.00"}, {"Betrag": None}, "", None, set())
r.check("build_cfs: null der KI entfernt die Zuordnung weiterhin",
        _feld(_cfs, 2) == [] and _flog["Betrag"] == "geleert")

# Die gewohnten Wege bleiben, wie sie waren.
_cfs, _flog = classify.build_cfs(
    _CF, {2: "EUR10.00"}, {"Betrag": "BEHALTEN"}, "", None, _SKIP)
r.check("build_cfs: BEHALTEN lässt den alten Wert stehen",
        _feld(_cfs, 2) == [{"field": 2, "value": "EUR10.00"}] and _flog["Betrag"] == "behalten")

_cfs, _flog = classify.build_cfs(
    _CF, {2: "EUR10.00"}, {"Betrag": None}, "", None, _SKIP)
r.check("build_cfs: null leert ein KI-Feld",
        _feld(_cfs, 2) == [] and _flog["Betrag"] == "geleert")

_cfs, _ = classify.build_cfs(
    _CF, {2: "EUR10.00"}, {"Betrag": "12,50"}, "", None, _SKIP)
r.check("build_cfs: neuer Wert wird typgerecht gesetzt",
        _feld(_cfs, 2) == [{"field": 2, "value": "EUR12.50"}])


# ---- korrespondent_beispiele: Few-Shot fuer den Pass-2-Abgleich.
# Die konkreten Beispiele standen frueher hartkodiert im Prompt — mit echten Namen, die
# in einem oeffentlichen Repo nichts zu suchen haben. Sie gehoeren in die Config; hier
# steht, dass der Schluessel existiert, einen sicheren Default hat und Unsinn ueberlebt.
r.check("korrespondent_beispiele ist ein Config-Schluessel",
        "korrespondent_beispiele" in classify.CFG)
r.check("beispiel_text: leere Liste ergibt leeren Baustein",
        classify.beispiel_text([]) == "" and classify.beispiel_text(None) == "")
r.check("beispiel_text: Paare werden als z.B.-Liste formatiert",
        classify.beispiel_text([["Mustrmann", "Mustermann"], ["ACME Vers", "ACME"]])
        == " (z.B. 'Mustrmann'='Mustermann', 'ACME Vers'='ACME')")
r.check("beispiel_text: kaputte Eintraege werden uebergangen, nicht geworfen",
        classify.beispiel_text([["nur eins"], [], ["a", "b"], ["", "x"], "quatsch", ["c", "d"]])
        == " (z.B. 'a'='b', 'c'='d')")
r.check("beispiel_text: deckelt die Anzahl",
        classify.beispiel_text([[f"a{i}", f"b{i}"] for i in range(20)]).count("=") == 6)

# ---- cfull_hint: der Grounding-Baustein aus dem Korrespondent-Store.
# `ustid` hiess bis 2026-09-21 `uid`; ein Store von vorher muss weiter verstanden werden,
# sonst verliert eine bestehende Installation still ihre Kennungen.
_corr_meta_vorher = classify.CORR_META          # danach zuruecksetzen, sonst faerbt der
classify.CORR_META = {"7": {"kontext": "Kfz-Teile", "kundennummer": "KD-1", "ustid": "ATU111"},
                      "8": {"kontext": "Versicherung", "uid": "ATU222"},
                      "9": {}}
r.check("cfull_hint: Kontext, Kundennr und UID landen im Grounding",
        classify.cfull_hint({"id": 7}) == "Kfz-Teile; Kundennr KD-1; UID ATU111")
r.check("cfull_hint: alter Feldname uid wird weiter verstanden",
        classify.cfull_hint({"id": 8}) == "Versicherung; UID ATU222")
r.check("cfull_hint: leerer Eintrag ergibt leeren Hinweis",
        classify.cfull_hint({"id": 9}) == "")
classify.CORR_META = _corr_meta_vorher          # Test auf jeden folgenden ab

# ---- fehler_mit_feldnamen(): Paperless schluesselt Custom-Field-Fehler nach LISTEN-INDEX.
# Ein Modell kann Index -> Name nicht aufloesen; es raet. Deshalb uebersetzen wir im Code.
# Reihenfolge der gesendeten Liste = die Indizes, die Paperless zurueckmeldet.
_CFS = [{"field": 2, "value": "x"}, {"field": 13, "value": "y"}, {"field": 38, "value": "z"}]

r.check("fehler_mit_feldnamen: Index wird zum Feldnamen",
        classify.fehler_mit_feldnamen(
            '{"custom_fields": {"1": {"value": ["ungueltig"]}}}', _CFS, _CF)
        == """Feld 'Bezahlt-Am': {"value": ["ungueltig"]}""")

r.check("fehler_mit_feldnamen: mehrere Fehler werden alle benannt",
        classify.fehler_mit_feldnamen(
            '{"custom_fields": {"0": {"value": ["a"]}, "2": {"value": ["b"]}}}', _CFS, _CF)
        == """Feld 'Betrag': {"value": ["a"]} | Feld 'Zusammenfassung': {"value": ["b"]}""")

r.check("fehler_mit_feldnamen: Listenform, leere Eintraege sind fehlerfrei",
        classify.fehler_mit_feldnamen(
            '{"custom_fields": [{}, {"value": ["kaputt"]}, {}]}', _CFS, _CF)
        == """Feld 'Bezahlt-Am': {"value": ["kaputt"]}""")

r.check("fehler_mit_feldnamen: Index ausserhalb der Liste bleibt als Nummer stehen",
        "Eintrag 99" in classify.fehler_mit_feldnamen(
            '{"custom_fields": {"99": {"value": ["x"]}}}', _CFS, _CF))

r.check("fehler_mit_feldnamen: andere Fehlerteile gehen nicht verloren",
        "weitere" in classify.fehler_mit_feldnamen(
            '{"custom_fields": {"0": {"value": ["a"]}}, "title": ["zu lang"]}', _CFS, _CF))

# Kein JSON, kein custom_fields, Unsinn: lieber unveraendert als falsch geraten.
r.check("fehler_mit_feldnamen: Nicht-JSON bleibt unveraendert",
        classify.fehler_mit_feldnamen("500 Internal Server Error", _CFS, _CF)
        == "500 Internal Server Error")
r.check("fehler_mit_feldnamen: Fehler ohne custom_fields bleibt unveraendert",
        classify.fehler_mit_feldnamen('{"title": ["zu lang"]}', _CFS, _CF) == '{"title": ["zu lang"]}')
r.check("fehler_mit_feldnamen: leere Liste ergibt keine Ausgabe-Aenderung",
        classify.fehler_mit_feldnamen('{"custom_fields": []}', _CFS, _CF) == '{"custom_fields": []}')

# ---- Stille Fehlschlaege: ein kaputter Store darf nicht lautlos zu leeren Daten fuehren.
# Bis 2026-09-21 verschluckte _load_json jeden Fehler; ein Tippfehler im Korrespondent-Store
# haette das Grounding lautlos abgeschaltet.
import json as _json
_alt_dir = classify.SCRIPT_DIR
_probe = Path(_TMP) / "stores"
_probe.mkdir(exist_ok=True)
classify.SCRIPT_DIR = str(_probe)
classify._STORE_FEHLER.clear()

(_probe / "leer.json").write_text("{}", encoding="utf-8")
r.check("_load_json: gueltige Datei wird geladen", classify._load_json("leer.json", {}) == {})
r.check("_load_json: gueltige Datei meldet nichts", classify._STORE_FEHLER == [])

r.check("_load_json: fehlende Datei ist KEIN Befund",
        classify._load_json("gibtsnicht.json", {"a": 1}) == {"a": 1} and classify._STORE_FEHLER == [])

(_probe / "kaputt.json").write_text("{das ist kein json", encoding="utf-8")
r.check("_load_json: kaputte Datei liefert den Default",
        classify._load_json("kaputt.json", {"a": 1}) == {"a": 1})
r.check("_load_json: kaputte Datei WIRD gemeldet",
        any("kaputt.json" in f and "nicht lesbar" in f for f in classify._STORE_FEHLER))

(_probe / "falsch.json").write_text("[1, 2, 3]", encoding="utf-8")
classify._STORE_FEHLER.clear()
r.check("_load_json: falscher Aufbau liefert den Default",
        classify._load_json("falsch.json", {}) == {})
r.check("_load_json: falscher Aufbau WIRD gemeldet",
        any("falsch.json" in f and "Aufbau" in f for f in classify._STORE_FEHLER))

classify.SCRIPT_DIR = _alt_dir
classify._STORE_FEHLER.clear()

# ---- nachbearbeiten(): die Naht fuer installationseigene Schritte.
# Ohne sie muss jede Installation, die mehr braucht als Klassifizierung, den Klassifizierer
# forken — genau so sind vier auseinanderlaufende Staende entstanden.
_nb_dir = Path(_TMP) / "nachbearbeitung"
_nb_dir.mkdir(exist_ok=True)


def _log_seit(marke):
    """Neue Logzeilen seit einer Marke."""
    text = Path(os.environ["CLASSIFY_LOG"]).read_text(encoding="utf-8") if Path(os.environ["CLASSIFY_LOG"]).exists() else ""
    return text.split(marke, 1)[-1] if marke in text else text


_alt_cfg = classify.CFG.get("nachbearbeitung")

# (1) Nichts konfiguriert: der Lauf darf davon nichts merken.
classify.CFG["nachbearbeitung"] = ""
classify.log("MARKE-1")
classify.nachbearbeiten(1, {}, True, {})
r.check("nachbearbeiten: ohne Konfiguration passiert nichts", _log_seit("MARKE-1").strip() == "")

# (2) Konfiguriert, aber nicht vorhanden: melden statt schweigen.
classify.CFG["nachbearbeitung"] = str(_nb_dir / "gibtsnicht.py")
classify.log("MARKE-2")
classify.nachbearbeiten(2, {}, True, {})
r.check("nachbearbeiten: fehlendes Skript wird gemeldet", "nachbearbeitung-fehlt" in _log_seit("MARKE-2"))

# (3) Skript laeuft und bekommt die Daten auf stdin.
_echo = _nb_dir / "echo.py"
_echo.write_text(
    "import json,sys\n"
    "d = json.load(sys.stdin)\n"
    "print('bekam doc', d['doc_id'], 'erfolg', d['erfolg'], 'quelle', d['quelle'])\n",
    encoding="utf-8")
classify.CFG["nachbearbeitung"] = str(_echo)
classify.log("MARKE-3")
classify.nachbearbeiten(915, {"tags": [1]}, True, {"x": 1})
_z3 = _log_seit("MARKE-3")
r.check("nachbearbeiten: Skript bekommt Dokument-ID und Erfolg",
        "bekam doc 915 erfolg True" in _z3, _z3.strip()[:120])

# (4) Ein scheiterndes Skript darf den Lauf NICHT mitreissen.
_kaputt = _nb_dir / "kaputt.py"
_kaputt.write_text("import sys; sys.exit('absichtlich kaputt')\n", encoding="utf-8")
classify.CFG["nachbearbeitung"] = str(_kaputt)
classify.log("MARKE-4")
try:
    classify.nachbearbeiten(4, {}, True, {})
    _durchgelaufen = True
except BaseException:
    _durchgelaufen = False
r.check("nachbearbeiten: ein Fehler im Skript beendet den Lauf nicht", _durchgelaufen)
r.check("nachbearbeiten: und wird protokolliert", "nachbearbeitung-fail" in _log_seit("MARKE-4"))

# (5) Im Trockenlauf wird nicht nachbearbeitet — sonst schreibt ein DRY-Lauf doch etwas.
classify.CFG["nachbearbeitung"] = str(_echo)
_alt_dry = classify.DRY
classify.DRY = True
classify.log("MARKE-5")
classify.nachbearbeiten(5, {}, True, {})
classify.DRY = _alt_dry
r.check("nachbearbeiten: im Trockenlauf passiert nichts", "bekam doc 5" not in _log_seit("MARKE-5"))

classify.CFG["nachbearbeitung"] = _alt_cfg

sys.exit(r.done())
