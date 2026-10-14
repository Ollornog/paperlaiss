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

# ---- ocr_gruende(): das Regel-Gate VOR Pass 1, einstellbar über "ocr_regeln".
_cfg = {"ocr_min_len": 300}
r.check("OCR-Regel: brauchbarer Text → keine Gründe", classify.ocr_gruende(_gut, _cfg) == [])
r.check("OCR-Regel: zu kurz nennt die Länge", classify.ocr_gruende("Rechnung", _cfg)[0].startswith("zu kurz"))
_salat = ("Rechnung Datum Betrag " + "§$~^{}\\|~^°¬¦ ~^{}~^ " * 40)
r.check("OCR-Regel: Zeichensalat erkannt",
        any("Zeichensalat" in g for g in classify.ocr_gruende(_salat, _cfg)), str(classify.ocr_gruende(_salat, _cfg)))
r.check("OCR-Regel: fremdsprachiger, sauberer Text ohne Schlüsselwörter → Grund Schlüsselwörter",
        any("bekannte" in g for g in classify.ocr_gruende("Lorem ipsum dolor sit amet consectetur " * 12, _cfg)))
r.check("OCR-Regel: Schwelle aus der Config", classify.ocr_gruende(
    "Rechnung Datum Betrag " * 3, {"ocr_min_len": 300, "ocr_regeln": {"min_zeichen": 10}}) == [])
r.check("OCR-Regel: eigene Schlüsselwörter", classify.ocr_gruende(
    "Lorem ipsum dolor sit amet consectetur " * 12,
    {"ocr_min_len": 300, "ocr_regeln": {"schluesselwoerter": ["lorem", "dolor"]}}) == [])
r.check("OCR-Regel: Schlüsselwörter als ganze Wörter (' der ' trifft nicht in 'oder')",
        classify.ocr_regeln({})["schluesselwoerter"][0] == " der ")
r.check("OCR-Regel: altes ocr_min_len gilt weiter, wenn min_zeichen fehlt",
        classify.ocr_regeln({"ocr_min_len": 123})["min_zeichen"] == 123)

# ---- ocr_nachhol_gruende(): das Gate NACH Pass 1 — KI-Meldung und optionale Regeln.
r.check("OCR-Nachlauf: KI meldet Müll", classify.ocr_nachhol_gruende({"needs_ocr": True}, {}) == ["KI meldet unlesbaren Text"])
r.check("OCR-Nachlauf: KI-Meldung abschaltbar",
        classify.ocr_nachhol_gruende({"needs_ocr": True}, {"ocr_regeln": {"nach_ki_meldung": False}}) == [])
r.check("OCR-Nachlauf: kein Typ zählt nur, wenn eingeschaltet",
        classify.ocr_nachhol_gruende({"document_type": None}, {}) == []
        and classify.ocr_nachhol_gruende({"document_type": None}, {"ocr_regeln": {"wenn_kein_typ": True}}) == ["kein Dokumenttyp erkannt"])
r.check("OCR-Nachlauf: kein Korrespondent, wenn eingeschaltet",
        classify.ocr_nachhol_gruende({"correspondent": ""}, {"ocr_regeln": {"wenn_kein_korrespondent": True}}) == ["kein Korrespondent erkannt"])
r.check("OCR-Nachlauf: alles erkannt → nichts", classify.ocr_nachhol_gruende(
    {"document_type": "Rechnung", "correspondent": "X", "needs_ocr": False},
    {"ocr_regeln": {"wenn_kein_typ": True, "wenn_kein_korrespondent": True}}) == [])

# ---- typ_setzen(): vorbelegten Typ überschreiben dürfen alle Läufe außer dem Bestands-Durchlauf.
r.check("Typ: leer → gesetzt", classify.typ_setzen(3, None, False) == 3)
r.check("Typ: Bestands-Durchlauf lässt vorhandenen stehen", classify.typ_setzen(3, 5, False) is None)
r.check("Typ: sonst (Import, Knopf, Panel) überschreiben", classify.typ_setzen(3, 5, True) == 3)
r.check("Typ: gleich oder nichts erkannt → nichts schreiben",
        classify.typ_setzen(5, 5, True) is None and classify.typ_setzen(None, 5, True) is None)

# ---- Verdrahtung: main() fuehrt den OCR-Nachlauf WIRKLICH aus. Der alte Zweig war unerreichbar
# und fiel in keinem Test auf, weil nur die Hilfsfunktionen geprueft wurden. Hier laeuft main()
# gegen gefaelschte Paperless- und Mistral-Aufrufe (Trockenlauf, nichts wird geschrieben).
import contextlib as _ctx, io as _io


def _lauf(chat_antworten, force_ocr=False, text=_gut, korrespondenten=(), felder=(), feldwerte=(), typ=None,
          dry=True, source="", force=False, korr=None, titel="Beleg", typen=None, besitzer=None, cfg=None,
          datei=None, hinzu=None, patch_ergebnis=None, tags=(), alle_tags=()):
    aufrufe = {"ocr": 0, "chat": []}
    routen = {"/documents/5/": {"id": 5, "content": text, "title": titel, "tags": list(tags),
                                "custom_fields": list(feldwerte), "created": "2026-01-01", "document_type": typ,
                                "correspondent": korr, "owner": 3 if besitzer else None,
                                "original_file_name": datei, "added": hinzu},
              "/users/3/": besitzer or {},
              "/tags/": {"results": list(alle_tags)}, "/document_types/": {"results": list(typen or [{"id": 1, "name": "Rechnung"}, {"id": 2, "name": "Mahnung"}])},
              "/correspondents/": {"results": list(korrespondenten)}, "/custom_fields/": {"results": list(felder)}}

    def get(pfad, raw=False):
        return next(v for k, v in routen.items() if pfad.startswith(k))

    def ocr(did):
        aufrufe["ocr"] += 1
        return "Neu gelesener Text " * 10
    antworten = list(chat_antworten)

    def chat(messages, max_tokens=900, schema=None, name=""):
        aufrufe.setdefault("schemas", []).append(schema)
        aufrufe["chat"].append(messages[-1]["content"])
        aufrufe.setdefault("laengen", []).append(len(messages))
        aufrufe.setdefault("system", messages[0]["content"])
        return dict(antworten.pop(0)), "{}"
    # Echter (nicht trockener) Lauf: Schreibzugriffe abfangen — send legt Korrespondenten an,
    # patch_doc schreibt das Dokument, Stammdaten landen im Skriptordner (→ temporär).
    def send(pfad, daten, methode="POST"):
        aufrufe.setdefault("send", []).append((pfad, daten))
        return {"id": 99, **(daten or {})}

    def patch_doc(did, patch, pause=None):
        aufrufe.setdefault("patch", []).append(dict(patch))
        return patch_ergebnis or (True, "")
    tmp = tempfile.mkdtemp()
    alt = {n: getattr(classify, n) for n in ("get", "mistral_ocr", "mistral_chat", "TOK", "DRY", "FORCE_OCR",
                                            "send", "patch_doc", "SCRIPT_DIR", "SOURCE", "FORCE", "CFG")}
    if cfg:
        classify.CFG = {**classify.CFG, **cfg}
    classify.get, classify.mistral_ocr, classify.mistral_chat = get, ocr, chat
    classify.TOK, classify.DRY, classify.FORCE_OCR = "x", dry, force_ocr
    classify.send, classify.patch_doc, classify.SCRIPT_DIR = send, patch_doc, tmp
    classify.SOURCE, classify.FORCE = source, force
    os.environ["CLASSIFY_DOC"] = "5"
    try:
        with _ctx.redirect_stdout(_io.StringIO()):
            classify.main()
    finally:
        for n, v in alt.items():
            setattr(classify, n, v)
        os.environ.pop("CLASSIFY_DOC", None)
    aufrufe["get"] = get
    return aufrufe


_ok = {"document_type": "Rechnung", "correspondent": "X", "fields": {}, "needs_ocr": False}
_a = _lauf([{**_ok, "needs_ocr": True}, _ok])
r.check("Verdrahtung: KI meldet Müll → genau ein OCR-Nachlauf", _a["ocr"] == 1, str(_a["ocr"]))
r.check("Verdrahtung: danach Pass 1 erneut mit dem OCR-Text",
        len(_a["chat"]) == 2 and "per OCR neu gelesene" in _a["chat"][1], str(len(_a["chat"])))
_b = _lauf([_ok])
r.check("Verdrahtung: alles lesbar → kein OCR", _b["ocr"] == 0 and len(_b["chat"]) == 1)
_c = _lauf([{**_ok, "needs_ocr": True}], force_ocr=True)
r.check("Verdrahtung: OCR lief schon vor Pass 1 → kein zweites Mal", _c["ocr"] == 1 and len(_c["chat"]) == 1,
        f"ocr={_c['ocr']} chat={len(_c['chat'])}")

# Pass 2 hängt an die Pass-1-Unterhaltung an: die KI sieht das Dokument, nicht nur den Namen.
_e = _lauf([{**_ok, "correspondent": "Mustr Autoteile"}, {"match": "Muster Autoteile GmbH"}],
           korrespondenten=[{"id": 7, "name": "Muster Autoteile GmbH"}, {"id": 8, "name": "Anderes Haus"}])
r.check("Pass 2: Schema lässt nur die Kandidaten zu",
        (_e.get("schemas") or [None, None])[1] and "Muster Autoteile GmbH" in _e["schemas"][1]["properties"]["match"]["enum"])
r.check("Pass 2: zweiter Aufruf in derselben Unterhaltung (Dokument + Analyse + Frage)",
        len(_e["chat"]) == 2 and _e["laengen"] == [2, 4] and "Muster Autoteile GmbH" in _e["chat"][1],
        f"{len(_e['chat'])} Aufrufe, Längen {_e.get('laengen')}")

# Die Vorschau im Panel muss GENAU den Prompt zeigen, den die KI bekommt — nicht einen Nachbau.
_alt_get = classify.get
classify.get = _b["get"]
try:
    _vorschau = classify.prompt_vorschau()
finally:
    classify.get = _alt_get
r.check("Prompt-Vorschau = tatsächlich gesendeter System-Prompt", _vorschau["system"] == _b["system"])
r.check("Prompt-Vorschau: Typen eingesetzt, keine Platzhalter übrig",
        "Rechnung" in _vorschau["system"] and "{TYPES}" not in _vorschau["system"])

r.check("Prompt-Vorschau: Stücke ergeben genau den System-Prompt",
        "".join(t for t, _ in _vorschau["system_teile"]) == _vorschau["system"])
r.check("Prompt-Vorschau: eingesetzte Typen als Platzhalter markiert",
        any(v == "TYPES" and "Rechnung" in t for t, v in _vorschau["system_teile"]))
r.check("Prompt-Vorschau: Nachricht zeigt Beispielwerte markiert und Bedingungen",
        any(v and "‹Titel›" in t for t, v, _ in _vorschau["nachricht_teile"])
        and any(w and "MÖGLICHE KORRESPONDENTEN" in t for t, _, w in _vorschau["nachricht_teile"]))
classify.get = _b["get"]
os.environ["CLASSIFY_PROMPT_ENTWURF"] = "Nur {TYPES} und sonst nichts"
try:
    _entwurf = classify.prompt_vorschau()
finally:
    classify.get = _alt_get
    os.environ.pop("CLASSIFY_PROMPT_ENTWURF")
r.check("Prompt-Vorschau: Entwurf aus dem Editor wird eingesetzt, ohne zu speichern",
        _entwurf["system"].startswith("Nur ") and "Rechnung" in _entwurf["system"]
        and not classify.CFG.get("system_prompt", "").startswith("Nur "))

# Die Nachricht an Pass 1 entsteht aus Stücken — zusammengesetzt muss sie Zeichen für Zeichen
# der bisherigen Nachricht entsprechen (Vergleich gegen die alte Formel, mit und ohne Zusatzblöcke).
def _alte_nachricht(hinweis, cname, chint, kand_lines, mail_ktx, added, created, fname, fieldspec, title, content):
    _NL = "\n"
    hint_block = (f"WICHTIGER NUTZER-HINWEIS (was zuletzt falsch war — bitte korrigieren):\n{hinweis}\n\n" if hinweis else "")
    corr_hint_block = (f"BISHER ZUGEORDNETER KORRESPONDENT (kann falsch sein — nur behalten, wenn das Dokument von ihm stammt): "
                       f"'{cname}' — {chint}\n\n" if chint else "")
    kand_block = (("MÖGLICHE KORRESPONDENTEN (bekannte Korrespondenten, die passen könnten — stammt das Dokument von einem davon, übernimm seinen Namen exakt im Feld correspondent; dass sein Name im Text steht, reicht nicht; sonst nenne den tatsächlichen Absender):" + _NL + kand_lines + _NL + _NL) if kand_lines else "")
    mail_block = ("HERKUNFT-KONTEXT (Nachricht/Anschreiben zu diesem Dokument — für Absender und Einordnung nutzen):" + _NL + mail_ktx + _NL + _NL) if mail_ktx else ""
    meta = (f"METADATEN:\n- Hinzugefügt am: {added}\n- Von Paperless beim Import geratenes Datum (das erste Datum im Text, oft ein Geburtsdatum — kein Beleg, document_date selbst im Dokument bestimmen): {created}\n"
            f"- Originaldateiname: {fname}\n")
    return (f"{hint_block}{corr_hint_block}{kand_block}{mail_block}{meta}\n"
            f"VERFÜGBARE FELDER (im fields-Objekt je Feld: Wert / null=leeren / \"BEHALTEN\"=unsicher):\n{fieldspec}\n\n"
            f"TITEL: {title}\n\nINHALT:\n{content}")
for _args in [("Bitte Typ Mahnung", "Firma A", "zahlt immer spät", "- Firma A\n- Firma B", "Hallo, anbei",
               "2026-01-02", "2026-01-01", "a.pdf", "- Betrag (Zahl), aktuell: —", "Titel", "Inhalt"),
              ("", None, "", "", "", "2026-01-02", "", "—", "", "", "Inhalt")]:
    r.check("Pass-1-Nachricht aus Stücken = bisherige Nachricht" + (" (mit allen Blöcken)" if _args[0] else " (ohne Zusatzblöcke)"),
            "".join(t for t, _, _ in classify.pass1_nachricht_teile(*_args)) == _alte_nachricht(*_args))
r.check("Kandidatenliste ist ein Angebot, keine Pflicht (kein „GENAU einen dieser Namen“)",
        "GENAU einen" not in classify.KAND_KOPF and "tatsächlichen Absender" in classify.KAND_KOPF)
r.check("Verdrahtung: der Lauf schickt die aus Stücken gebaute Nachricht",
        _b["chat"][0].startswith("METADATEN:") and "VERFÜGBARE FELDER" in _b["chat"][0] and "\nINHALT:\n" in _b["chat"][0])

