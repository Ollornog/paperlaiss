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

# ---- merge_metadaten(): zwei Korrespondenten zusammenführen, ohne Kundendaten zu verlieren.
#
# Die Namen sind NEUTRAL (RFC 2606, `.example`), nicht aus einem echten Mandanten.
# Bis 2026-09-22 standen hier ein realer Firmenname und zwei real registrierte
# `.at`-Domains — in einem ÖFFENTLICHEN Repo. Gefunden hat es keine Prüfung:
# `pruefe_adressen` sieht nur URLs MIT Schema, und das Infrastruktur-Muster
# verlangt drei Namensteile (`sub.domain.tld`) — eine blanke Second-Level-Domain
# fällt durch beide. Testdaten sind Veröffentlichung wie jede andere Zeile auch.
_ziel = {"kundennummer": "KD-1", "kontext": "", "domains": "kunde.example", "aliase": "Kunde"}
_q1 = {"kundennummer": "KD-99", "kontext": "Reifenhandel", "domains": "kunde-handel.example",
       "aliase": "KUNDE Handel"}
_erg = kern.merge_metadaten(_ziel, [_q1])

r.check("Merge: das Ziel behält seine Kundennummer", _erg["kundennummer"] == "KD-1")
r.check("Merge: leeres Zielfeld wird aus der Quelle gefüllt", _erg["kontext"] == "Reifenhandel")
r.check("Merge: Domains werden vereinigt, nicht überschrieben",
        _erg["domains"] == "kunde.example, kunde-handel.example")
r.check("Merge: Aliase werden vereinigt", _erg["aliase"] == "Kunde, KUNDE Handel")

# Dubletten in Listen fallen raus — die zuerst gesehene Schreibweise gewinnt.
_erg2 = kern.merge_metadaten({"domains": "Kunde.EXAMPLE"},
                             [{"domains": "kunde.example, neu.example"}])
r.check("Merge: Dubletten fallen raus, Groß-/Kleinschreibung egal",
        _erg2["domains"] == "Kunde.EXAMPLE, neu.example")

# Leere Felder bleiben draußen, damit der Store nicht mit "" zuwächst.
r.check("Merge: leere Werte landen nicht im Ergebnis",
        "telefon" not in kern.merge_metadaten({"telefon": ""}, [{"telefon": "  "}]))

# Mehrere Quellen: die erste, die etwas hat, gewinnt.
r.check("Merge: erste Quelle mit Wert gewinnt",
        kern.merge_metadaten({}, [{"email": ""}, {"email": "a@example.com"},
                                  {"email": "b@example.com"}])["email"] == "a@example.com")

# Ohne Quellen bleibt das Ziel unverändert (aber bereinigt).
r.check("Merge: ohne Quellen bleibt das Ziel",
        kern.merge_metadaten({"kundennummer": "KD-1"}, []) == {"kundennummer": "KD-1"})
r.check("Merge: leeres Ziel und leere Quellen ergibt leeren Eintrag",
        kern.merge_metadaten({}, []) == {})

# ---- config_uebernehmen(): ein Formular liefert Text, die Konfiguration braucht Typen.
# Ohne Rückwandlung stünde nach dem ersten Speichern "true" statt true und "300" statt 300 —
# und der Klassifizierer liest eine Zeichenkette, wo er eine Zahl erwartet.
_alt = {"enabled": True, "ocr_min_len": 300, "temperature": 0.1, "model": "mistral-small",
        "manual_fields": ["Bezahlt-Am"], "tag_descriptions": {"a": "b"}, "system_prompt": "lang…"}

r.check("feld_typ erkennt Wahrheitswerte", kern.feld_typ(True) == "bool")
r.check("feld_typ erkennt Zahlen", kern.feld_typ(300) == "zahl" and kern.feld_typ(0.1) == "zahl")
r.check("feld_typ erkennt Listen und Wörterbücher",
        kern.feld_typ([]) == "json" and kern.feld_typ({}) == "json")
r.check("feld_typ trennt Zeile von Fließtext",
        kern.feld_typ("kurz") == "zeile" and kern.feld_typ("x" * 200) == "text"
        and kern.feld_typ("mit\nUmbruch") == "text")

_neu, _weg = kern.config_uebernehmen(_alt, {
    "enabled": "false", "ocr_min_len": "500", "temperature": "0,3",
    "model": "mistral-large", "manual_fields": '["Bezahlt-Am", "Notiz"]'})
