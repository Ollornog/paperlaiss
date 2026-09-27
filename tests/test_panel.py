#!/usr/bin/env python3
"""Fachtest: die reine Logik des Panels (panel/kern.py).

`app.py` braucht FastAPI und ist damit in dieser stdlib-only-Suite nicht importierbar. Alles,
was eine Entscheidung trifft und ohne Netz auskommt, steht deshalb in `kern.py` — und wird hier
geprüft. Bis 2026-09-21 war am Panel nichts getestet.
"""
from __future__ import annotations

import os
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
_v = [t for t in kern.verlauf(_log) if not t.get("vor_beginn")]
r.check("verlauf: ein Eintrag je Tag", len(_v) == 2)
r.check("verlauf: zählt je Art", _v[0]["tag"] == "2026-09-01" and _v[0]["klassifiziert"] == 2
        and _v[0]["ocr"] == 1)
r.check("verlauf: Fehler getrennt gezählt", _v[1].get("fehler") == 1 and _v[1].get("klassifiziert") == 1)
r.check("verlauf: Zeilen ohne Datum werden übergangen", all("tag" in e for e in _v))
r.check("verlauf: leeres Log ergibt leere Liste", kern.verlauf([]) == [])
r.check("verlauf: schneidet auf die gewünschte Anzahl Tage",
        len(kern.verlauf(_log, tage=1)) == 1)

# Lücken gehören dazu — "seit drei Wochen läuft nichts" sieht man nur mit leeren Tagen.
_luecke = [t for t in kern.verlauf(["2026-09-01 10:00:00 OK 1 | x", "2026-09-05 10:00:00 OK 2 | x"])
           if not t.get("vor_beginn")]
r.check("verlauf: Lücken werden aufgefüllt", len(_luecke) == 5)
r.check("verlauf: leere Tage sind leer, nicht erfunden",
        _luecke[1] == {"tag": "2026-09-02"} and _luecke[0]["klassifiziert"] == 1)
r.check("verlauf: ab der ersten Logzeile ohne vor_beginn", _luecke[0]["tag"] == "2026-09-01")
# Volles Fenster auch bei frischer Installation (PO 2026-09-27: „nur ein Tag statt vieler“).
_frisch = kern.verlauf(["2026-09-27 04:51:34 OK 1 | x"], tage=60, heute="2026-09-27")
r.check("verlauf: frische Installation — trotzdem 60 Tage bis heute, davor vor_beginn",
        len(_frisch) == 60 and _frisch[0] == {"tag": "2026-07-30", "vor_beginn": True}
        and _frisch[-1] == {"tag": "2026-09-27", "klassifiziert": 1}
        and sum(1 for t in _frisch if t.get("vor_beginn")) == 59, str(_frisch[:2] + _frisch[-1:]))
_still = kern.verlauf(["2026-09-20 10:00:00 OK 1 | x"], tage=10, heute="2026-09-27")
r.check("verlauf: Fenster endet heute, auch wenn seitdem nichts lief (leere Tage, nicht vor_beginn)",
        _still[-1] == {"tag": "2026-09-27"} and _still[-8] == {"tag": "2026-09-20", "klassifiziert": 1}
        and _still[0] == {"tag": "2026-09-18", "vor_beginn": True}, str(_still))
r.check("verlauf: leeres Log mit heute — Fenster ganz vor_beginn",
        len(kern.verlauf([], tage=3, heute="2026-09-27")) == 3
        and all(t.get("vor_beginn") for t in kern.verlauf([], tage=3, heute="2026-09-27")))

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
r.check("Anmeldung: kein Einmal-Token für den TinySesam-Admin (sonst steht er im Container-Log)",
        _pw["tinysesam"].get("admin_claim_ttl_min") == 0)
r.check("Anmeldung: Seite trägt den Projektnamen", _pw["tinysesam"]["rp_name"] == "paperlaiss")
r.check("Anmeldung: Erst-Admin wird übergeben", _pw["admin"] == ("admin", "x"))
_oidc = _ae({"PANEL_AUTH": "tinysesam", "PANEL_BASE_URL": "https://panel.example.com/",
             "PANEL_OIDC_ISSUER": "https://id.example.com", "PANEL_OIDC_CLIENT_ID": "c",
             "PANEL_OIDC_CLIENT_SECRET": "s", "PANEL_OIDC_GROUPS": "buero, chef"})