# ---- Stammdaten: Mail-Zuordnung, Suche im Text, Nachtragen (PO 2026-09-27) ----------------
_eig = classify.eigene_kennungen({"eigene_kennungen": {"ustid": ["ATU 1111 2222"], "iban": ["AT61 1904 3002 3457 3201"],
                                                        "domains": ["eigenfirma.example"], "email": ["chef.firma@gmail.com"],
                                                        "namen": ["Eigenfirma"]}})
_ks = [{"id": 1, "name": "Beispiel Software"}, {"id": 2, "name": "Nord Autoteile"}, {"id": 3, "name": "Privat Maier"},
       {"id": 4, "name": "Zweitfirma"}]
_km = {1: {"domains": "software.example", "ustid": "ATU99988777", "kundennummer": "424242"},
       2: {"email": "office@nord.example", "iban": "AT48 3200 0000 1234 5864"},
       3: {"email": "maier@gmail.com"}, 4: {"domains": "zweit.example, software.example"}}
_meta = lambda cid: _km.get(cid, {})
_z = lambda m, ks=_ks[:3]: classify.mail_zuordnung(ks, _meta, m, _eig)
r.check("Mail: volle Adresse ordnet zu", (_z("Office@Nord.example")[0] or {}).get("id") == 2)
r.check("Mail: Domain ordnet zu, auch als Subdomain", (_z("rechnung@mail.software.example")[0] or {}).get("id") == 1)
r.check("Mail: Freemail nur über die volle Adresse",
        (_z("maier@gmail.com")[0] or {}).get("id") == 3 and _z("jemand@gmail.com")[0] is None)
r.check("Mail: eigene Domain ist eine Weiterleitung und ordnet nichts zu",
        _z("chef@eigenfirma.example")[0] is None and "Weiterleitung" in _z("chef@eigenfirma.example")[1])
r.check("Mail: eigene Freemail-Adresse ist eine Weiterleitung, andere gmail-Adressen nicht gesperrt",
        # auch dann, wenn die eigene Adresse versehentlich bei einem Korrespondenten steht
        classify.mail_zuordnung([{"id": 5, "name": "Falsch"}], lambda c: {"email": "chef.firma@gmail.com"},
                                "Chef.Firma@gmail.com", _eig)[0] is None
        and (_z("maier@gmail.com")[0] or {}).get("id") == 3)
r.check("Nachtragen: eigene Freemail-Adresse wird nie erfasst",
        not classify.stammdaten_nachtragen({}, {"email": "chef.firma@gmail.com"}, "", _eig, "q")[1])
r.check("Mail: passt zu mehreren → entscheidet nicht", _z("x@software.example", _ks)[0] is None)

_txt = ("Rechnung an Eigenfirma, UID ATU 1111 2222.\nAbsender Beispiel, UID: ATU 999 88777, Ihre Kundennummer 424242, "
        "Mail info@notnord.example, IBAN AT48 3200 0000 1234 5864")
_tr = {c["id"]: g for c, g in classify.stammdaten_treffer(_ks[:3], _meta, _txt, _eig)}
r.check("Treffer: USt-ID trotz Leerzeichen im Text gefunden", any("ATU99988777" in g for g in _tr.get(1, [])), str(_tr))
r.check("Treffer: Kundennummer als ganzes Wort", any("424242" in g for g in _tr.get(1, [])))
r.check("Treffer: IBAN trotz Gruppierung", "IBAN" in _tr.get(2, []))
r.check("Treffer: Domain nur als ganze Domain (notnord ≠ klein), Namen zählen nicht",
        not any("Mail" in g for g in _tr.get(2, [])) and 3 not in _tr)
_dm = lambda c: {"domains": "nord.example"}
r.check("Treffer: Domain nur als ganze Domain hinter @/www.",
        not classify.stammdaten_treffer([{"id": 2, "name": "K"}], _dm, "info@notnord.example", _eig)
        and classify.stammdaten_treffer([{"id": 2, "name": "K"}], _dm, "Mail: info@nord.example", _eig))
r.check("Treffer: eigene USt-ID im Empfängerblock zählt nie",
        not classify.stammdaten_treffer([{"id": 9, "name": "Ich"}], lambda c: {"ustid": "ATU11112222"}, _txt, _eig))

_nk = [{"id": 1, "name": "Nord Autoteile GmbH"}, {"id": 2, "name": "Autohaus Groß"}, {"id": 3, "name": "ACME AG"}]
_na = lambda c: {3: "Acme Versicherung"}.get(c["id"], "")
_nt = [c["id"] for c, _ in classify.namens_treffer(_nk, _na, "Rechnung der nord autoteile, Mühlweg 5; ACME Versicherung AG")]
r.check("Namen: ein kurzes Einzelwort („Bank“) ist kein Kandidat, ein langes schon",
        not classify.namens_treffer([{"id": 5, "name": "Bank"}], lambda c: "", "Überweisung an die Bank")
        and classify.namens_treffer([{"id": 6, "name": "Stahlgruber"}], lambda c: "", "Lieferung Stahlgruber"))
r.check("Namen: eigene Firma ist bei der Namenssuche kein Kandidat",
        not classify.namens_treffer([{"id": 9, "name": "Eigenfirma e.U."}], lambda c: "", "an Eigenfirma, Musterstadt", _eig["namen"])
        and classify.namens_treffer([{"id": 9, "name": "Eigenfirma e.U."}], lambda c: "", "an Eigenfirma, Musterstadt"))
_ew = classify.eigene_firma_anweisung({"eigene_kennungen": {"namen": ["Eigenfirma"], "ustid": ["ATU1"]}})
r.check("Prompt: nennt die eigene Firma samt Kennungen und verlangt das Gegenüber",
        "Eigenfirma (USt-ID ATU1)" in _ew and "GEGENÜBER" in _ew)
r.check("Prompt: interne Dokumente dürfen zur eigenen Firma, eine Bank nur als Ausstellerin",
        "NUR bei internen Dokumenten" in _ew and "unter dem Namen Eigenfirma" in _ew
        and "nicht weil ihre Bankverbindung" in _ew and "NIE die eigene Firma" not in _ew)
r.check("Prompt: ohne eigene Firmennamen kein Zusatz", classify.eigene_firma_anweisung({}) == ""
        and not any("Wir und das Gegenüber" in (v or "") for _, v in classify.pass1_system_teile({}, {"A": 1}, [], set(), False)))
r.check("Prompt: der Zusatz steht im gesendeten System-Prompt",
        any(v and v.startswith("Wir und das Gegenüber") for _, v in classify.pass1_system_teile(
            {"eigene_kennungen": {"namen": ["Eigenfirma"]}}, {"A": 1}, [], set(), False)))
# Eigene Regel (Haushalt statt Firma): ersetzt nur den Satz nach „das sind WIR.“ — Kopf mit Namen und
# Kennungen und der Schluss „absender enthält NIE …“ bleiben, sonst landete die eigene IBAN beim Absender.
_hr = classify.eigene_firma_anweisung({"eigene_kennungen": {"namen": ["Erika Muster", "Max Muster"], "iban": ["DE00 1"]},
                                        "eigene_regel": "Bei Lebenslauf die Person selbst; erster: {ERSTER}."})
r.check("Eigene Regel: ersetzt die Firmenregel, Kopf und Schluss bleiben, {ERSTER} eingesetzt",
        "Erika Muster / Max Muster (IBAN DE00 1) — das sind WIR. Bei Lebenslauf die Person selbst; erster: Erika Muster."
        in _hr and _hr.endswith("absender enthält NIE unsere eigenen Stammdaten.")
        and "Ausgangsrechnung" not in _hr and "Kunden" not in _hr, _hr)
r.check("Eigene Regel: leer oder nur Leerzeichen = eingebaute Firmenregel",
        classify.eigene_firma_anweisung({"eigene_kennungen": {"namen": ["Eigenfirma"]}, "eigene_regel": "  "})
        == classify.eigene_firma_anweisung({"eigene_kennungen": {"namen": ["Eigenfirma"]}})
        and "Ausgangsrechnung" in classify.eigene_firma_anweisung({"eigene_kennungen": {"namen": ["Eigenfirma"]}}))
r.check("Eigene Regel: ohne eigene Namen kein Zusatz, auch mit Regel",
        classify.eigene_firma_anweisung({"eigene_regel": "irgendwas"}) == "")
r.check("Eigene Regel: das Panel nennt die Quelle des Blocks",
        any(v and "Regel zum Gegenüber" in v for _, v in classify.pass1_system_teile(
            {"eigene_kennungen": {"namen": ["X"]}, "eigene_regel": "R."}, {"A": 1}, [], set(), False)))
r.check("Eigene Regel: ist ein bekannter Config-Schlüssel (sonst zeigt das Panel ihn nicht)",
        "eigene_regel" in classify.CFG and classify.CFG["eigene_regel"] == "")
r.check("Namen: Zeilen mit Bankdaten zählen nicht, auch wenn sie im Briefkopf stehen",
        not classify.namens_treffer([{"id": 6, "name": "Raiffeisenbank"}], lambda c: "",
                                    "Eigenfirma - Testweg 1\nRechnung\nBank Raiffeisenbank IBAN AT00")
        and classify.namens_treffer([{"id": 6, "name": "Raiffeisenbank"}], lambda c: "",
                                    "Raiffeisenbank Musterstadt\nKontoauszug Nr. 3"))
r.check("Namen: Zeilen mit Dateinamen zählen nicht (Druckkopf „… - Google Docs.pdf“)",
        not classify.namens_treffer([{"id": 6, "name": "Google"}], lambda c: "",
                                    "Zeugenerklärung\n• Phillip Zeugenaussage - Google Docs.pdf\nName: Erika Muster")
        and classify.namens_treffer([{"id": 6, "name": "Google"}], lambda c: "",
                                    "Google Ireland Limited\nGordon House, Dublin\nRechnung"))
r.check("Namen: nur im Briefkopf — die Bank in der Fußzeile ist kein Kandidat",
        not classify.namens_treffer([{"id": 6, "name": "Raiffeisenbank"}], lambda c: "", "Rechnung " + "x " * 600 + "Bank: Raiffeisenbank"))
r.check("Namen: alle Wörter ohne Rechtsform, auch über Aliase; halber Name trifft nicht",
        _nt == [1, 3] or _nt == [3, 1], str(_nt))

_q = "KI · 2026-09-27 · Dokument 5"
_n, _g, _v = classify.stammdaten_nachtragen(
    {"kontext": "Software", "telefon": "+43 1 234"},
    {"ustid": "ATU 999 88777", "iban": "at48 3200 0000 1234 5864", "email": "null", "telefon": "+43 660 000000",
     "adresse": "Musterweg 1, 1010 Wien", "kundennummer": "424242"}, "Rechnung <buchhaltung@software.example>", _eig, _q)
r.check("Nachtragen: leere Felder gefüllt, IBAN in Vierergruppen",
        _g.get("ustid") == "ATU99988777" and _g.get("iban") == "AT48 3200 0000 1234 5864"
        and _g.get("email") == "buchhaltung@software.example" and _g.get("domains") == "software.example", str(_g))
r.check("Nachtragen: gefülltes Feld wird nie überschrieben", _n["telefon"] == "+43 1 234" and "telefon" not in _g)
r.check("Nachtragen: Herkunft vermerkt — bei Listenfeldern je Wert", _n["erfasst"].get("ustid") == {"ATU99988777": _q}
        and _n["erfasst"].get("adresse") == _q and "telefon" not in _n["erfasst"], str(_n["erfasst"]))
r.check("Nachtragen: ohne sichere Zuordnung wird nichts angehängt (nur leere Felder)",
        _v.get("telefon", "").startswith("nicht angehängt"), str(_v))

# ---- Anhängen an Listenfelder (PO 2026-09-27: „man kann doch hinzufügen?“)
_alt_e = {"telefon": "+43 1 234567", "iban": ["AT61 1904 3002 3457 3201"], "ustid": ["ATU11122233"], "adresse": "Alt 1",
          "kundennummer": ["K-1"], "erfasst": {"telefon": "KI · alt"}}
_fr = lambda feld, w: "Andere Firma" if feld == "iban" and classify.norm_iban(w) == "DE89370400440532013000" else None
_n2, _g2, _v2 = classify.stammdaten_nachtragen(
    _alt_e, {"telefon": "0662 99 88 77", "iban": "AT48 3200 0000 1234 5864", "ustid": "ATU99988777",
             "adresse": "Neu 2", "kundennummer": "K 1"}, "", _eig, _q, anhaengen=True, fremd=_fr)
r.check("Anhängen: neue Telefonnummer und IBAN kommen dazu, die alten bleiben",
        _n2["telefon"] == ["+43 1 234567", "0662998877"] and _n2["iban"] == ["AT61 1904 3002 3457 3201", "AT48 3200 0000 1234 5864"], str(_n2))
r.check("Anhängen: Herkunft je Wert, der alte Vermerk (Text) gilt weiter für den alten Wert",
        _n2["erfasst"]["telefon"] == {"+43 1 234567": "KI · alt", "0662998877": _q} and _n2["erfasst"]["iban"] == {"AT48 3200 0000 1234 5864": _q},
        str(_n2["erfasst"]))
r.check("Anhängen: gleicher Wert in anderer Schreibweise („K 1“ = „K-1“) kommt nicht doppelt", _n2["kundennummer"] == ["K-1"], str(_n2))
r.check("Anhängen: USt-ID und Adresse nie — eine zweite USt-ID wird als Warnung verworfen",
        _n2["ustid"] == ["ATU11122233"] and _n2["adresse"] == "Alt 1" and "USt-ID" in _v2.get("ustid", ""), str(_v2))
_n3, _g3b, _v3b = classify.stammdaten_nachtragen({}, {"iban": "DE89 3704 0044 0532 0130 00"}, "", _eig, _q, anhaengen=True, fremd=_fr)
r.check("Nie: ein Wert, der schon einem anderen Korrespondenten gehört — auch nicht in ein leeres Feld",
        "iban" not in _n3 and _v3b.get("iban") == "gehört schon zu Andere Firma", str(_v3b))
_voll = {"telefon": [f"+43 1 {i:06d}" for i in range(classify.MAX_WERTE)]}
r.check("Anhängen: höchstens MAX_WERTE Werte je Feld",
        "telefon" not in classify.stammdaten_nachtragen(_voll, {"telefon": "+43 699 111222"}, "", _eig, _q, anhaengen=True)[1])
r.check("fremd: findet den anderen Korrespondenten über jede Schreibweise, nie sich selbst",
        classify.stammdaten_fremd([{"id": 1, "name": "A"}, {"id": 2, "name": "B"}],
                                  lambda i: {"telefon": ["+43 662 123456"]} if i == 2 else {}, 1)("telefon", "0662 12 34 56") == "B"
        and classify.stammdaten_fremd([{"id": 2, "name": "B"}], lambda i: {"telefon": ["+43 662 123456"]}, 2)("telefon", "0662123456") is None)