r.check("Übernahme: Wahrheitswert aus Text", _neu["enabled"] is False)
r.check("Übernahme: ganze Zahl bleibt ganz", _neu["ocr_min_len"] == 500 and isinstance(_neu["ocr_min_len"], int))
r.check("Übernahme: Komma als Dezimaltrenner", _neu["temperature"] == 0.3)
r.check("Übernahme: Liste aus JSON", _neu["manual_fields"] == ["Bezahlt-Am", "Notiz"])
r.check("Übernahme: nichts übergangen bei gültiger Eingabe", _weg == [])

# Unsinn wird ÜBERGANGEN, nicht geraten — ein Tippfehler darf keinen Schlüssel zerstören.
_neu2, _weg2 = kern.config_uebernehmen(_alt, {"ocr_min_len": "dreihundert"})
r.check("Übernahme: unlesbare Zahl lässt den alten Wert stehen", _neu2["ocr_min_len"] == 300)
r.check("Übernahme: und wird gemeldet", any("ocr_min_len" in w for w in _weg2))

_neu3, _weg3 = kern.config_uebernehmen(_alt, {"manual_fields": '{"kein": "array"}'})
r.check("Übernahme: falscher JSON-Typ lässt den alten Wert stehen",
        _neu3["manual_fields"] == ["Bezahlt-Am"])
r.check("Übernahme: falscher Typ wird gemeldet", any("manual_fields" in w for w in _weg3))

_neu4, _weg4 = kern.config_uebernehmen(_alt, {"gibtsnicht": "x"})
r.check("Übernahme: unbekannter Schlüssel wird nicht angelegt", "gibtsnicht" not in _neu4)
r.check("Übernahme: unbekannter Schlüssel wird gemeldet", any("gibtsnicht" in w for w in _weg4))

r.check("Übernahme: leere Eingabe ändert nichts", kern.config_uebernehmen(_alt, {})[0] == _alt)

# ---- log_art(): die Reihenfolge der Muster entscheidet.
# "OCR-rescue-fail" enthält "OCR-rescue", "repair-fehlgeschlagen" enthält "repariert" —
# wer zuerst auf das kürzere prüft, zählt Fehler als Erfolge.
r.check("log_art: OCR-rescue-fail ist ein Fehler, kein OCR-Lauf",
        kern.log_art("OCR-rescue-fail 42: kaputt") == "fehler")
r.check("log_art: OCR-rescue ist ein OCR-Lauf", kern.log_art("OCR-rescue 42: 340 Zeichen") == "ocr")
r.check("log_art: repair-fehlgeschlagen ist ein Fehler",
        kern.log_art("repair-fehlgeschlagen 42") == "fehler")
r.check("log_art: repariert ist kein Fehler", kern.log_art("repariert 42 nach 2 Runde(n)") == "repariert")
r.check("log_art: OK ist klassifiziert", kern.log_art("OK 42 | exakt='X'") == "klassifiziert")
r.check("log_art: VORSCHLAG eigene Art", kern.log_art("VORSCHLAG 42 | ...") == "vorschlag")
r.check("log_art: unbekannte Zeile ergibt None", kern.log_art("irgendwas anderes") is None)

# ---- verlauf(): tägliche Zählung
_log = [
    "2026-09-01 10:00:00 OK 1 | x",
    "2026-09-01 10:01:00 OK 2 | x",
    "2026-09-01 10:02:00 OCR-rescue 3: 100 Zeichen",
    "2026-09-02 09:00:00 patch-fail 4 R1: kaputt",
    "2026-09-02 09:01:00 OK 4 | x",
    "kaputte Zeile ohne Datum",
]
_v = kern.verlauf(_log)
r.check("verlauf: ein Eintrag je Tag", len(_v) == 2)
r.check("verlauf: zählt je Art", _v[0]["tag"] == "2026-09-01" and _v[0]["klassifiziert"] == 2
        and _v[0]["ocr"] == 1)
r.check("verlauf: Fehler getrennt gezählt", _v[1].get("fehler") == 1 and _v[1].get("klassifiziert") == 1)
r.check("verlauf: Zeilen ohne Datum werden übergangen", all("tag" in e for e in _v))
r.check("verlauf: leeres Log ergibt leere Liste", kern.verlauf([]) == [])
r.check("verlauf: schneidet auf die gewünschte Anzahl Tage",
        len(kern.verlauf(_log, tage=1)) == 1)

# Lücken gehören dazu — "seit drei Wochen läuft nichts" sieht man nur mit leeren Tagen.
_luecke = kern.verlauf(["2026-09-01 10:00:00 OK 1 | x", "2026-09-05 10:00:00 OK 2 | x"])
r.check("verlauf: Lücken werden aufgefüllt", len(_luecke) == 5)
r.check("verlauf: leere Tage sind leer, nicht erfunden",
        _luecke[1] == {"tag": "2026-09-02"} and _luecke[0]["klassifiziert"] == 1)