r.check("Anmeldung: mit Gruppensperre wird der Scope groups angefordert",
        "groups" in _oidc["tinysesam"].get("oidc_scopes", "").split()
        and _oidc["tinysesam"]["oidc_allowed_groups"] == ["buero", "chef"], str(_oidc["tinysesam"].get("oidc_scopes")))
_tp = _ae({"PANEL_AUTH": "tinysesam", "PANEL_BASE_URL": "https://panel.example.com/",
           "PANEL_OIDC_ISSUER": "https://id.example.com", "PANEL_OIDC_CLIENT_ID": "c",
           "PANEL_OIDC_CLIENT_SECRET": "s", "PANEL_TRUSTED_PROXIES": "172.16.0.0/12, 192.0.2.7/32"})
r.check("Anmeldung: Proxys aus PANEL_TRUSTED_PROXIES gehen an TinySesam",
        not _tp["fehler"] and _tp["tinysesam"].get("trusted_proxies") == ["172.16.0.0/12", "192.0.2.7/32"], str(_tp))
r.check("Anmeldung: ohne PANEL_TRUSTED_PROXIES bleibt TinySesams Vorgabe",
        "trusted_proxies" not in _oidc["tinysesam"])
_tpx = _ae({"PANEL_AUTH": "tinysesam", "PANEL_BASE_URL": "https://panel.example.com/",
            "PANEL_PASSWORD_LOGIN": "1", "PANEL_TRUSTED_PROXIES": "caddy"})
r.check("Anmeldung: ein Proxy-Eintrag, der kein IP-Netz ist, hält den Start an",
        any("PANEL_TRUSTED_PROXIES" in f for f in _tpx["fehler"]), str(_tpx["fehler"]))
_df = (Path(__file__).resolve().parent.parent / "panel" / "Dockerfile").read_text(encoding="utf-8")
r.check("Dockerfile: uvicorn schreibt die Client-IP nicht selbst um (--no-proxy-headers)",
        "--no-proxy-headers" in _df.split("CMD", 1)[1])
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
        _hand["erfasst"] == {"ustid": "KI · Dok 5"} and _hand["iban"] == ["AT22"], str(_hand))
_leer = kern.korr_eintrag(_ki, {})
r.check("Adressbuch: alles geleert → kein verwaister Vermerk", "erfasst" not in _leer, str(_leer))
r.check("Adressbuch: IBAN ist ein Feld im Dialog", any(f == "iban" for f, _, _ in kern.KORR_FELDER))
# ---- Mehrere Werte je Feld („+“ im Dialog) und einheitliche Telefonnummern (2026-09-27)
_mw = kern.korr_eintrag({}, {"telefon": ["+49 (0) 30 123 45", "0049 30 12345", "+49 030 12345", "030 12345", " "],
                             "iban": ["de89 3704 0044 0532 0130 00"], "ustid": ["atu 123.456.78"],
                             "email": ["Info@Example.COM"], "domains": ["www.example.com"]})
r.check("Listenfelder: drei internationale Schreibweisen werden eine, die nationale bleibt national (kein geratenes Land)",
        _mw.get("telefon") == ["+493012345", "03012345"], str(_mw.get("telefon")))
r.check("Listenfelder: IBAN in Vierergruppen, USt-ID ohne Trenner, Mail/Domain klein",
        _mw.get("iban") == ["DE89 3704 0044 0532 0130 00"] and _mw.get("ustid") == ["ATU12345678"]
        and _mw.get("email") == ["info@example.com"] and _mw.get("domains") == ["example.com"], str(_mw))
r.check("Listenfelder: alter Einzelwert/Kommaliste wird für den Dialog zur Liste (auch uid → ustid)",
        kern.korr_anzeige({"email": "a@x.de, b@y.de", "uid": "ATU1"}) == {"email": ["a@x.de", "b@y.de"], "uid": "ATU1", "ustid": ["ATU1"]},
        str(kern.korr_anzeige({"email": "a@x.de, b@y.de", "uid": "ATU1"})))
r.check("Listenfelder: ein zweiter Wert zu einem KI-Wert ist eine Handänderung (Vermerk weg)",
        "erfasst" not in kern.korr_eintrag({"telefon": ["+4366212345"], "erfasst": {"telefon": "KI"}},
                                           {"telefon": ["+4366212345", "0662 99999"]}))