_n2, _g2, _v2 = classify.stammdaten_nachtragen(
    {"uid": "ATU11111111"}, {"ustid": "ATU11112222", "iban": "AT61 1904 3002 3457 3201"}, "", _eig, _q)
r.check("Nachtragen: eigene IBAN verworfen, Alt-Schlüssel uid zählt als gefüllt",
        not _g2 and _v2.get("iban") == "eigene IBAN" and "ustid" not in _n2)
_n4, _g4, _v4 = classify.stammdaten_nachtragen({}, {"ustid": "ATU 1111 2222"}, "", _eig, _q)
r.check("Nachtragen: eigene USt-ID wird nie einem Absender zugeschlagen",
        not _g4 and _v4.get("ustid") == "eigene USt-ID", f"{_g4} {_v4}")
_n3, _g3, _v3 = classify.stammdaten_nachtragen({}, {"ustid": "12345", "iban": "DE00", "email": "x@gmail.com"},
                                               "chef@eigenfirma.example", _eig, _q)
r.check("Nachtragen: kaputte Formate verworfen, Freemail ohne Domain, eigene Mail-Domain nie",
        _v3.get("ustid") == "kein USt-ID-Format" and _v3.get("iban") == "kein IBAN-Format"
        and _g3 == {"email": "x@gmail.com"} and "eigene Adresse" in _v3.get("email", ""), f"{_g3} {_v3}")

import json, tempfile as _tf
with _tf.TemporaryDirectory() as _d:
    _alt_dir, _alt_meta = classify.SCRIPT_DIR, dict(classify.CORR_META)
    classify.SCRIPT_DIR = _d
    try:
        _pf = os.path.join(_d, "correspondents.json")
        open(_pf, "w").write(json.dumps({"1": {"kontext": "a"}, "2": {"email": "b@x.example"}}))
        _gs, _ = classify.stammdaten_schreiben(1, lambda alt: classify.stammdaten_nachtragen(alt, {"ustid": "ATU99988777"}, "", _eig, _q))
        _st = json.load(open(_pf))
        r.check("Schreiben: Eintrag ergänzt, andere Einträge und Felder bleiben",
                _gs == {"ustid": "ATU99988777"} and _st["1"]["kontext"] == "a" and _st["2"] == {"email": "b@x.example"})
        open(_pf, "w").write("[kaputt")
        try:
            classify.stammdaten_schreiben(1, lambda alt: ({"x": 1}, {"x": 1}, {}))
            _geworfen = False
        except Exception:
            _geworfen = True
        r.check("Schreiben: kaputte Datei wird nicht überschrieben", _geworfen and open(_pf).read() == "[kaputt")
        # Sperrdatei, die das Panel (root) angelegt hat: nur lesbar. flock braucht kein Schreibrecht —
        # die Erfassung darf daran nicht scheitern (bis 2026-09-27: PermissionError, still im Log).
        open(_pf, "w").write("{}")
        os.chmod(_pf + ".lock", 0o444)
        _flags = []
        _os_open = os.open
        def _merken(pfad, flags, *a):
            if not str(pfad).endswith(".lock"):
                return _os_open(pfad, flags, *a)
            _flags.append(flags)
            if os.geteuid() == 0 and flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND):
                raise PermissionError(13, "Permission denied (als root nachgestellt)")
            return _os_open(pfad, flags, *a)
        os.open = _merken
        try:
            _gs2, _ = classify.stammdaten_schreiben(3, lambda alt: ({"ustid": "ATU1"}, {"ustid": "ATU1"}, {}))
            _fehler = None
        except Exception as e:
            _gs2, _fehler = None, e
        finally:
            os.open = _os_open
        r.check("Schreiben: fremde, nur lesbare Sperrdatei — gesperrt und geschrieben, ohne Schreibrecht auf die Sperre",
                _gs2 == {"ustid": "ATU1"} and _fehler is None
                and bool(_flags) and not any(f & (os.O_WRONLY | os.O_RDWR | os.O_APPEND) for f in _flags), f"{_fehler!r} {_flags}")
    finally:
        classify.SCRIPT_DIR = _alt_dir
        classify.CORR_META.clear(); classify.CORR_META.update(_alt_meta)

# Verdrahtung: Pass 0 gibt es nicht mehr (2026-09-27) — Pass 1 ist der einzige KI-Aufruf; der
# Stammdaten-Treffer steht mit Begründung in der Kandidatenliste, und Pass 1 liefert Stammdaten,
# die nachgetragen würden.
classify.CORR_META.clear(); classify.CORR_META.update({"7": {"ustid": "ATU99988777"}})
_s = _lauf([{**_ok, "correspondent": "Beispiel Software", "absender": {"iban": "AT48 3200 0000 1234 5864"}}],
           text=_gut + " UID ATU99988777", korrespondenten=[{"id": 7, "name": "Beispiel Software"}])
classify.CORR_META.clear()
r.check("Verdrahtung: nur ein KI-Aufruf (Pass 1), kein Pass 0", len(_s["chat"]) == 1, str(len(_s["chat"])))
_v = classify.pass1_nachricht_teile("", None, "", "", "", "2026-01-02", "", "a.pdf", "", "T", "I", typ_vorschlag="Mahnung")
r.check("Typ-Vorschlag: vorbelegter Typ steht als Vorschlag in der Nachricht",
        "von Paperless vorbelegt (nur ein Vorschlag, kann falsch sein): Mahnung" in "".join(t for t, _, _ in _v))
r.check("Typ überschreibbar: Import ohne FORCE, Knopf, Panel ja — Bestand, FORCE-Handaufruf, Unbekanntes nein",
        classify.typ_ueberschreibbar("", False) and classify.typ_ueberschreibbar("knopf", True)
        and classify.typ_ueberschreibbar("manual", True) and not classify.typ_ueberschreibbar("", True)
        and classify.typ_ueberschreibbar("mail", True)
        and not classify.typ_ueberschreibbar("bulk", False) and not classify.typ_ueberschreibbar("irgendwas", False))
r.check("Typ-Vorschlag: ohne vorbelegten Typ kein Hinweis",
        "vorbelegt" not in "".join(t for t, _, _ in classify.pass1_nachricht_teile("", None, "", "", "", "d", "", "a", "", "T", "I")))
r.check("Verdrahtung: Pass 1 läuft mit Schema (Dokumenttyp frei, Typen im Prompt)",
        (_s.get("schemas") or [None])[0] and "enum" not in _s["schemas"][0]["properties"]["document_type"]
        and "Rechnung" in _s["system"])
r.check("Verdrahtung: Treffer steht mit Begründung in der Nachricht an Pass 1",
        "Beispiel Software" in _s["chat"][0] and "gefunden: USt-ID ATU99988777" in _s["chat"][0])
r.check("Verdrahtung: Trockenlauf zeigt die Stammdaten, schreibt sie nicht",
        (classify.TRACE.get("stammdaten") or {}).get("geschrieben") == {"iban": "AT48 3200 0000 1234 5864"}
        and classify.TRACE["stammdaten"].get("trocken") is True, str(classify.TRACE.get("stammdaten")))
_o = _lauf([_ok], text=_gut + " Absender: Nord Autoteile, Musterstadt",
           korrespondenten=[{"id": 7, "name": "Beispiel Software"}, {"id": 8, "name": "Nord Autoteile GmbH"}])
classify.CORR_META.clear(); classify.CORR_META.update({"7": {"iban": ["AT61 1904 3002 3457 3201"]},
                                                       "8": {"iban": ["DE89 3704 0044 0532 0130 00"]}})
_a1 = _lauf([{**_ok, "correspondent": "Beispiel Software", "absender": {"iban": "AT48 3200 0000 1234 5864"}}],
            korrespondenten=[{"id": 7, "name": "Beispiel Software"}, {"id": 8, "name": "Andere Firma"}])
_a1sd = classify.TRACE.get("stammdaten") or {}
_a2 = _lauf([{**_ok, "correspondent": "Beispiel Software", "absender": {"iban": "DE89 3704 0044 0532 0130 00"}}],
            korrespondenten=[{"id": 7, "name": "Beispiel Software"}, {"id": 8, "name": "Andere Firma"}])
_a2sd = classify.TRACE.get("stammdaten") or {}
_a3 = _lauf([{**_ok, "correspondent": "Beispiel Softwar", "absender": {"iban": "AT48 3200 0000 1234 5864"}},
             {"match": "Beispiel Software"}], korrespondenten=[{"id": 7, "name": "Beispiel Software"}])
_a3sd = classify.TRACE.get("stammdaten") or {}
classify.CORR_META.clear()
r.check("Im Lauf: exakte Zuordnung hängt die neue IBAN an", _a1sd.get("geschrieben", {}).get("iban") == "AT48 3200 0000 1234 5864", str(_a1sd))
r.check("Im Lauf: IBAN eines anderen Korrespondenten wird verworfen", "Andere Firma" in _a2sd.get("verworfen", {}).get("iban", ""), str(_a2sd))
r.check("Im Lauf: Zuordnung über Pass 2 (ähnlicher Name) hängt nicht an",
        "iban" not in _a3sd.get("geschrieben", {}) and _a3sd.get("verworfen", {}).get("iban", "").startswith("nicht angehängt"),
        f"chat={len(_a3['chat'])} {_a3sd}")
r.check("Verdrahtung: ohne Kennung findet der Name im Text den Kandidaten (Rechtsform egal)",
        "- Nord Autoteile GmbH" in _o["chat"][0] and "Name „Nord Autoteile GmbH“ im Briefkopf" in _o["chat"][0]
        and "Beispiel Software" not in _o["chat"][0].split("METADATEN")[0])
r.check("Verdrahtung: Pass 1 wird nach den Absender-Stammdaten gefragt", "absender = Objekt" in _b["system"])

# Die Schreibstelle selbst (nicht nur die Hilfsfunktion): echter Lauf, vorbelegter Typ 1, die KI
# sagt „Mahnung" (Typ 2). Import überschreibt, Handaufruf mit FORCE und Bestand lassen stehen.
def _typ_geschrieben(**kw):
    a = _lauf([{**_ok, "document_type": "Mahnung"}], typ=1, dry=False, **kw)
    return [p.get("document_type") for p in a.get("patch", [])]
r.check("Schreibstelle: Import (keine Quelle, kein FORCE) überschreibt den vorbelegten Typ",
        _typ_geschrieben() == [2], str(_typ_geschrieben()))
r.check("Schreibstelle: KI-Knopf und Panel überschreiben",
        _typ_geschrieben(source="knopf") == [2] and _typ_geschrieben(source="manual") == [2])
# Der Mail-Nachlauf läuft mit FORCE (das Dokument trägt vom Import schon den Marker), ist aber noch der
# Import: der Typ kann nur von der Paperless-Automatik stammen.
r.check("Schreibstelle: Mail-Nachlauf (Quelle mail, mit FORCE) überschreibt den vorbelegten Typ",
        _typ_geschrieben(source="mail", force=True) == [2], str(_typ_geschrieben(source="mail", force=True)))
r.check("Schreibstelle: Handaufruf mit FORCE oder FORCE_OCR und Bestands-Durchlauf lassen den Typ stehen",
        _typ_geschrieben(force=True) == [None] and _typ_geschrieben(source="bulk") == [None]
        and _typ_geschrieben(force_ocr=True) == [None],
        f"{_typ_geschrieben(force=True)} {_typ_geschrieben(source='bulk')}")
_tv = _lauf([_ok], typ=1)
r.check("Verdrahtung: der von Paperless vorbelegte Typ geht als Vorschlag an Pass 1",
        "vorbelegt (nur ein Vorschlag, kann falsch sein): Rechnung" in _tv["chat"][0])

# Neuer Absender auf kurzem, lesbarem Beleg (2026-09-27): die KI erkennt „Beispielportal",
# kein bestehender passt → neu anlegen. Die alte Faustregel (Text kurz = unsicher) behielt stattdessen
# den bisherigen Korrespondenten, selbst mit Hinweis.
_kurz = "Beispielportal Rechnung Nr. 4711 Betrag 29,99 EUR"
# Wie in Produktion: Pass 2 läuft (ein bestehender ist entfernt ähnlich) und antwortet „keiner".
_nk = _lauf([{**_ok, "correspondent": "Beispielportal"}, {"match": None}], text=_kurz, dry=False, korr=98,
            korrespondenten=[{"id": 98, "name": "Eigenfirma e.U."}])
_nk_unl = _lauf([{**_ok, "correspondent": "Beispielportal", "needs_ocr": True},
                 {**_ok, "correspondent": "Beispielportal", "needs_ocr": True}, {"match": None}], text=_kurz, dry=False, korr=98,
                korrespondenten=[{"id": 98, "name": "Eigenfirma e.U."}])
r.check("Korrespondent: kurzer, von der KI lesbar gemeldeter Beleg → neuer Absender wird angelegt",
        ("/correspondents/", {"name": "Beispielportal"}) in _nk.get("send", []), str(_nk.get("send")))
r.check("Korrespondent: meldet die KI auch nach OCR unlesbar, bleibt der bisherige (kein Anlegen)",
        not any(p == "/correspondents/" for p, _ in _nk_unl.get("send", []))
        and all(x.get("correspondent") == 98 for x in _nk_unl.get("patch", [])), str(_nk_unl.get("send")))
r.check("Korrespondent behalten nur bei KI-Meldung „unlesbar“ und ohne Hinweis",
        classify.korrespondent_behalten(98, True, "") and not classify.korrespondent_behalten(98, False, "")
        and not classify.korrespondent_behalten(98, True, "das ist Beispielportal")
        and not classify.korrespondent_behalten(None, True, ""))

# Portal-Fall (PO 2026-09-27): Die Absender-Mail gehört einem Portal, das Dokumente vieler Firmen
# verschickt. Die Mail ist dann nur ein Kandidat — nennt Pass 1 die Firma aus dem Text, gilt die.
classify.CORR_META.clear(); classify.CORR_META.update({"20": {"domains": "portal.example"}})
_alt_mf = classify.CFG["mail_from_field"]; classify.CFG["mail_from_field"] = "Absender-Mail"
try:
    _pt = _lauf([{**_ok, "correspondent": "Nord Autoteile GmbH"}], text=_gut + " Nord Autoteile GmbH",
                korrespondenten=[{"id": 20, "name": "Rechnungsportal"}, {"id": 8, "name": "Nord Autoteile GmbH"}],
                felder=[{"id": 90, "name": "Absender-Mail", "data_type": "string"}],
                feldwerte=[{"field": 90, "value": "noreply@portal.example"}])
finally:
    classify.CFG["mail_from_field"] = _alt_mf; classify.CORR_META.clear()
r.check("Portal: Mail-Treffer ist nur Kandidat, beide gehen an Pass 1",
        "Rechnungsportal" in _pt["chat"][0] and "Absender-Mail" in _pt["chat"][0] and "Nord Autoteile GmbH [" in _pt["chat"][0])