r.check("verlauf: beginnt nicht vor dem ersten Ereignis", _luecke[0]["tag"] == "2026-09-01")

# ---- auffaelligkeiten(): was ist inzwischen gelöst?
_a = kern.auffaelligkeiten(_log)
r.check("auffaelligkeiten: nur Fehlerzeilen", len(_a) == 1)
r.check("auffaelligkeiten: als gelöst erkannt, weil später ein OK für dasselbe Dokument kam",
        _a[0]["geloest"] is True and _a[0]["doc"] == "4")

_offen = kern.auffaelligkeiten(["2026-09-03 08:00:00 patch-fail 7 R1: kaputt"])
r.check("auffaelligkeiten: ohne späteren Erfolg bleibt es offen", _offen[0]["geloest"] is False)

# Ein Erfolg VOR dem Fehler zählt nicht als Lösung.
_vorher = kern.auffaelligkeiten([
    "2026-09-03 07:00:00 OK 9 | x",
    "2026-09-03 08:00:00 patch-fail 9 R1: kaputt"])
r.check("auffaelligkeiten: ein früherer Erfolg löst nichts", _vorher[0]["geloest"] is False)

# ---- auth_einstellungen(): welche Anmeldung das Panel faehrt. Eine Fehlkonfiguration muss den
# Start verhindern, statt still offen oder unbenutzbar zu laufen.
_ae = kern.auth_einstellungen
r.check("Anmeldung: ohne PANEL_AUTH bleibt es beim Token", _ae({})["modus"] == "" and _ae({})["tinysesam"] is None)
r.check("Anmeldung: unbekannter Modus ist ein Fehler", _ae({"PANEL_AUTH": "tinyauth"})["fehler"])
_basis = {"PANEL_AUTH": "tinysesam", "PANEL_BASE_URL": "http://192.0.2.10:8400"}
r.check("Anmeldung: tinysesam ohne Anmeldeweg startet nicht", _ae(_basis)["fehler"])
r.check("Anmeldung: tinysesam ohne Basisadresse startet nicht",
        _ae({"PANEL_AUTH": "tinysesam", "PANEL_PASSWORD_LOGIN": "1"})["fehler"])
_pw = _ae({**_basis, "PANEL_PASSWORD_LOGIN": "1", "PANEL_ADMIN_USER": "admin", "PANEL_ADMIN_PASSWORD": "x"})
r.check("Anmeldung: Passwort-Login zum Debuggen", not _pw["fehler"] and _pw["tinysesam"]["password_enabled"] is True
        and _pw["tinysesam"]["oidc_enabled"] is False, str(_pw))
r.check("Anmeldung: über http kein Secure-Cookie", _pw["tinysesam"]["cookie_secure"] is False
        and _pw["tinysesam"]["https_mode"] == "off")
r.check("Anmeldung: Origin und rp_id aus der Basisadresse",
        _pw["tinysesam"]["origin"] == "http://192.0.2.10:8400" and _pw["tinysesam"]["rp_id"] == "192.0.2.10")
r.check("Anmeldung: keine Selbstregistrierung", _pw["tinysesam"]["allow_signup"] is False)
r.check("Anmeldung: Seite trägt den Projektnamen", _pw["tinysesam"]["rp_name"] == "paperlaiss")
r.check("Anmeldung: Erst-Admin wird übergeben", _pw["admin"] == ("admin", "x"))
_oidc = _ae({"PANEL_AUTH": "tinysesam", "PANEL_BASE_URL": "https://panel.example.com/",
             "PANEL_OIDC_ISSUER": "https://id.example.com", "PANEL_OIDC_CLIENT_ID": "c",
             "PANEL_OIDC_CLIENT_SECRET": "s", "PANEL_OIDC_GROUPS": "buero, chef"})
r.check("Anmeldung: Produktion = nur PocketID, Passwort aus", not _oidc["fehler"]
        and _oidc["tinysesam"]["oidc_enabled"] is True and _oidc["tinysesam"]["password_enabled"] is False, str(_oidc))
r.check("Anmeldung: über https Secure-Cookie", _oidc["tinysesam"]["cookie_secure"] is True
        and _oidc["tinysesam"]["base_url"] == "https://panel.example.com")
r.check("Anmeldung: Gruppenfilter aus Kommaliste", _oidc["tinysesam"]["oidc_allowed_groups"] == ["buero", "chef"])
r.check("Anmeldung: halbe OIDC-Konfiguration ist ein Fehler",
        _ae({**_basis, "PANEL_PASSWORD_LOGIN": "1", "PANEL_OIDC_ISSUER": "https://id.example.com"})["fehler"])