r.check("Listenfelder: unveränderte Liste behält den KI-Vermerk (auch in anderer Schreibweise)",
        kern.korr_eintrag({"telefon": ["+4366212345"], "erfasst": {"telefon": "KI"}},
                          {"telefon": ["0043 (0) 662 123 45"]}).get("erfasst") == {"telefon": "KI"})
# Herkunft je Wert (seit 2026-09-27): wer einen Wert von Hand löscht, nimmt nur dessen Vermerk mit.
_hj = kern.korr_eintrag({"telefon": ["+4366212345", "066299999"],
                         "erfasst": {"telefon": {"+4366212345": "KI · Dok 1", "066299999": "KI · Dok 2"}}},
                        {"telefon": ["+43 662 12345", "0664 5555555"]})
r.check("Listenfelder: Herkunft je Wert bleibt für die übrigen Werte, gelöschte und neue haben keine",
        _hj.get("erfasst") == {"telefon": {"+4366212345": "KI · Dok 1"}}, str(_hj))
r.check("Listenfelder: alle KI-Werte gelöscht → kein Vermerk",
        "erfasst" not in kern.korr_eintrag({"telefon": ["+4366212345"], "erfasst": {"telefon": {"+4366212345": "KI"}}},
                                           {"telefon": ["0664 5555555"]}))
# Beide Seiten vereinheitlichen gleich: Dialog (kern) und Suche/Erfassung (classify)
import importlib.util as _ilu
os.environ.setdefault("CLASSIFY_CONFIG", "/nicht/da.json")
_cs = _ilu.spec_from_file_location("classify_fuer_panel", Path(__file__).resolve().parent.parent / "classify.py")
_cl = _ilu.module_from_spec(_cs); _alt_argv = sys.argv; sys.argv = ["x"]; _cs.loader.exec_module(_cl); sys.argv = _alt_argv
_nummern = ["+49 (0) 30 123 45", "0049 30 12345", "030 12345", "+43 0662 12345", "Tel. 0662/12 34 5", "0043-662-12345",
            "12345", "", "+41 (0)44 123 45 67", "0170 1234567"]
r.check("Telefon: Dialog und Klassifizierer vereinheitlichen identisch",
        all(kern.norm_telefon(n) == _cl.norm_telefon(n) for n in _nummern))

# ---- Sperrdatei nur lesend öffnen (2026-09-27): das Panel läuft als root; legte es die Sperre mit "a"
# an (root, 0644), scheiterte danach jede Stammdaten-Erfassung des Klassifizierers (uid 1000).
import fcntl as _fcntl, tempfile as _tfs
with _tfs.TemporaryDirectory() as _sd:
    _sp = os.path.join(_sd, "correspondents.json.lock")
    _mit = []
    _oo = os.open
    os.open = lambda p, f, *a: (_mit.append(f), _oo(p, f, *a))[1]
    try:
        with kern.sperre_oeffnen(_sp) as _f:
            _fcntl.flock(_f, _fcntl.LOCK_EX)
    finally:
        os.open = _oo
    r.check("Sperre: angelegt für alle lesbar, geöffnet ohne Schreibrecht, flock klappt",
            bool(_mit) and not any(f & (os.O_WRONLY | os.O_RDWR | os.O_APPEND) for f in _mit)
            and (os.stat(_sp).st_mode & 0o044) == 0o044, f"{_mit} {oct(os.stat(_sp).st_mode)}")

# ---- PANEL_PFAD: das Panel unter einem Unterpfad derselben Domain (etwa /paperlaiss hinter Paperless).
r.check("Pfad: normalisiert, ungültige Werte zählen als leer",
        kern.panel_pfad({"PANEL_PFAD": "/paperlaiss/"}) == "/paperlaiss" and kern.panel_pfad({}) == ""
        and kern.panel_pfad({"PANEL_PFAD": '/x"><script>'}) == "" and kern.panel_pfad({"PANEL_PFAD": "paperlaiss"}) == "")
_sub = {**_basis, "PANEL_BASE_URL": "https://paper.example.com/paperlaiss", "PANEL_PASSWORD_LOGIN": "1",
        "PANEL_ADMIN_USER": "admin", "PANEL_ADMIN_PASSWORD": "x"}
r.check("Pfad: Basisadresse mit Pfad ohne passendes PANEL_PFAD startet nicht", _ae(_sub)["fehler"])
_ok_sub = _ae({**_sub, "PANEL_PFAD": "/paperlaiss"})
r.check("Pfad: passend konfiguriert startet, Logo der Anmeldeseite trägt den Pfad",
        not _ok_sub["fehler"] and _ok_sub["tinysesam"]["brand_icon"] == "/paperlaiss/logo.png", str(_ok_sub["fehler"]))