r.check("Portal: die Portal-Mail wird NICHT bei der Firma nachgetragen",
        "absender_mail" in (classify.TRACE.get("stammdaten") or {}).get("verworfen", {})
        and "domains" not in (classify.TRACE.get("stammdaten") or {}).get("geschrieben", {}), str(classify.TRACE.get("stammdaten")))
_m = {"id": 1, "name": "M"}
r.check("Mail bestätigt: Domain steht im Dokument, kein anderer Korrespondent hat sie",
        classify.mail_bestaetigt("a@nord.example", 8, None, "www.nord.example", {})
        and not classify.mail_bestaetigt("a@nord.example", 8, _m, "www.nord.example", {})
        and not classify.mail_bestaetigt("a@nord.example", 8, None, "nichts", {})
        and classify.mail_bestaetigt("a@nord.example", 8, None, "nichts", {"email": "office@nord.example"}))
r.check("Portal: zugeordnet wird die Firma, die Pass 1 nennt, nicht das Portal",
        "exakt='Nord Autoteile GmbH'" in (classify.TRACE.get("correspondent") or {}).get("ergebnis", ""),
        str(classify.TRACE.get("correspondent")))

# ---- KI-Aufrufe: Kürzung (Anfang + Ende), JSON-Schema, Prompt-Caching (PO 2026-09-27)
_lang = "A" * 9500 + "MITTE" + "x" * 3000 + "ENDE-SUMME 123,45"
_k = classify.text_kuerzen(_lang, 10000, 1000)
r.check("Kürzung: kurzer Text bleibt ganz", classify.text_kuerzen("kurz", 10000, 1000) == "kurz")
r.check("Kürzung: Anfang 9000 + Ende 1000, dazwischen ein Hinweis, Summe am Ende bleibt",
        _k.startswith("A" * 9000) and _k.endswith("ENDE-SUMME 123,45") and "Zeichen ausgelassen" in _k
        and "MITTE" not in _k and len(_k) < 10100, str(len(_k)))
_s1 = classify.pass1_schema({"Rechnung": 1, "Brief": 2}, ["Betrag", "IBAN"], False, True, True)
r.check("Schema Pass 1: Dokumenttyp ohne Auswahlliste, Felder und Absender vorgegeben",
        "enum" not in _s1["properties"]["document_type"] and "dokumentart" in _s1["required"]
        and set(_s1["properties"]["fields"]["properties"]) == {"Betrag", "IBAN"}
        and "absender" in _s1["required"] and "summary" in _s1["properties"] and "tags" not in _s1["properties"])
r.check("Schema Pass 1: offen für Zusatzschlüssel eigener Prompts (summary_long …)",
        _s1["additionalProperties"] is True)
# Reihenfolge = Schreibreihenfolge des Modells. Der Typ vorn zwang ein eigenes Wort („Bußgeldbescheid“)
# über die Auswahlliste auf den ersten Eintrag mit gleichem Anfang (Bewerbung, Mahnung).
_ord = [list(classify.pass1_schema({"Bescheid": 1, "Bewerbung": 2}, ["Betrag"], t, a, m)["properties"])
        for t in (False, True) for a in (False, True) for m in (False, True)]
r.check("Schema Pass 1: der Dokumenttyp steht in jeder Variante zuletzt",
        all(o[-1] == "document_type" for o in _ord) and len(_ord) == 8, str(_ord[-1]))
r.check("Schema Pass 1: Zusammenfassung, Felder und Korrespondent stehen vor dem Typ",
        all(o.index(k) < o.index("document_type") for o in _ord for k in ("correspondent", "fields") )
        and _ord[-1].index("summary") < _ord[-1].index("document_type"))
# Mistral prüft das Schema gegen das JSON-Schema-Metaschema: `required` mit Doppelten → 422, und
# JEDER Lauf scheitert (2026-09-27 im Labor, eingeführt mit „Typ zuletzt“). Strukturell je Variante:
_sch = [classify.pass1_schema({"Bescheid": 1, "Bewerbung": 2}, ["Betrag"], t, a, m)
        for t in (False, True) for a in (False, True) for m in (False, True)]
r.check("Schema Pass 1: required ohne Doppelte und nur aus properties (sonst 422 von Mistral)",
        all(len(x["required"]) == len(set(x["required"])) and set(x["required"]) <= set(x["properties"]) for x in _sch),
        str([x["required"] for x in _sch if len(x["required"]) != len(set(x["required"]))][:1]))
r.check("Schema Pass 1: Dokumenttyp Pflicht, freie Dokumentart direkt davor",
        all("document_type" in x["required"] and list(x["properties"])[-2:] == ["dokumentart", "document_type"]
            for x in _sch))

# ---- typ_zuordnen(): die freie Antwort auf die Typen abbilden (seit die Auswahlliste fehlt).
_ty = {"Rechnung": 1, "Bescheid": 2, "Erklaerung": 3, "Vollmacht": 4, "Kuendigung": 5, "Brief": 6}
r.check("Typ: genau und ohne Schreibweise (ä = ae, Groß/klein)",
        classify.typ_zuordnen("Rechnung", _ty) == 1 and classify.typ_zuordnen("Erklärung", _ty) == 3
        and classify.typ_zuordnen("kündigung", _ty) == 5)
r.check("Typ: über das Wortende auf den Oberbegriff",
        classify.typ_zuordnen("Einverständniserklärung", _ty) == 3 and classify.typ_zuordnen("Bußgeldbescheid", _ty) == 2
        and classify.typ_zuordnen("Stromrechnung", _ty) == 1)
r.check("Typ: nichts Passendes, leer oder zu kurzes Ende → None",
        classify.typ_zuordnen("Zeugenaussage", _ty) is None and classify.typ_zuordnen(None, _ty) is None
        and classify.typ_zuordnen("Personalakte", {"Akte": 6}) is None and classify.typ_zuordnen("Liebesbrief", {"Brief": 6}) == 6)
_tz = _lauf([{**_ok, "document_type": "Haftungserklärung"}], dry=False, typ=None)
_tz2 = _lauf([{**_ok, "document_type": None, "dokumentart": "Zahlungsmahnung"}], dry=False, typ=None)
r.check("Schreibstelle: freie Typ-Antwort und ersatzweise die Dokumentart werden zugeordnet",
        [p.get("document_type") for p in _tz.get("patch", [])] == [None] and
        [p.get("document_type") for p in _tz2.get("patch", [])] == [2], f"{_tz.get('patch')} {_tz2.get('patch')}")
r.check("Schema Pass 2: nur Kandidaten oder null", classify.pass2_schema(["A", "B"])["properties"]["match"]["enum"] == ["A", "B", None])

# Was tatsächlich an Mistral geht: response_format json_schema (strict) und prompt_cache_key.
import urllib.request as _ur
_gesendet = []
class _Antwort:
    def __init__(self): self._d = json.dumps({"choices": [{"message": {"content": "{\"match\": null}"}}],
                                             "usage": {"prompt_tokens": 100, "completion_tokens": 5,
                                                       "prompt_tokens_details": {"cached_tokens": 80}}}).encode()
    def read(self, *a): return self._d
_alt_open, _alt_key = _ur.urlopen, classify.CACHE_KEY
_ur.urlopen = lambda req, timeout=0: (_gesendet.append(json.loads(req.data)), _Antwort())[1]
try:
    classify.CACHE_KEY = "paperlaiss-test"; classify.NUTZUNG.clear()
    classify.mistral_chat([{"role": "user", "content": "x"}], 50, classify.pass2_schema(["A"]), "pass2")
    classify.mistral_chat([{"role": "user", "content": "x"}], 50, name="korrektur")
finally:
    _ur.urlopen, classify.CACHE_KEY = _alt_open, _alt_key
r.check("Mistral-Aufruf: Schema als response_format json_schema, strict",
        _gesendet[0]["response_format"]["type"] == "json_schema" and _gesendet[0]["response_format"]["json_schema"]["strict"] is True)
r.check("Mistral-Aufruf: ohne Schema weiter json_object", _gesendet[1]["response_format"] == {"type": "json_object"})
r.check("Mistral-Aufruf: prompt_cache_key wird mitgeschickt", all(g.get("prompt_cache_key") == "paperlaiss-test" for g in _gesendet))
r.check("Mistral-Aufruf: zwischengespeicherte Tokens landen im Trace", classify.NUTZUNG[0]["cached"] == 80)

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

# ---- baue_system(): beide Generationen von Tag-Platzhaltern. Ein Bestandsprompt mit {TAGS}
# bekam bis 2026-09-27 still keine Tag-Liste — der Lauf sah normal aus, nur ohne Tags.
_typen = {"Rechnung": 1, "Brief": 2}
_liste = "- Finanzen: Geld\n- Wohnen: Miete"
_alt = classify.baue_system("Typen: {TYPES}\nTags: {TAGS}\nEnde", _typen, _liste)
r.check("baue_system: {TAGS} wird durch die Tag-Liste ersetzt",
        "- Finanzen: Geld" in _alt and "{TAGS}" not in _alt, _alt)
r.check("baue_system: {TAGS} bekommt nur die Liste, nicht den ganzen Block", "new_tags" not in _alt)
_neu = classify.baue_system("Typen: {TYPES}\n{TAGBLOCK}Ende", _typen, _liste)
r.check("baue_system: {TAGBLOCK} bekommt den ganzen Block",
        "- Wohnen: Miete" in _neu and "new_tags" in _neu and "{TAGBLOCK}" not in _neu)
_ohne = classify.baue_system("Typen: {TYPES}", _typen, _liste)
r.check("baue_system: ohne Platzhalter wird der Block angehängt statt verschluckt", "- Finanzen: Geld" in _ohne)
_aus = classify.baue_system("Typen: {TYPES}\nTags: {TAGS}{TAGBLOCK}", _typen, None)
r.check("baue_system: Tagging aus → keine Tags, keine Platzhalterreste",
        "Finanzen" not in _aus and "{TAG" not in _aus, _aus)
r.check("baue_system: Typen sortiert eingesetzt", "Typen: Brief, Rechnung" in _aus)

# ---- summary_aus(): Bestandsprompts verlangen summary_long/summary_short statt summary.
r.check("summary_aus: summary hat Vorrang",
        classify.summary_aus({"summary": "A", "summary_long": "B"}) == "A")
r.check("summary_aus: summary_long, wenn summary fehlt",
        classify.summary_aus({"summary_long": " Lang. ", "summary_short": "Kurz"}) == "Lang.")
r.check("summary_aus: summary_short als letzter Rückfall", classify.summary_aus({"summary_short": "Kurz"}) == "Kurz")
r.check("summary_aus: leer/null/kein String → leer",
        classify.summary_aus({"summary": "  ", "summary_long": None, "summary_short": 3}) == "")


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

# ---- Jede Einstellung hat im Panel Titel und Beschreibung (panel/seiten.EINSTELLUNGEN).
# Fehlt ein Eintrag, erschiene der Schlüssel roh unter „Weitere" — genau das soll nicht passieren.
sys.path.insert(0, str(ROOT / "panel"))
import seiten  # noqa: E402
_meta = seiten.EINSTELLUNGEN
_fehlt = [k for k in sorted(classify._BEKANNT) if not k.startswith("api_key")
          and k not in _meta and not any(m.startswith(k + ".") for m in _meta)]
_fehlt += [f"ocr_regeln.{k}" for k in classify.OCR_REGELN_VORGABE if f"ocr_regeln.{k}" not in _meta]
r.check("Einstellungen: jeder Schlüssel hat Titel und Beschreibung im Panel", not _fehlt, str(_fehlt))
r.check("Einstellungen: nur bekannte Gruppen", all(g in seiten.GRUPPEN for g, *_ in _meta.values()))

# ausfuehren(): ein gescheiterter Lauf meldet sich per Exit-Code, wenn ihn jemand auswertet (Panel,
# KI-Knopf, Mail-Nachlauf mit CLASSIFY_DOC) — als Post-Consume-Skript (nur DOCUMENT_ID) nie.
def _exitcode(fehler, umgebung):
    alt = {k: getattr(classify, k) for k in ("main", "log", "save_trace", "unmark_running")}
    altenv = {k: os.environ.pop(k, None) for k in ("CLASSIFY_DOC", "DOCUMENT_ID")}
    def _main():
        if fehler:
            raise RuntimeError("422")
    classify.main = _main
    classify.log = classify.save_trace = classify.unmark_running = lambda *a, **k: None
    os.environ.update(umgebung)
    try:
        return classify.ausfuehren()
    finally:
        for k, v in alt.items():
            setattr(classify, k, v)
        for k in ("CLASSIFY_DOC", "DOCUMENT_ID"):
            os.environ.pop(k, None)
            if altenv[k] is not None:
                os.environ[k] = altenv[k]
r.check("Exit-Code: Fehler im Knopf-/Panel-Lauf (CLASSIFY_DOC) → 2, damit dort nicht „fertig“ steht",
        _exitcode(True, {"CLASSIFY_DOC": "5"}) == 2)
r.check("Exit-Code: Fehler als Post-Consume-Skript (DOCUMENT_ID) → 0, der Import bleibt gültig",
        _exitcode(True, {"DOCUMENT_ID": "5"}) == 0)
r.check("Exit-Code: Erfolg → 0", _exitcode(False, {"CLASSIFY_DOC": "5"}) == 0)

# Eine unlesbare Store-Datei ist eine Warnung, kein Absturz. Bis 2026-09-27 rief classify.py dafür
# log() VOR dessen Definition auf: NameError, Exit 1 — und Paperless 3 wertet den Import dann als
# gescheitert. Echter Aufruf in einem eigenen Verzeichnis (SCRIPT_DIR = Ort der Datei).
import shutil as _sh, subprocess as _sp, stat as _stat
with tempfile.TemporaryDirectory() as _td:
    _sh.copy(Path(__file__).resolve().parent.parent / "classify.py", _td)
    Path(_td, "correspondents.json").write_text("{kaputt", encoding="utf-8")
    _env = {**os.environ, "CLASSIFY_LOG": str(Path(_td, "classify.log")), "CLASSIFY_CONFIG": str(Path(_td, "fehlt.json")),
            "CLASSIFY_DUMP_DEFAULTS": "1"}
    _run = _sp.run([sys.executable, str(Path(_td, "classify.py"))], env=_env, capture_output=True, text=True, timeout=60)
    _logtext = Path(_td, "classify.log").read_text(encoding="utf-8") if Path(_td, "classify.log").exists() else ""
r.check("Store kaputt: classify.py stürzt nicht ab (Exit 0), meldet es aber im Log",
        _run.returncode == 0 and "STORE: correspondents.json nicht lesbar" in _logtext,
        f"rc={_run.returncode} log={_logtext[:120]!r} err={_run.stderr[-200:]!r}")

