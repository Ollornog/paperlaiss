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
r.check("log_art: Erfolg MIT OCR zählt als klassifiziert, nicht als OCR (erstes Wort entscheidet)",
        kern.log_art("OK 913 | exakt='X' id=13 | typ=21 | tags=[] | new=[] | OCR-rescue(340)") == "klassifiziert")
r.check("log_art: Trockenlauf ist keine Art", kern.log_art("DRY 908 | exakt='X' | OCR-rescue(1)") is None)
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

# ---- knopf_rechte(): der Knopf in Paperless darf nur, was der Nutzer dort darf.
_ant = {"results": [{"id": 1, "user_can_change": True}, {"id": 2, "user_can_change": False}]}
r.check("Knopf: änderbar erlaubt, nur lesbar verweigert", kern.knopf_rechte(_ant, [2, 1]) == ([1], [2]))
r.check("Knopf: unsichtbares Dokument gilt als verweigert", kern.knopf_rechte(_ant, [1, 3]) == ([1], [3]))
r.check("Knopf: leere Antwort verweigert alles", kern.knopf_rechte({}, [5]) == ([], [5]))
r.check("log_art: OCR-Nachlauf und Nur-OCR zählen als OCR, ihre Fehler als Fehler",
        kern.log_art("OCR-nachgeholt 5: x") == "ocr" and kern.log_art("OCR-neu 5: 1 → 2") == "ocr"
        and kern.log_art("OCR-neu-fail 5: x") == "fehler" and kern.log_art("OCR-nachgeholt-fail 5") == "fehler")

# ---- Knöpfe in Paperless: Browser-Skript und Init-Skript müssen dieselben Platzhalter kennen,
# sonst landet „%%OCR_TAG%%" wörtlich im Browser und der Knopf sucht einen Tag, den es nicht gibt.
import re as _re
_knopf = (ROOT / "deploy/paperless-knoepfe/paperlaiss-knoepfe.js").read_text(encoding="utf-8")
_init = (ROOT / "deploy/paperless-knoepfe/10-paperlaiss-knoepfe.sh").read_text(encoding="utf-8")
_im_js = set(_re.findall(r"%%([A-Z_]+)%%", _knopf))
_ersetzt = set(_re.findall(r"s[/#]%%([A-Z_]+)%%[/#]", _init))
r.check("Knöpfe: jeder Platzhalter im Browser-Skript wird ersetzt",
        _im_js and _im_js == _ersetzt, f"js={sorted(_im_js)} init={sorted(_ersetzt)}")
r.check("Knöpfe: Init-Skript bricht Paperless nie ab (endet immer mit exit 0)",
        _init.rstrip().endswith("exit 0") and "exit 1" not in _init)

# ---- aktivitaet(): Liste, Filter, Seiten, Kennzahlen.
_z = ["2026-09-26 23:56:40 OCR-rescue 913: 340 Zeichen",
      "2026-09-26 23:56:46 OK 913 | exakt='Klein GmbH' id=13 | typ=21 | tags=[] | new=[] | OCR-rescue(340)",
      "kein Zeitstempel", "2026-09-27 00:22:29 FEHLER 5 | ValueError()",
      "2026-09-27 00:23:00 OK 7 | NEU='Neu AG' id=99 | typ=3 | tags=[] | new=[] | ",
      "2026-09-27 00:24:00 skip 8: schon klassifiziert"]
_e = kern.eintrag_lesen(_z[1])
r.check("Aktivität: Eintrag zerlegt (Art, Dokument, Korrespondent, Typ, OCR)",
        (_e["art"], _e["doc"], _e["korrespondent"], _e["typ"], _e["ocr"]) ==
        ("klassifiziert", 913, "Klein GmbH", "21", "OCR-rescue(340)"), str(_e))
r.check("Aktivität: neuer Korrespondent erkannt", kern.eintrag_lesen(_z[4])["korrespondent_neu"] is True)
r.check("Aktivität: Zeile ohne Zeitstempel fällt weg", kern.eintrag_lesen(_z[2]) is None)
_a = kern.aktivitaet(_z)
r.check("Aktivität: neueste zuerst", _a["eintraege"][0]["doc"] == 8 and _a["gesamt"] == 5)
r.check("Aktivität: Kennzahlen je Art", _a["kennzahlen"] ==
        {"klassifiziert": 2, "ocr": 1, "repariert": 0, "fehler": 1, "uebersprungen": 1}, str(_a["kennzahlen"]))
_f = kern.aktivitaet(_z, art="klassifiziert")
r.check("Aktivität: Filter nach Art", [e["doc"] for e in _f["eintraege"]] == [7, 913])
r.check("Aktivität: Kennzahlen zählen ungefiltert (Einstieg in den Filter)", _f["kennzahlen"] == _a["kennzahlen"])
r.check("Aktivität: Filter nach Tag und Dokument kombiniert",
        [e["art"] for e in kern.aktivitaet(_z, tag="2026-09-26", doc=913)["eintraege"]] == ["klassifiziert", "ocr"])
_s = kern.aktivitaet(_z, je=2, seite=9)
r.check("Aktivität: Seiten zu je N, zu große Seite wird auf die letzte gezogen",
        _s["seiten"] == 3 and _s["seite"] == 3 and len(_s["eintraege"]) == 1, str((_s["seiten"], _s["seite"])))

# ---- korr_eintrag(): Adressbuch-Eintrag aus dem Paperless-Dialog.
_alt = {"email": "a@example.com", "quelle": "import", "extern_id": "K-7", "kontext": "alt"}
_neu = kern.korr_eintrag(_alt, {"kontext": "  Werkstattzulieferer ", "email": "", "unbekannt": "x"})
r.check("Adressbuch: Werte getrimmt, leere Felder fallen weg", _neu.get("kontext") == "Werkstattzulieferer"
        and "email" not in _neu, str(_neu))
r.check("Adressbuch: Import-Herkunft bleibt erhalten", _neu.get("quelle") == "import" and _neu.get("extern_id") == "K-7")
r.check("Adressbuch: unbekannte Eingaben werden nicht übernommen", "unbekannt" not in _neu)
_ki = {"ustid": "ATU1", "iban": "AT11", "erfasst": {"ustid": "KI · Dok 5", "iban": "KI · Dok 5"}}
_hand = kern.korr_eintrag(_ki, {"ustid": "ATU1", "iban": "AT22"})
r.check("Adressbuch: von Hand geänderter Wert verliert den KI-Vermerk, unveränderter behält ihn",
        _hand["erfasst"] == {"ustid": "KI · Dok 5"} and _hand["iban"] == "AT22", str(_hand))
_leer = kern.korr_eintrag(_ki, {})
r.check("Adressbuch: alles geleert → kein verwaister Vermerk", "erfasst" not in _leer, str(_leer))
r.check("Adressbuch: IBAN ist ein Feld im Dialog", any(f == "iban" for f, _, _ in kern.KORR_FELDER))

r.check("Aktivität: Trockenlauf ist eine eigene Art, keine Info",
        kern.eintrag_lesen("2026-09-20 19:52:14 DRY DRY 918 | exakt='X' | typ=Rechnung |")["art"] == "trockenlauf")
r.check("Aktivität: unbekannte Zeile ist ein Hinweis",
        kern.eintrag_lesen("2026-09-20 19:52:14 nachbearbeitung 5: ok")["art"] == "hinweis")

sys.exit(r.done())
