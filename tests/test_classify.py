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
          dry=True, source="", force=False, korr=None):
    aufrufe = {"ocr": 0, "chat": []}
    routen = {"/documents/5/": {"id": 5, "content": text, "title": "Beleg", "tags": [],
                                "custom_fields": list(feldwerte), "created": "2026-01-01", "document_type": typ,
                                "correspondent": korr},
              "/tags/": {"results": []}, "/document_types/": {"results": [{"id": 1, "name": "Rechnung"}, {"id": 2, "name": "Mahnung"}]},
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

    def patch_doc(did, patch):
        aufrufe.setdefault("patch", []).append(dict(patch))
        return True, ""
    tmp = tempfile.mkdtemp()
    alt = {n: getattr(classify, n) for n in ("get", "mistral_ocr", "mistral_chat", "TOK", "DRY", "FORCE_OCR",
                                            "send", "patch_doc", "SCRIPT_DIR", "SOURCE", "FORCE")}
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
    corr_hint_block = f"HINWEIS zum Korrespondenten '{cname}': {chint}\n\n" if chint else ""
    kand_block = (("MÖGLICHE KORRESPONDENTEN (bekannte Korrespondenten, die passen könnten — passt einer, übernimm seinen Namen exakt im Feld correspondent; sonst nenne den tatsächlichen Absender):" + _NL + kand_lines + _NL + _NL) if kand_lines else "")
    mail_block = ("HERKUNFT-KONTEXT (Nachricht/Anschreiben zu diesem Dokument — für Absender und Einordnung nutzen):" + _NL + mail_ktx + _NL + _NL) if mail_ktx else ""
    meta = (f"METADATEN:\n- Hinzugefügt am: {added}\n- Aktuelles Dokumentdatum (evtl. falsch): {created}\n"
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
r.check("Nachtragen: Herkunft je Feld vermerkt", _n["erfasst"].get("ustid") == _q and "telefon" not in _n["erfasst"])
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
r.check("Verdrahtung: Pass 1 läuft mit Schema (Dokumenttyp aus der Liste)",
        (_s.get("schemas") or [None])[0] and "Rechnung" in _s["schemas"][0]["properties"]["document_type"]["enum"])
r.check("Verdrahtung: Treffer steht mit Begründung in der Nachricht an Pass 1",
        "Beispiel Software" in _s["chat"][0] and "gefunden: USt-ID ATU99988777" in _s["chat"][0])
r.check("Verdrahtung: Trockenlauf zeigt die Stammdaten, schreibt sie nicht",
        (classify.TRACE.get("stammdaten") or {}).get("geschrieben") == {"iban": "AT48 3200 0000 1234 5864"}
        and classify.TRACE["stammdaten"].get("trocken") is True, str(classify.TRACE.get("stammdaten")))
_o = _lauf([_ok], text=_gut + " Absender: Nord Autoteile, Musterstadt",
           korrespondenten=[{"id": 7, "name": "Beispiel Software"}, {"id": 8, "name": "Nord Autoteile GmbH"}])
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
r.check("Schema Pass 1: Dokumenttyp nur aus der Liste oder null, Felder und Absender vorgegeben",
        _s1["properties"]["document_type"]["enum"] == ["Brief", "Rechnung", None]
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
r.check("Schema Pass 1: Auswahlliste ohne Doppelte, Dokumenttyp Pflicht",
        all(len(x["properties"]["document_type"]["enum"]) == len(set(map(str, x["properties"]["document_type"]["enum"])))
            and "document_type" in x["required"] for x in _sch))
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
# Echter Lauf: Pass 1 erkennt „Anna Berger“, Pass 2 wählt „Anna Zeller“ → nicht zuordnen, neu anlegen.
_sp = _lauf([{**_ok, "correspondent": "Anna Berger"}, {"match": "Anna Zeller"}], dry=False,
            korrespondenten=[{"id": 192, "name": "Anna Zeller"}])
_sp_korr = [p.get("correspondent") for p in _sp.get("patch", [])]
r.check("Pass-2-Sperre im Lauf: die KI-Wahl „Anna Zeller“ wird verworfen, der Beleg geht nicht an 192",
        192 not in _sp_korr and (classify.TRACE.get("correspondent") or {}).get("pass2", {}).get("sperre", {}).get("zugelassen") is False,
        f"{_sp_korr} {(classify.TRACE.get('correspondent') or {}).get('pass2', {}).get('sperre')}")

sys.exit(r.done())