# schreibe_json: Rechte und Besitzer bleiben — ein Lauf als root darf den Store nicht root-eigen machen.
with tempfile.TemporaryDirectory() as _td:
    _alt = Path(_td, "store.json"); _alt.write_text("{}", encoding="utf-8"); os.chmod(_alt, 0o640)
    _aufrufe = []
    _chown = os.chown
    os.chown = lambda p, u, g: _aufrufe.append((os.path.basename(str(p)), u, g))
    try:
        classify.schreibe_json(str(_alt), {"a": 1})
        classify.schreibe_json(str(Path(_td, "neu.json")), {"b": 2})
    finally:
        os.chown = _chown
    _st_dir = os.stat(_td)
    r.check("schreibe_json: der Modus der alten Datei bleibt (0640 statt 0600 aus mkstemp)",
            _stat.S_IMODE(os.stat(_alt).st_mode) == 0o640, oct(_stat.S_IMODE(os.stat(_alt).st_mode)))
    r.check("schreibe_json: Besitzer der alten Datei bzw. des Ordners wird übernommen",
            len(_aufrufe) == 2 and _aufrufe[0][1:] == (os.stat(_alt).st_uid, os.stat(_alt).st_gid)
            and _aufrufe[1][1:] == (_st_dir.st_uid, _st_dir.st_gid), str(_aufrufe))
_app = (Path(__file__).resolve().parent.parent / "panel" / "app.py").read_text(encoding="utf-8")
_sj = _app[_app.index("def schreibe_json"):_app.index("raise\n", _app.index("def schreibe_json"))]
r.check("Panel-schreibe_json übernimmt Rechte und Besitzer genauso",
        "os.chown(tmp, vorbild.st_uid, vorbild.st_gid)" in _sj and "os.chmod(tmp, vorbild.st_mode" in _sj)

# ---- Pass-2-Sperre (2026-09-27): die KI ordnete „Anna Berger“ → „Anna Zeller“ (gleicher Vorname) und
# „Klein + Verbrauchsmaterial“ → „Klein Werkzeughandel“ zu; die Stammdaten-Erfassung trug dann die IBAN des einen
# beim anderen ein. Die Sperre im Code lässt nur echte Namensvarianten durch.
_p2 = [("Anna Berger", "Anna Zeller", False), ("Berger Anna", "Anna Zeller", False),
       ("Klein + Verbrauchsmaterial", "Klein Werkzeughandel Ges.m.b.H.", False),
       ("Mustrmann GmbH", "Mustermann", True), ("Autohaus Neuhauserr", "Autohaus Neuhauser GmbH", True),
       ("AUER Reifen GesmbH", "AUER REIFEN GmbH", True), ("Amazon EU Sarl", "Amazon EU S.à r.l.", True),
       ("ÖBB", "ÖBB-Personenverkehr AG", True), ("Deutsche Telekom", "Telekom Deutschland GmbH", True),
       ("Max Mustermann", "Maximilian Mustermann", True), ("Mustermann Max", "Max Mustermann", True)]
_p2f = [(v, n, classify.pass2_plausibel(v, n)) for v, n, soll in _p2 if classify.pass2_plausibel(v, n)[0] != soll]
r.check("Pass-2-Sperre: gleicher Vorname oder kurzes Allerweltswort reicht nicht, echte Varianten gehen durch",
        not _p2f, str(_p2f))
r.check("Pass-2-Sperre: ein Alias zählt als Name (Zuordnung über den gepflegten Alias bleibt möglich)",
        classify.pass2_plausibel("Telefonica", "O2", "Telefónica Germany, O2")[0])
# Echter Lauf: Pass 1 erkennt „Anna Berger“; „Anna Zeller“ besteht die Namensregel nicht → Pass 2 wird gar
# nicht gefragt, kein zweiter KI-Aufruf, neuer Korrespondent (seit 2026-09-27 spät).
_sp = _lauf([{**_ok, "correspondent": "Anna Berger"}, {"match": "Anna Zeller"}], dry=False,
            korrespondenten=[{"id": 192, "name": "Anna Zeller"}])
_sp_korr = [p.get("correspondent") for p in _sp.get("patch", [])]
_sp_p2 = (classify.TRACE.get("correspondent") or {}).get("pass2") or {}
r.check("Pass 2 nur mit Kandidat, der die Namensregel besteht: „Anna Zeller“ fällt vorher raus — ein KI-Aufruf, neu angelegt",
        192 not in _sp_korr and len(_sp["chat"]) == 1 and "uebersprungen" in _sp_p2
        and any("Anna Zeller" in x for x in _sp_p2.get("abgelehnt", [])), f"{_sp_korr} chat={len(_sp['chat'])} {_sp_p2}")
# Eine echte Namensvariante: Pass 2 wird gefragt und darf zuordnen.
_sv = _lauf([{**_ok, "correspondent": "Mavros"}, {"match": "Georg Mavros Automobil GmbH"}], dry=False,
            korrespondenten=[{"id": 55, "name": "Georg Mavros Automobil GmbH"}, {"id": 56, "name": "Anna Zeller"}])
r.check("Pass 2 bei echter Namensvariante: gefragt (zweiter Aufruf) und zugeordnet",
        len(_sv["chat"]) == 2 and [p.get("correspondent") for p in _sv.get("patch", [])][:1] == [55],
        f"chat={len(_sv['chat'])} {_sv.get('patch')}")

# Die Regel an den Fällen, die sie am 2026-09-27 an zwei echten Namenslisten falsch durchgelassen hätte
# (Namen verfremdet): gleicher Nachname/anderer Vorname, kurzes Wort per Tippfehler, häufiges Wort.
_hf = {"hamburg": 3, "autohaus": 5, "osterreichische": 2, "telekom": 1, "beispielmann": 2, "mavros": 1}
_p3 = [("Florian Musterer", "Judith Anna Musterer", False), ("Uber", "Gregor Huber", False),
       ("Bundesnetzagentur", "Bundesagentur für Arbeit", False), ("Amtsgericht Hamburg-Nord", "Jugendhilfe Hamburg gGmbH", False),
       ("Autohaus Beispiel e.U.", "Autohaus Muster GmbH", False), ("Mag. Karl Beispielmann", "Lena Maria Beispielmann", False),
       ("Mavros", "Georg Mavros Automobil GmbH", True), ("Georg Mavros Automobil GmbH", "Mavros Automobile GmbH", True),
       ("BLEU CIEL", "SARL BLEU CIEL Gesellschaft mit beschränkter Haftung", True),
       ("Kleinreparatur.example", "Firma kleinrepartur.example", True),
       ("Engel", "Engels Reisen", False), ("Engel Bau", "Engels Bau", False), ("Alex Muster", "Alexander Muster", True)]
_p3f = [(v, n, classify.pass2_plausibel(v, n, "", _hf)) for v, n, soll in _p3 if classify.pass2_plausibel(v, n, "", _hf)[0] != soll]
r.check("Namensregel: anderer Vorname, kurzes Wort per Tippfehler, häufiges Wort reichen nicht; echte Varianten gehen durch",
        not _p3f, str(_p3f))
r.check("Namensregel: Häufigkeit zählt Name und Aliase je Korrespondent einmal",
        classify.namens_haeufigkeit([{"id": 1, "name": "Autohaus A"}, {"id": 2, "name": "Autohaus B"}, {"id": 3, "name": "X"}],
                                    lambda c: "Autohaus Alt" if c["id"] == 3 else "").get("autohaus") == 3)

# ---- Telefon: einheitlich speichern und in allen Schreibweisen finden (2026-09-27)
# Ohne Annahme über das Land (PO: Deutschland und Österreich kommen beide vor — „0“ → „+49“ wäre falsch).
_tel = [("+49 (0) 30 123 45", "+493012345"), ("0049 30 12345", "+493012345"), ("030 12345", "03012345"),
        ("+43 0662 12345", "+4366212345"), ("Tel. 0662/12 34 5", "066212345"), ("0043-662-12345", "+4366212345"),
        ("Tel. +43 662 12345", "+4366212345"), ("12345", ""), ("", "")]
_telf = [(n, classify.norm_telefon(n), soll) for n, soll in _tel if classify.norm_telefon(n) != soll]
r.check("Telefon: +49/0049/(0) werden eins, national bleibt national, Buchstaben/Trenner fallen weg", not _telf, str(_telf))
_gl = [("0662 123456", "+43 662 123456", True), ("0662 123456", "+49 662 123456", True),
       ("+43 662 123456", "+49 662 123456", False), ("0043 662 123456", "+43 (0) 662 123456", True),
       ("0123 45", "+43 12345", False), ("0662 123456", "0662 123457", False)]
_glf = [(a, b, soll) for a, b, soll in _gl if classify.telefon_gleich(a, b) != soll]
r.check("Telefon gleich: national passt zu jeder Landesvorwahl, zwei internationale nur ganz, kurzer Kern nie",
        not _glf, str(_glf))
_meta = {7: {"telefon": ["+43 662 123456"], "iban": ["AT61 1904 3002 3457 3201", "AT48 3200 0000 1234 5864"],
             "kundennummer": ["K-99881", "7766554"], "ustid": ["ATU99988777"]},
         8: {"telefon": "0662 999888"},
         9: {"telefon": ["+49 30 7654321"]}}
_kd = [{"id": 7, "name": "Beispiel Werkstatt"}, {"id": 8, "name": "Eigenes Büro"}, {"id": 9, "name": "Andere Firma"}]
_eig_tel = classify.eigene_kennungen({"eigene_kennungen": {"telefon": ["+43 662 999888"]}})
_tt = classify.stammdaten_treffer(_kd, lambda i: _meta.get(i, {}),
                                  "Rechnung\nTel.: 0662 / 12 34 56\nFax 0662 999888\nZentrale +43 30 7654321\n"
                                  "Kd-Nr 7766554\nAT48 3200 0000 1234 5864", _eig_tel)
_g = dict((c["id"], g) for c, g in _tt)
r.check("Suche: gespeicherte +43-Nummer wird als „0662 / 12 34 56“ im Text gefunden",
        "Telefon +43662123456" in _g.get(7, []), str(_tt))
r.check("Suche: +49-Nummer passt nicht auf dieselben Ziffern mit +43", 9 not in _g, str(_g.get(9)))
r.check("Suche: mehrere Werte je Feld (zweite IBAN, zweite Kundennummer) werden gefunden",
        "IBAN" in _g.get(7, []) and "Kundennummer 7766554" in _g.get(7, []), str(_g.get(7)))
r.check("Suche: eine eigene Telefonnummer zählt nie (auch national und als alter Einzelwert gespeichert)", 8 not in _g, str(_g))
_nt, _gs, _vw = classify.stammdaten_nachtragen({}, {"telefon": "Tel. +43 (0)662 55 44 33"}, "", _eig_tel, "KI")
r.check("Erfassen: Telefon einheitlich und als Liste gespeichert", _nt.get("telefon") == ["+43662554433"], str(_nt))
_nt3, _, _ = classify.stammdaten_nachtragen({}, {"telefon": "0662 55 44 33"}, "", _eig_tel, "KI")
r.check("Erfassen: nationale Nummer bleibt national (keine geratene Landesvorwahl)", _nt3.get("telefon") == ["0662554433"], str(_nt3))
_nt2, _, _vw2 = classify.stammdaten_nachtragen({}, {"telefon": "0662 999 888"}, "", _eig_tel, "KI")
r.check("Erfassen: eigene Telefonnummer wird verworfen", "telefon" not in _nt2 and _vw2.get("telefon") == "eigene Telefonnummer", str(_vw2))
r.check("Erfassen: ein Listenfeld mit Altwert (Text) gilt als gefüllt",
        "telefon" not in classify.stammdaten_nachtragen({"telefon": "0662 1"}, {"telefon": "0662 123456"}, "", _eig_tel, "KI")[1])


# ---- Titel „Korrespondent – Dokumentart Kennung“ (PO 2026-09-27)
_tb = [(("Beispiel GmbH", "Rechnung", "12/2026"), "Beispiel GmbH – Rechnung 12/2026"),
       (("Beispiel GmbH", "Rechnung", "Rechnung RE-4711"), "Beispiel GmbH – Rechnung RE-4711"),
       (("Beispiel GmbH", "Rechnung", "Beispiel GmbH: Zahlungserinnerung"), "Beispiel GmbH – Rechnung Zahlungserinnerung"),
       (("Beispiel GmbH", None, "Hagelschaden  Golf"), "Beispiel GmbH – Hagelschaden Golf"),
       (("", "Bescheid", "Kfz-Steuer 2026"), "Bescheid Kfz-Steuer 2026"),
       (("Beispiel GmbH", "Brief", None), "Beispiel GmbH – Brief"),
       (("Beispiel GmbH", "Rechnung", "Ersatzteilrechnung 60565557"), "Beispiel GmbH – Rechnung 60565557"),
       (("Beispiel GmbH", "Kaufvertrag", "VW Golf Kaufvertrag"), "Beispiel GmbH – Kaufvertrag VW Golf"),
       (("Beispiel GmbH", None, None), None), (("Beispiel GmbH", None, "  – "), None)]
_tbf = [(e, classify.titel_bilden(*e), soll) for e, soll in _tb if classify.titel_bilden(*e) != soll]
r.check("Titel: Muster, doppelte Dokumentart/Absender in der Kennung fallen weg, ohne Typ und Kennung kein Titel",
        not _tbf, str(_tbf))
r.check("Titel: höchstens 128 Zeichen (Paperless-Grenze)", len(classify.titel_bilden("A" * 100, "Rechnung", "x" * 100)) == 128)
_st = classify.pass1_schema({"Rechnung": 1}, ["Betrag"], False, True, True, True)
r.check("Titel: Schema verlangt titel_kennung, vor dem Dokumenttyp, ohne doppelte Pflichtangabe",
        "titel_kennung" in _st["required"] and list(_st["properties"])[-1] == "document_type"
        and len(_st["required"]) == len(set(_st["required"])), str(_st["required"]))
r.check("Titel: Anweisung im Prompt nur bei eingeschaltetem „Titel setzen“",
        "titel_kennung" in classify.pass1_system({"titel_setzen": True}, {"Rechnung": 1}, [], set(), False)
        and "titel_kennung" not in classify.pass1_system({"titel_setzen": False}, {"Rechnung": 1}, [], set(), False))
_tk = {**_ok, "correspondent": "Beispiel GmbH", "titel_kennung": "RE-4711"}
_t1 = _lauf([_tk], dry=False, source="knopf", korrespondenten=[{"id": 7, "name": "Beispiel GmbH"}])
r.check("Titel im Lauf: KI-Knopf schreibt „Beispiel GmbH – Rechnung RE-4711“",
        (_t1.get("patch") or [{}])[0].get("title") == "Beispiel GmbH – Rechnung RE-4711", str(_t1.get("patch")))