import importlib, os as _os
_os.environ["PANEL_PFAD"] = "/pl"
try:
    import huelle
    importlib.reload(huelle)
    _html = huelle.seite("T", "/", "<p>x</p>", abmelden=True)
finally:
    _os.environ.pop("PANEL_PFAD")
    importlib.reload(huelle)
_roh = _re.findall(r'(?:href|src)="(/[^"]*)"', _html)
r.check("Pfad: jede Adresse der Seite trägt den Präfix (Navigation, Stile, Logo, Abmelden)",
        _roh and all(x == "/pl" or x.startswith("/pl/") for x in _roh), str([x for x in _roh if not x.startswith("/pl")]))
r.check("Pfad: das JavaScript bekommt den Präfix für seine Abrufe", 'const PL_BASIS="/pl"' in _html)

r.check("Aktivität: Trockenlauf ist eine eigene Art, keine Info",
        kern.eintrag_lesen("2026-09-20 19:52:14 DRY DRY 918 | exakt='X' | typ=Rechnung |")["art"] == "trockenlauf")
r.check("Aktivität: unbekannte Zeile ist ein Hinweis",
        kern.eintrag_lesen("2026-09-20 19:52:14 nachbearbeitung 5: ok")["art"] == "hinweis")

# ---- KI-Knopf: kein Doppelstart, Fortschritt je Schritt
_j = {5: {"status": "laeuft"}, 6: {"status": "wartet"}, 7: {"status": "fertig"}, 8: {"status": "fehler"}}
r.check("Knopf: wartende/laufende Dokumente werden nicht noch einmal gestartet, fertige und neue schon",
        kern.knopf_annehmen(_j, [5, 6, 7, 8, 9]) == ([7, 8, 9], [5, 6]))
r.check("Knopf: Fortschritt steigt mit den Schritten",
        kern.knopf_fortschritt("wartet")["prozent"] < kern.knopf_fortschritt("laeuft", "Kandidaten")["prozent"]
        < kern.knopf_fortschritt("laeuft", "Pass 1")["prozent"] < kern.knopf_fortschritt("laeuft", "Tags & Schreiben")["prozent"]
        < kern.knopf_fortschritt("fertig")["prozent"] == 100)
r.check("Knopf: nummerierte Schritte (Feld-Korrektur 2) werden erkannt",
        kern.knopf_fortschritt("laeuft", "Feld-Korrektur 2")["schritt"] == "Felder korrigieren")
# Wächter: jeder Schritt, den classify.py meldet, ist der Anzeige bekannt — sonst stünde nach einer
# Umbenennung still „startet" da.
import ast as _ast2
_cl = _ast2.parse((ROOT / "classify.py").read_text(encoding="utf-8"))
_stufen = []
for _n in _ast2.walk(_cl):
    if isinstance(_n, _ast2.Call) and getattr(_n.func, "id", None) == "set_stage" and len(_n.args) == 2:
        _a = _n.args[1]
        if isinstance(_a, _ast2.Constant):
            _stufen.append(_a.value)
        elif isinstance(_a, _ast2.JoinedStr) and _a.values and isinstance(_a.values[0], _ast2.Constant):
            _stufen.append(_a.values[0].value.strip())
_unbekannt = [x for x in _stufen if not any(x.startswith(n) for n, _, _ in kern.KNOPF_SCHRITTE)]
r.check(f"Knopf: jeder Schritt aus classify.py ist der Anzeige bekannt ({len(_stufen)} gefunden)",
        len(_stufen) >= 6 and not _unbekannt, str(_unbekannt))

_app = _ast2.parse((ROOT / "panel" / "app.py").read_text(encoding="utf-8"))
_knopf = next((f for f in _ast2.walk(_app) if isinstance(f, _ast2.AsyncFunctionDef) and f.name == "knopf"), None)
r.check("Knopf-Endpunkt: nimmt Dokumente nur über die Sperre an (knopf_annehmen unter _JOBS_LOCK)",
        _knopf is not None and any(isinstance(w, _ast2.With) and "_JOBS_LOCK" in _ast2.unparse(w.items[0].context_expr)
                                   and "knopf_annehmen" in _ast2.unparse(w) for w in _ast2.walk(_knopf)))

sys.exit(r.done())