r.check("Anmeldung: Admin-Konto ohne Passwort-Login ist ein Fehler",
        _ae({"PANEL_AUTH": "tinysesam", "PANEL_BASE_URL": "https://panel.example.com",
             "PANEL_OIDC_ISSUER": "https://id.example.com", "PANEL_OIDC_CLIENT_ID": "c",
             "PANEL_OIDC_CLIENT_SECRET": "s", "PANEL_ADMIN_USER": "a", "PANEL_ADMIN_PASSWORD": "b"})["fehler"])

# ---- ausloeser_auswerten(): welcher Knopf in Paperless gedrückt wurde, und was vorher weg muss.
_aw = kern.ausloeser_auswerten
_hf = [{"field": 39, "value": "  bitte Typ Rechnung  "}, {"field": 2, "value": "EUR1"}]
m, h, pt = _aw([1, 239], [], 239, 240, 39)
r.check("Auslöser: Tag neu → neu klassifizieren, Tag entfernt", m == "neu" and pt == {"tags": [1]}, str((m, pt)))
m, h, pt = _aw([1], _hf, 239, 240, 39)
r.check("Auslöser: Hinweis → neu, Text gelesen, nur das Hinweisfeld entfernt",
        m == "neu" and h == "bitte Typ Rechnung" and pt == {"custom_fields": [{"field": 2, "value": "EUR1"}]}, str((m, h, pt)))
m, h, pt = _aw([240], [], 239, 240, 39)
r.check("Auslöser: Tag OCR → nur OCR, Tag bleibt (der Lauf entfernt ihn am Ende)", m == "nur_ocr" and pt == {}, str((m, pt)))
m, h, pt = _aw([239, 240], [], 239, 240, 39)
r.check("Auslöser: beide Tags → neu gewinnt, beide entfernt", m == "neu" and pt == {"tags": []}, str((m, pt)))
m, h, pt = _aw([1, 5], [{"field": 39, "value": ""}], 239, 240, 39)
r.check("Auslöser: nichts gesetzt (auch leeres Hinweisfeld) → kein Lauf, nichts zu entfernen",
        m is None and pt == {}, str((m, pt)))
m, h, pt = _aw([1], [], None, None, None)
r.check("Auslöser: nichts konfiguriert → kein Lauf", m is None and pt == {})
m, h, pt = _aw([1, 239, 77], [], 239, 240, 39, marker_id=77)
r.check("Auslöser: neu → Marker geht mit weg (Fertig-Signal für den Knopf)", m == "neu" and pt == {"tags": [1]}, str(pt))
m, h, pt = _aw([1, 240, 77], [], 239, 240, 39, marker_id=77)
r.check("Auslöser: nur OCR → Marker bleibt", m == "nur_ocr" and pt == {}, str(pt))
m, h, pt = _aw([1, 77], [], 239, 240, 39, marker_id=77)
r.check("Auslöser: nichts ausgelöst → Marker bleibt, nichts zu tun", m is None and pt == {}, str(pt))
r.check("log_art: OCR-Nachlauf und Nur-OCR zählen als OCR, ihre Fehler als Fehler",
        kern.log_art("OCR-nachgeholt 5: x") == "ocr" and kern.log_art("OCR-neu 5: 1 → 2") == "ocr"
        and kern.log_art("OCR-neu-fail 5: x") == "fehler" and kern.log_art("OCR-nachgeholt-fail 5") == "fehler")

# ---- Knöpfe in Paperless: Browser-Skript und Init-Skript müssen dieselben Platzhalter kennen,
# sonst landet „%%OCR_TAG%%" wörtlich im Browser und der Knopf sucht einen Tag, den es nicht gibt.
import re as _re
_knopf = (ROOT / "deploy/paperless-knoepfe/paperlaiss-knoepfe.js").read_text(encoding="utf-8")
_init = (ROOT / "deploy/paperless-knoepfe/10-paperlaiss-knoepfe.sh").read_text(encoding="utf-8")
_im_js = set(_re.findall(r"%%([A-Z_]+)%%", _knopf))
_ersetzt = set(_re.findall(r"s/%%([A-Z_]+)%%/", _init))
r.check("Knöpfe: jeder Platzhalter im Browser-Skript wird ersetzt",
        _im_js and _im_js == _ersetzt, f"js={sorted(_im_js)} init={sorted(_ersetzt)}")
r.check("Knöpfe: Init-Skript bricht Paperless nie ab (endet immer mit exit 0)",
        _init.rstrip().endswith("exit 0") and "exit 1" not in _init)

sys.exit(r.done())