_t2 = _lauf([_tk], dry=False, source="bulk", force=True, korrespondenten=[{"id": 7, "name": "Beispiel GmbH"}])
r.check("Titel im Lauf: Bestands-Durchlauf lässt den Titel stehen", "title" not in (_t2.get("patch") or [{}])[0], str(_t2.get("patch")))
_t3 = _lauf([{**_tk, "correspondent": "Neue Firma"}], dry=False, source="knopf", korrespondenten=[{"id": 7, "name": "Beispiel GmbH"}])
r.check("Titel im Lauf: neuer Korrespondent steht mit seinem Namen im Titel",
        (_t3.get("patch") or [{}])[0].get("title") == "Neue Firma – Rechnung RE-4711", str(_t3.get("patch")))
_alt_ts = classify.CFG.get("titel_setzen")
classify.CFG["titel_setzen"] = False
try:
    _t4 = _lauf([_tk], dry=False, source="knopf", korrespondenten=[{"id": 7, "name": "Beispiel GmbH"}])
finally:
    classify.CFG["titel_setzen"] = _alt_ts
r.check("Titel im Lauf: „Titel setzen“ aus → kein Titel", "title" not in (_t4.get("patch") or [{}])[0], str(_t4.get("patch")))


# ---- Kontext: was ist das Gegenüber (PO 2026-09-27) — bis dahin verlangt, aber nie gespeichert
_sk = classify.pass1_schema({"Rechnung": 1}, ["Betrag"], False, True, False)
r.check("Kontext: Pass 1 muss korrespondent_kontext liefern, wenn Stammdaten erfasst werden",
        "korrespondent_kontext" in _sk["required"] and "korrespondent_kontext" in _sk["properties"]
        and "korrespondent_kontext" not in classify.pass1_schema({"Rechnung": 1}, [], False, False, False)["properties"])
_nk, _gk, _ = classify.stammdaten_nachtragen({}, {}, "", _eig, _q, kontext="Kfz-Werkstatt in Salzburg")
r.check("Kontext: leerer Kontext wird gefüllt, mit Herkunft",
        _nk.get("kontext") == "Kfz-Werkstatt in Salzburg" and _nk["erfasst"].get("kontext") == _q, str(_nk))
r.check("Kontext: ein gepflegter Kontext bleibt, auch bei anderem Satz der KI",
        classify.stammdaten_nachtragen({"kontext": "Hausbank"}, {}, "", _eig, _q, anhaengen=True, kontext="Bank")[0]["kontext"] == "Hausbank")
r.check("Kontext: null/leer von der KI schreibt nichts", "kontext" not in classify.stammdaten_nachtragen({}, {}, "", _eig, _q, kontext="null")[0])
r.check("Kontext: gleiche Adresse oder Kundennummer bei einem anderen ist kein Widerspruch (fremd nur für eindeutige Kennungen)",
        classify.stammdaten_fremd([{"id": 2, "name": "B"}], lambda i: {"kundennummer": ["12345"], "adresse": "Weg 1"}, 1)("kundennummer", "12345") is None)

# ---- Prüfen: Daten des Dokuments passen nicht zum Korrespondenten → markieren (Tag, Log, Aktivität)
classify.CORR_META.clear(); classify.CORR_META.update({"7": {"ustid": ["ATU11122233"]}, "8": {"iban": ["DE89 3704 0044 0532 0130 00"]}})
_alt_ut = classify.CFG.get("unsicher_tag")
classify.CFG["unsicher_tag"] = "KI-unsicher"
_log_vorher = []
_alt_log = classify.log
classify.log = lambda m: _log_vorher.append(m)
try:
    # Trockenlauf: Stammdaten gegen den geladenen Stand (CORR_META) — beide Widersprüche im Trace.
    _lauf([{**_ok, "correspondent": "Beispiel Software", "absender": {"iban": "DE89 3704 0044 0532 0130 00", "ustid": "ATU99988777"}}],
          korrespondenten=[{"id": 7, "name": "Beispiel Software"}, {"id": 8, "name": "Andere Firma"}])
    _pr_trace = classify.TRACE.get("pruefen") or {}
    # Echter Lauf (Store im Testordner leer, fremd prüft gegen CORR_META): IBAN eines anderen → PRÜFEN-Zeile, Tag.
    _alt_rt = classify.resolve_tag
    classify.resolve_tag = lambda idx, name: 77 if name == "KI-unsicher" else _alt_rt(idx, name)
    _pr = _lauf([{**_ok, "correspondent": "Beispiel Software", "absender": {"iban": "DE89 3704 0044 0532 0130 00"}}],
                dry=False, korrespondenten=[{"id": 7, "name": "Beispiel Software"}, {"id": 8, "name": "Andere Firma"}])
    _ok_tags = _lauf([{**_ok, "correspondent": "Beispiel Software"}], dry=False,
                     korrespondenten=[{"id": 7, "name": "Beispiel Software"}])
    classify.resolve_tag = _alt_rt
finally:
    classify.log = _alt_log
    classify.CFG["unsicher_tag"] = _alt_ut
    classify.CORR_META.clear()
_pr_zeilen = [m for m in _log_vorher if m.startswith("PRÜFEN 5")]
r.check("Prüfen: IBAN eines anderen und abweichende USt-ID stehen im Trace",
        "Andere Firma" in _pr_trace.get("iban", "") and "USt-ID" in _pr_trace.get("ustid", ""), str(_pr_trace))
r.check("Prüfen: Tag „KI-unsicher“ am Dokument — ohne Widerspruch nicht",
        77 in (_pr.get("patch") or [{}])[0].get("tags", []) and 77 not in (_ok_tags.get("patch") or [{}])[0].get("tags", []),
        f"{_pr.get('patch')} {_ok_tags.get('patch')}")
r.check("Prüfen: eigene Logzeile NACH der OK-Zeile (die Aktivität zeigt „Prüfen“)",
        len(_pr_zeilen) == 1 and _log_vorher.index(_pr_zeilen[0]) > 0
        and _log_vorher[_log_vorher.index(_pr_zeilen[0]) - 1].startswith("OK 5"),
        str(_log_vorher[-3:]))

# ---- Pass 2 sieht Aliase und Kontext der Kandidaten, nicht nur Namen
classify.CORR_META.clear(); classify.CORR_META.update({"55": {"kontext": "Autohaus in Wien", "aliase": ["Mavros Wien"]}})
_pk = _lauf([{**_ok, "correspondent": "Mavros"}, {"match": "Georg Mavros Automobil GmbH"}],
            korrespondenten=[{"id": 55, "name": "Georg Mavros Automobil GmbH"}])
classify.CORR_META.clear()
r.check("Pass 2: Kandidat mit Alias und Kontext in der Frage", len(_pk["chat"]) == 2 and "Autohaus in Wien" in _pk["chat"][1]
        and "Mavros Wien" in _pk["chat"][1], _pk["chat"][-1][:400])

# ---- Dokumentdatum: steht seit dem JSON-Schema auf oberster Ebene der Antwort. Bis 2026-10-10 las die
# Schreibstelle es aus fields und schrieb nie eines (gemessen: 18 von 18 Vorschlägen verloren).
r.check("Datum: oberste Ebene wird gelesen", classify.dokument_datum({"document_date": "2026-08-19", "fields": {}}) == "2026-08-19")
r.check("Datum: fields als Rückfall für eigene Prompts", classify.dokument_datum({"fields": {"document_date": "2026-08-19"}}) == "2026-08-19")
r.check("Datum: Unsinn, ungültiger Tag und Jahre außerhalb → None",
        classify.dokument_datum({"document_date": "19.08.2026"}) is None
        and classify.dokument_datum({"document_date": "2026-02-30"}) is None
        and classify.dokument_datum({"document_date": "1890-01-01"}) is None
        and classify.dokument_datum({"document_date": None, "fields": None}) is None)


def _datum_geschrieben(antwort, text=_gut + " Ausgestellt am 19.08.2026."):
    a = _lauf([{**_ok, **antwort}], dry=False, text=text)
    return [p.get("created") for p in a.get("patch", [])]


r.check("Schreibstelle: Datum der obersten Ebene landet in created",
        _datum_geschrieben({"document_date": "2026-08-19"}) == ["2026-08-19T12:00:00+00:00"],
        str(_datum_geschrieben({"document_date": "2026-08-19"})))
r.check("Schreibstelle: gleiches Datum oder keines → created bleibt unberührt",
        _datum_geschrieben({"document_date": "2026-01-01"}) == [None] and _datum_geschrieben({}) == [None])
r.check("Schreibstelle: Datumswechsel steht in der OK-Zeile",
        "datum 2026-01-01 -> 2026-08-19" in Path(os.environ["CLASSIFY_LOG"]).read_text(encoding="utf-8"))

# ---- Prompt: Herkunft des Korrespondenten und Dokumentdatum gelten auch bei eigenem system_prompt.
_sys_eigen = classify.pass1_system({"system_prompt": "Eigener Prompt {TYPES}"}, {"Rechnung": 1}, [], set(), False)
r.check("Prompt: Korrespondenten-Regel auch bei eigenem Prompt (Werkzeug ≠ Absender, Unterschrift für die Stelle)",
        classify.KORRESPONDENT_ANWEISUNG in _sys_eigen and "STAMMT" in _sys_eigen and "Google Docs" in _sys_eigen)
r.check("Prompt: eigene Vorlage, die ein anderer unterschreibt, gehört zum anderen",
        "selbst aufgesetzt" in _sys_eigen and "diese andere Person, nicht wir" in _sys_eigen)
r.check("Prompt: Datumsregel auch bei eigenem Prompt (Unterschrift, nie Geburtsdatum)",
        classify.DATUM_ANWEISUNG in _sys_eigen and "Geburtsdatum" in _sys_eigen and "Unterschrift" in _sys_eigen)
r.check("Prompt: Kandidatenliste verlangt Herkunft, nicht bloße Nennung",
        "stammt das Dokument von" in classify.KAND_KOPF and "reicht nicht" in classify.KAND_KOPF)

# ---- Erneuter Lauf: der selbst gesetzte Titelkopf ist kein Fund „im Briefkopf“.
r.check("Titel: eigener Kopf „Korrespondent – “ fällt für die Suche weg, sonst bleibt der Titel",
        classify.titel_ohne_eigenen_kopf("Google – Sonstiges Zeugenaussage", "Google") == "Sonstiges Zeugenaussage"
        and classify.titel_ohne_eigenen_kopf("Rechnung Google März", "Google") == "Rechnung Google März"
        and classify.titel_ohne_eigenen_kopf("Google – Rechnung", None) == "Google – Rechnung")
r.check("Titel: mit Typ fällt auch der Typ weg, die Kennung bleibt",
        classify.titel_ohne_eigenen_kopf("Daniel – Vollmacht Unterrichtsvereinbarung", "Daniel", "Vollmacht") == "Unterrichtsvereinbarung"
        and classify.titel_ohne_eigenen_kopf("Daniel – Vollmachten 2026", "Daniel", "Vollmacht") == "Vollmachten 2026")
_rn = _lauf([_ok], korrespondenten=[{"id": 7, "name": "Nord Autoteile"}], korr=7, typ=1, titel="Nord Autoteile – Rechnung 4711")
r.check("Verdrahtung: Nachricht an Pass 1 zeigt den Titel ohne eigenen Kopf und Typ",
        "TITEL: 4711" in _rn["chat"][0] and "Nord Autoteile – Rechnung" not in _rn["chat"][0], _rn["chat"][0][-400:])
_rk = _lauf([_ok], korrespondenten=[{"id": 7, "name": "Nord Autoteile"}], korr=7, titel="Nord Autoteile – Rechnung 4711")
_rt = _lauf([_ok], korrespondenten=[{"id": 7, "name": "Nord Autoteile"}], titel="Rechnung Nord Autoteile 4711")
r.check("Verdrahtung: erneuter Lauf findet den eigenen Titelkopf nicht als Kandidaten, einen Paperless-Titel schon",
        "Name „Nord Autoteile“" not in _rk["chat"][0] and "Name „Nord Autoteile“" in _rt["chat"][0], _rk["chat"][0][:300])

# ---- Tabellenreste aus dem OCR: weder im Namen noch in den Stammdaten.
r.check("Tabellenrest: Rand weg, Inhalt bleibt",
        classify.ohne_tabellenrest("| Häuser ") == "Häuser" and classify.ohne_tabellenrest("• A-B GmbH |") == "A-B GmbH"
        and classify.ohne_tabellenrest(None) == "")
_tr, _tg, _ = classify.stammdaten_nachtragen({}, {"adresse": "| Fasanenweg 20a, 21614 Buxtehude"}, "", classify.eigene_kennungen({}), "Test")
r.check("Tabellenrest: Stammdaten-Wert wird ohne Rand gespeichert",
        _tr.get("adresse") == "Fasanenweg 20a, 21614 Buxtehude", str(_tr))
_tn = _lauf([{**_ok, "correspondent": "| Neue Firma"}], dry=False)
r.check("Tabellenrest: neuer Korrespondent wird ohne Rand angelegt",
        any(d and d.get("name") == "Neue Firma" for _, d in _tn.get("send", [])), str(_tn.get("send")))

# ---- Beschreibungen der Dokumenttypen: unter der Typliste, nur für vorhandene Typen.
_tb = classify.typ_block({"Unterrichtsvereinbarung": 1, "Rechnung": 2},
                         {"Unterrichtsvereinbarung": "Einverständniserklärung für private Anleitung", "Gibtsnicht": "x", "Rechnung": " "})
r.check("Typ-Beschreibung: nur vorhandene Typen mit Text, Vorrang vor dem Wortlaut genannt",
        "- Unterrichtsvereinbarung: Einverständniserklärung" in _tb and "Gibtsnicht" not in _tb
        and "- Rechnung" not in _tb and "vor dem Wortlaut" in _tb)
r.check("Typ-Beschreibung: ohne Beschreibungen kein Block", classify.typ_block({"A": 1}, {}) == "" and classify.typ_block({"A": 1}, None) == "")
_sys_tb = classify.pass1_system({"system_prompt": "Typen: {TYPES}", "type_descriptions": {"Rechnung": "auch Abrechnungen"}},
                                {"Rechnung": 1, "Brief": 2}, [], set(), False)
r.check("Typ-Beschreibung: landet im System-Prompt an der Stelle von {TYPES}",
        _sys_tb.startswith("Typen: Brief, Rechnung\nBEDEUTUNG") and "- Rechnung: auch Abrechnungen" in _sys_tb, _sys_tb[:200])
r.check("Typ-Anweisung: kein festes Beispiel, das einen Oberbegriff erzwingt",
        "Erklärung für eine Einverständniserklärung" not in classify.TYP_ANWEISUNG and "genauesten" in classify.TYP_ANWEISUNG)

# ---- Feste Zuweisung aus Paperless (Exakt / Regulärer Ausdruck) geht der KI vor, grobe Arten nicht.
_rt = [{"id": 1, "name": "Rechnung", "matching_algorithm": 1, "match": "Rechnung Invoice", "is_insensitive": True},
       {"id": 2, "name": "Mahnung", "matching_algorithm": 1, "match": "Mahnung", "is_insensitive": True},
       {"id": 3, "name": "Unterrichtsvereinbarung", "matching_algorithm": 3,
        "match": "Einverständniserklärung für private Anleitung", "is_insensitive": True},
       {"id": 4, "name": "Tandem", "matching_algorithm": 4, "match": r"Beförderungsvertrag\s+Tandem", "is_insensitive": False},
       {"id": 5, "name": "Kaputt", "matching_algorithm": 4, "match": "(", "is_insensitive": True},
       {"id": 6, "name": "Leer", "matching_algorithm": 3, "match": " ", "is_insensitive": True}]
_ta = lambda text: (classify.typ_aus_regel(_rt, text) or {}).get("name")
r.check("Typ-Regel: Exakt trifft über Zeilenumbruch und Groß/klein",
        _ta("EINVERSTÄNDNISERKLÄRUNG FÜR PRIVATE\nANLEITUNG – Seite 1") == "Unterrichtsvereinbarung")
r.check("Typ-Regel: Exakt verlangt die Reihenfolge und ganze Wörter",
        _ta("private Anleitung, Einverständniserklärung für") is None
        and _ta("Einverständniserklärung für private Anleitungen") is None)
r.check("Typ-Regel: Regulärer Ausdruck mit Groß/klein, kaputter Ausdruck stört nicht",
        _ta("Beförderungsvertrag  Tandemflug") == "Tandem" and _ta("beförderungsvertrag tandem") is None)
r.check("Typ-Regel: „Irgendein Wort“ und leere Zuweisung gelten nicht fest",
        _ta("Rechnung mit Mahnung") is None and classify.typ_aus_regel([], "x") is None)
_rv = _lauf([{**_ok, "document_type": "Rechnung"}], dry=False, typen=_rt,
            text=_gut + " Einverständniserklärung für private Anleitung")
r.check("Schreibstelle: feste Zuweisung schlägt die KI und steht im Trace",
        [p.get("document_type") for p in _rv.get("patch", [])] == [3]
        and (classify.TRACE.get("typ_regel") or {}).get("typ") == "Unterrichtsvereinbarung"
        and "typ per Zuweisung Unterrichtsvereinbarung" in Path(os.environ["CLASSIFY_LOG"]).read_text(encoding="utf-8"),
        str(_rv.get("patch")))
_rw = _lauf([{**_ok, "document_type": "Rechnung"}], dry=False, typen=_rt, text=_gut + " Mahnung")
r.check("Schreibstelle: ohne feste Zuweisung bleibt die KI-Wahl",
        [p.get("document_type") for p in _rw.get("patch", [])] == [1], str(_rw.get("patch")))

# ---- Feste Zuweisung auch für Korrespondenten (2026-10-14, Seite Nacharbeit): Marktplatz-Rechnungen
# nennen den Händler, das Archiv führt sie unter der Plattform. Die Zuweisung gewinnt VOR dem Abgleich —
# sonst legte der Lauf den Händler erst neu an —, und Stammdaten des Händlers landen nicht bei der Plattform.
_rk = [{"id": 40, "name": "Plattform", "matching_algorithm": 3, "match": "Auf das Konto von Plattform eingezahlt",
        "is_insensitive": True},
       {"id": 41, "name": "Grob", "matching_algorithm": 1, "match": "Rechnung", "is_insensitive": True},
       {"id": 42, "name": "Händler GmbH"}]
_mk = _gut + " Verkäufer Händler GmbH, UID LT100001158219. Auf das Konto von Plattform\neingezahlt."
r.check("Korrespondent-Regel: Exakt trifft, „Irgendein Wort“ nicht",
        (classify.korrespondent_aus_regel(_rk, _mk) or {}).get("name") == "Plattform"
        and classify.korrespondent_aus_regel(_rk, _gut + " Rechnung") is None)
classify.TRACE.clear()   # main() leert den Trace nicht (ein Prozess je Dokument), die Tests laufen hintereinander
_kz = _lauf([{**_ok, "correspondent": "Händler Neu UAB", "absender": {"ustid": "LT100001158219"}}, {"match": None}],
            dry=False, korrespondenten=_rk, text=_mk)
r.check("Schreibstelle Korrespondent: Zuweisung schlägt die KI, kein neuer Korrespondent, Trace nennt beides",
        [p.get("correspondent") for p in _kz.get("patch", [])] == [40]
        and not any(x[0] == "/correspondents/" for x in _kz.get("send", []))
        and (classify.TRACE.get("correspondent") or {}).get("vorschlag") == "Händler Neu UAB"
        and (classify.TRACE.get("correspondent") or {}).get("ergebnis") == "zuweisung='Plattform'",
        f"patch={_kz.get('patch')} send={_kz.get('send')}")
r.check("Schreibstelle Korrespondent: keine Händler-Stammdaten bei der Plattform",
        not classify.TRACE.get("stammdaten"), str(classify.TRACE.get("stammdaten")))
r.check("Schreibstelle Korrespondent: Titel trägt die Plattform",
        str((_kz.get("patch") or [{}])[0].get("title") or "").startswith("Plattform"), str(_kz.get("patch")))
_kn = _lauf([{**_ok, "correspondent": "Händler GmbH"}], dry=False, korrespondenten=_rk, text=_gut + " Rechnung")
r.check("Schreibstelle Korrespondent: ohne Zuweisung bleibt die KI-Wahl",
        [p.get("correspondent") for p in _kn.get("patch", [])] == [42], str(_kn.get("patch")))

# Eigene Firma nie als Stammdaten-Kandidat — auch wenn eine ihrer Kennungen in eigene_kennungen fehlt
# (Telefon im Briefkopf jeder eigenen Ausgangsrechnung; 2026-10-14 landete jede bei der eigenen Firma).
_eigk = [{"id": 98, "name": "Eigenfirma e.U."}, {"id": 2, "name": "Nord Autoteile"}]
_eigm = lambda c: {"telefon": "0664 1234567"} if c == 98 else {"telefon": "0662 999888"}
_eigt = "Eigenfirma - Hauptstraße 5 - Tel. 0664 1234567\nRechnung RE-516 an Kunde Nord Autoteile, Tel. 0662 999888"
_eigtr = [c["id"] for c, _ in classify.stammdaten_treffer(_eigk, _eigm, _eigt, _eig)]
r.check("Treffer: eigene Firma ist nie Kandidat, auch bei Kennung außerhalb eigene_kennungen",
        98 not in _eigtr and 2 in _eigtr, str(_eigtr))

# ---- Kennungen je Konto: im Haushalt ist „wir" nur der Besitzer des Dokuments.
_haus = {"kennungen_je_konto": True, "eigene_kennungen": {"namen": ["Erika Muster", "Max Muster"]},
         "konten": {"erika": {"iban": ["DE00 1111"]}, "*": {"email": ["post@example.com"]}}}
_erika = {"username": "erika", "first_name": "Erika", "last_name": "Muster", "email": "erika@example.com"}
_kc = classify.konto_cfg(_haus, 3, _erika)
r.check("Konto: nur der Besitzer ist „wir“, mit Mail aus dem Konto, IBAN aus konten, Gemeinsames aus „*“",
        _kc["eigene_kennungen"]["namen"] == ["Erika Muster"] and _kc["_konto"] == "erika"
        and set(_kc["eigene_kennungen"]["email"]) == {"erika@example.com", "post@example.com"}
        and _kc["eigene_kennungen"]["iban"] == ["DE00 1111"], str(_kc.get("eigene_kennungen")))
r.check("Konto: Schalter aus, kein Besitzer oder kein lesbares Konto → gemeinsame Kennungen",
        classify.konto_cfg({**_haus, "kennungen_je_konto": False}, 3, _erika)["eigene_kennungen"]["namen"] == ["Erika Muster", "Max Muster"]
        and classify.konto_cfg(_haus, None, _erika) is _haus and classify.konto_cfg(_haus, 3, {}) is _haus)
r.check("Konto: Prompt nennt nur den Besitzer und die anderen als Gegenüber",
        "im Konto von Erika Muster" in classify.eigene_firma_anweisung(_kc)
        and "Max Muster" not in classify.eigene_firma_anweisung(_kc)
        and "Gegenüber wie jedes andere" in classify.eigene_firma_anweisung(_kc))
_kl = _lauf([{**_ok, "correspondent": "Max Muster"}], text=_gut + " Absender: Max Muster, Musterweg 1",
            korrespondenten=[{"id": 7, "name": "Max Muster"}], besitzer=_erika, cfg=_haus)
r.check("Verdrahtung: bei Erikas Dokument ist Max ein Kandidat und Erika allein „wir“",
        "Name „Max Muster“" in _kl["chat"][0] and "im Konto von Erika Muster" in _kl["system"]
        and (classify.TRACE.get("konto") == "erika"), _kl["chat"][0][:300])
_kg = _lauf([{**_ok, "correspondent": "Max Muster"}], text=_gut + " Absender: Max Muster, Musterweg 1",
            korrespondenten=[{"id": 7, "name": "Max Muster"}], besitzer=_erika, cfg={**_haus, "kennungen_je_konto": False})
r.check("Verdrahtung: ohne Schalter bleibt Max „wir“ (kein Kandidat)", "Name „Max Muster“" not in _kg["chat"][0])

# ---- Datum nur mit Beleg im Text; Mistral-Anfragen werden bei 429/5xx wiederholt.
r.check("Datumsbeleg: gängige Schreibweisen werden gefunden",
        classify.datum_belegt("2026-08-19", "Krik DK, 19.8.26") and classify.datum_belegt("2010-12-16", "16. 12. 2010")
        and classify.datum_belegt("2026-08-20", "Unterzeichnet: 2026-08-20") and classify.datum_belegt("2026-09-24", "24. September 2026")
        and classify.datum_belegt("2018-01-31", "31. Jänner 2018") and classify.datum_belegt("2026-08-19", "8/19/2026, 12:45 PM"))
r.check("Datumsbeleg: ein Datum, das nicht im Text steht, gilt nicht",
        not classify.datum_belegt("2026-07-01", "Seite 2 von 7 … vom 01.09.2012 bis 28.02.2013")
        and not classify.datum_belegt("kaputt", "x"))
r.check("Schreibstelle: KI-Datum ohne Beleg im Text wird nicht geschrieben",
        _datum_geschrieben({"document_date": "2026-07-01"}) == [None]
        and classify.TRACE.get("datum_ohne_beleg") == "2026-07-01")

import urllib.error as _ue


def _senden_mit(fehlercodes):
    folge = list(fehlercodes); aufrufe = []
    def urlopen(req, timeout=0):
        aufrufe.append(1)
        if folge:
            code = folge.pop(0)
            raise _ue.HTTPError("u", code, "x", {}, None)
        return io.BytesIO(json.dumps({"ok": True}).encode())
    alt = classify.urllib.request.urlopen
    classify.urllib.request.urlopen = urlopen
    try:
        try:
            return classify.mistral_senden(object(), 5, warten=(0, 0)), len(aufrufe)
        except _ue.HTTPError as e:
            return e.code, len(aufrufe)
    finally:
        classify.urllib.request.urlopen = alt


import io, json
r.check("Mistral: 429 und 503 werden wiederholt, dann klappt es", _senden_mit([429, 503]) == ({"ok": True}, 3))
r.check("Mistral: nach allen Versuchen kommt der Fehler durch", _senden_mit([429, 429, 429]) == (429, 3))
r.check("Mistral: 401 wird nicht wiederholt", _senden_mit([401]) == (401, 1))
r.check("Prompt: Lohnunterlagen stammen vom Arbeitgeber, Krankenkasse ist nur Angabe",
        "ARBEITGEBER" in classify.KORRESPONDENT_ANWEISUNG and "Krankenkasse" in classify.KORRESPONDENT_ANWEISUNG)

# ---- Office-Datei: ein Datum gleich dem Importtag stammt aus einem automatischen Datumsfeld.
_of = _lauf([{**_ok, "document_date": "2026-07-01"}], dry=False, text=_gut + " Hamburg, 01.07.2026",
            datei="Bewerbung.docx", hinzu="2026-07-01T09:00:00Z")
_op = _lauf([{**_ok, "document_date": "2026-07-01"}], dry=False, text=_gut + " Hamburg, 01.07.2026",
            datei="Brief.pdf", hinzu="2026-07-01T09:00:00Z")
r.check("Schreibstelle: Importtag einer Word-Datei wird nicht geschrieben, bei einem PDF schon",
        [p.get("created") for p in _of.get("patch", [])] == [None]
        and [p.get("created") for p in _op.get("patch", [])] == ["2026-07-01T12:00:00+00:00"],
        f"{_of.get('patch')} {_op.get('patch')}")
r.check("Office-Importtag: Word-Datei mit Datum = Importtag zählt nicht, sonst schon",
        classify.office_importtag("2026-07-01", {"original_file_name": "Bewerbung.DOCX", "added": "2026-07-01T10:00:00Z"})
        and not classify.office_importtag("2017-04-17", {"original_file_name": "Bewerbung.docx", "added": "2026-07-01T10:00:00Z"})
        and not classify.office_importtag("2026-07-01", {"original_file_name": "scan.pdf", "added": "2026-07-01T10:00:00Z"}))

# ---- Zeitüberschreitung beim Speichern: nachsehen statt nachschießen, keine KI-Reparatur.
import socket as _so


def _patch_mit(folge, angekommen=False):
    """folge: je PATCH-Versuch 'zeit', 400 oder 'ok'. Gibt (Ergebnis, Anzahl PATCHes) zurück."""
    folge = list(folge); zaehl = []
    def send(pfad, daten, methode="PATCH", timeout=45):
        zaehl.append(timeout); f = folge.pop(0)
        if f == "zeit": raise _so.timeout("timed out")
        if f == 400: raise _ue.HTTPError("u", 400, "x", {}, io.BytesIO(b'{"custom_fields":["bad"]}'))
        return {}
    alt = (classify.send, classify.patch_angekommen)
    classify.send, classify.patch_angekommen = send, (lambda did, p: angekommen)
    try:
        return classify.patch_doc(5, {"title": "T"}, pause=0), zaehl
    finally:
        classify.send, classify.patch_angekommen = alt


_z1, _n1 = _patch_mit(["zeit", "zeit"])
r.check("PATCH: zweimal Zeitüberschreitung → höchstens zwei Versuche, längere Frist, als ZEIT gemeldet",
        _z1[0] is False and _z1[1].startswith(classify.ZEIT) and _n1 == list(classify.PATCH_FRIST_S), f"{_z1} {_n1}")
_z2, _n2 = _patch_mit(["zeit"], angekommen=True)
r.check("PATCH: nach Zeitüberschreitung schon angekommen → kein zweiter PATCH", _z2 == (True, None) and len(_n2) == 1)
_z3, _n3 = _patch_mit([400])
r.check("PATCH: Feldfehler (400) kommt als Text zurück, ohne Wiederholung", _z3[0] is False and "custom_fields" in _z3[1] and len(_n3) == 1)


_lp_fehler = None
try:
    _lp = _lauf([_ok], dry=False, patch_ergebnis=(False, classify.ZEIT + "timeout"))
except RuntimeError as _e:
    _lp_fehler = str(_e)
r.check("Schreibstelle: Zeitüberschreitung endet als Fehler (für ausfuehren), nicht als „OK“",
        _lp_fehler and "nicht möglich" in _lp_fehler, str(_lp_fehler))
r.check("Schreibstelle: bei Zeitüberschreitung keine KI-Reparatur (keine Korrektur-Runde)",
        classify.TRACE.get("repair") == []
        and (classify.TRACE.get("writeback") or {}).get("fehler", "").startswith(classify.ZEIT),
        str(classify.TRACE.get("repair")))
_lf = _lauf([_ok, {"fields": {}}, {"fields": {}}, {"fields": {}}, {"fields": {}}], dry=False,
            patch_ergebnis=(False, '{"custom_fields":["bad"]}'))
r.check("Schreibstelle: Feldfehler (400) wird weiter von der KI repariert",
        len(_lf["chat"]) == 5, f"chat={len(_lf['chat'])}")

# ---- Trockenlauf zeigt, was geschrieben würde (für die Testsammlung).
r.check("Ergebnis-Korrespondent aus der Info, bei „behalten“ der bisherige",
        classify.korrespondent_ergebnis("exakt='O2'") == "O2" and classify.korrespondent_ergebnis("NEU='X Y' (dry)") == "X Y"
        and classify.korrespondent_ergebnis("bestehenden behalten (Text unsicher)", "Alt") == "Alt"
        and classify.korrespondent_ergebnis("kein") is None)
r.check("Wirksames Datum: ohne Beleg im Text keins",
        classify.wirksames_datum({"document_date": "2026-07-01"}, "kein Datum hier", {}) is None
        and classify.wirksames_datum({"document_date": "2026-07-01"}, "Hamburg, 01.07.2026", {}) == "2026-07-01")

# ---- Kennnummern: Personal-/Vertragsnummer zählt, eigene Nummern (SV-Nr, Steuer-ID) nie.
_eg = classify.eigene_kennungen({"eigene_kennungen": {"nummern": ["864 093 317 53"]}})
r.check("Eigene Nummer: aus der Config (ohne Schreibweise) und per SV-Muster",
        classify.eigene_nummer("86409331753", _eg) and classify.eigene_nummer("66130593 B017", _eg)
        and not classify.eigene_nummer("782125149", _eg))
_kn, _kg, _kv = classify.stammdaten_nachtragen({}, {"kundennummer": "66130593B017"}, "", _eg, "Test")
_kn2, _kg2, _ = classify.stammdaten_nachtragen({}, {"kundennummer": "Pers.-Nr. 782125149"}, "", _eg, "Test")
r.check("Erfassen: SV-Nummer wird verworfen, Personalnummer gespeichert",
        "kundennummer" not in _kn and "eigene Nummer" in _kv.get("kundennummer", "")
        and _kn2.get("kundennummer") == ["Pers.-Nr. 782125149"], f"{_kn} {_kv} {_kn2}")
_tr = classify.stammdaten_treffer([{"id": 7, "name": "Arbeitgeber A"}, {"id": 8, "name": "Arbeitgeber B"}],
                                  {7: {"kundennummer": ["782125149"]}, 8: {"kundennummer": ["66130593B017"]}}.get,
                                  "Lohnabrechnung Pers.-Nr. 782125149 SV-Nr 66130593B017", _eg)
r.check("Vorsuche: Personalnummer findet den Arbeitgeber, eine gespeicherte SV-Nummer zählt nicht",
        [c["id"] for c, _ in _tr] == [7], str(_tr))
r.check("Prompt: Kennnummer umfasst Personal-/Vertragsnummer, nicht SV-Nr/Steuer-ID",
        "Personal-" in classify.ABSENDER_ANWEISUNG and "Sozialversicherungsnummer" in classify.ABSENDER_ANWEISUNG)

# ---- Prüf-Befunde: Teilstück, Dublette, Sammeldokument, erfundener OCR-Text (nur markieren).
r.check("Teilstück: „Seite 2 von 7“ bei einer Seite, nicht bei vollständigen Dokumenten",
        classify.teilstueck("… Seite 2 von 7 …", 1) and classify.teilstueck("Seite 1/2", 2) is None
        and classify.teilstueck("Seite 1 von 1", 1) is None and classify.teilstueck("ohne Angabe", 1) is None)
_t1 = "Rechnung 12.03.2025 Betrag 1.234,56 Nr 4711123 Summe 99,00 fällig 30.03.2025"
r.check("Dublette: fast gleiche Zahlen und gleiche Seitenzahl; andere Beträge oder Seiten nicht",
        classify.dublette(_t1, 1, [{"id": 9, "title": "Alt", "content": _t1 + " x", "page_count": 1}]) == "wie Dokument 9 (Alt)"
        and classify.dublette(_t1, 1, [{"id": 9, "content": _t1, "page_count": 2}]) is None
        and classify.dublette(_t1, 1, [{"id": 9, "content": "Rechnung 01.01.2024 5,00 7,00 8,00 9,00 1234567", "page_count": 1}]) is None)
r.check("Sammeldokument: ab drei anderen Korrespondenten mit Kennung",
        classify.sammeldokument([({"id": i, "name": f"F{i}"}, ["IBAN"]) for i in (1, 2, 3)])
        and classify.sammeldokument([({"id": i, "name": f"F{i}"}, ["IBAN"]) for i in (1, 2, 3)], ausser=3) is None)
r.check("OCR-Verdacht: fremde Schrift und Modell-Kommentar ja, deutscher Text und leere Seite nein",
        classify.ocr_seite_verdaechtig("1. 2017年1月1日，公司与上海浦东发展银行股份有限公司签订了") == "überwiegend fremde Schrift"
        and classify.ocr_seite_verdaechtig("The Ground Truth image displays a single line") == "Modell-Kommentar statt Seitentext"
        and classify.ocr_seite_verdaechtig("Sehr geehrter Herr Muster, anbei die Rechnung.") is None
        and classify.ocr_seite_verdaechtig("") is None)
_pb = _lauf([_ok], text=_gut + " Seite 2 von 7", dry=False)
r.check("Verdrahtung: Teilstück landet in „Prüfen“ (Tag KI-unsicher, PRÜFEN-Zeile)",
        "teilstueck" in (classify.TRACE.get("pruefen") or {})
        and "PRÜFEN 5" in Path(os.environ["CLASSIFY_LOG"]).read_text(encoding="utf-8"), str(classify.TRACE.get("pruefen")))

# ---- Teile aus dem Aufteilen (2026-10-14): Paperless kopiert Titel, Korrespondent, Typ,
# Datum, Tags (auch den Marker) und alle Feldwerte des Ausgangsdokuments in jeden Teil.
r.check("Teil: PDF-Editor und Aufteilen erkannt, andere Dateien nicht",
        classify.teildokument_von("1205_edit_3.pdf") == 1205 and classify.teildokument_von("1164_2-4.pdf") == 1164
        and classify.teildokument_von("Gescannt_20261014-1511.pdf") is None and classify.teildokument_von(None) is None
        and classify.teildokument_von("Rechnung_1205_edit_3.pdf") is None)
r.check("Teil: Dateiname geht nicht in den Prompt (die KI nahm die ID als Kennung)",
        classify.dateiname_fuer_prompt("1205_edit_2.pdf") == "—" and classify.dateiname_fuer_prompt("a.pdf") == "a.pdf")
_td = tempfile.mkdtemp()
r.check("Teil: Erbe offen, solange paperlaiss selbst nie lief",
        classify.erbe_offen({"id": 5, "original_file_name": "1205_edit_3.pdf"}, _td)
        and not classify.erbe_offen({"id": 5, "original_file_name": "scan.pdf"}, _td))
Path(_td, "5.json").write_text("{}", encoding="utf-8")
r.check("Teil: mit eigenem Trace gilt der Bestand wieder", not classify.erbe_offen({"id": 5, "original_file_name": "1205_edit_3.pdf"}, _td))


def _teil_lauf(trace_da=False, **kw):
    _alt_td = classify.TRACE_DIR
    classify.TRACE_DIR = tempfile.mkdtemp()
    if trace_da:
        Path(classify.TRACE_DIR, "5.json").write_text("{}", encoding="utf-8")
    try:
        return _lauf([{**_ok, "correspondent": "Reifen Muster GmbH"}], dry=False, datei="1205_edit_3.pdf",
                     titel="Versicherung Muster AG – Kaufvertrag 5031907", korr=177, typ=2,
                     korrespondenten=[{"id": 177, "name": "Versicherung Muster AG"}, {"id": 18, "name": "Reifen Muster GmbH"}],
                     felder=[{"id": 4, "name": "Fahrzeug", "data_type": "string"}],
                     feldwerte=[{"field": 4, "value": "Musterauto X1"}],
                     tags=[50], alle_tags=[{"id": 50, "name": "ai-processed"}], **kw)
    finally:
        classify.TRACE_DIR = _alt_td


_t = _teil_lauf()
_p = (_t.get("patch") or [{}])[0]
r.check("Teil beim Import: geerbter Marker überspringt den Lauf nicht", len(_t["chat"]) == 1, str(len(_t["chat"])))
r.check("Teil: kein geerbter Feldwert, Titel, Korrespondent oder Dateiname im Prompt",
        _t["chat"] and not any(x in _t["chat"][0] for x in ("Musterauto", "Versicherung Muster", "Kaufvertrag", "1205_edit")),
        (_t["chat"] or [""])[0][:400])
r.check("Teil: geerbter Feldwert wird nicht zurückgeschrieben",
        "Musterauto X1" not in str(_p.get("custom_fields")), str(_p.get("custom_fields")))
r.check("Teil: Typ und Titel aus dem eigenen Lauf", _p.get("document_type") == 1 and "Reifen Muster" in str(_p.get("title")), str(_p))
_k = _teil_lauf(source="knopf", force=True)
r.check("Teil beim KI-Knopf: ohne eigenen Lauf ebenso ohne Erbe",
        _k["chat"] and "Musterauto" not in _k["chat"][0] and "Versicherung Muster" not in _k["chat"][0])
_s = _teil_lauf(trace_da=True)
r.check("Teil mit eigenem Lauf: Marker überspringt wie bei jedem Dokument", _s["chat"] == [], str(len(_s["chat"])))
_v = _teil_lauf(trace_da=True, source="knopf", force=True)
r.check("Teil mit eigenem Lauf: KI-Knopf sieht den Bestand", _v["chat"] and "Musterauto" in _v["chat"][0])

# ---- Unbelegte Altwerte (2026-10-14): eine Kennung im Bestand, die nicht im Text steht, bestätigte
# sich beim KI-Knopf selbst (Titel und Feld trugen die ID des Ausgangsdokuments, „Rechnung 1205“).
_sg = classify.text_schluessel(_gut)
r.check("Beleg: Kennung im Text ja, fremde nein",
        classify.im_text_belegt("4711", _sg) and not classify.im_text_belegt("1205", _sg))
r.check("Beleg: ein Lesefehler je acht Zeichen gilt noch als belegt (OCR „J“ → „9“)",
        classify.im_text_belegt("WDD2470121J074035", classify.text_schluessel("FIN: WDD 24701219074035 x"))
        and not classify.im_text_belegt("WDD2470121J074035", classify.text_schluessel("FIN: WDD 99999999999999 x")))
r.check("Beleg: nur Werte mit mindestens drei Ziffern sind Kennungen",
        classify.ist_kennung("S-475TC") and not classify.ist_kennung("VW Polo") and not classify.ist_kennung("C 18"))
r.check("Titel: unbelegte Kennung fällt weg, belegte bleibt",
        classify.titel_ohne_unbelegtes("Rechnung 1205", _gut) == "Rechnung"
        and classify.titel_ohne_unbelegtes("Rechnung 4711", _gut) == "Rechnung 4711")
_uf = [{"id": 1, "name": "Rechnungsnummer", "data_type": "string"}, {"id": 2, "name": "Fahrzeug", "data_type": "string"},
       {"id": 3, "name": "Betrag", "data_type": "monetary"}, {"id": 4, "name": "Kilometerstand", "data_type": "integer"}]
r.check("Beleg: Beträge und Wörter werden nicht geprüft, Ganzzahlen schon",
        classify.unbelegte_werte(_uf, {1: "1205", 2: "VW Polo", 3: "EUR11.50", 4: 82000}, {1, 2, 3, 4}, _gut) == {1: "1205", 4: 82000})


def _beleg_lauf(nummer):
    return _lauf([{**_ok, "fields": {"Rechnungsnummer": "BEHALTEN", "Fahrzeug": "BEHALTEN", "Betrag": "BEHALTEN"}}],
                 dry=False, source="knopf", force=True, titel=f"X – Rechnung {nummer}", korr=7,
                 korrespondenten=[{"id": 7, "name": "X"}], felder=_uf[:3],
                 feldwerte=[{"field": 1, "value": nummer}, {"field": 2, "value": "VW Polo"}, {"field": 3, "value": "EUR11.50"}])


_ub = _beleg_lauf("1205")
_ubp = {c["field"]: c["value"] for c in (_ub.get("patch") or [{}])[0].get("custom_fields", [])}
_ubm = (_ub["chat"] or [""])[0]
r.check("KI-Knopf: unbelegte Kennung nicht mehr im Titel der Nachricht",
        "TITEL: Rechnung\n" in _ubm, _ubm[-700:-500])
r.check("KI-Knopf: unbelegte Kennung im Feld als „steht so NICHT im Text“ gekennzeichnet",
        "aktuell: 1205 " + classify.UNBELEGT_HINWEIS in _ubm)
r.check("KI-Knopf: bei BEHALTEN bleibt auch eine unbelegte Kennung (keine Daten verlieren)", _ubp.get(1) == "1205", str(_ubp))
r.check("KI-Knopf: Wort und Betrag bleiben bei BEHALTEN", _ubp.get(2) == "VW Polo" and _ubp.get(3) == "EUR11.50", str(_ubp))
_bb = _beleg_lauf("4711")
_bbp = {c["field"]: c["value"] for c in (_bb.get("patch") or [{}])[0].get("custom_fields", [])}
r.check("KI-Knopf: belegte Kennung ohne Kennzeichnung angeboten und behalten",
        "aktuell: 4711\n" in _bb["chat"][0] and "TITEL: Rechnung 4711" in _bb["chat"][0] and _bbp.get(1) == "4711", str(_bbp))

sys.exit(r.done())
