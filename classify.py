#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
paperlaiss — grounded Dokumenten-Klassifizierer für Paperless-ngx (ersetzt paperless-ai).

Läuft als Paperless POST_CONSUME_SCRIPT (oder manuell/per Panel). Mandantenunabhängig:
alle Feld-/Tag-Referenzen werden per NAME gegen die Paperless-API aufgelöst — keine
hartkodierten IDs, keine Secrets im Code (Token/Key kommen aus ENV bzw. der Config).

Features:
  - Korrespondent-Feedback-Loop (Token-Match + Pass-2-LLM-Auflösung, verhindert Dubletten)
  - OCR-Rescue via Mistral-OCR bei schwachem/Müll-Text (+ needs_ocr aus Pass 1)
  - Custom-Field-Voll-Steuerung (Wert / null=leeren / "BEHALTEN"), typgerecht
  - Dokumentdatum-Prüfung (echtes Ausstellungsdatum statt referenzierter Daten)
  - Self-Repair-Loop (Ping-Pong mit dem Paperless-Fehler bis der PATCH sitzt)
  - Trace + Live-Marke fürs Panel

Bewusst NICHT enthalten: Vertrags-/Geräte-Verknüpfung, owner-/Rechte-Setzen
(macht der Paperless-Konsumpfad / post-consume.sh), Steuer-Automatik, Personen-Routing.

Secrets NUR aus ENV/Config: PAPERLESS_TOKEN, MISTRAL_KEY (bzw. config api_key_text/_ocr).

Env-Schalter:
  DOCUMENT_ID / CLASSIFY_DOC   Doc-ID (Post-Consume setzt DOCUMENT_ID)
  CLASSIFY_DRY=1               nur ausgeben, nichts schreiben
  CLASSIFY_FORCE=1             auch schon-klassifizierte (Marker-Tag bzw. Trace-Marke) neu machen
  CLASSIFY_WIE_IMPORT=1        für Messungen (eval.py --wie-import): Titel, Korrespondent, Typ, Datum und Felder
                               des Dokuments ausblenden, als käme es gerade an — sonst stünde der korrigierte
                               Wert als „bisheriger Korrespondent“ im Prompt und die Messung belegte nichts
  CLASSIFY_FORCE_OCR=1         Mistral-OCR erzwingen (+ content immer ersetzen)
  CLASSIFY_NO_OCR=1            OCR komplett aus (günstiger Bestandslauf)
  CLASSIFY_HINWEIS=<text>      Freitext des Nutzers, wenn der Anstoss ihn schon gelesen hat
  CLASSIFY_SOURCE=knopf|manual|mail|bulk  Herkunft des Laufs (Trace/Log) — entscheidet auch, ob ein
                               schon gesetzter Dokumenttyp ersetzt werden darf: knopf/manual/mail ja, leer
                               (Import) nur ohne CLASSIFY_FORCE, bulk und Handaufrufe mit CLASSIFY_FORCE nein.
                               `mail` = Nachlauf eines Mail-Imports, der den Mail-Kontext erst nach dem
                               Import setzen kann und deshalb mit CLASSIFY_FORCE nachklassifiziert
  CLASSIFY_DUMP_DEFAULTS=1     Default-Prompt/Config als JSON ausgeben (fürs Panel)
  CLASSIFY_PROMPT_VORSCHAU=1   fertig eingesetzten Pass-1-Prompt als JSON ausgeben (fürs Panel)
  CLASSIFY_DUMP_CONFIG=1       wirksame Config (Datei + Vorgaben, ohne Schlüssel) als JSON (fürs Panel)
  CLASSIFY_STAMMDATEN=<id>     Stammdaten-Vorschläge für einen Korrespondenten aus seinen Dokumenten als JSON
                               (KI-Knopf im Korrespondenten-Dialog; schreibt nichts). CLASSIFY_STAMMDATEN_DOKS=
                               1,2,3 begrenzt auf die Dokumente, die der Nutzer sehen darf
"""
import os, sys, json, re, unicodedata, urllib.request, urllib.error, urllib.parse, difflib, datetime, base64, traceback, tempfile, subprocess

BASE = os.environ.get("PAPERLESS_API", "http://localhost:8000/api")
TOK = os.environ.get("PAPERLESS_TOKEN", "")
MISTRAL_URL = "https://api.mistral.ai/v1/chat/completions"
MISTRAL_OCR = "https://api.mistral.ai/v1/ocr"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.environ.get("CLASSIFY_LOG", os.path.join(SCRIPT_DIR, "classify.log"))
CONFIG = os.environ.get("CLASSIFY_CONFIG", os.path.join(SCRIPT_DIR, "classify-config.json"))

DRY = os.environ.get("CLASSIFY_DRY") == "1"
FORCE = os.environ.get("CLASSIFY_FORCE") == "1"
FORCE_OCR = os.environ.get("CLASSIFY_FORCE_OCR") == "1"
NO_OCR = os.environ.get("CLASSIFY_NO_OCR") == "1"
SOURCE = os.environ.get("CLASSIFY_SOURCE", "")

# --- Config (vom Panel schreibbar, mit Defaults) ---
CFG = {
    "enabled": True,
    "model": "mistral-small-latest",
    "ocr_model": "mistral-ocr-latest",
    "ocr_enabled": True,
    "ocr_always": False,
    "ocr_min_len": 300,
    "temperature": 0.1,
    "content_max_len": 10000,          # Zeichen Dokumenttext an die KI, gesamt (Anfang + Ende)
    "content_end_len": 1000,           # davon am Ende des Dokuments (Summe, Fälligkeit)
    # Defaults:
    "tagging_enabled": False,          # KI vergibt KEINE inhaltlichen Tags (Firmen-DMS: Tags sind manuelle Status/Richtung)
    "marker_tag": "ai-processed",      # gesetzt nach Klassifizierung + Skip-Signal; leer = Marke im Trace (T-15)
    "unsicher_tag": "",                # optional: Flag-Tag bei Unsicherheit / KI-Tag-Vorschlag
    # Optional tag for a broken scan: blank pages, pages missing ("page 2 of 3" on a one-page document),
    # invented OCR text. Empty = such findings get the unsicher_tag like any other (T-10).
    "kaputt_tag": "",
    # Write the reason of a finding as a note on the document (prefix "paperlaiss: "), once per text — so
    # nobody has to open the trace to see why a document is flagged (T-9 item 7, T-10).
    "pruef_notiz": False,
    # Accounts that only upload (a scanner, a mail fetch): the real owner is set later. For their documents
    # "we" are all own names of `eigene_kennungen`, not the upload account (T-10: a scan account made the
    # owner of the scan a correspondent).
    "technische_konten": [],
    # Document types issued by the EMPLOYER. On them a health insurance fund or collecting agency named on
    # the form is never the correspondent (T-10: 21 payslips filed under the health insurer).
    "arbeitgeber_typen": ["Lohnabrechnung", "Gehaltsabrechnung", "Lohnsteuerbescheinigung",
                          "Meldebescheinigung zur Sozialversicherung", "Arbeitsbescheinigung"],
    # Fields the model never fills on those types: a payslip has no contract or invoice number, the reference
    # numbers in its header belong to the payroll (T-11: 37 payslips with such a "contract number").
    "arbeitgeber_ohne_felder": ["Vertragsnummer", "Rechnungsnummer", "Aktenzeichen"],
    # Tags that exclude others: [{"tag": "Vorsorge", "ohne": ["Versicherungen"], "ausser_text": ["Unfall"]}] —
    # with "tag" set, the tags in "ohne" are not given, unless one of the "ausser_text" patterns (regular
    # expressions, case-insensitive) is in the text (T-11: life insurances also got "Versicherungen").
    "tag_ausschluss": [],
    # Names of people whose documents do not belong here ("Erika Muster"): a document that names one of them
    # and none of our own persons is flagged for checking (T-12: a stack scan of one person held the tax
    # notices and payslips of a former partner). Per account: konten[<username>]["fremde_namen"].
    "fremde_namen": [],
    # Types whose date is the LAST day of the billing month when the document has no date of issue (a payslip
    # names only "Abrechnungsmonat Juni 2023" or "Monat/Jahr 8 / 99"). Decided in code from the text, not
    # left to the model: it proposed the first day in 43 of 67 payslips, and the month of a correction
    # ("Rückrechnung März 2022") instead of the billing month (T-14). Empty = off.
    "monatsletzter_typen": [],
    # Never a NEW correspondent (T-15): a role or function ("Arbeitgeber", "Personalabteilung" — built-in list
    # ALLERWELTSNAMEN, extended here by words or whole names), a placeholder, or fewer letters/digits than
    # `korrespondent_min_zeichen` ("PA"). Then no correspondent and a note to check.
    "allerweltsnamen": [],
    "korrespondent_min_zeichen": 3,
    "einzugsstellen_muster": r"\b(?:AOK|BKK|IKK|DAK|BARMER|HEK|hkk|KKH|\w*Knappschaft|\w*krankenkasse|Ersatzkasse|"
                             r"Gesundheitskasse|\w*GKK|ÖGK|Einzugsstelle)\b",   # case-insensitive
    "summary_field": "",               # optional: longtext-Feld für adaptive Zusammenfassung
    "mail_context_field": "",          # optional: Herkunft-Kontext (Mail-/Chat-Anschreiben) fürs Prompt
    "mail_from_field": "",             # optional: Absender-Mail → Korrespondent-Domain-Match
    "manual_fields": [],               # Custom-Field-Namen, die die KI NIE anfasst (rein manuell gepflegt, z.B. Bezahlt-Am)
    "reserved_tags": [],               # Namen, die die KI NIE vergibt + die beim Writeback erhalten bleiben (Status/Quelle/Marker)
    "system_prompt": "",               # leer = DEFAULT_PROMPT
    # Beispielpaare für den Korrespondent-Abgleich (Pass 2), z.B.
    #   [["Mustrmann GmbH", "Mustermann"], ["ACME Vers", "ACME"]]
    # Few-Shot-Beispiele tragen bei OCR-Fehlern mehr als jede Beschreibung — "Mustrmann"
    # → "Mustermann" ist ein Muster, das man zeigen, nicht erklären kann. Sie gehören in die
    # Config und nicht in den Code, weil es echte Namen der jeweiligen Installation sind.
    "korrespondent_beispiele": [],
    # Pfad zu einem Skript, das NACH dem Writeback laeuft — die Naht fuer alles, was zu einer
    # einzelnen Installation gehoert und nicht in einen mandantenneutralen Klassifizierer:
    # Verknuepfungen in ein Fremdsystem, Rechte, hauseigene Sonderregeln. Es bekommt JSON auf
    # stdin und darf scheitern, ohne den Lauf mitzureissen.
    "nachbearbeitung": "",
    # Stammdaten des Absenders (USt-ID, IBAN, Mail, Telefon, Adresse, Kundennummer), die Pass 1
    # im Dokument findet, werden beim zugeordneten Korrespondenten nachgetragen — nur in LEERE
    # Felder, nie überschreibend, mit Herkunft (`erfasst`).
    "stammdaten_erfassen": True,
    # Titel aus dem Muster „Korrespondent – Dokumentart Kennung“ (PO 2026-09-27). Überschrieben wird
    # wie beim Dokumenttyp: beim Import, beim KI-Knopf und im Panel, nie beim Bestands-Durchlauf.
    "titel_setzen": True,
    # Komplett weiße Seiten beim Import entfernen — liest nicht classify.py, sondern das Pre-Consume-
    # Skript deploy/vorab/leerseiten.py aus derselben Config. Hier steht der Schlüssel, damit das
    # Panel ihn zeigt und speichert.
    "leerseiten_entfernen": True,
    # Kennungen der eigenen Firma. Sie stehen auf fast jedem eingehenden Dokument (Empfänger-
    # block, Lastschrift) und dürfen nie einem Absender zugeschlagen werden; eine Mail von einer
    # eigenen Domain ist eine Weiterleitung und ordnet nichts zu.
    "eigene_kennungen": {"ustid": [], "iban": [], "domains": [], "email": [], "namen": [], "telefon": []},
    # Wie Pass 1 das Gegenüber bestimmt, wenn eigene Namen gesetzt sind — der Satz nach
    # „… das sind WIR.“. Leer = die eingebaute Regel, geschrieben für eine Firma (Kunden,
    # Ausgangsrechnung, Lohnabrechnung). Ein Haushalt braucht andere Beispiele (eigener Brief,
    # Lebenslauf, Vollmacht zwischen Mitgliedern) — deshalb einstellbar statt fest.
    "eigene_regel": "",
    "tag_descriptions": {},            # merged über TAG_DESC (nur relevant wenn tagging_enabled)
    "type_descriptions": {},           # {"Typname": "wann dieser Typ gilt"} — steht im Prompt unter den Typen
    # Document types we write ourselves: there one of our own persons may be the correspondent. For any
    # other type an own person as correspondent is marked for checking (T-9).
    "eigene_typen": ["Bewerbung", "Lebenslauf", "Anschreiben", "Brief", "Kündigung", "Antrag", "Widerspruch",
                     "Vollmacht", "Erklärung", "Notiz"],
    # Document types the "collective document" check skips: they list many counterparts by nature (T-9).
    "sammeldokument_ausser_typen": ["Kontoauszug", "Kreditkartenabrechnung"],
    "kennungen_je_konto": False,       # an: „wir" = Besitzer des Dokuments (Haushalt mit eigenen Konten)
    "konten": {},                      # {"benutzername": {iban, email, domains, ustid, telefon, namen}, "*": gemeinsam}
    "api_key_text": "",                # leer = ENV MISTRAL_KEY
    "api_key_ocr": "",
}
# Fehler beim Laden werden gesammelt und weiter unten protokolliert — hier oben gibt es
# log() noch nicht. Eine kaputte Config darf NICHT still zu Standardwerten fuehren: dann
# faellt der installationsspezifische Prompt weg, manual_fields ist leer, und der Lauf sieht
# aeusserlich normal aus, waehrend er gegen die falsche Taxonomie arbeitet.
# Welche Schlüssel der Klassifizierer kennt — festgehalten VOR dem Einlesen der Datei. Die Panel-
# Ausgabe (CLASSIFY_DUMP_CONFIG) zeigt nur diese: ein veralteter Schlüssel in einer alten Datei
# (z. B. redo_tag aus der Zeit des Tag-Auslösers) soll nicht als einstellbar erscheinen.
_BEKANNT = set(CFG)
_CFG_FEHLER = None
try:
    CFG.update(json.load(open(CONFIG)))
except FileNotFoundError:
    pass                      # keine Config = Standardwerte, das ist der vorgesehene Fall
except Exception as _e:
    _CFG_FEHLER = f"{CONFIG} nicht lesbar ({_e!r}) — es gelten die Standardwerte!"

MODEL = CFG["model"]
OCR_MODEL = CFG["ocr_model"]
_ENV_KEY = os.environ.get("MISTRAL_KEY", "")
KEY_TEXT = CFG.get("api_key_text") or _ENV_KEY
KEY_OCR = CFG.get("api_key_ocr") or _ENV_KEY

# Optionale Panel-Stores (Korrespondent-Hinweise/Aliase/E-Mail-Domains) — fehlen = leer
_STORE_FEHLER = []


def _load_json(name, default):
    """Einen Store laden. Fehlt die Datei, ist das normal — ist sie KAPUTT, ist es ein Befund.

    Ohne die Unterscheidung verschwindet ein gepflegter Korrespondent-Store bei einem einzigen
    Tippfehler lautlos, und die Klassifizierung laeuft ohne Grounding weiter.
    """
    pfad = os.path.join(SCRIPT_DIR, name)
    try:
        v = json.load(open(pfad))
    except FileNotFoundError:
        return default
    except Exception as e:
        _STORE_FEHLER.append(f"{name} nicht lesbar ({e!r}) — wird ignoriert")
        return default
    if not isinstance(v, type(default)):
        _STORE_FEHLER.append(f"{name} hat den falschen Aufbau ({type(v).__name__}) — wird ignoriert")
        return default
    return v
# Korrespondent-Metadaten-Store (im Panel gepflegt), an Paperless-Korrespondenten per ID gebunden:
#   {"<paperless_id>": {email, domains, telefon, adresse, kundennummer, ustid, kontext,
#                        aliase, quelle, extern_id}}
# `ustid` hiess bis 2026-09-21 `uid`. Umbenannt, weil `UID` in vCard (RFC 6350 §6.7.6) der
# globale Datensatzschluessel ist, hier aber die Umsatzsteuer-Identifikationsnummer gemeint
# war — eine stille Kollision, sobald je ein Adressbuch angebunden wird. Alte Stores werden
# beim Lesen weiter verstanden.
CORR_META = _load_json("correspondents.json", {})
# Gemeldet wird weiter unten, wenn log() existiert. Bis 2026-09-27 stand hier ein log()-Aufruf VOR der
# Definition: eine unlesbare Store-Datei (etwa root-eigen nach einem Lauf als root) endete in einem
# NameError — Exit 1, und Paperless 3 meldet damit den ganzen Import als gescheitert.


# Stammdaten-Felder mit mehreren Werten (seit 2026-09-27 als Liste gespeichert; ältere Einträge
# haben einen Einzelwert oder eine Kommaliste — beides wird weiter gelesen).
LISTENFELDER = ("aliase", "email", "domains", "kundennummer", "ustid", "iban", "telefon")


def werte(m, feld):
    """Die Werte eines Stammdaten-Felds als Liste — aus Liste, Einzelwert oder Kommaliste."""
    v = (m or {}).get(feld)
    if feld == "ustid" and not v:
        v = (m or {}).get("uid")                   # Altname vor 2026-09-21
    teile = v if isinstance(v, (list, tuple)) else re.split(r"[,;\n]", str(v or ""))
    return [str(t).strip() for t in teile if str(t).strip()]


def norm_telefon(v):
    """Telefonnummer bereinigt, ohne Annahme über das Land: international bleibt international, national
    bleibt national (PO 2026-09-27: Deutschland und Österreich kommen beide vor — „0“ → „+49“ wäre falsch).

    „+49 (0) 30 123 45“ und „0049 30 12345“ → „+493012345“; „030 12345“ → „03012345“. Buchstaben,
    Leerzeichen, / - . ( ) fallen weg; eine nach der Landesvorwahl stehen gebliebene 0 („+43 0662 …“)
    bei AT/DE/CH ebenso. Unter 6 Ziffern: „“ (keine Nummer). Verglichen wird über telefon_kern()."""
    s = re.sub(r"\(\s*0\s*\)", "", str(v or ""))
    erstes = re.search(r"[+\d]", s)                  # „Tel. +43 …“: das + vor der ersten Ziffer zählt
    plus = bool(erstes and erstes.group() == "+")
    s = re.sub(r"\D", "", s)
    if plus:
        s = "+" + s
    elif s.startswith("00"):
        s = "+" + s[2:]
    s = re.sub(r"^\+(43|49|41)0(?=\d)", r"+\1", s)
    return s if len(re.sub(r"\D", "", s)) >= 6 else ""


# Landesvorwahlen mit 1 und 2 Ziffern (ITU E.164); alle anderen haben 3.
_LAND_1 = {"1", "7"}
_LAND_2 = {"20", "27", "30", "31", "32", "33", "34", "36", "39", "40", "41", "43", "44", "45", "46", "47", "48", "49",
           "51", "52", "53", "54", "55", "56", "57", "58", "60", "61", "62", "63", "64", "65", "66", "81", "82",
           "84", "86", "90", "91", "92", "93", "94", "95", "98"}


def telefon_kern(v):
    """Die Nummer ohne Landesvorwahl und ohne führende 0 — gleich für „+43 662 12345“ und „0662 12345“.
    So findet die Suche eine Nummer in beiden Schreibweisen, ohne das Land raten zu müssen."""
    n = norm_telefon(v)
    if n.startswith("+"):
        z = n[1:]
        cc = z[:1] if z[:1] in _LAND_1 else z[:2] if z[:2] in _LAND_2 else z[:3]
        return z[len(cc):]
    return n.lstrip("0")


def telefon_gleich(a, b):
    """Dieselbe Nummer? Zwei internationale müssen ganz gleich sein (+43 662 … ist nicht +49 662 …);
    sonst entscheidet der Kern — „0662 12345“ und „+43 662 12345“ sind gleich. Kern ab 7 Ziffern, damit
    eine kurze Durchwahl nicht zufällig in einer fremden Nummer steckt."""
    a, b = norm_telefon(a), norm_telefon(b)
    if not a or not b:
        return False
    if a.startswith("+") and b.startswith("+"):
        return a == b
    ka = telefon_kern(a)
    return len(ka) >= 7 and ka == telefon_kern(b)


# Kandidaten für Telefonnummern im Text: optional + oder 00, dann Ziffern mit üblichen Trennern.
TELEFON_IM_TEXT = re.compile(r"(?<![\w+])(?:\+|00)?\(?\d[\d \t/().\-]{5,22}\d(?!\w)")


def cmeta(cid):
    m = CORR_META.get(str(cid))
    return m if isinstance(m, dict) else {}


def cfull_hint(c):  # Kontext + harte Kennungen (Kundennr/UID) fürs KI-Grounding
    m = cmeta(c["id"]); parts = []
    if m.get("kontext"):
        parts.append(str(m["kontext"]).strip())
    if werte(m, "kundennummer"):
        parts.append("Kundennr " + ", ".join(werte(m, "kundennummer")))
    if werte(m, "ustid"):                       # uid = Altname vor 2026-09-21
        parts.append("UID " + ", ".join(werte(m, "ustid")))
    return "; ".join(p for p in parts if p)


def calias(c):
    return ", ".join(werte(cmeta(c["id"]), "aliase"))


# ---- Stammdaten: Mail-Zuordnung, Nachtragen, eigene Kennungen --------------------------------
# Freemail-Domains ordnen nie über die Domain zu (sonst gehörte jede gmail-Adresse demselben
# Korrespondenten) — dort zählt nur die volle Adresse.
FREEMAIL = {"gmail.com", "googlemail.com", "gmx.at", "gmx.de", "gmx.net", "gmx.ch", "web.de", "outlook.com",
            "outlook.de", "hotmail.com", "hotmail.de", "live.com", "live.at", "yahoo.com", "yahoo.de",
            "icloud.com", "me.com", "aon.at", "a1.net", "chello.at", "t-online.de", "posteo.de",
            "proton.me", "protonmail.com", "mail.de", "freenet.de"}


def _liste(v):
    teile = v if isinstance(v, (list, tuple)) else re.split(r"[,;\s]+", str(v or ""))
    return [str(t).strip().lower().strip("<>") for t in teile if str(t).strip()]


def norm_ustid(v):
    s = re.sub(r"[\s.\-/]", "", str(v or "")).upper()
    return s if re.fullmatch(r"[A-Z]{2}[0-9A-Z]{8,12}", s) else ""


# IBAN length per country (ISO 13616 registry), for the countries seen on documents here; others only get
# the check digits tested.
IBAN_LAENGE = {"AT": 20, "BE": 16, "CH": 21, "CZ": 24, "DE": 22, "DK": 18, "ES": 24, "FI": 18, "FR": 27, "GB": 22,
               "HR": 21, "HU": 28, "IE": 22, "IT": 27, "LI": 21, "LU": 20, "NL": 18, "NO": 15, "PL": 28, "PT": 25,
               "SE": 24, "SI": 19, "SK": 24}


def iban_gueltig(v):
    """Does `v` carry valid IBAN check digits (ISO 13616, mod 97 = 1) and the length of its country?
    The model builds "IBANs" from a bank code and an account number printed on old payslips; they fail
    here (T-11: 53 such field values on one installation)."""
    s = re.sub(r"\s", "", str(v or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s) or IBAN_LAENGE.get(s[:2], len(s)) != len(s):
        return False
    return int("".join(str(int(c, 36)) for c in s[4:] + s[:4])) % 97 == 1


def norm_iban(v, pruefen=True):
    """An IBAN without spaces, upper case; "" if it is none. With `pruefen` (default) the check digits must
    be valid too — an own IBAN in the config is taken as written (`pruefen=False`)."""
    s = re.sub(r"\s", "", str(v or "")).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return ""
    return s if not pruefen or iban_gueltig(s) else ""


def kennung_im_text(wert, text):
    """Is an identifier (a VAT ID "DE 113 822 785") printed in the text, spaces, dots and hyphens ignored?"""
    w = re.sub(r"[\s.\-/]", "", str(wert or "")).upper()
    return bool(w) and w in re.sub(r"[\s.\-/]", "", str(text or "")).upper()


def iban_im_text(iban, text):
    """Is the IBAN printed in the text (spaces, dots and hyphens ignored)?"""
    i = norm_iban(iban, pruefen=False)
    return bool(i) and i in re.sub(r"[\s.\-/]", "", str(text or "")).upper()


def norm_mail(v):
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", str(v or ""))
    return m.group(0).lower() if m else ""


def eigene_kennungen(cfg):
    e = cfg.get("eigene_kennungen") or {}
    return {"ustid": {norm_ustid(x) for x in _liste(e.get("ustid"))} - {""},
            "iban": {norm_iban(x, pruefen=False) for x in (e.get("iban") or []) if norm_iban(x, pruefen=False)},
            "domains": set(_liste(e.get("domains"))),
            # Volle Adressen — für eine eigene Freemail-Adresse, deren Domain man nicht sperren kann.
            "email": {norm_mail(x) for x in _liste(e.get("email"))} - {""},
            # Namen der eigenen Firma: stehen im Empfängerblock jedes Dokuments. Ein Korrespondent,
            # dessen Name sie enthält, ist bei der Namenssuche kein Kandidat. Gemessen 2026-09-27 an
            # 16 Dokumenten: markiert statt ausgeschlossen füllte er fast jede Kandidatenliste, und die
            # KI griff öfter daneben; ausgeschlossen traf sie so oft wie mit Pass 0.
            "namen": [set(ctoks(n)) for n in (e.get("namen") or []) if ctoks(n)],
            "telefon": {norm_telefon(x) for x in werte(e, "telefon")} - {""},
            # Nummern, die bei JEDEM Gegenüber gleich sind (Sozialversicherungsnummer, Steuer-ID) —
            # nie Kennnummer eines Korrespondenten, sonst „gewinnt“ der erste, der sie erfasst, jedes
            # spätere Dokument mit derselben Nummer (2026-10-11).
            "nummern": {norm_nummer(x) for x in werte(e, "nummern")} - {""}}


# Deutsche Renten-/Sozialversicherungsnummer: 8 Ziffern, Buchstabe, 3 Ziffern (66130593B017).
SV_NUMMER = re.compile(r"^\d{8}[A-Z]\d{3}$")


def norm_nummer(x):
    """Eine Kennnummer ohne Schreibweise: nur Buchstaben und Ziffern, groß."""
    return re.sub(r"[^0-9A-Za-z]", "", str(x or "")).upper()


def eigene_nummer(x, eigene):
    """Gehört die Nummer uns (eigene Liste oder Muster einer SV-Nummer)?"""
    n = norm_nummer(x)
    return bool(n) and (n in eigene.get("nummern", ()) or bool(SV_NUMMER.match(n)))


# A personnel number is how an employer files US, not a number of the employer: two employers' numbers
# were learned as "customer numbers" and pulled later payslips to the wrong correspondent (T-9).
PERSONAL_LABEL = re.compile(r"(?<![A-Za-zÄÖÜäöüß])(?:Persona\s?[lI1|]|Pers|P(?=\s*\.\s*-))\s*\.?\s*-?\s*(?:nummer|nr|no)\b\.?",
                            re.IGNORECASE)     # "P.-Nr." only with dot and hyphen: "P Nr" may be a postcode
_PERSONAL_WERT = re.compile(r"\s*[.:#]?\s*([0-9A-Za-z](?:[0-9A-Za-z]|[ ./-](?=\d))*)")
# A cost centre ("Kostenstelle 1160/Werkstatt") is the employer's account for the job, not a number under which
# the counterpart files us (T-13: learned as customer number from the payslip header, combined with others).
KOSTENSTELLE_LABEL = re.compile(r"(?<![A-Za-zÄÖÜäöüß])(?:Kostenstelle|Kst\s*\.)", re.IGNORECASE)


def personalnummer(wert, text="", als_teil=False, etikett=PERSONAL_LABEL):
    """Is `wert` a personnel number: labelled so in the value itself, or right after such a label in the text?

    With `als_teil`, a value that CONTAINS the personnel number as one of its parts counts too: payslips
    print a reference "611 7437/ 40/88901" (form, client, personnel number) in the header and
    "Pers.-Nr. 88901" further down, and the model took the reference as contract or invoice number (T-11).
    `etikett` is the label pattern (default: personnel number; KOSTENSTELLE_LABEL for a cost centre)."""
    if etikett.search(str(wert or "")):
        return True
    n = norm_nummer(wert)
    if not n:
        return False
    teile = {n}
    if als_teil:
        teile |= {t for t in map(norm_nummer, re.split(r"[\s/]+", str(wert))) if len(t) >= 4}
    text = str(text or "")
    for m in etikett.finditer(text):
        folgt = _PERSONAL_WERT.match(text[m.end():].split("\n", 1)[0])
        if folgt and norm_nummer(folgt.group(1)) in teile:
            return True
        # A header cell (nothing after the label in its cell): the value stands one row below.
        if not re.search(r"\d", _ZELLEN.split(text[m.end():].split("\n", 1)[0])[0]) \
                and teile & _spalte_darunter(text, m.start(), etikett):
            return True
    return False


_ZELLEN = re.compile(r"\s*\|\s*|\s{2,}|\t")


def _spalte_darunter(text, pos, etikett=PERSONAL_LABEL):
    """Numbers in the cell below the label at `pos`: a payslip header row ("Personal-Nr. | Geburtsdatum | …")
    with the values in the next non-empty row (T-10: personnel numbers were learned as customer numbers of
    the health insurer that is named on the same form)."""
    anfang = text.rfind("\n", 0, pos) + 1
    ende = text.find("\n", pos)
    if ende < 0:
        return set()
    kopf = [z for z in _ZELLEN.split(text[anfang:ende]) if z.strip()]
    spalte = next((i for i, z in enumerate(kopf) if etikett.search(z)), None)
    folgende = (z for z in text[ende + 1:].split("\n")[:3] if z.strip() and not set(z.strip()) <= set("|-: "))
    zeile = next(folgende, None)
    if spalte is None or zeile is None:
        return set()
    zellen = [z for z in _ZELLEN.split(zeile) if z.strip()]
    if spalte >= len(zellen):
        return set()
    return {norm_nummer(w) for w in zellen[spalte].split() if norm_nummer(w)}



def _roh_liste(v):
    """Einträge einer Config-Liste wie geschrieben (eine Zeichenkette zählt als ein Eintrag)."""
    return [str(x).strip() for x in (v if isinstance(v, (list, tuple)) else [v]) if x is not None and str(x).strip()]


CFG_LAUF = CFG   # Config dieses Laufs: bei kennungen_je_konto mit den Kennungen des Dokument-Besitzers


def konto_cfg(cfg, owner_id, benutzer=None):
    """Die Config für ein Dokument: bei `kennungen_je_konto` sind „wir" nur der Besitzer.

    Haushalt mit eigenen Konten (PO 2026-10-11): jede Person klassifiziert für sich; die anderen
    sind ein Gegenüber wie jedes andere — mit einer gemeinsamen Liste konnte bei Daniels Dokumenten
    weder Melli noch Martin Korrespondent werden. Name und Mail kommen aus dem Paperless-Konto
    (`benutzer` oder GET /users/<id>/), IBAN & Co. aus `konten[<benutzername>]`, Gemeinsames
    (etwa das Postfach eines Mail-Abrufs) aus `konten["*"]`. Ohne Schalter, ohne Besitzer oder
    ohne lesbares Konto bleibt die gemeinsame `eigene_kennungen` (Firma: alle für die Firma)."""
    if not cfg.get("kennungen_je_konto") or not owner_id:
        return cfg
    try:
        u = benutzer if benutzer is not None else get(f"/users/{owner_id}/")
    except Exception:
        u = None
    if not u or not u.get("username"):
        return cfg
    if u["username"] in (cfg.get("technische_konten") or ()):
        # An upload account owns the document only until the real owner is set (T-10).
        return {**cfg, "_konto": u["username"] + " (technisch: alle eigenen Namen)"}
    konten = cfg.get("konten") or {}
    eigen, alle = konten.get(u["username"]) or {}, konten.get("*") or {}
    name = f"{u.get('first_name') or ''} {u.get('last_name') or ''}".strip()
    e = {}
    for feld in ("namen", "email", "iban", "ustid", "domains", "telefon", "nummern"):
        e[feld] = list(dict.fromkeys(
            ([name] if feld == "namen" and name else []) + ([u["email"]] if feld == "email" and u.get("email") else [])
            + _roh_liste(eigen.get(feld)) + _roh_liste(alle.get(feld))))
    if not e["namen"]:
        return cfg
    fremde = _roh_liste(eigen.get("fremde_namen")) + _roh_liste(alle.get("fremde_namen"))
    return {**cfg, "eigene_kennungen": e, "_konto": u["username"],
            **({"fremde_namen": list(dict.fromkeys(fremde))} if fremde else {}),
            **({"_konto_tags": _roh_liste(eigen.get("tags"))} if _roh_liste(eigen.get("tags")) else {})}


def konto_tag_ids(cfg_lauf, tagid_by_norm):
    """Tag IDs every document of this account gets (`konten.<user>.tags`, T-15), whatever the model says.

    Paperless workflows cannot filter by owner; a household that tags everything of one person (for sharing
    or a view) had to tag uploads from the web by hand. Tags that do not exist are left out (no new tag)."""
    return [tagid_by_norm[norm(n)] for n in cfg_lauf.get("_konto_tags") or () if norm(n) in tagid_by_norm]

def _domain_passt(dom, domains):
    return any(dom == d or dom.endswith("." + d) for d in domains)


def mail_zuordnung(corrs, meta, mail_from, eigene):
    """Korrespondent über die Absender-Mail: (korrespondent oder None, Grund).

    Volle Adresse vor Domain; Freemail nur über die volle Adresse; eine eigene Domain ist eine
    Weiterleitung und ordnet nichts zu; passen mehrere, entscheidet die Mail nicht."""
    addr = norm_mail(mail_from)
    if not addr:
        return None, "keine Absender-Mail"
    dom = addr.split("@")[1]
    if _domain_passt(dom, eigene["domains"]) or addr in eigene["email"]:
        return None, f"eigene Adresse ({addr}) — Weiterleitung, ordnet nichts zu"
    treffer = [c for c in corrs if addr in _liste(meta(c["id"]).get("email"))]
    if not treffer and dom not in FREEMAIL:
        treffer = [c for c in corrs if _domain_passt(dom, _liste(meta(c["id"]).get("domains")))]
    if len(treffer) == 1:
        return treffer[0], f"Absender-Mail ({addr})"
    if treffer:
        return None, "Mail passt zu mehreren: " + ", ".join(c["name"] for c in treffer[:5])
    return None, "Mail/Domain in keinen Stammdaten"


def stammdaten_treffer(corrs, meta, text, eigene):
    """Die Stammdaten ALLER Korrespondenten im Dokumenttext suchen: [(korrespondent, [Gründe])].

    Nur harte Kennungen (USt-ID, IBAN, Mail, Domain, Kundennummer), keine Namen — ein Name
    steht auch im Empfängerblock oder in einer Erwähnung. Eigene Kennungen zählen nie. Die
    Treffer sind Kandidaten für Pass 1, keine Zuordnung: entscheiden tut die KI."""
    klein = str(text or "").lower()
    kompakt = re.sub(r"[\s.\-/]", "", str(text or "")).upper()
    tel_im_text = {norm_telefon(t) for t in TELEFON_IM_TEXT.findall(str(text or ""))} - {""}
    aus = []
    for c in corrs:
        # Die eigene Firma ist nie ein Kandidat: ihre Kennungen (Telefon, Adresse, Kundennummer bei uns)
        # stehen im Briefkopf jeder eigenen Ausgangsrechnung. Fehlte eine davon in eigene_kennungen,
        # schlug die Vorsuche „wir“ als harten Treffer vor, und die KI nahm ihn — statt des Kunden
        # (2026-10-14, Seite Nacharbeit: jede eigene Rechnung bei der eigenen Firma). Wie namens_treffer.
        if any(n <= set(ctoks(c["name"])) for n in eigene.get("namen", ())):
            continue
        m = meta(c["id"])
        gruende = []
        for u in {norm_ustid(x) for x in werte(m, "ustid")} - {""}:
            if u not in eigene["ustid"] and u in kompakt:
                gruende.append(f"USt-ID {u}")
        for i in {norm_iban(x) for x in werte(m, "iban")} - {""}:
            if i not in eigene["iban"] and i in kompakt:
                gruende.append("IBAN")
        for t in {norm_telefon(x) for x in werte(m, "telefon")} - {""}:
            if (not any(telefon_gleich(t, x) for x in eigene.get("telefon", ()))
                    and any(telefon_gleich(t, x) for x in tel_im_text)):
                gruende.append(f"Telefon {t}")
        for e in _liste(m.get("email")):
            if (norm_mail(e) and e in klein and e not in eigene["email"]
                    and not _domain_passt(e.split("@")[1], eigene["domains"])):
                gruende.append(f"Mail {e}")
        for d in _liste(m.get("domains")):
            if (d and "." in d and d not in FREEMAIL and not _domain_passt(d, eigene["domains"])
                    and re.search(r"(?:@|www\.|//)" + re.escape(d) + r"(?![a-z0-9-])", klein)):
                gruende.append(f"Domain {d}")
        for k in werte(m, "kundennummer"):
            if eigene_nummer(k, eigene) or personalnummer(k, text):
                continue
            if len(re.sub(r"\W", "", k)) >= 5 and re.search(r"(?<![0-9A-Za-z])" + re.escape(k) + r"(?![0-9A-Za-z])", str(text or "")):
                gruende.append(f"Kundennummer {k}")
        if gruende:
            aus.append((c, list(dict.fromkeys(gruende))))
    return sorted(aus, key=lambda x: -len(x[1]))



# Ein Dateiname in einer Textzeile („Angebot.pdf", „Liste - Google Sheets.xlsx").
DATEINAME_IN_ZEILE = re.compile(r"\S\.(?:pdf|docx?|odt|rtf|txt|xlsx?|ods|pptx?|odp|jpe?g|png|heic|tiff?|eml|msg)\b",
                                re.IGNORECASE)

# Franking mark of the postal service in the address window: "DV 08.22 0,85 Deutsche Post", "0,85 Deutsche Post".
# It names who carried the letter, not who wrote it — four letters (licence fee, health insurer, pension
# fund) were filed under "Deutsche Post AG" (T-10). The price is what tells it from a sender line.
_FRANKIERUNG = re.compile(r"(?:\bDV\s?\d{2,4}(?:[.\s]\d{2})?\s+)?(?<![\d,.])\d[.,]?\d{2}\s+Deutsch\w*\s+Post\b(?!\s*AG\b)",
                          re.IGNORECASE)
FRANKIERVERMERK = "[Frankiervermerk]"


def ohne_frankierung(text):
    """The text with franking marks replaced by a neutral placeholder (for the search and the prompt)."""
    return _FRANKIERUNG.sub(FRANKIERVERMERK, str(text or ""))


def namens_treffer(corrs, alias, text, eigene_namen=()):
    """Korrespondenten, deren Name oder Alias im Text steht: [(korrespondent, [Grund])].

    Alle Wörter des Namens (ohne Rechtsform, ab 3 Zeichen) müssen im Briefkopf vorkommen (den
    ersten 1000 Zeichen): unten stehen Bankverbindung und Zahlungsdienste, deren Namen sonst jede
    Rechnung zur Rechnung der Bank machten (2026-09-27, Stichprobe). Schwächer als eine Kennung,
    deshalb nur Kandidat für Pass 1. Längere Namen zuerst: „Muster Autoteile" sagt mehr als „Muster"."""
    # Zeilen mit Bankdaten zählen nicht: „Bank: Raiffeisenbank …" nennt, wo gezahlt wird, nicht wer
    # schreibt — bei kurzen Dokumenten rutscht die Fusszeile sonst in den Briefkopf (2026-09-27).
    # Ebenso Zeilen mit einem Dateinamen: „Zeugenaussage - Google Docs.pdf" (Druckkopf des Browsers,
    # Signaturseite von Documenso) nennt das Werkzeug, mit dem das Dokument entstand, nicht wer es
    # ausstellt — eine Zeugenaussage landete so bei Google (2026-10-10).
    kopf = "\n".join(z for z in str(text or "")[:1000].splitlines()
                     if not re.search(r"\b(IBAN|BIC|SWIFT|Bank|Bankverbindung|Konto|Kto)\b", z, re.IGNORECASE)
                     and not DATEINAME_IN_ZEILE.search(z))
    woerter = set(ctoks(kopf))
    aus = []
    for c in corrs:
        if any(n <= set(ctoks(c["name"])) for n in eigene_namen):
            continue
        for nm in [c["name"]] + [a.strip() for a in str(alias(c) or "").split(",") if a.strip()]:
            t = [w for w in ctoks(nm) if len(w) >= 3]
            # Ein einzelnes kurzes Wort („Bank", „Privat") steht in fast jedem Text — als Kandidat
            # verführte es die KI (2026-09-27: Lohnzettel landete bei „Bank"). Einwortnamen erst ab 6 Zeichen.
            if len(t) == 1 and len(t[0]) < 6:
                continue
            if t and all(w in woerter for w in t):
                aus.append((len(t), c, [f"Name „{nm}“ im Briefkopf"]))
                break
    return [(c, g) for _, c, g in sorted(aus, key=lambda x: -x[0])]


def alias_treffer(name, corrs, alias):
    """The one correspondent whose alias is `name` (same tokens, legal form ignored), else None.
    Two correspondents with the same alias decide nothing."""
    t = " ".join(ctoks(name or ""))
    if not t:
        return None
    hits = [c for c in corrs if any(" ".join(ctoks(a)) == t for a in str(alias(c) or "").split(",") if a.strip())]
    return hits[0] if len(hits) == 1 else None


def mail_bestaetigt(mail_from, corr_id, mail_corr, text, absender):
    """Gehört die Absender-Mail wirklich zum zugeordneten Korrespondenten? Nur dann wird sie
    nachgetragen. Ein Portal verschickt Dokumente vieler Firmen von derselben Adresse — ohne
    diese Prüfung landete die Portal-Domain bei der ersten Firma, und jede spätere Portal-Mail
    zeigte auf sie. Bestätigt heißt: kein anderer Korrespondent hat die Mail, und Adresse oder
    Domain stehen im Dokument (oder die KI nennt dieselbe Domain als Absender-Mail)."""
    addr = norm_mail(mail_from)
    if not addr or not corr_id or (mail_corr and mail_corr["id"] != corr_id):
        return False
    dom = addr.split("@")[1]
    klein = str(text or "").lower()
    ki = norm_mail((absender or {}).get("email") if isinstance(absender, dict) else "")
    return addr in klein or dom in klein or (ki and ki.split("@")[1] == dom)


# Listenfelder, an die die Erfassung einen weiteren Wert anhängen darf (PO 2026-09-27: „man kann doch
# hinzufügen?“). Nicht die USt-ID — eine Firma hat eine; eine zweite spricht für eine Fehlzuordnung.
ANHAENGBAR = {"iban", "email", "domains", "telefon", "kundennummer"}
MAX_WERTE = 10


def strassen(adresse):
    """Street and house number of an address, spelling folded ("Musterstr. 5" = "MUSTERSTRASSE 5" =
    "Musterstraße 5"); a postcode-and-town part has no street and gives nothing.

    The own address was learned as the address of eight correspondents (it is the addressee block on every
    letter) because "Musterstr. 5" and "Musterstraße 5" were different values (T-12)."""
    erg = set()
    for teil in re.split(r"[,;\n]", str(adresse or "")):
        t = re.sub(r"['’`]", "", teil.strip().lower().replace("ß", "ss"))
        m = re.search(r"([a-zäöü][a-zäöü.\- ]{2,}?)\s*(\d+\s*[a-z]?)\s*$", t)
        if not m:
            continue
        name = re.sub(r"(strasse|str\.?)$", "str", re.sub(r"[\s\-]+", "", m.group(1)).rstrip("."))
        erg.add(name.replace(".", "") + re.sub(r"\s+", "", m.group(2)))
    return erg


def gleicher_wert(feld, a, b):
    """Derselbe Wert in einem Stammdatenfeld, unabhängig von der Schreibweise."""
    if feld == "iban":
        return bool(norm_iban(a)) and norm_iban(a) == norm_iban(b)
    if feld == "ustid":
        return bool(norm_ustid(a)) and norm_ustid(a) == norm_ustid(b)
    if feld == "email":
        return bool(norm_mail(a)) and norm_mail(a) == norm_mail(b)
    if feld == "telefon":
        return telefon_gleich(a, b)
    if feld == "adresse":
        return bool(strassen(a) & strassen(b))
    k = lambda v: re.sub(r"^(www\.|@)|[\s.\-/]", "", str(v or "")).upper()
    return bool(k(a)) and k(a) == k(b)


# Kennungen, die genau einem Gegenüber gehören. Kundennummer (vergibt jeder Lieferant selbst),
# Adresse (Firmen im selben Haus) und Kontext können sich legitim wiederholen.
EINDEUTIG = {"iban", "ustid", "email", "domains", "telefon"}


# An IBAN or phone number printed on documents of this many different correspondents is most likely
# ours (own account, own phone), however it got into the master data: an own IBAN missing from
# eigene_kennungen was learned at a health insurer, and every payslip afterwards reported
# "belongs to <insurer>" (T-9). Customer numbers are excluded: every supplier assigns its own.
VERBREITUNG_FELDER = ("iban", "telefon")
VERBREITET_AB = 3


def verbreitung_suchtexte(feld, wert):
    """The spellings to search the archive for: an IBAN compact and in groups of four, a phone number as
    stored and as given. Phone numbers have more spellings than a substring search can cover."""
    if feld == "iban":
        i = norm_iban(wert)
        return [i, " ".join(i[k:k + 4] for k in range(0, len(i), 4))] if i else []
    if feld == "telefon":
        return list(dict.fromkeys(x for x in (norm_telefon(wert), str(wert or "").strip()) if len(x) >= 6))
    return []


def korrespondenten_mit(feld, wert, holen=None):
    """IDs of the correspondents whose documents contain the value (Paperless content search), or None
    if no search succeeded. `holen` = get (replaceable in tests)."""
    holen = holen or get
    ids, ok = set(), False
    for q in verbreitung_suchtexte(feld, wert):
        try:
            r = holen("/documents/?page_size=100&fields=id,correspondent&content__icontains="
                      + urllib.parse.quote(q))
        except Exception:
            continue
        if isinstance(r, dict) and isinstance(r.get("results"), list):
            ok = True
            ids |= {d.get("correspondent") for d in r["results"] if isinstance(d, dict) and d.get("correspondent")}
    return ids if ok else None


def stammdaten_fremd(corrs, meta, eigener_id):
    """fremd(feld, wert) → Name des ANDEREN Korrespondenten, der den Wert schon hat, sonst None."""
    def fremd(feld, w):
        if feld not in EINDEUTIG:
            return None
        for c in corrs:
            if c["id"] != eigener_id and any(gleicher_wert(feld, w, x) for x in werte(meta(c["id"]), feld)):
                return c["name"]
        return None
    return fremd



def ist_eigene_person(name, eigene):
    """Is the correspondent one of us (its name contains an own name)? As in stammdaten_treffer."""
    return any(n <= set(ctoks(name)) for n in (eigene or {}).get("namen", ()))


# Identifier fields that never go into the entry of an own person: they are OUR numbers, and from there
# they pulled other documents to us (T-11: an own entry with 10 numbers and 2 phone numbers).
EIGENE_PERSON_OHNE = ("iban", "ustid", "email", "domains", "telefon", "kundennummer")


def stammdaten_belegt(corrs, meta, eigener_id, eigene):
    """belegt(feld, wert) → why the value must not be learned at `eigener_id`, else None (T-11).

    - The value is in the entry of an own person: it is ours (own account number, own customer number at
      a supplier), not one of the counterpart's — any field.
    - A customer number already stored at another correspondent: it is that one's number for us (the
      employer's personnel number, our account number at the bank), printed on a third party's form. It
      was learned at four correspondents of one installation, each later pulling the others' documents.
    Unlike `fremd` this is no contradiction to report: the value is dropped silently."""
    def belegt(feld, w):
        for c in corrs:
            if c["id"] == eigener_id or not any(gleicher_wert(feld, w, x) for x in werte(meta(c["id"]), feld)):
                continue
            if ist_eigene_person(c["name"], eigene):
                return f"eigene Kennung (steht bei {c['name']})"
            if feld == "kundennummer":
                return f"schon bei {c['name']} gespeichert — dessen Nummer für uns, nicht die dieses Gegenübers"
        return None
    return belegt


def kennungs_teile(wert):
    """The parts of an identifier value that lists several ("A, B; C"), each at most 60 characters, no repeats.
    A comma inside a number ("12,50") is no separator: only a comma or semicolon followed by a space splits."""
    teile = (ohne_tabellenrest(x) for x in re.split(r"\s*[,;]\s+|\s*;\s*", str(wert or "")))
    return list(dict.fromkeys(t[:60] for t in teile if t))


def ohne_tabellenrest(wert):
    """Ein Wert ohne die Tabellen- und Aufzählungszeichen, die das OCR an den Rand setzt
    („| Häuser“, „| Fasanenweg 20a …“). Gilt für den Korrespondentennamen und die Stammdaten
    (2026-10-10: beide kamen so aus einer Tabelle)."""
    return str(wert or "").strip(" \t\n|·•-–—:;,")

def stammdaten_nachtragen(alt, absender, mail_from, eigene, quelle, anhaengen=False, fremd=None, kontext="",
                          text="", verbreitet=None, belegt=None, eigene_person=False):
    """Stammdaten eines Korrespondenten aus dem Dokument nachtragen.

    Rein: bekommt den alten Eintrag, gibt (neuer Eintrag, geschrieben, verworfen) zurück.
    Überschreibt nie. Ein leeres Feld wird gefüllt; an ein Listenfeld aus ANHAENGBAR wird ein
    neuer Wert angehängt, wenn `anhaengen` (die Zuordnung ist sicher: Pass 1 nannte den
    Korrespondenten exakt). Nie übernommen: eigene Kennungen, kaputte Formate und ein Wert, der
    schon einem anderen Korrespondenten gehört (`fremd`) — sonst zöge eine Fehlzuordnung jedes
    spätere Dokument mit derselben IBAN zum falschen. `erfasst` merkt sich die Herkunft, bei
    Listenfeldern je Wert ({wert: quelle}). Bis 2026-09-27 füllte die Erfassung nur leere Felder.

    `text` is the document text: a number printed as a personnel number is never stored as a customer
    number. `verbreitet(feld, wert)` counts the correspondents whose documents carry an IBAN or phone
    number (None = unknown); from VERBREITET_AB on it is most likely one of ours and is neither stored
    nor reported as "belongs to another" (T-9). `belegt(feld, wert)` (stammdaten_belegt) gives a reason not
    to learn a value that is ours or another's number for us; at an `eigene_person` no identifiers are
    stored at all (T-11)."""
    alt = dict(alt or {})
    neu, erfasst = dict(alt), dict(alt.get("erfasst") or {})
    geschrieben, verworfen = {}, {}
    ab = absender if isinstance(absender, dict) else {}
    wert = lambda k: "" if is_null(ab.get(k)) else ohne_tabellenrest(ab.get(k))

    def setze(feld, w):
        if not w or feld in geschrieben:
            return
        bisher = werte(alt, feld)
        if any(gleicher_wert(feld, w, x) for x in bisher):
            return                                              # schon da
        if eigene_person and feld in EIGENE_PERSON_OHNE:
            verworfen[feld] = "eigene Person — ihre Kennungen gehören in eigene_kennungen, nicht in die Stammdaten"
            return
        b = belegt(feld, w) if belegt else None
        if b:
            verworfen[feld] = b
            return
        n = verbreitet(feld, w) if verbreitet and feld in VERBREITUNG_FELDER else None
        if n is not None and n >= VERBREITET_AB:
            verworfen[feld] = f"steht auf Dokumenten von {n} Korrespondenten — wahrscheinlich eine eigene Kennung"
            return
        anderer = fremd(feld, w) if fremd else None
        if anderer:
            verworfen[feld] = f"gehört schon zu {anderer}"
            return
        if not bisher:
            geschrieben[feld] = w
            neu[feld] = [w] if feld in LISTENFELDER else w       # Listenfelder als Liste speichern
            erfasst[feld] = {w: quelle} if feld in LISTENFELDER else quelle
            return
        if feld not in ANHAENGBAR:
            if feld == "ustid":
                verworfen[feld] = "andere USt-ID schon gespeichert — Zuordnung prüfen"
            return
        if not anhaengen:
            verworfen[feld] = "nicht angehängt — Zuordnung nur über einen ähnlichen Namen"
            return
        if len(bisher) >= MAX_WERTE:
            verworfen[feld] = f"schon {MAX_WERTE} Werte"
            return
        geschrieben[feld] = w
        neu[feld] = list(bisher) + [w]
        e = erfasst.get(feld)
        if isinstance(e, str):                                  # alter Vermerk galt den bisherigen Werten
            e = {x: e for x in bisher}
        erfasst[feld] = {**(e if isinstance(e, dict) else {}), w: quelle}

    roh = wert("ustid")
    if roh:
        u = norm_ustid(roh)
        if not u:
            verworfen["ustid"] = "kein USt-ID-Format"
        elif u in eigene["ustid"]:
            verworfen["ustid"] = "eigene USt-ID"
        elif text and not kennung_im_text(u, text):
            # The model copied it from a candidate in the prompt (T-14: every letter of an employer got the
            # VAT ID of its group parent, which the letters do not print, and a "belongs to" finding).
            verworfen["ustid"] = "steht so nicht im Text"
        else:
            setze("ustid", u)
    roh = wert("iban")
    if roh:
        i = norm_iban(roh)
        if not norm_iban(roh, pruefen=False):
            verworfen["iban"] = "kein IBAN-Format"
        elif not i:
            verworfen["iban"] = "Prüfziffer falsch (ISO 13616) — keine IBAN"
        elif text and not iban_im_text(i, text):
            verworfen["iban"] = "steht so nicht im Text (aus Bankleitzahl und Konto zusammengesetzt?)"
        elif i in eigene["iban"]:
            verworfen["iban"] = "eigene IBAN"
        else:
            setze("iban", " ".join(i[k:k + 4] for k in range(0, len(i), 4)))
    for m in (norm_mail(mail_from), norm_mail(wert("email"))):
        if not m:
            continue
        dom = m.split("@")[1]
        if _domain_passt(dom, eigene["domains"]) or m in eigene["email"]:
            verworfen["email"] = f"eigene Adresse ({m})"
            continue
        setze("email", m)
        if dom not in FREEMAIL:
            setze("domains", dom)
    roh = wert("telefon")[:60]
    if roh:
        t = norm_telefon(roh)
        if not t:
            verworfen["telefon"] = "keine Telefonnummer"
        elif any(telefon_gleich(t, x) for x in eigene.get("telefon", ())):
            verworfen["telefon"] = "eigene Telefonnummer"
        else:
            setze("telefon", t)
    setze("adresse", wert("adresse")[:300])
    # The model sometimes returns several numbers as one value ("007/200/73702/1, 73702/1, 1160/Werkstatt"); each
    # part is checked and stored on its own (T-13: four such lists stood at one employer).
    for kn in kennungs_teile(wert("kundennummer")):
        if eigene_nummer(kn, eigene):
            verworfen["kundennummer"] = "eigene Nummer (gilt bei jedem Gegenüber)"
        elif personalnummer(kn, text):
            verworfen["kundennummer"] = "Personalnummer — keine Kennnummer des Gegenübers"
        elif personalnummer(kn, text, als_teil=True, etikett=KOSTENSTELLE_LABEL):
            verworfen["kundennummer"] = "Kostenstelle — keine Kennnummer des Gegenübers"
        else:
            setze("kundennummer", kn)
    # Was das Gegenüber ist („Kfz-Werkstatt in Salzburg“) — nur in einen leeren Kontext. Bis 2026-09-27
    # verlangten die Prompts diesen Satz schon, aber niemand speicherte ihn.
    setze("kontext", "" if is_null(kontext) else str(kontext).strip()[:300])
    if geschrieben:
        neu["erfasst"] = erfasst
    return neu, geschrieben, verworfen


def sperre_oeffnen(pfad):
    """Die Sperrdatei für flock öffnen — nur lesend (flock braucht kein Schreibrecht), angelegt mit 0666.

    Panel und Klassifizierer (uid 1000) sperren dieselbe Datei (das Panel lief bis 2026-10-11 als root,
    ältere Installationen können also noch so laufen). Bis 2026-09-27 öffneten beide
    mit "a": legte das Panel die Datei zuerst an (root, 0644), scheiterte danach jede Stammdaten-
    Erfassung des Klassifizierers mit PermissionError — still, nur als Zeile im Log."""
    return os.fdopen(os.open(pfad, os.O_RDONLY | os.O_CREAT, 0o666), "rb")


def stammdaten_schreiben(cid, aenderung):
    """correspondents.json unter Sperre neu lesen, ändern, atomar schreiben.

    Das Panel schreibt dieselbe Datei (Korrespondenten-Dialog), und mehrere Läufe können
    parallel laufen: ohne Sperre gewinnt, wer zuletzt schreibt, und die anderen Änderungen sind
    weg. Die Sperre ist flock auf einer Nachbardatei — sie gilt auch über Container hinweg,
    solange beide dasselbe Verzeichnis sehen. Eine kaputte Datei wird NICHT überschrieben."""
    import fcntl
    pfad = os.path.join(SCRIPT_DIR, "correspondents.json")
    with sperre_oeffnen(pfad + ".lock") as sperre:
        fcntl.flock(sperre, fcntl.LOCK_EX)
        try:
            store = json.load(open(pfad, encoding="utf-8"))
        except FileNotFoundError:
            store = {}
        if not isinstance(store, dict):
            raise ValueError("correspondents.json hat den falschen Aufbau — nicht überschrieben")
        neu, geschrieben, verworfen = aenderung(store.get(str(cid)))
        if geschrieben:
            store[str(cid)] = neu
            schreibe_json(pfad, store)
            CORR_META[str(cid)] = neu
        return geschrieben, verworfen


def log(m):
    try:
        with open(LOG, "a") as f:
            f.write(f"{datetime.datetime.now():%F %T} {'DRY ' if DRY else ''}{m}\n")
    except Exception as e:
        # Letzte Instanz: wenn nicht einmal das Log schreibbar ist, nach stderr —
        # das landet im post-consume-Log von Paperless und ist damit auffindbar.
        print(f"classify: Log nicht schreibbar ({e!r}): {m}", file=sys.stderr)


if _CFG_FEHLER:
    log(f"KONFIGURATION: {_CFG_FEHLER}")
    print(f"classify: {_CFG_FEHLER}", file=sys.stderr)
for _f in _STORE_FEHLER:
    log(f"STORE: {_f}")
    print(f"classify: STORE: {_f}", file=sys.stderr)

TRACE_DIR = os.path.join(os.path.dirname(LOG), "traces")
RUN_DIR = os.path.join(os.path.dirname(LOG), "running")
TRACE = {}


def schreibe_json(pfad, daten):
    """JSON atomar schreiben: erst in eine Nachbardatei, dann umbenennen.

    `json.dump(d, open(pfad, "w"))` kürzt die Zieldatei sofort auf null; bricht der Vorgang
    danach ab, steht dort eine halbe Datei. Bei einem Trace heisst das: die Panel-Ansicht
    zeigt kaputtes JSON statt des letzten brauchbaren Standes.

    Rechte und Besitzer bleiben: die Ersatzdatei übernimmt Modus und Besitzer der alten, eine
    neue Datei den Besitzer des Ordners. Bis 2026-09-27 gehörte sie dem, der gerade schrieb — ein
    Lauf als root machte den Korrespondenten-Store root-eigen (0600), und der Paperless-Worker
    konnte ihn danach nicht mehr lesen.
    """
    ordner = os.path.dirname(os.path.abspath(pfad)) or "."
    try:
        vorbild, bestand = os.stat(pfad), True
    except FileNotFoundError:
        vorbild, bestand = os.stat(ordner), False
    fd, tmp = tempfile.mkstemp(dir=ordner, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        if bestand:
            os.chmod(tmp, vorbild.st_mode & 0o777)
        try:
            os.chown(tmp, vorbild.st_uid, vorbild.st_gid)   # nur als root wirksam
        except PermissionError:
            pass
        os.replace(tmp, pfad)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_trace(did, extra=None):
    if DRY or not did:
        return
    try:
        os.makedirs(TRACE_DIR, exist_ok=True)
        t = dict(TRACE); t["id"] = did; t["ts"] = f"{datetime.datetime.now():%F %T}"
        if not t.get("klassifiziert"):
            # The mark of an earlier run stays when this one broke off (T-15: the trace is the marker).
            alt = klassifiziert_seit(did)
            if alt:
                t["klassifiziert"] = alt
        # ts in Ortszeit (lesbar), ts_utc eindeutig — die Nacharbeit im Panel vergleicht ihn mit der
        # Paperless-Historie (UTC); die Ortszeit des Containers ist nicht überall dieselbe.
        t["ts_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
        if extra:
            t.update(extra)
        schreibe_json(os.path.join(TRACE_DIR, f"{did}.json"), t)
    except Exception as e:
        # NICHT still verschlucken. Bis 2026-09-21 stand hier `pass` — auf einer Instanz
        # entstanden dadurch ueber zwei Monate keine Traces, ohne dass es jemandem auffiel.
        # Ein Trace ist Diagnose, kein Selbstzweck: faellt er aus, muss man es SEHEN.
        log(f"trace-fail {did}: {e!r}")


def klassifiziert_seit(did, trace_dir=None):
    """When paperlaiss last classified the document to the end (its trace mark), or None (T-15).

    With an empty `marker_tag` this mark replaces the marker tag: the skip signal of the automatic run
    lives in the trace, nobody sees a tag. Written only by a real run (never a dry run), kept by later
    runs that break off."""
    try:
        with open(os.path.join(trace_dir or TRACE_DIR, f"{did}.json"), encoding="utf-8") as f:
            v = json.load(f).get("klassifiziert")
        return v if isinstance(v, str) and v else None
    except (OSError, ValueError, AttributeError):
        return None


def schon_klassifiziert(cfg, marker_id, tag_ids_on, did, trace_dir=None):
    """The skip signal: the marker tag on the document, or — with an empty `marker_tag` — the trace mark."""
    if (cfg.get("marker_tag") or "").strip():
        return bool(marker_id) and marker_id in tag_ids_on
    return klassifiziert_seit(did, trace_dir) is not None


def wartet_auf_mail(doc, cfields, feldname):
    """Is the document a mail import whose context is still to come? (T-15)

    A mail poller uploads the attachment with the mail-context field attached EMPTY, sets the value
    afterwards and then classifies with CLASSIFY_SOURCE=mail. The automatic post-consume run in between
    would classify without the mail and learn from it — it waits. Until T-15 a mail poller blocked it with
    the marker tag, which no longer exists when the trace is the marker."""
    fid = resolve_field(cfields, feldname)
    return bool(fid) and any(c.get("field") == fid and c.get("value") in (None, "")
                             for c in (doc.get("custom_fields") or []))


def nachbearbeiten(did, patch, erfolg, lesbar):
    """Ein installationseigenes Skript nach dem Writeback aufrufen.

    Warum es das gibt: Ohne diese Naht muss jede Installation, die mehr braucht als
    Klassifizierung — eine Verknuepfung in ein Fremdsystem, eine hauseigene Regel — den
    Klassifizierer forken. Genau so sind vier auseinanderlaufende Staende desselben Codes
    entstanden. Mit der Naht bleibt der Kern ueberall gleich, und das Eigene liegt daneben.

    Das Skript bekommt auf stdin:
      {"doc_id": 915, "erfolg": true, "patch": {…}, "lesbar": {…}, "quelle": "knopf",
       "dry": false}
    Es laeuft mit denselben Umgebungsvariablen (PAPERLESS_TOKEN, PAPERLESS_API …), kann also
    selbst die API benutzen. Seine Ausgabe geht ins Log.

    Es darf scheitern: ein Fehler dort wird protokolliert, beendet aber NICHT den Lauf — die
    Klassifizierung ist zu diesem Zeitpunkt bereits geschrieben, und eine Zusatzaufgabe darf
    kein Dokument unklassifiziert zuruecklassen.
    """
    skript = (CFG.get("nachbearbeitung") or "").strip()
    if not skript or DRY:
        return
    if not os.path.exists(skript):
        log(f"nachbearbeitung-fehlt {did}: {skript} nicht gefunden")
        return
    eingabe = json.dumps({"doc_id": int(did), "erfolg": bool(erfolg), "patch": patch,
                          "lesbar": lesbar, "quelle": SOURCE or "auto",
                          "dry": DRY}, ensure_ascii=False)
    try:
        r = subprocess.run([sys.executable, skript], input=eingabe, text=True,
                           capture_output=True, timeout=120, env=os.environ.copy())
        ausgabe = ((r.stdout or "") + (r.stderr or "")).strip().replace("\n", " | ")[:300]
        if r.returncode == 0:
            if ausgabe:
                log(f"nachbearbeitung {did}: {ausgabe}")
        else:
            log(f"nachbearbeitung-fail {did} (exit {r.returncode}): {ausgabe}")
    except subprocess.TimeoutExpired:
        log(f"nachbearbeitung-timeout {did}: {skript} nach 120 s abgebrochen")
    except Exception as e:
        log(f"nachbearbeitung-fail {did}: {e!r}")


def mark_running(did, stage="Start"):
    if DRY or not did:
        return
    try:
        os.makedirs(RUN_DIR, exist_ok=True)
        p = os.path.join(RUN_DIR, f"{did}.json")
        since = json.load(open(p)).get("since") if os.path.exists(p) else f"{datetime.datetime.now():%F %T}"
        schreibe_json(p, {"id": did, "since": since, "stage": stage,
                          "src": "manuell" if (FORCE or FORCE_OCR) else "auto"})
    except Exception as e:
        # Wie beim Trace: ein stilles `pass` laesst die „laeuft gerade"-Anzeige monatelang
        # ausfallen, ohne dass es jemand bemerkt. Ein Lauf scheitert daran NICHT.
        log(f"running-fail {did}: {e!r}")


def unmark_running(did):
    try:
        if did:
            os.remove(os.path.join(RUN_DIR, f"{did}.json"))
    except FileNotFoundError:
        pass                      # nie markiert oder schon weg — kein Befund
    except Exception as e:
        log(f"unrunning-fail {did}: {e!r}")


def set_stage(did, s):
    TRACE["_stage"] = s
    mark_running(did, s)


# Paperless itself is overloaded at times (bulk scan of hundreds of pages, index rebuild): it answers 502/503/
# 504 for a minute (T-10). A read or an idempotent write is simply repeated. A POST creates something
# (correspondent, note): after 502/504 it may have gone through, so it is repeated only on 429/503, which
# say "not processed".
PAPERLESS_WIEDERHOLEN_BEI = {429, 502, 503, 504}
PAPERLESS_POST_WIEDERHOLEN_BEI = {429, 503}
PAPERLESS_WARTEN_S = (2, 5, 15, 30)


def _pause_aus(e, vorgabe):
    """Pause before the next attempt: the server's `Retry-After` (seconds, at most 120) wins."""
    nach = e.headers.get("Retry-After") if getattr(e, "headers", None) else None
    return min(120, int(nach)) if nach and str(nach).isdigit() else vorgabe


def mit_wiederholung(aufruf, codes, pausen, wer, netz=True):
    """Run `aufruf()`; on an HTTP status in `codes` or (with `netz`) a network error wait and try again, then
    give up. Other HTTP errors (400, 401, 404, 422) are passed on at once — waiting does not heal them."""
    for versuch in range(len(pausen) + 1):
        try:
            return aufruf()
        except urllib.error.HTTPError as e:
            if e.code not in codes or versuch == len(pausen):
                raise
            pause = _pause_aus(e, pausen[versuch])
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if not netz or versuch == len(pausen):
                raise
            pause = pausen[versuch]
        log(f"{wer}: Versuch {versuch + 1} gescheitert, neuer Versuch in {pause} s")
        __import__("time").sleep(pause)


def get(path, raw=False, warten=None):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Token {TOK}"})

    def lesen():
        r = urllib.request.urlopen(req, timeout=45)
        return r.read() if raw else json.load(r)
    return mit_wiederholung(lesen, PAPERLESS_WIEDERHOLEN_BEI, PAPERLESS_WARTEN_S if warten is None else warten,
                            "Paperless")


def send(path, data, method="PATCH", timeout=45, warten=None):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Authorization": f"Token {TOK}", "Content-Type": "application/json"}, method=method)
    codes = PAPERLESS_POST_WIEDERHOLEN_BEI if method == "POST" else PAPERLESS_WIEDERHOLEN_BEI
    # A write that timed out may still arrive — no blind repeat (patch_doc checks first, then sends once more).
    return mit_wiederholung(lambda: json.load(urllib.request.urlopen(req, timeout=timeout)), codes,
                            PAPERLESS_WARTEN_S if warten is None else warten, "Paperless", netz=False)


# Cache-Schlüssel für Mistrals Prompt-Caching (`prompt_cache_key`): zwischengespeicherte
# Präfix-Tokens kosten 10 % (https://docs.mistral.ai/studio-api/conversations/advanced/prompt-caching).
# Ein Schlüssel je System-Prompt —
# so trifft der Cache über Dokumente hinweg (gleicher System-Prompt) und innerhalb einer
# Unterhaltung (Pass 1 → OCR-Nachlauf → Pass 2 → Korrektur schicken denselben Anfang erneut).
CACHE_KEY = ""
# Nutzung je Aufruf (prompt/cached/completion) — fürs Trace, damit man sieht, ob der Cache trifft.
NUTZUNG = []


# Wiederholen bei Ratenbegrenzung und vorübergehenden Fehlern (2026-10-11): ein Probelauf mit drei
# gleichzeitigen Dokumenten bekam 94 von 203 Mal HTTP 429 — ohne Wiederholung blieb jedes davon
# unklassifiziert, genauso wie beim Hochladen vieler Dokumente auf einmal.
WIEDERHOLEN_BEI = {429, 500, 502, 503, 504}
# 2026-11-12 (T-10): Mistral answered 503 for about two minutes during a bulk scan; the four pauses up to
# 60 s (110 s in all) ran out and two documents stayed unclassified. With 120 s more the wait covers ~4 min.
WARTEN_S = (5, 15, 30, 60, 120)


def mistral_senden(req, timeout, warten=None):
    """Eine Mistral-Anfrage senden, bei 429/5xx und Netzfehlern mit wachsender Pause wiederholen.
    Ein `Retry-After` der Gegenseite geht vor (höchstens 120 s). Andere Fehler (400, 401, 422)
    werden sofort weitergereicht — sie heilen nicht durch Warten."""
    return mit_wiederholung(lambda: json.load(urllib.request.urlopen(req, timeout=timeout)), WIEDERHOLEN_BEI,
                            WARTEN_S if warten is None else warten, "Mistral")


def voruebergehend(e):
    """Is `e` a passing outage (overload, network) rather than a fault of this document?"""
    if isinstance(e, urllib.error.HTTPError):
        return e.code in WIEDERHOLEN_BEI
    return isinstance(e, (urllib.error.URLError, TimeoutError, ConnectionError))


def mistral_chat(messages, max_tokens=900, schema=None, name="antwort"):
    """Ein Chat-Aufruf mit JSON-Antwort. Mit `schema` erzwingt Mistral dessen Aufbau
    (`response_format: json_schema`, strict) — nicht nur „irgendein JSON" wie `json_object`."""
    rf = ({"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}
          if schema else {"type": "json_object"})
    body = {"model": MODEL, "temperature": CFG["temperature"], "max_tokens": max_tokens,
            "response_format": rf, "messages": messages}
    if CACHE_KEY:
        body["prompt_cache_key"] = CACHE_KEY
    req = urllib.request.Request(MISTRAL_URL, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY_TEXT}", "Content-Type": "application/json"})
    r = mistral_senden(req, 120)
    u = r.get("usage") or {}
    NUTZUNG.append({"name": name, "prompt": u.get("prompt_tokens"), "completion": u.get("completion_tokens"),
                    "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens")})
    raw = r["choices"][0]["message"]["content"]
    return json.loads(raw), raw


_NULLBAR = lambda t: {"type": [t, "null"]}


def pass1_schema(typen, feldnamen, mit_tags, mit_absender, mit_summary, mit_titel=False):
    """JSON-Schema der Pass-1-Antwort. Dokumenttyp als Auswahlliste (plus null), Felder als
    bekannte Schlüssel. `additionalProperties` bleibt offen: eigene Prompts verlangen teils
    weitere Schlüssel (summary_long, korrespondent_kontext), die sonst wegfielen. Ein gültiges
    Schema heisst nicht, dass die Werte stimmen — es garantiert den Aufbau.

    Der Dokumenttyp steht ZULETZT. Das Modell schreibt die Schlüssel in Schema-Reihenfolge; stand
    der Typ vorn, wollte es oft ein eigenes Wort („Bußgeldbescheid", „Meldebestätigung") — die
    Auswahlliste liess dann nur den ersten Eintrag mit passendem Anfang zu: Bewerbung, Mahnung.
    Gemessen 2026-09-27 an einem Bußgeldbescheid: Typ vorn 0 von 3 richtig, Typ hinten 3 von 3
    („Bescheid"), weil Zusammenfassung und Felder dann schon geschrieben sind."""
    wert = {"type": ["string", "number", "boolean", "null"]}
    props = {
        "correspondent": _NULLBAR("string"),
        "fields": {"type": "object", "properties": {f: wert for f in feldnamen}, "additionalProperties": True},
        "document_date": _NULLBAR("string"),
        "needs_ocr": {"type": "boolean"},
    }
    pflicht = ["correspondent", "fields", "needs_ocr"]      # document_type kommt unten dazu
    if mit_summary:
        props["summary"] = _NULLBAR("string")
    if mit_tags:
        props["tags"] = {"type": "array", "items": {"type": "string"}}
        props["new_tags"] = {"type": "array", "items": {"type": "string"}}
    if mit_absender:
        props["absender"] = {"type": "object", "additionalProperties": False, "properties": {
            k: _NULLBAR("string") for k in ("ustid", "iban", "email", "telefon", "adresse", "kundennummer")}}
        pflicht.append("absender")
        props["korrespondent_kontext"] = _NULLBAR("string")
        pflicht.append("korrespondent_kontext")
    if mit_titel:
        props["titel_kennung"] = _NULLBAR("string")
        pflicht.append("titel_kennung")
    # Frei vor der Auswahl (2026-10-10): wie das Dokument sich selbst nennt. Stand die Art nicht in der
    # Liste („Einverständniserklärung“), kippte die erzwungene Auswahl auf ein falsches Wort (Vollmacht),
    # obwohl die Zusammenfassung die Art richtig nannte.
    props["dokumentart"] = _NULLBAR("string")
    pflicht.append("dokumentart")
    # Ohne Auswahlliste (seit 2026-10-10): mit `enum` wählte Mistral bei einer Einverständniserklärung
    # 5 von 5 Mal „Vollmacht“, ohne Liste „Erklärung“ — die Beschränkung beim Erzeugen lenkte auf ein
    # falsches Wort. Die Typen stehen im Prompt; typ_zuordnen() bildet die Antwort auf sie ab.
    props["document_type"] = _NULLBAR("string")
    pflicht.insert(0, "document_type")
    return {"type": "object", "properties": props, "required": pflicht, "additionalProperties": True}


def gegenueber_schema():
    """Rückfrage, wenn Pass 1 uns selbst als Korrespondenten nennt: wer ist der Empfänger?"""
    return {"type": "object", "properties": {"empfaenger": _NULLBAR("string"), "adresse": _NULLBAR("string")},
            "required": ["empfaenger", "adresse"], "additionalProperties": False}


GEGENUEBER_FRAGE = (
    "Du hast {NAME} als correspondent genannt — das sind WIR. Steht unser Briefkopf oben, ist das ein Dokument "
    "VON uns an jemanden (Ausgangsrechnung, Angebot, Gutschrift, Kaufvertrag, Lieferschein): dann ist der "
    "correspondent der EMPFÄNGER aus dem Adressblock (Person oder Firma, ohne Anrede wie Herrn/Frau). "
    "Nur bei einem internen Dokument ohne externes Gegenüber (Lohnabrechnung, Überweisungsliste, interne "
    "Aufstellung) oder wenn kein Empfänger genannt ist (z. B. „Barverkauf“), antworte null. Antworte NUR JSON "
    "{{\"empfaenger\": <Name oder null>, \"adresse\": <Anschrift des Empfängers oder null>}}.")


AUSSTELLER_FRAGE = (
    "Du hast {NAME} als correspondent genannt. {GRUND} Wer hat das Dokument ausgestellt (Firma, Behörde, "
    "Arbeitgeber — Briefkopf, Stempel, Feld „Arbeitgeber“ bzw. „Name und Anschrift des Arbeitgebers“)? Antworte "
    "NUR JSON {{\"aussteller\": <Name ohne Anrede oder null>}}; null, wenn es im Dokument nicht erkennbar ist.")


def aussteller_schema():
    return {"type": "object", "properties": {"aussteller": _NULLBAR("string")}, "required": ["aussteller"],
            "additionalProperties": False}


def nicht_aussteller_grund(korrespondent, typ, cfg_lauf, cfg):
    """Why `korrespondent` cannot be the issuer: (finding key, reason for the model) or None.

    An own PERSON on a document we do not write ourselves (the addressee), or a health insurance fund /
    collecting agency on a document the employer issues (payslip, social insurance notice) — the form names
    it, it did not write it (T-10)."""
    if not korrespondent:
        return None
    if eigene_person_befund(korrespondent, typ, (cfg_lauf.get("eigene_kennungen") or {}).get("namen"),
                            cfg.get("eigene_typen") or []):
        return "eigene_person", "Das ist eine eigene Person (der Empfänger), nicht das Gegenüber."
    muster = cfg.get("einzugsstellen_muster")
    if muster and typ_in(typ, cfg.get("arbeitgeber_typen") or ()):
        try:
            if re.search(muster, str(korrespondent), re.IGNORECASE):
                return ("einzugsstelle", f"Das ist die Krankenkasse/Einzugsstelle, die das Formular nur angibt; "
                                         f"eine {typ} stellt der Arbeitgeber aus.")
        except re.error:
            pass
    return None


def ist_eigener_name(name, eigene_namen):
    """Enthält der Name einen eigenen Namen (Token-Teilmenge, wie bei der Vorsuche)?"""
    t = set(ctoks(name or ""))
    return bool(t) and any(n <= t for n in eigene_namen)


def pass2_schema(kandidaten):
    """Pass 2 darf nur einen der Kandidaten nennen — oder null."""
    return {"type": "object", "properties": {"match": {"type": ["string", "null"], "enum": list(kandidaten) + [None]}},
            "required": ["match"], "additionalProperties": False}


def text_kuerzen(text, gesamt, ende):
    """Den Dokumenttext auf `gesamt` Zeichen bringen: Anfang UND Ende behalten.

    Summe, Fälligkeit und Bankverbindung stehen oft am Schluss; nur den Anfang zu schicken
    verlor sie bei langen Dokumenten ganz (PO 2026-09-27: 9000 + 1000 Zeichen)."""
    text = str(text or "")
    if len(text) <= gesamt:
        return text
    ende = max(0, min(ende, gesamt // 2))
    kopf = gesamt - ende
    weg = len(text) - kopf - ende
    return (text[:kopf] + f"\n\n[… {weg} Zeichen ausgelassen …]\n\n" + (text[-ende:] if ende else "")).rstrip()



# Mistral-OCR erfindet auf leeren oder fast leeren Seiten Text — gemessen 2026-10-11: chinesische Sätze
# und Kommentare wie „The Ground Truth image displays a single, solid horizontal line …“. Erkannt wird
# das nur, korrigiert nicht (PO: markieren, nicht automatisieren) → Prüfen + KI-unsicher.
OCR_VERDACHT = []
_FREMDE_SCHRIFT = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\u0600-\u06ff]")
_MODELL_FLOSKEL = re.compile(r"ground truth|the image (shows|displays|contains)|as an ai\b|i cannot (read|see)", re.I)


def wiederholung(text, seiten=None):
    """A loop of the OCR model on a blank or nearly blank page (T-10, 2026-11-12): the same line again and
    again (`\\( \\therefore m = \\frac{3}{11} \\)` fifty times, „und die in der Zeitung im Fraktionischen …“
    twenty times). Returns (piece, count) or None.

    Only lines with a letter count — table rules („| --- |“) repeat in real documents. A real page has at
    most a few equal lines; here one line makes at least half of the page. A line that comes at most once
    per page of a multi-page document (`seiten`) is a page header, not a loop (T-11: a 13-page account
    statement with "Kontenanzeige-Druck" on every page)."""
    zeilen = [" ".join(z.split()) for z in str(text or "").splitlines() if re.search(r"[^\W\d_]", z)]
    if len(zeilen) >= 6:
        z, n = __import__("collections").Counter(zeilen).most_common(1)[0]
        if n >= 5 and n * 2 >= len(zeilen) and not ((seiten or 1) > 1 and n <= seiten):
            return z, n
    # Without line breaks: a long text made of a handful of words. A table repeats its words too (the
    # 13-page statement: 1365 words, 92 different, 218 lines) — so only without line structure or with a
    # vocabulary as small as a loop's.
    woerter = re.findall(r"[^\W\d_]{3,}", str(text or "").lower())
    if (len(woerter) >= 60 and len(set(woerter)) * 10 < len(woerter)
            and (len(zeilen) < 6 or len(set(woerter)) <= WIEDERHOLUNG_WORTSCHATZ)):
        return " ".join(woerter[:6]), len(woerter) // len(set(woerter))
    return None


WIEDERHOLUNG_WORTSCHATZ = 30


def ocr_seite_verdaechtig(text, seiten=None):
    """Grund, warum der OCR-Text einer Seite (oder eines Dokuments mit `seiten` Seiten) erfunden aussieht — oder None."""
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", str(text or ""))
    if _MODELL_FLOSKEL.search(t):
        return "Modell-Kommentar statt Seitentext"
    buchstaben = [c for c in t if c.isalpha()]
    if len(buchstaben) >= 10 and len(_FREMDE_SCHRIFT.findall(t)) / len(buchstaben) > 0.2:
        return "überwiegend fremde Schrift"
    w = wiederholung(t, seiten)
    if w:
        return f"Wiederholungsschleife („{w[0][:40]}“ {w[1]}×)"
    return None


def ocr_text_pruefen(text):
    """The OCR text as a whole: (usable text, [reason]). An invented text never replaces the document's text
    (T-10: three blank pages got 50× „m = 3/11“ as content, a payslip a Dada poem)."""
    grund = ocr_seite_verdaechtig(text)
    if grund:
        return "", [grund]
    return str(text or "").strip(), []

def mistral_ocr(did):
    pdf = get(f"/documents/{did}/download/", raw=True)  # Archiv = immer PDF (auch bei Bild-Originalen)
    b64 = base64.b64encode(pdf).decode()
    body = {"model": OCR_MODEL, "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}}
    req = urllib.request.Request(MISTRAL_OCR, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY_OCR}", "Content-Type": "application/json"})
    resp = mistral_senden(req, 180)
    seiten = [p.get("markdown", "") for p in resp.get("pages", [])]
    OCR_VERDACHT[:] = [(n, g) for n, g in ((i, ocr_seite_verdaechtig(t)) for i, t in enumerate(seiten, 1)) if g]
    # Invented pages are left out (T-10): until 0.4 they went into the document's text and replaced the
    # text Paperless had read. They stay visible as a finding (ocr_erfunden).
    erfunden = {n for n, _ in OCR_VERDACHT}
    return "\n\n".join(t for i, t in enumerate(seiten, 1) if i not in erfunden).strip()


def norm(s):
    s = unicodedata.normalize('NFKD', s or '').encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]', ' ', s).strip()


TOKENS = [' der ', 'die ', 'und ', 'fur', 'rechnung', 'datum', 'betrag', 'gmbh', 'fahrzeug',
          'kennzeichen', 'kunde', 'lieferung', 'auftrag', 'sehr', 'geehrt', 'herr', 'frau',
          'strasse', 'nummer', 'gultig', 'summe', 'netto', 'brutto', 'ust']
LEGAL = {"gmbh", "ag", "kg", "ohg", "mbh", "ug", "co", "kgaa", "se", "ev", "ltd", "limited",
         "llc", "inc", "sa", "srl", "sarl", "bv", "og", "gesmbh", "online", "group", "holding",
         "deutschland", "germany", "austria", "oesterreich", "international", "services", "service", "the", "und"}


def ctoks(s):
    return [w for w in norm(s).split() if w and w not in LEGAL]


# Regeln, nach denen ein Text als zu schwach gilt und per OCR neu gelesen wird. Einstellbar
# unter "ocr_regeln" in der Config; fehlende Schluessel nehmen diese Vorgaben.
OCR_REGELN_VORGABE = {
    "min_zeichen": None,              # None = ocr_min_len (aeltere Configs)
    "min_schluesselwoerter": 2,       # so viele Allerweltswoerter muessen vorkommen …
    # Wörtlich, MIT Leerzeichen: ' der ' soll „der" als Wort treffen, nicht „oder" oder „Kinder".
    # (PR #58 hatte sie per strip() gekürzt — die Regel wurde dadurch unbemerkt lockerer.)
    "schluesselwoerter": list(TOKENS),
    "max_zeichen_je_wort": 40,        # … und auf so viele Zeichen mindestens ein echtes Wort
    "max_muell_anteil": 0.25,         # Anteil von Zeichen, die in keinem Text vorkommen (Zeichensalat)
    # Nach Pass 1 (die KI hat den Text gesehen):
    "nach_ki_meldung": True,          # KI meldet needs_ocr → OCR nachholen, Pass 1 wiederholen
    "wenn_kein_typ": False,           # kein Dokumenttyp erkannt → ebenso
    "wenn_kein_korrespondent": False, # kein Korrespondent erkannt → ebenso
}
_NORMALE_ZEICHEN = set(".,:;-–/()[]€$%&+'\"!?#*_@=<>|§°")


def ocr_regeln(cfg):
    r = {**OCR_REGELN_VORGABE, **(cfg.get("ocr_regeln") or {})}
    if r["min_zeichen"] is None:
        r["min_zeichen"] = cfg.get("ocr_min_len", 300)
    return r


def ocr_gruende(content, cfg):
    """Warum der Text vor Pass 1 per OCR neu gelesen werden soll — leer heisst: gar nicht.

    Die Gruende statt eines Ja/Nein, weil genau das im Trace stehen muss: „Text zu kurz"
    fuehrt zu einer anderen Frage als „60 % Zeichensalat".
    """
    r = ocr_regeln(cfg)
    c = (content or "").strip()
    if len(c) < r["min_zeichen"]:
        return [f"zu kurz ({len(c)} < {r['min_zeichen']} Zeichen)"]
    gruende = []
    cl = c.lower()
    treffer = sum(1 for t in r["schluesselwoerter"] if t.strip() and t.lower() in cl)
    if treffer < r["min_schluesselwoerter"]:
        gruende.append(f"zu wenig bekannte Wörter ({treffer} < {r['min_schluesselwoerter']})")
    woerter = re.findall(r"[a-zA-ZäöüÄÖÜß]{3,}", c)
    if len(woerter) < len(c) / r["max_zeichen_je_wort"]:
        gruende.append(f"zu wenig Wörter ({len(woerter)} auf {len(c)} Zeichen)")
    sichtbar = [z for z in c if not z.isspace()]
    muell = sum(1 for z in sichtbar if not z.isalnum() and z not in _NORMALE_ZEICHEN)
    if sichtbar and muell / len(sichtbar) > r["max_muell_anteil"]:
        gruende.append(f"Zeichensalat ({muell * 100 // len(sichtbar)} % Sonderzeichen)")
    return gruende


def ocr_nachhol_gruende(prop, cfg):
    """Warum nach Pass 1 doch noch OCR laufen soll: die KI meldet Muell, oder eine Regel greift."""
    r = ocr_regeln(cfg)
    gruende = []
    if r["nach_ki_meldung"] and prop.get("needs_ocr"):
        gruende.append("KI meldet unlesbaren Text")
    if r["wenn_kein_typ"] and not prop.get("document_type"):
        gruende.append("kein Dokumenttyp erkannt")
    if r["wenn_kein_korrespondent"] and not prop.get("correspondent"):
        gruende.append("kein Korrespondent erkannt")
    return gruende


def bad_ocr(content):
    return bool(ocr_gruende(content, CFG))


# Themen-Tag-Beschreibungen (nur relevant wenn tagging_enabled). Primär via Config gepflegt.
TAG_DESC = {}

DEFAULT_PROMPT = (
    "Du klassifizierst ein Dokument für ein Dokumentenarchiv. "
    "Antworte AUSSCHLIESSLICH als gültiges JSON. Deutsch mit echten Umlauten.\n"
    "DOKUMENTTYPEN (wähle GENAU EINEN oder null): {TYPES}\n\n"
    "{TAGBLOCK}"
    "Korrespondent = ABSENDER/Aussteller (Firma/Behörde/Person), NICHT der Archiv-Inhaber selbst. Kurzer gängiger Markenname.\n"
    "JSON-KEYS: document_type (String|null), correspondent (String|null), "
    "korrespondent_kontext (1 kurzer Satz: was ist dieser Absender / welche Dokumente kommen von ihm — bei NEUEM Korrespondent und bei einem bekannten ohne [Kontext], sonst null), "
    "needs_ocr (true wenn Text unbrauchbar/Müll), "
    "fields (Objekt, siehe VERFÜGBARE FELDER). "
    "Ein Feld nur füllen, wenn das Dokument den Wert konkret hergibt — nichts hineinraten; im Zweifel null lassen."
)  # document_date regelt DATUM_ANWEISUNG, die immer angehängt wird.



def dokument_datum(prop):
    """Das Dokumentdatum aus der Pass-1-Antwort als 'YYYY-MM-DD', sonst None.

    Seit dem JSON-Schema (#71) steht document_date auf der obersten Ebene der Antwort; gelesen
    wurde es bis 2026-10-10 aber aus fields — dort stand es nie, und kein Lauf hat je ein Datum
    geschrieben (gemessen: 18 von 18 Vorschlägen verloren). fields bleibt als Rückfall für eigene
    Prompts, die es dort ablegen."""
    for quelle in (prop, prop.get("fields") or {}):
        if not isinstance(quelle, dict):
            continue
        wert = str(quelle.get("document_date") or "").strip()
        if not re.match(r"\d{4}-\d{2}-\d{2}$", wert):
            continue
        try:
            tag = datetime.date.fromisoformat(wert)
        except ValueError:
            continue
        if 1950 <= tag.year <= 2035:
            return wert
    return None


_MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
           "November", "Dezember"]


def datum_belegt(iso, text):
    """Steht das Datum 'YYYY-MM-DD' in irgendeiner gängigen Schreibweise im Text?

    Die KI erfand bei einem Teilstück ohne jedes Datum („Seite 2 von 7“) den 01.07.2026 (2026-10-11).
    Ein Datum, das nicht im Dokument steht, wird deshalb nicht geschrieben. Lieber das alte Datum
    stehen lassen als ein erfundenes setzen. Leerraum zählt nicht („16. 12. 2010“ = „16.12.2010“)."""
    try:
        j, m, t = iso.split("-"); mi, ti = int(m), int(t)
    except (ValueError, AttributeError):
        return False
    roh = re.sub(r"\s+", "", str(text or "")).lower()
    jj = j[2:]
    formen = {f"{t}.{m}.{j}", f"{ti}.{mi}.{j}", f"{t}.{m}.{jj}", f"{ti}.{mi}.{jj}", f"{t}.{mi}.{j}", f"{ti}.{m}.{j}",
              iso, f"{j}{m}{t}", f"{t}/{m}/{j}", f"{ti}/{mi}/{j}", f"{mi}/{ti}/{j}", f"{m}/{t}/{j}", f"{t}-{m}-{j}",
              f"{ti}.{_MONATE[mi - 1]}{j}", f"{t}.{_MONATE[mi - 1]}{j}", f"{ti}.{_MONATE[mi - 1][:3]}{j}",
              f"{ti}{_MONATE[mi - 1]}{j}", f"{ti}.{_MONATE[mi - 1]}{jj}"}
    if mi == 1:
        formen |= {f"{ti}.jänner{j}", f"{t}.jänner{j}"}
    return any(re.sub(r"\s+", "", x).lower() in roh for x in formen)



def monat_belegt(iso, text):
    """Is 'YYYY-MM-DD' the first or last day of a month that the text names as month and year only?

    Payslips carry no date of issue, only the billing month ("Monat/Jahr 8 / 99", "12/1998", "März 2005").
    The model then proposes the last (or first) day of that month, and `datum_belegt` rejected it: the date
    stayed the day of the import (T-12: 15 payslips of one employer)."""
    try:
        tag = datetime.date.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return False
    letzter = (tag.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    if tag.day not in (1, letzter.day):
        return False
    t = str(text or "")
    j, jj, m = str(tag.year), str(tag.year)[2:], tag.month
    zahl = rf"(?<![\d.,/])0?{m}\s*[./]\s*(?:{j}|{jj})(?![\d.,])"
    name = rf"\b{_MONATE[m - 1]}\s+{j}\b" + (rf"|\bJänner\s+{j}\b" if m == 1 else "")
    return bool(re.search(zahl, t) or re.search(name, t, re.IGNORECASE))


_MONAT_NR = {**{n.lower(): i for i, n in enumerate(_MONATE, 1)}, "maerz": 3, "marz": 3, "jänner": 1, "jaenner": 1}
_MONAT_NAME = "|".join(sorted(_MONAT_NR, key=len, reverse=True))
# The billing month, in order of trust: a labelled "Abrechnungsmonat"/"Abrechnungszeitraum", then the
# "Monat/Jahr" box of old payslips, then "Abrechnung für <Monat> <Jahr>". A correction line
# ("Rückrechnung März 2022") is never one of these — it names the corrected month, not the billing month.
_ABRECHNUNGSMONAT = [
    re.compile(rf"Abrechnungs(?:monat|zeitraum)\s*:?\s*({_MONAT_NAME})\s+((?:19|20)\d\d)\b", re.IGNORECASE),
    re.compile(r"Abrechnungs(?:monat|zeitraum)\s*:?\s*(0?[1-9]|1[0-2])\s*[./]\s*((?:19|20)?\d\d)(?![\d.])", re.IGNORECASE),
    re.compile(r"Monat\s*/\s*Jahr[\s:\-|]*?(0?[1-9]|1[0-2])\s*/\s*((?:19|20)?\d\d)(?!\d)", re.IGNORECASE),
    re.compile(rf"(?:Entgelt|Gehalts|Lohn|Verdienst|Bezüge)?abrechnung\s+(?:für\s+)?(?:den\s+Monat\s+)?({_MONAT_NAME})\s+((?:19|20)\d\d)\b",
               re.IGNORECASE),
]


# Table layout of the OCR: the labels of the header stand one under the other, their values follow later in the
# same order ("Rückrechnung / Abrechnungsmonat / … / Januar 2022 / Juni 2022").
_LABEL_ALLEIN = re.compile(r"^[ \t]*Abrechnungsmonat[ \t:]*$", re.IGNORECASE | re.MULTILINE)
_MONAT_JAHR_WERT = re.compile(rf"\b({_MONAT_NAME})\s+((?:19|20)\d\d)\b", re.IGNORECASE)


def _abrechnungsmonat_spalte(text):
    """The billing month of a header whose labels and values the OCR wrote as separate columns, or None."""
    m = _LABEL_ALLEIN.search(text)
    if not m:
        return None
    davor = [z.strip() for z in text[:m.start()].splitlines()[-3:] if z.strip()]
    index = sum(1 for z in davor if re.fullmatch(r"R[üu]ckrechnung:?", z, re.IGNORECASE))
    werte = _MONAT_JAHR_WERT.findall(text[m.end():m.end() + 400])
    if len(werte) <= index:
        return None
    return _MONAT_NR.get(werte[index][0].lower()), int(werte[index][1])


def abrechnungsmonat(text):
    """(year, month) of the billing month named in the text, or None."""
    spalte = _abrechnungsmonat_spalte(str(text or ""))
    if spalte and spalte[0]:
        return spalte[1], spalte[0]
    for rx in _ABRECHNUNGSMONAT:
        m = rx.search(str(text or ""))
        if not m:
            continue
        mon = _MONAT_NR.get(m.group(1).lower()) if not m.group(1).isdigit() else int(m.group(1))
        jahr = int(m.group(2))
        if jahr < 100:
            jahr += 1900 if jahr >= 50 else 2000
        if mon and 1950 <= jahr <= 2035:
            return jahr, mon
    return None


_DATUM_ETIKETT = r"(?:Erstellungs|Ausstellungs|Druck|Abrechnungs)?datum|Datum|erstellt am|wurde am|, den|[A-ZÄÖÜ][a-zäöüß]+,"


def ausstellungsdatum(iso, text):
    """Does the text print `iso` as a date of issue — after a label ("Erstellungsdatum", "Datum", "Hamburg, den")?
    ("Die Abrechnung wurde am 17.07.2018 … erstellt" counts.) A date in a list ("03.10.2022 - 03.10.2022: Feiertag")
    is none (T-14: payslips kept a holiday or a day of leave as their date)."""
    try:
        tag = datetime.date.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return False
    t, m, j = tag.day, tag.month, tag.year
    formen = {f"{t:02d}.{m:02d}.{j}", f"{t}.{m}.{j}", f"{t:02d}.{m:02d}.{j % 100:02d}", f"{t}.{m}.{j % 100:02d}"}
    datum = "|".join(re.escape(f).replace(r"\.", r"\.\s*") for f in sorted(formen, key=len, reverse=True))
    return bool(re.search(rf"(?:{_DATUM_ETIKETT})\s*:?\s*(?:{datum})(?![\d])", str(text or "")))


def _monatsletzter(jahr, monat):
    return ((datetime.date(jahr, monat, 28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)).isoformat()


def monatsletzter_datum(datum, text, typ, typen):
    """The date of a document of the `monatsletzter_typen`: the last day of the billing month (T-14).

    A date of issue stays: the proposal is kept when the text prints it after a label (`ausstellungsdatum`).
    Otherwise the billing month from the text decides; without one, the month of the proposal if the text names
    it as month and year (`monat_belegt`)."""
    if not typ_in(typ, typen):
        return datum
    if datum and ausstellungsdatum(datum, text):
        return datum                                            # a date of issue
    am = abrechnungsmonat(text)
    if am:
        return _monatsletzter(*am)
    if datum and monat_belegt(datum, text):
        tag = datetime.date.fromisoformat(datum)
        return _monatsletzter(tag.year, tag.month)
    return datum


def wirksames_datum(prop, content, doc):
    """Das Datum, das tatsächlich geschrieben würde: KI-Vorschlag, nur mit Beleg im Text und nicht
    der Importtag einer Office-Datei. Eine Funktion für Lauf und Trockenlauf, damit der Trockenlauf
    (und die Testsammlung) dasselbe zeigt wie ein echter Lauf. Bei den `monatsletzter_typen` entscheidet
    der Code (T-14)."""
    datum = dokument_datum(prop)
    if CFG.get("monatsletzter_typen"):
        neu = monatsletzter_datum(datum, content, prop.get("document_type"), CFG.get("monatsletzter_typen"))
        if neu != datum:
            TRACE["datum_monatsletzter"] = {"vorschlag": datum, "gesetzt": neu}
            return neu
    if datum and not datum_belegt(datum, content) and not monat_belegt(datum, content):
        TRACE["datum_ohne_beleg"] = datum
        return None
    if datum and office_importtag(datum, doc):
        TRACE["datum_importtag_office"] = datum
        return None
    return datum

OFFICE_ENDUNGEN = (".doc", ".docx", ".docm", ".odt", ".rtf", ".xls", ".xlsx", ".ods", ".ppt", ".pptx", ".odp")


def office_importtag(datum, doc):
    """Ist das Datum der Importtag einer Office-Datei? Dann kommt es aus einem automatischen
    Datumsfeld (Word: „Datum, automatisch aktualisieren“), das beim Umwandeln in PDF das Tagesdatum
    einsetzt — nicht der Tag, an dem das Dokument entstand (PO 2026-10-11: eine Bewerbung von 2017
    bekam so den Importtag 01.07.2026)."""
    name = str(doc.get("original_file_name") or "").lower()
    return name.endswith(OFFICE_ENDUNGEN) and str(doc.get("added") or "")[:10] == datum

def is_null(raw):
    return raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "null", "none", "-", "—", "n/a", "kein", "unbekannt"))


def sel_label(f, val):
    for o in (f.get("extra_data") or {}).get("select_options", []):
        if o.get("id") == val:
            return o.get("label")
    return val


_WAEHRUNG_ZEICHEN = (("€", "EUR"), ("$", "USD"), ("£", "GBP"), ("DM", "DEM"), ("ÖS", "ATS"), ("öS", "ATS"),
                     ("SFR", "CHF"), ("Fr.", "CHF"))


def betrag_wert(v):
    """A monetary field value for Paperless ("EUR1234.56", "DEM-12.30"), or None.

    The currency stays what the document says: an ISO code in front or behind, or a sign/abbreviation (DM →
    DEM). Until T-12 every amount became EUR (payslips in DM were stored as euros), and "2.004,98" was cut
    to "2.004" (the German thousands point read as decimal point)."""
    s = str(v or "").strip()
    if not s:
        return None
    m = re.search(r"(?<![A-Za-z])([A-Z]{3})(?![A-Za-z])", s)
    waehrung = m.group(1) if m else next((iso for zeichen, iso in _WAEHRUNG_ZEICHEN if zeichen in s), "EUR")
    m = re.search(r"-?\s*\d[\d.,' ]*", s)
    if not m:
        return None
    roh = re.sub(r"[\s']", "", m.group(0)).rstrip(".,")
    negativ, roh = roh.startswith("-"), roh.lstrip("-")
    if "," in roh and "." in roh:
        dezimal = "," if roh.rfind(",") > roh.rfind(".") else "."
    elif "," in roh:
        dezimal = "," if len(roh) - roh.rfind(",") - 1 in (1, 2) else ""
    elif "." in roh:
        dezimal = "" if roh.count(".") > 1 or len(roh) - roh.rfind(".") - 1 == 3 else "."
    else:
        dezimal = ""
    tausender = {",", "."} - {dezimal}
    zahl = "".join(c for c in roh if c not in tausender).replace(",", ".")
    try:
        wert = float(zahl)
    except ValueError:
        return None
    return f"{waehrung}{'-' if negativ and wert else ''}{wert:.2f}"


def coerce_field(f, v):
    t = f["data_type"]
    try:
        if t == "integer":
            s = re.sub(r"[^\d-]", "", str(v)); return int(s) if s not in ("", "-") else None
        if t == "float":
            return float(str(v).replace(",", ".").strip())
        if t == "monetary":
            return betrag_wert(v)
        if t == "boolean":
            return v if isinstance(v, bool) else str(v).strip().lower() in ("true", "ja", "1", "yes", "wahr")
        if t == "date":
            m = re.match(r"\d{4}-\d{2}-\d{2}", str(v).strip()); return m.group(0) if m else None
        if t == "url":
            return str(v).strip()
        if t == "select":
            for o in (f.get("extra_data") or {}).get("select_options", []):
                if norm(str(v)) == norm(o.get("label", "")):
                    return o.get("id")
            return None
        return str(v).strip()
    except (ValueError, TypeError):
        return None


def beispiel_text(paare, max_paare=6):
    """Few-Shot-Beispiele für den Korrespondent-Abgleich als Prompt-Baustein.

    Nimmt [["Mustrmann GmbH", "Mustermann"], …] und macht daraus " (z.B. 'a'='b', …)".
    Unbrauchbare Einträge (falsche Länge, leer, kein Text) werden übergangen statt zu
    scheitern — die Config pflegt ein Mensch, ein Tippfehler dort darf keinen
    Klassifizierungslauf abbrechen.
    """
    gut = []
    for eintrag in (paare or []):
        if not isinstance(eintrag, (list, tuple)) or len(eintrag) != 2:
            continue
        a, b = (str(x).strip() for x in eintrag)
        if a and b:
            gut.append((a, b))
    if not gut:
        return ""
    return " (z.B. " + ", ".join(f"'{a}'='{b}'" for a, b in gut[:max_paare]) + ")"


def fehler_mit_feldnamen(err, cfs, cfields):
    """Paperless-Fehlermeldung so umschreiben, dass Feldnamen darin stehen.

    Bei Custom-Field-Fehlern schlüsselt Paperless nach **Listen-Index** der gesendeten
    `custom_fields`, nicht nach Feld-ID und nicht nach Name — bei Fehlern an Position 2 und 3
    kommt `{"custom_fields": {"1": {…}, "2": {…}}}` zurück. Diesen Text roh an ein Modell zu
    geben und es um Korrektur „mit denselben Feldnamen" zu bitten, kann nicht funktionieren:
    das Modell sieht Zahlen, kennt die gesendete Reihenfolge nicht und rät. Bis 2026-09-21
    endete das regelmäßig damit, dass nach vier Runden ohne Custom Fields gespeichert wurde.

    Gibt den Originaltext zurück, wenn er sich nicht als JSON lesen lässt oder keine
    Index-Schlüssel enthält — eine unverständliche Meldung ist besser als eine falsch geratene.
    """
    try:
        daten = json.loads(err)
    except (ValueError, TypeError):
        return err
    if not isinstance(daten, dict) or "custom_fields" not in daten:
        return err
    cf_fehler = daten["custom_fields"]
    name_je_id = {f["id"]: f["name"] for f in cfields}

    def benenne(idx):
        try:
            fid = cfs[int(idx)]["field"]
        except (ValueError, TypeError, IndexError, KeyError):
            return None
        return name_je_id.get(fid)

    teile = []
    if isinstance(cf_fehler, dict):
        for idx, detail in cf_fehler.items():
            name = benenne(idx)
            teile.append(f"Feld '{name}': {json.dumps(detail, ensure_ascii=False)}" if name
                         else f"Eintrag {idx}: {json.dumps(detail, ensure_ascii=False)}")
    elif isinstance(cf_fehler, list):
        # Listenform: Position = Index, leere Einträge sind fehlerfrei
        for idx, detail in enumerate(cf_fehler):
            if not detail:
                continue
            name = benenne(idx)
            teile.append(f"Feld '{name}': {json.dumps(detail, ensure_ascii=False)}" if name
                         else f"Eintrag {idx}: {json.dumps(detail, ensure_ascii=False)}")
    if not teile:
        return err
    rest = {k: v for k, v in daten.items() if k != "custom_fields"}
    text = " | ".join(teile)
    return f"{text} | weitere: {json.dumps(rest, ensure_ascii=False)}" if rest else text


def _behalten(cfs, cur_vals, fid):
    """Bestehende Feldzuordnung unverändert übernehmen — auch wenn ihr Wert LEER ist.

    Paperless löscht jede Zuordnung, die in der gesendeten `custom_fields`-Liste fehlt. Ein
    Feld mit leerem Wert steht in `cur_vals` als `{fid: None}`: der Schlüssel existiert, der
    Wert ist None. Die frühere Prüfung `cur_vals.get(fid) is not None` konnte beides nicht
    unterscheiden und liess leere Zuordnungen fallen.

    Das traf ausgerechnet die geschützten Felder: ein manuelles Feld wie „Bezahlt-Am", das
    ein post-consume-Skript bewusst LEER anlegt, damit es in der Eingabemaske erscheint,
    verschwand nach dem ersten Klassifizierungslauf wieder. Aufgefallen 2026-09-21 bei einem
    Lauf gegen echte Dokumente im Testbett.
    """
    if fid in cur_vals:
        cfs.append({"field": fid, "value": cur_vals[fid]})
        return True
    return False


def _feldname(name):
    return re.sub(r"[^a-z0-9]", "", norm(name))


def feldvorschlag_verwerfen(f, wert, text, typ=None, cfg=None):
    """Why the model's value for custom field `f` must not be written — or None (T-11).

    - An IBAN field takes only an IBAN with valid check digits that is printed in the text: on payslips
      the model composed IBANs from bank code and account number (53 values on one installation).
    - An identifier field (text/number) takes no personnel number and no value that contains one
      ("611 7437/ 40/88901" next to "Pers.-Nr. 88901"); a field named for personnel numbers is exempt.
    - On a document type issued by the employer (`arbeitgeber_typen`) the fields in
      `arbeitgeber_ohne_felder` stay as they are: a payslip has no contract or invoice number, the
      reference numbers in its header are how the employer files us (37 payslips on one installation).
    A rejected value is dropped; the field keeps what it had."""
    cfg = cfg if cfg is not None else CFG
    if is_null(wert) or (isinstance(wert, str) and wert.strip().upper() in ("BEHALTEN", "KEEP")):
        return None
    name = f.get("name") or ""
    if "iban" in _feldname(name) and f.get("data_type") in ("string", "longtext"):
        if not norm_iban(wert):
            return "keine gültige IBAN (Prüfziffer ISO 13616)"
        if not iban_im_text(wert, text):
            return "IBAN steht so nicht im Text (aus Bankleitzahl und Konto zusammengesetzt?)"
        return None
    if (f.get("data_type") not in ("string", "integer") or not ist_kennung(wert) or len(str(wert)) > 40
            or PERSONAL_LABEL.search(name) or "personal" in _feldname(name)):
        return None                     # free text, a date or amount, or a field meant for the number
    if (typ_in(typ, cfg.get("arbeitgeber_typen") or ())
            and _feldname(name) in {_feldname(x) for x in _roh_liste(cfg.get("arbeitgeber_ohne_felder") or [])}):
        return f"bei „{typ}“ keine {name} (Nummern im Kopf gehören zur Abrechnung)"
    if personalnummer(wert, text, als_teil=True):
        return "Personalnummer bzw. enthält sie — keine Kennung des Gegenübers"
    return None


def felder_filtern(cfields, flds, text, typ=None, cfg=None):
    """The model's field proposals without the rejected ones: (kept, {field name: reason})."""
    je_name = {f["name"]: f for f in cfields}
    behalten, verworfen = {}, {}
    for name, wert in (flds or {}).items():
        grund = feldvorschlag_verwerfen(je_name[name], wert, text, typ, cfg) if name in je_name else None
        if grund:
            verworfen[name] = grund
        else:
            behalten[name] = wert
    return behalten, verworfen


def build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds=None):
    """KI-Entscheidung je Feld → custom_fields-Liste.

    Drei Quellen entscheiden über ein Feld, und sie dürfen sich nicht vermischen:
      flds        was die KI vorschlägt (Wert / null / "BEHALTEN")
      skip_fids   Felder, die die KI NICHT setzen darf (manuelle, Mail-Kontext, Hinweis) —
                  ihr bisheriger Wert wird unverändert übernommen
      code_flds   {fid: wert}, was der Klassifizierer SELBST setzt, auch für Felder aus
                  skip_fids. None heißt „Zuordnung entfernen" (Paperless löscht alles, was
                  in der gesendeten Liste fehlt). Eigener Kanal, damit ein halluzinierter
                  Feldname der KI nie ein geschütztes Feld erreichen kann.
    summary_fid wird ausschließlich am Ende angehängt — nie in der Schleife.

    Bis 2026-09-21 warf skip_fids alle drei in einen Topf, der nur „behalten" konnte. Folge:
    das Hinweisfeld wurde nie geleert (der Redo-Trigger feuerte dadurch erneut) und die
    Zusammenfassung landete zweimal in der Liste. Beides in tests/test_classify.py festgehalten.
    """
    code_flds = code_flds or {}
    cfs, flog = [], {}
    for f in cfields:
        fid, name, t = f["id"], f["name"], f["data_type"]
        if fid == summary_fid:
            continue                            # wird unten gesetzt, genau einmal
        if fid in code_flds:                    # der Klassifizierer selbst entscheidet
            v = code_flds[fid]
            if v is None:
                flog[name] = "entfernt"         # nicht anhängen ⇒ Zuordnung fällt weg
            else:
                cfs.append({"field": fid, "value": v}); flog[name] = v
            continue
        if fid in skip_fids or t == "documentlink":
            _behalten(cfs, cur_vals, fid)       # unverändert, auch leer
            continue
        if name not in flds:                    # von KI nicht erwähnt → behalten
            _behalten(cfs, cur_vals, fid)
            continue
        raw = flds[name]
        if isinstance(raw, str) and raw.strip().upper() in ("BEHALTEN", "KEEP"):
            if _behalten(cfs, cur_vals, fid):
                flog[name] = "behalten"
        elif is_null(raw):
            flog[name] = "geleert"
        else:
            v = coerce_field(f, raw)
            if v is not None:
                cfs.append({"field": fid, "value": v}); flog[name] = v
            elif _behalten(cfs, cur_vals, fid):
                flog[name] = "behalten(unparsebar)"
    if summary and summary_fid:
        cfs.append({"field": summary_fid, "value": summary})
    return cfs, flog


# Zeitüberschreitung beim Speichern: kein Feldfehler, keine Reparatur (2026-10-11). Eine abgebrochene
# Anfrage läuft beim Server weiter; jeder sofort nachgeschickte PATCH auf dasselbe Dokument stapelte
# sich dahinter — fünf gleichzeitige Änderungen verklemmten Paperless, bis der Webserver neu startete.
ZEIT = "ZEITUEBERSCHREITUNG: "
PATCH_FRIST_S = (90, 240)
PATCH_PAUSE_S = 30


def patch_angekommen(did, patch):
    """Steht der PATCH schon am Dokument? (Titel, Korrespondent, Typ, Datum; Tags als Teilmenge)"""
    try:
        d = get(f"/documents/{did}/")
    except Exception:
        return False
    for k, v in patch.items():
        if k == "custom_fields":
            continue
        if k == "tags":
            if not set(v) <= set(d.get("tags") or []):
                return False
        elif k == "created":
            if str(d.get("created") or "")[:10] != str(v)[:10]:
                return False
        elif d.get(k) != v:
            return False
    return True


def patch_doc(did, patch, pause=None):
    """Ein Dokument ändern. HTTP-Fehler (400 & Co.) kommen als Text zurück, damit die Reparatur sie
    der KI zeigen kann. Bei Zeitüberschreitung oder Netzfehler: warten, nachsehen, ob die Änderung
    doch ankam, und höchstens EINMAL mit längerer Frist neu senden — nie mehrere zugleich."""
    pause = PATCH_PAUSE_S if pause is None else pause
    for versuch, frist in enumerate(PATCH_FRIST_S):
        try:
            send(f"/documents/{did}/", patch, "PATCH", timeout=frist)
            return True, None
        except urllib.error.HTTPError as e:
            try:
                return False, e.read().decode("utf-8", "replace")[:900]
            except Exception:
                return False, repr(e)
        except Exception as e:
            fehler = repr(e)
        log(f"patch-zeit {did} V{versuch + 1}: {fehler[:80]}")
        __import__("time").sleep(pause)
        if patch_angekommen(did, patch):
            return True, None
    return False, ZEIT + fehler


def resolve_tag(tagid_by_norm, name):
    return tagid_by_norm.get(norm(name)) if name else None


def summary_aus(prop):
    """Die Zusammenfassung aus der KI-Antwort — auch unter den Schluesseln aelterer Prompts.

    Der eingebaute Prompt verlangt `summary`. Bestandsprompts verlangen `summary_long` bzw.
    `summary_short`, und das Modell haelt sich an den Prompt. Ohne den Rueckfall bleibt das
    Zusammenfassungsfeld bei ihnen still leer (bis 2026-09-27 so im Repo).
    """
    for k in ("summary", "summary_long", "summary_short"):
        v = prop.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def baue_system(tpl, types, taglines):
    """Setzt Typen und Tags in den System-Prompt ein. taglines=None heisst: Tagging aus.

    Zwei Platzhalter fuer die Tags, weil es zwei Generationen von Prompts gibt: {TAGBLOCK}
    (der ganze Block samt Anweisung) und das aeltere {TAGS} (nur die Liste, die Anweisung steht
    im Prompt selbst). Bis 2026-09-27 kannte der Code nur {TAGBLOCK} — ein Prompt mit {TAGS}
    lief weiter, bekam aber still keine Tag-Liste, und die KI vergab keinen einzigen Tag.
    Enthaelt ein Prompt bei aktivem Tagging keinen der beiden, wird der Block angehaengt,
    statt das Tagging wortlos ausfallen zu lassen.
    """
    if taglines is None:
        tagblock = ""
        taglines = ""
    else:
        tagblock = ("TAGS — nutze NUR exakte Namen aus dieser Liste, 1-3 wirklich zutreffende, den spezifischsten:\n"
                    + taglines + "\n"
                    "Wenn WIRKLICH kein Tag passt, gib in new_tags 1-2 kurze Vorschläge (sonst leeres Array). Sonst KEINE Tags erfinden.\n"
                    "JSON zusätzlich: tags (Array bestehender Namen), new_tags (Array).\n\n")
    return "".join(t for t, _ in baue_system_teile(tpl, types, taglines))


# Platzhalter im Pass-1-Prompt und was fuer sie eingesetzt wird (fuer die Beschriftung im Panel).
PLATZHALTER = {"TYPES": "Dokumenttypen aus Paperless", "TAGBLOCK": "Tag-Liste samt Anweisung",
               "TAGS": "nur die Tag-Liste"}



def typ_block(types, beschreibungen):
    """Die Beschreibungen der Dokumenttypen für den Prompt, direkt hinter der Typliste; leer ohne.

    Nur Typen, die es gibt. Anlass (2026-10-11): eigene Typen wie „Unterrichtsvereinbarung“ für eine
    Vorlage, die sich selbst „Einverständniserklärung“ nennt — ohne Beschreibung nahm die KI den Typ,
    der nach dem Wortlaut klingt (Erklärung)."""
    zeilen = [f"- {n}: {str(b).strip()}" for n, b in sorted((beschreibungen or {}).items())
              if n in types and str(b or "").strip()]
    if not zeilen:
        return ""
    return ("\nBEDEUTUNG EINZELNER TYPEN (gilt vor dem Wortlaut, mit dem sich ein Dokument selbst nennt):\n"
            + "\n".join(zeilen))

def baue_system_teile(tpl, types, taglines, typ_beschreibungen=None):
    """Wie baue_system(), aber in Stuecken: (Text, Platzhaltername oder None).

    Der Lauf fuegt die Stuecke zusammen, das Panel markiert die eingesetzten Werte. Eine
    Funktion fuer beide, damit die Vorschau nie vom gesendeten Prompt abweicht."""
    if taglines is None:
        tagblock = ""
        taglines = ""
    else:
        tagblock = ("TAGS — nutze NUR exakte Namen aus dieser Liste, 1-3 wirklich zutreffende, den spezifischsten:\n"
                    + taglines + "\n"
                    "Wenn WIRKLICH kein Tag passt, gib in new_tags 1-2 kurze Vorschläge (sonst leeres Array). Sonst KEINE Tags erfinden.\n"
                    "JSON zusätzlich: tags (Array bestehender Namen), new_tags (Array).\n\n")
    werte = {"TYPES": ", ".join(sorted(types)) + typ_block(types, typ_beschreibungen), "TAGBLOCK": tagblock, "TAGS": taglines}
    teile = []
    for i, stueck in enumerate(re.split(r"\{(TYPES|TAGBLOCK|TAGS)\}", tpl)):
        if i % 2:
            teile.append((werte[stueck], stueck))
        elif stueck:
            teile.append((stueck, None))
    if tagblock and "{TAGBLOCK}" not in tpl and "{TAGS}" not in tpl:
        teile.append(("\n" + tagblock, "TAGBLOCK (angehängt, weil der Prompt keinen Platzhalter hat)"))
    return teile


def korrespondent_behalten(bisher, ki_meldet_unlesbar, hinweis):
    """Den bisherigen Korrespondenten stehen lassen, statt einen neuen anzulegen? Nur wenn es einen
    gibt, die KI den Text als unlesbar meldet und kein Hinweis vorliegt."""
    return bool(bisher) and bool(ki_meldet_unlesbar) and not (hinweis or "").strip()


# Dateinamen, unter denen Paperless die Teile eines Dokuments neu einliest: der PDF-Editor
# `<id>_edit_<n>.pdf` (bulk_edit.edit_pdf), das Aufteilen `<id>_<von>-<bis>.pdf` (bulk_edit.split).
TEIL_RE = re.compile(r"^(\d+)_(?:edit_\d+|\d+-\d+)\.pdf$", re.IGNORECASE)


def teildokument_von(dateiname):
    """ID des Ausgangsdokuments, wenn das Dokument ein Teil aus dem PDF-Editor oder dem Aufteilen
    von Paperless ist, sonst None."""
    m = TEIL_RE.match(str(dateiname or "").strip())
    return int(m.group(1)) if m else None


def erbe_verwerfen(doc):
    """Das Dokument ohne die Metadaten, die es beim Aufteilen von seinem Ausgangsdokument bekam.

    Paperless kopiert beim Aufteilen (mit „Metadaten übernehmen“) Titel, Korrespondent, Typ, Datum,
    Tags und alle Feldwerte des Ausgangsdokuments in JEDEN Teil (DocumentMetadataOverrides.
    from_document). Bis 2026-10-14 sah paperlaiss darin den Bestand: das geerbte Marker-Tag liess den
    Import-Lauf überspringen, und beim KI-Knopf standen Fahrzeug, Fahrgestell-Nr., Kennzeichen und
    Polizze des Ausgangsdokuments als „aktuell“ im Prompt — die KI behielt sie, obwohl der Teil eine
    ganz andere Rechnung war (42 Teile eines 50-seitigen Scans, alle „<Versicherung> – Kaufvertrag“).
    Tags bleiben: dort mischen sich Erbe und das, was die Workflows für den Teil selbst gesetzt haben.
    Die Felder gehen ganz, auch Mail-Kontext und Handfelder: sie gehörten zum Ausgangsdokument.
    """
    d = dict(doc)
    d.update({"title": "", "correspondent": None, "document_type": None, "created": None, "custom_fields": []})
    return d


def dateiname_fuer_prompt(dateiname):
    """Der Originaldateiname für die Nachricht an Pass 1 — bei einem Teil aus dem Aufteilen keiner.
    `1205_edit_2.pdf` trägt nur die ID des Ausgangsdokuments, und die KI nahm sie als Kennung in den
    Titel („Rechnung 1205“, 2026-10-14)."""
    if not dateiname or teildokument_von(dateiname) is not None:
        return "—"
    return dateiname


def erbe_offen(doc, trace_dir):
    """Trägt das Dokument noch das Erbe seines Ausgangsdokuments? Ja bei einem Teil, für den
    paperlaiss selbst noch nie gelaufen ist (kein eigener Trace)."""
    if teildokument_von(doc.get("original_file_name")) is None:
        return False
    return not os.path.exists(os.path.join(trace_dir, f"{doc.get('id')}.json"))


def typ_ueberschreibbar(source, force):
    """Darf dieser Lauf einen schon gesetzten Dokumenttyp ersetzen? Siehe typ_setzen().

    Ja beim KI-Knopf (`knopf`) und im Panel (`manual`), und beim echten Import: keine Quelle
    UND kein CLASSIFY_FORCE — nur dort kann der Typ ausschliesslich von der Paperless-Automatik
    stammen. Ebenso beim Nachlauf eines Mail-Imports (`mail`): das Dokument ist gerade erst
    angekommen, der Mail-Kontext steht aber erst nach dem Import fest — der Nachlauf braucht
    CLASSIFY_FORCE, ist inhaltlich aber noch der Import. Nein bei allem anderen: dem Bestands-Durchlauf (`bulk`) und jedem Handaufruf mit
    CLASSIFY_FORCE über vorhandene Dokumente, deren Typ ein Mensch gesetzt haben kann. Die sichere
    Seite ist „stehen lassen": eine unbekannte Aufrufart überschreibt nie (Prüfrunde 2026-09-27 —
    „alles ausser bulk" hätte den dokumentierten Handaufruf in einer Schleife überschreiben lassen)."""
    return source in ("knopf", "manual", "mail") or (source == "" and not force)


def typ_setzen(dt_id, bisher, darf_ueberschreiben):
    """Welchen Dokumenttyp schreiben — oder keinen (None).

    Seit 2026-09-27 (PO): Die Paperless-Automatik darf einen Typ vorbelegen, paperlaiss bekommt
    ihn als Vorschlag in die Nachricht und darf ihn ueberschreiben — nach dem Import (dort kann der
    Typ nur von der Automatik stammen), beim KI-Knopf und im Panel. Nur der Bestands-Durchlauf
    laesst einen vorhandenen Typ stehen: dort kann ihn ein Mensch gesetzt haben.
    (Bis dahin ueberschrieb nur der Knopf; ein von der Automatik gesetzter Typ blieb stehen.)
    """
    if not dt_id or dt_id == bisher:
        return None
    if bisher and not darf_ueberschreiben:
        return None
    return dt_id




def _typ_falte(s):
    """Typname zum Vergleichen: klein, Umlaute als ae/oe/ue/ss, nur Buchstaben und Ziffern —
    „Erklärung“ und „Erklaerung“ sind derselbe Typ (norm() machte aus ä ein a)."""
    s = str(s or "").lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        s = s.replace(a, b)
    return re.sub(r"[^a-z0-9]", "", unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode())



# Zuweisungsarten von Paperless, die als bewusste, genaue Regel gelten: Exakt (3) und Regulärer Ausdruck (4).
FESTE_ZUWEISUNG = {3, 4}


def typ_aus_regel(types_roh, text):
    """Der Dokumenttyp, den eine genaue Zuweisung in Paperless festlegt, sonst None (feste_zuweisung)."""
    return feste_zuweisung(types_roh, text)


def korrespondent_aus_regel(corrs, text, eigene_namen=()):
    """Der Korrespondent, den eine genaue Zuweisung in Paperless festlegt, sonst None.

    Gleiche Regel wie beim Typ (feste_zuweisung) und ebenso vor der KI. Anlass (2026-10-14, Seite
    Nacharbeit): Rechnungen über einen Marktplatz nennen den einzelnen Händler als Verkäufer, das
    Archiv führt sie aber unter der Plattform, über die bezahlt wurde. Die KI nimmt verlässlich den
    Verkäufer — der steht ja im Briefkopf. Die Plattform erkennt man an einem festen Satz („Auf das
    Konto von … eingezahlt“, eine Kontaktadresse), und genau dafür ist die Zuweisung „Exakt“ da.

    Nie die eigene Firma: ihr Name steht auf fast jedem Dokument. Eine Installation hatte „Exakt:
    <Inhaber>“ an einem Korrespondenten — das traf 664 Dokumente und hätte jedes dorthin gelegt
    (gemessen 2026-10-14 vor dem Ausrollen). Wie bei Namens- und Stammdaten-Vorsuche."""
    return feste_zuweisung([c for c in corrs or () if not any(n <= set(ctoks(c["name"])) for n in eigene_namen)], text)


def feste_zuweisung(objekte, text):
    """Das Objekt (Typ oder Korrespondent), das eine genaue Zuweisung in Paperless festlegt, sonst None.

    Nur „Exakt“ und „Regulärer Ausdruck“ (Paperless-Doku: Exakt = der Text steht genau so, in dieser
    Reihenfolge, im Dokument). Sie gelten vor der KI: eine eigene Vorlage, die sich selbst anders nennt
    („Einverständniserklärung“ → Typ Unterrichtsvereinbarung), erkennt die KI nicht zuverlässig, eine
    Zuweisung schon (PO 2026-10-11). „Irgendein Wort“, „Alle Wörter“, „Ungefähr“ und „Automatisch“
    bleiben Sache der KI — sie sind grob („Rechnung Invoice Faktura“) und machten sonst aus jeder
    Rechnung, die eine Mahnung erwähnt, eine Mahnung. Bei Exakt zählt jeder Leerraum als Leerraum
    (das OCR bricht Zeilen). Treffen mehrere, gewinnt die längste Zuweisung."""
    treffer = []
    for t in objekte or ():
        m = str(t.get("match") or "").strip()
        if t.get("matching_algorithm") not in FESTE_ZUWEISUNG or not m:
            continue
        flags = re.IGNORECASE if t.get("is_insensitive", True) else 0
        if t["matching_algorithm"] == 3:
            muster = r"(?<!\w)" + r"\s+".join(re.escape(w) for w in m.split()) + r"(?!\w)"
        else:
            muster = m
        try:
            if re.search(muster, str(text or ""), flags):
                treffer.append((len(m), t))
        except re.error:
            continue
    return max(treffer, key=lambda x: x[0])[1] if treffer else None

def typ_zuordnen(antwort, types):
    """Die id des Dokumenttyps zur Antwort der KI, sonst None. Genau, dann ohne Schreibweise, dann
    über das Wortende: die deutsche Zusammensetzung endet auf den Oberbegriff
    („Einverständniserklärung“ → Erklärung, „Bußgeldbescheid“ → Bescheid); der längste passende
    Typ gewinnt, ab 5 Zeichen."""
    if not antwort:
        return None
    if antwort in types:
        return types[antwort]
    f = _typ_falte(antwort)
    gefaltet = {_typ_falte(n): i for n, i in types.items()}
    if f in gefaltet:
        return gefaltet[f]
    enden = [(len(n), i) for n, i in gefaltet.items() if len(n) >= 5 and f.endswith(n)]
    return max(enden)[1] if enden else None



def pruef_befunde(did, doc, content, treffer, corr_id, typ=None):
    """Hinweise zum Prüfen (PO 2026-10-11: markieren, nicht automatisch korrigieren): Teilstück,
    Dublette, Sammeldokument, erfundener OCR-Text. Jeder Fehler hier bricht den Lauf nicht ab."""
    b = {}
    try:
        t = teilstueck(content, doc.get("page_count"))
        if t:
            b["teilstueck"] = t
        aehnliche = aehnliche_holen(did, content)
        d = dublette(content, doc.get("page_count"), aehnliche)
        if d:
            b["dublette"] = d
        tk = None if d else teilkopie(content, doc.get("page_count"), aehnliche)
        if tk:
            b["teilkopie"] = tk
        sd = sammeldokument(treffer, corr_id, typ, CFG.get("sammeldokument_ausser_typen") or [])
        if sd:
            b["sammeldokument"] = sd
        if OCR_VERDACHT:
            b["ocr_erfunden"] = "; ".join(f"{'OCR-Text' if n == 'alle' else f'Seite {n}'}: {g}" for n, g in OCR_VERDACHT)
    except Exception as e:
        log(f"befunde-fail {did}: {e!r}")
    return b

# Findings that mean "the scan is broken" rather than "the classification may be wrong" (T-10).
KAPUTT_BEFUNDE = ("leer", "teilstueck", "ocr_erfunden")
BEFUND_NAMEN = {"leer": "leer", "teilstueck": "Seiten fehlen", "ocr_erfunden": "OCR-Text erfunden",
                "dublette": "Dublette", "teilkopie": "Teilkopie", "sammeldokument": "Sammeldokument", "datum": "Datum",
                "eigene_person": "eigene Person als Korrespondent", "einzugsstelle": "Einzugsstelle statt Arbeitgeber",
                "abbruch": "Lauf abgebrochen", "fremde_person": "fremde Person"}
NOTIZ_PRAEFIX = "paperlaiss: "


def befund_tags(befunde, unsicher_id, kaputt_id):
    """Flag tags for findings: a broken scan gets the kaputt tag (when set), anything else the unsicher tag."""
    if not befunde:
        return []
    kaputt = [k for k in befunde if k in KAPUTT_BEFUNDE]
    tags = [kaputt_id] if (kaputt and kaputt_id) else []
    if unsicher_id and (not tags or len(kaputt) < len(befunde)):
        tags.append(unsicher_id)
    return tags


def befund_text(befunde):
    """One line for the note and the log: what is wrong, in words."""
    return "prüfen — " + "; ".join(f"{BEFUND_NAMEN.get(k, k)}: {v}" for k, v in befunde.items())


def notiz_setzen(did, text):
    """Add a note to the document unless the same note is already there (re-runs must not pile them up).
    True when one was written."""
    text = NOTIZ_PRAEFIX + text
    try:
        da = get(f"/documents/{did}/notes/")
    except Exception:
        da = []
    if isinstance(da, dict):
        da = da.get("results") or []
    if any(isinstance(n, dict) and n.get("note") == text for n in da or ()):
        return False
    send(f"/documents/{did}/notes/", {"note": text}, "POST")
    return True


def _hat_ghostscript():
    return bool(__import__("shutil").which("gs"))


def alle_seiten_leer(did, seiten):
    """„alle N Seite(n) leer“ when every page is blank, else None — None also when it cannot be told: the
    check needs leerseiten.py next to this script and Ghostscript (the Paperless container has both, the
    panel container neither)."""
    pfad = os.path.join(SCRIPT_DIR, "leerseiten.py")
    try:
        seiten = int(seiten or 0)
        if seiten < 1 or not os.path.isfile(pfad) or not _hat_ghostscript():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("paperlaiss_leerseiten", pfad)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        pdf = get(f"/documents/{did}/download/", raw=True)
        with tempfile.TemporaryDirectory(prefix="paperlaiss-leer-") as tmp:
            datei = os.path.join(tmp, "dokument.pdf")
            with open(datei, "wb") as f:
                f.write(pdf)
            leer, _ = mod.leere_seiten(datei, seiten)
        return f"alle {seiten} Seite(n) leer" if len(leer) == seiten else None
    except Exception as e:
        log(f"leerseiten-fail {did}: {e!r}")
        return None


def nur_markieren(did, doc, tag_ids_on, befunde, marker_id, unsicher_id, kaputt_id):
    """Mark a document that cannot be classified (no text): marker (no endless re-runs), flag tags, note."""
    TRACE["pruefen"] = befunde
    if DRY:
        print(json.dumps({"id": did, "pruefen": befunde, "korrespondent_ergebnis": None, "document_type": None,
                          "document_date": None, "datum_bisher": (doc.get("created") or "")[:10]}, ensure_ascii=False))
        return
    tags = list(dict.fromkeys(list(tag_ids_on) + ([marker_id] if marker_id else [])
                              + befund_tags(befunde, unsicher_id, kaputt_id)))
    ok, err = patch_doc(did, {"tags": tags})
    if not ok:
        log(f"markieren-fail {did}: {str(err)[:200]}")
    else:
        TRACE["klassifiziert"] = f"{datetime.datetime.now():%F %T}"
    if CFG.get("pruef_notiz"):
        try:
            notiz_setzen(did, befund_text(befunde))
        except Exception as e:
            log(f"notiz-fail {did}: {e!r}")
    log(f"PRÜFEN {did} | ohne Klassifizierung | " + "; ".join(f"{k} {x}" for k, x in befunde.items()))
    TRACE["_stage"] = "fertig"
    save_trace(did)


def abbruch_markieren(did, e):
    """After a run broke off on a passing outage (overload, network): flag the document and say why, so it
    does not silently stay unclassified (T-10: two payslips after a two-minute 503 of the model)."""
    if DRY or not did or not CFG.get("unsicher_tag"):
        return
    try:
        doc = get(f"/documents/{did}/")
        tagid_by_norm = {norm(t["name"]): t["id"] for t in get("/tags/?page_size=1000")["results"]}
        uid = resolve_tag(tagid_by_norm, CFG["unsicher_tag"])
        if uid and uid not in (doc.get("tags") or []):
            patch_doc(did, {"tags": list(doc.get("tags") or []) + [uid]})
        if CFG.get("pruef_notiz"):
            notiz_setzen(did, befund_text({"abbruch": f"{e!r} — bitte neu klassifizieren"}))
    except Exception as e2:
        log(f"abbruch-markieren-fail {did}: {e2!r}")


def eigene_person_befund(korrespondent, typ, eigene_namen, eigene_typen):
    """One of our own PERSONS as correspondent of a document we do not write ourselves → hint, else None.

    On forms (registration certificates, social insurance notices) the model took the addressee — us —
    instead of the issuer (T-9). Our own letters, applications, notices of termination stay allowed
    (`eigene_typen`). Only names that look like a person's count: a company archive names its own
    company for internal documents (payroll, transfer lists) on purpose (EIGENE_REGEL)."""
    k = set(ctoks(korrespondent or ""))
    if not k or typ_in(typ, eigene_typen):
        return None
    for n in eigene_namen or ():
        t = set(ctoks(n))
        if t and t <= k and _personenname(n):
            return f"„{korrespondent}“ ist eine eigene Person — {f'„{typ}“' if typ else 'ein Dokument ohne Typ'} schreibt man nicht selbst"
    return None


def _woerter(text):
    return set(re.findall(r"[a-zäöüß]+", str(text or "").lower()))


def fremde_person_befund(text, eigene_namen, fremde_namen):
    """The text names one of `fremde_namen` and none of our own persons → hint, else None (T-12).

    A name counts when all its words are in the text, in any order ("Schulz, Erika", "FRAU ERIKA SCHULZ").
    A document of both (a joint tax notice) names an own person too and is no finding."""
    w = _woerter(text)
    if not w or any(_woerter(n) and _woerter(n) <= w for n in eigene_namen or ()):
        return None
    for n in fremde_namen or ():
        if _woerter(n) and _woerter(n) <= w:
            return f"nennt nur „{n}“, keine eigene Person — gehört das Dokument hierher?"
    return None


def datum_befund(vorschlag, wirksam, doc):
    """No usable document date, so the date stays the import day → hint, else None (T-9: it stayed silently).

    `vorschlag` is the model's date, `wirksam` the one that would be written (wirksames_datum). Only when
    the current date IS the import day: a date Paperless or a person set before is kept on purpose."""
    if wirksam:
        return None
    erstellt, hinzu = str(doc.get("created") or "")[:10], str(doc.get("added") or "")[:10]
    if not hinzu or erstellt != hinzu:
        return None
    if not vorschlag:
        return "kein Datum im Text — das Datum bleibt der Importtag"
    return f"Datum {vorschlag} verworfen (nicht im Text oder Importtag) — das Datum bleibt der Importtag"


# --- A re-run cleans up after the previous run (T-9) ---
# Until T-9 a re-run only added: tags and field values of an earlier bad run (on text read upside down)
# stayed, and the model saw them as "current" and kept them. What the previous run set itself is now
# taken back before the new run decides — unless a person changed the classification since.
GESICHTET = {"title", "correspondent", "document_type", "created", "tags", "custom_fields"}
GNADE_S = 15   # writes of the run itself and clock skew around the trace time stamp (as panel/nacharbeit.py)


def _utc(text):
    try:
        d = datetime.datetime.fromisoformat(str(text or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else None


def _feldwert(v):
    """Field values comparable: Paperless and the run may write a number as number or text."""
    return "" if v is None else " ".join(str(v).split())


def personen_tags(text):
    """Tag names of PANEL_ROUTE_PERSONS ("<tag>=<username>,…"), normalised — routing acts on them."""
    return {norm(t) for t, sep, u in (x.partition("=") for x in str(text or "").split(",")) if sep and t.strip() and u.strip()}


def vorlauf_kandidaten(trace, tags_on, cur_vals, tagid_by_norm, fid_by_name, geschuetzt):
    """What the previous run set and is still exactly as it left it: ({tag id: name}, {field id: name}).

    Only a finished run counts, and only what it CHANGED (`tags_gesetzt`, `fields_gesetzt`): a value
    that was there before the run, set by a person, is not the run's to take back. Older traces lack
    both keys and give nothing. Protected tags (reserved, person tags) are never candidates."""
    wb = (trace or {}).get("writeback") if isinstance(trace, dict) else None
    if not isinstance(wb, dict) or wb.get("fehler") or trace.get("error") or trace.get("_stage") != "fertig":
        return {}, {}
    tags = {}
    for name in wb.get("tags_gesetzt") or []:
        tid = tagid_by_norm.get(norm(name))
        if tid in tags_on and norm(name) not in geschuetzt:
            tags[tid] = name
    felder = {}
    for name, v in (wb.get("fields_gesetzt") or {}).items():
        fid = fid_by_name.get(name)
        if fid in cur_vals and _feldwert(cur_vals[fid]) == _feldwert(v):
            felder[fid] = name
    return tags, felder


def nach_lauf_gesichtet(trace, historie):
    """Has a user changed the classification since the run (document history)? None = unknown.

    Unknown counts as "yes" for the caller: no history (audit log off, no permission) or no time stamp
    means nothing is taken back. Entries without a user (workflows) do not count, as in the Nacharbeit."""
    ende = _utc((trace or {}).get("ts_utc"))
    if not isinstance(historie, list) or ende is None:
        return None
    grenze = ende + datetime.timedelta(seconds=GNADE_S)
    for e in historie:
        if not isinstance(e, dict):
            continue
        wer = (e.get("actor") or {}).get("username") if isinstance(e.get("actor"), dict) else None
        t = _utc(e.get("timestamp"))
        if wer and (t is None or t > grenze) and GESICHTET & set(e.get("changes") or {}):
            return True
    return False


def gesetzt(vorher_tags, tag_ids, tagname_by_id, cur_vals, cfs, fname_by_id):
    """What this run changed itself: (KI tag names it added, {field name: value} it set to a new value).
    Stored in the trace for the next run's clean-up (vorlauf_kandidaten)."""
    tags = [tagname_by_id.get(t) for t in dict.fromkeys(tag_ids) if t not in vorher_tags and tagname_by_id.get(t)]
    felder = {fname_by_id[c["field"]]: c["value"] for c in cfs or ()
              if c["field"] in fname_by_id and c.get("value") is not None
              and (c["field"] not in cur_vals or _feldwert(cur_vals[c["field"]]) != _feldwert(c["value"]))}
    return tags, felder


def korrespondent_ergebnis(corr_info, bisher=None):
    """Der Name, der am Dokument stünde: aus „exakt='X'“, „gewählt='X'“, „NEU='X' (dry)“; bei
    „bestehenden behalten“ der bisherige; sonst None."""
    m = re.search(r"'(.*)'", str(corr_info or ""))
    if m:
        return m.group(1)
    return bisher if str(corr_info or "").startswith("bestehenden") else None


_KENNZAHL = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d{1,2}\.\d{1,2}\.(?:19|20)?\d{2}\b|\b\d{5,}\b")


# A billing month on its own ("Abrechnungsmonat 03.2005/2", "Bezüge 04/2000"), not the tail of a full date. Two
# correction slips of one day differ only in it (T-12: January and March 2005 were reported as copies).
_MONAT_JAHR = re.compile(r"(?<![\d.,/])(0?[1-9]|1[0-2])\s?[./]\s?((?:19|20)\d{2})(?![\d.,])")


def kennzahlen(text):
    """Beträge, Daten, lange Ziffernfolgen und Abrechnungsmonate („MM/JJJJ“) — was zwei Fassungen desselben
    Dokuments gemeinsam haben."""
    t = str(text or "")
    return set(_KENNZAHL.findall(t)) | {f"{int(m):02d}/{j}" for m, j in _MONAT_JAHR.findall(t)}


def _ist_datum(z):
    """A date or billing month among the numbers of `kennzahlen`."""
    return bool(re.fullmatch(r"\d{1,2}\.\d{1,2}\.(?:19|20)?\d{2}|\d{2}/(?:19|20)\d{2}", z))


# "Seite 2 von 3"; the OCR reads "von" also as "van"/"v0n" (T-11).
SEITENANGABE = re.compile(r"(?:Seite|Blatt|Page)\s*:?\s*(\d{1,2})\s*(?:v[o0a]n|/|of)\s*(\d{1,2})\b", re.IGNORECASE)


def teilstueck(text, seiten):
    """„Seite x von y“ im Text, das Dokument hat aber weniger als y Seiten → Hinweis, sonst None.

    Not when the text names every page 1 … y: then all pages are there, on fewer sheets — an overlong
    scan of two pages as one, or two pages printed on one sheet (T-11)."""
    angaben = [(int(a), int(b)) for a, b in SEITENANGABE.findall(str(text or ""))
               if 1 < int(b) <= 50 and int(a) <= int(b)]
    if not angaben:
        # The last page announces a next one (T-10: a payslip ended in „Fortsetzung nächste Seite“, page 2
        # was missing).
        return ("„Fortsetzung nächste Seite“ am Ende — die Folgeseite fehlt"
                if _FORTSETZUNG.search(str(text or "").strip()[-150:]) else None)
    y = max(b for _, b in angaben); n = seiten or 1
    if n >= y or {a for a, b in angaben if b == y} >= set(range(1, y + 1)):
        return None
    return f"„Seite … von {y}“, das Dokument hat {n} Seite(n)"


# Not "bitte wenden": forms print it on every front page, also on the last sheet (seen on a pension notice).
_FORTSETZUNG = re.compile(r"Fortsetzung\s+(?:auf\s+(?:der\s+)?)?(?:nächste|naechste|folgende)n?\s+Seite", re.IGNORECASE)


ANREDE = re.compile(r"^[ \t]*((?:sehr\s+geehrte[rs]?|liebe[rs]?|hallo|guten\s+tag)\b[^\n,]{0,60})", re.IGNORECASE | re.MULTILINE)


def anrede(text):
    """The salutation line ("Sehr geehrte Frau Muster"), normalised; "" if there is none."""
    m = ANREDE.search(str(text or ""))
    return norm(m.group(1)) if m else ""


def anreden(text):
    """Every salutation line of a text, normalised — a compilation of letters has one per letter."""
    return {norm(m.group(1)) for m in ANREDE.finditer(str(text or ""))}


def dublette(text, seiten, aehnliche):
    """Ein ähnliches Dokument mit denselben Beträgen/Daten, derselben Anrede und gleicher Seitenzahl → Hinweis.

    Until T-9 "almost the same numbers" (Jaccard ≥ 0.85) was enough, and form letters were reported: the
    same text sent to other recipients differs only in the salutation and a number or two (customer
    number, postcode). A copy has all of them in common."""
    z = kennzahlen(text)
    if len(z) < 5:
        return None
    a = anrede(text)
    for d in aehnliche or ():
        zd = kennzahlen(d.get("content"))
        # Both need numbers: three birth dates and a postcode shared with a form of the same wording are no
        # evidence (T-12: two powers of attorney in opposite directions were reported as copies).
        if (len(zd) >= 5 and anrede(d.get("content")) == a and (d.get("page_count") or 1) == (seiten or 1)
                and gleiche_kennzahlen(z, zd, ocr=True, einseitig=(seiten or 1) < 2)):
            return f"wie Dokument {d.get('id')} ({str(d.get('title') or '')[:50]})"
    return None


def gleiche_kennzahlen(a, b, ocr=False, einseitig=False):
    """The same document read twice: one set of numbers contains the other, and the larger has at most a few
    more (max(2, an eighth)). A scan and the digital original differ by what the OCR misread or dropped
    (T-11: a wage tax certificate and its scan, 15 of 17 numbers, the rest unread); a form letter to someone
    else has a number of its own and is no subset."""
    klein, gross = (a, b) if len(a) <= len(b) else (b, a)
    if klein <= gross and len(gross - klein) <= max(2, len(gross) // 8):
        return True
    # With `ocr` also two OCR readings of one paper (ocr_gleich). Until T-13 only from two pages on: a one-page
    # letter may differ from a copy of the same form in one number of its own (T-11). With `einseitig` the
    # differing numbers must look like misreadings: those of one side all have a near twin on the other
    # (ocr_zwillinge); a number of its own does not. A one-page payslip scanned from paper has 50 numbers and
    # misreads one or two (T-13: six such scans of digital originals were missed; over 1,700 documents no
    # false pair).
    return ocr and ocr_gleich(a, b) and (not einseitig or ocr_zwillinge(a, b))


OCR_GLEICH_AB = 15


def ocr_gleich(a, b):
    """The same paper scanned twice: each OCR misreads a few numbers of its own, so neither set contains the
    other (T-12: eleven tax notices scanned a second time, 88–98 % of the numbers shared). Both have at least
    OCR_GLEICH_AB numbers, share 88 % of the smaller set and 75 % of the union, and none of the differing
    numbers is a date or billing month: two editions of a form (a notice and its correction, two monthly
    statements) differ exactly there. Measured on 1,400 documents of one installation: of the multi-page
    pairs only the rescans."""
    if min(len(a), len(b)) < OCR_GLEICH_AB:
        return False
    gemeinsam = len(a & b)
    return (gemeinsam >= 0.88 * min(len(a), len(b)) and gemeinsam >= 0.75 * len(a | b)
            and not any(_ist_datum(z) for z in a ^ b))


def _abstand(a, b):
    """Edit distance (insert, delete, replace) of two short strings."""
    vorher = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        jetzt = [i]
        for j, y in enumerate(b, 1):
            jetzt.append(min(vorher[j] + 1, jetzt[j - 1] + 1, vorher[j - 1] + (x != y)))
        vorher = jetzt
    return vorher[-1]


def _zwilling(z, andere):
    """Has the number `z` a near twin among `andere`: at most two digits read differently, or (from six digits)
    a cut-off reading of the same number?"""
    dz = re.sub(r"\D", "", z)
    for y in andere:
        dy = re.sub(r"\D", "", y)
        if min(len(dz), len(dy)) >= 3 and _abstand(dz, dy) <= 2:
            return True
        if min(len(dz), len(dy)) >= 6 and (dz in dy or dy in dz):
            return True
    return False


def ocr_zwillinge(a, b):
    """The numbers only one side has look like OCR misreadings: every one of one side has a near twin on the
    other side, and what the other side has beyond that (what this OCR dropped) stays within the tolerance of
    `gleiche_kennzahlen` (max(2, an eighth)). Two letters of one form with a number each of their own
    (1234567, 7654321), or one with three numbers more, are no copy (T-11)."""
    nur_a, nur_b = a - b, b - a
    grenze = max(2, max(len(a), len(b)) // 8)
    for eins, anderes in ((nur_a, nur_b), (nur_b, nur_a)):
        if all(_zwilling(z, anderes) for z in eins) and sum(not _zwilling(z, eins) for z in anderes) <= grenze:
            return True
    return False


TEILKOPIE_AB = 8


def teilkopie(text, seiten, aehnliche):
    """A document with fewer pages whose numbers (at least TEILKOPIE_AB) all appear in a longer one → hint.
    Partial copies (pages 1–2 of a four-page notice, scanned again on their own) were found by eye only (T-11).
    A salutation, if this one has one, must be one of the longer document's: a compilation of letters has one per
    letter, not only the first (T-13: an employment contract inside a 48-page folder of the employer's letters)."""
    z = kennzahlen(text)
    if len(z) < TEILKOPIE_AB:
        return None
    a, n = anrede(text), seiten or 1
    for d in aehnliche or ():
        nd = d.get("page_count") or 1
        if n < nd and z <= kennzahlen(d.get("content")) and (not a or a in anreden(d.get("content"))):
            return f"Teil von Dokument {d.get('id')} ({n} von {nd} Seiten; {str(d.get('title') or '')[:50]})"
    return None


def _suchzahlen(text, anzahl=2):
    """The most telling numbers of a text for a content search: amounts first, longest first."""
    return sorted((z for z in kennzahlen(text) if "/" not in z), key=lambda z: ("," in z, len(z), z),
                  reverse=True)[:anzahl]


def aehnliche_holen(did, text, holen=None):
    """Candidates for a copy: Paperless' "more like this" plus a content search for the two most telling
    numbers (T-11: a scan and its digital original were not among the five most similar texts). Without
    the document itself; a failed search is left out."""
    holen = holen or get
    felder = "&fields=id,title,content,page_count"
    pfade = [f"/documents/?more_like_id={did}&page_size=5" + felder]
    pfade += [f"/documents/?page_size=10&content__icontains={urllib.parse.quote(z)}" + felder for z in _suchzahlen(text)]
    gefunden = {}
    for p in pfade:
        try:
            r = holen(p)
        except Exception:
            continue
        for d in (r or {}).get("results") or []:
            if isinstance(d, dict) and d.get("id") is not None and str(d.get("id")) != str(did):
                gefunden.setdefault(d["id"], d)
    return list(gefunden.values())


def typ_in(typ, namen):
    """Is the document type one of `namen`, regardless of spelling? A compound ending in a listed name of
    5+ letters counts too ("Mietkündigung" → Kündigung), as in typ_zuordnen."""
    f = _typ_falte(typ)
    return bool(f) and any(f == g or (len(g) >= 5 and f.endswith(g)) for g in map(_typ_falte, namen or ()) if g)


def sammeldokument(treffer, ausser=None, typ=None, ausnahmen=()):
    """Harte Kennungen von mindestens drei verschiedenen Korrespondenten → Zusammenstellung.

    Not for the types in `ausnahmen`: a bank or credit card statement lists the IBANs of everyone who was
    paid, by nature (T-9: every statement was flagged)."""
    if typ_in(typ, ausnahmen):
        return None
    namen = [c["name"] for c, _ in treffer if c.get("id") != ausser]
    return f"Belege von {len(namen)} Absendern ({', '.join(namen[:4])})" if len(namen) >= 3 else None

def titel_ohne_eigenen_kopf(title, korrespondent, typ=None):
    """Der Titel ohne das, was ein früherer Lauf selbst vorangestellt hat: den Korrespondenten
    („Google – …“) und dahinter den Dokumenttyp („… – Vollmacht Unterrichtsvereinbarung“).

    Beides stammt aus der letzten Zuordnung, nicht aus dem Dokument. In der Vorsuche fand ein
    erneuter Lauf so den eigenen Namen „im Briefkopf“, in der Nachricht an Pass 1 übernahm die KI
    Korrespondent und Typ aus dem Titel — eine Fehlzuordnung bestätigte sich selbst (2026-10-10).
    Die Kennung bleibt, ebenso ein Titel von Paperless."""
    t, k = str(title or ""), str(korrespondent or "").strip()
    if not (k and t.startswith(k + " – ")):
        return t
    t = t[len(k) + 3:]
    ty = str(typ or "").strip()
    if ty and (t == ty or t.startswith(ty + " ")):
        t = t[len(ty):].strip()
    return t


# Unbelegte Altwerte (2026-10-14): ein Wert mit Ziffern, der im Text nicht vorkommt, stammt nicht
# sichtbar aus dem Dokument. Stand er als „aktuell“ im Prompt oder als Kennung im Titel, behielt die KI ihn —
# auch gegen frische OCR und einen ausdrücklichen Hinweis (eine Rechnung hieß „Rechnung 1205“, weil
# die ID ihres Ausgangsdokuments im Titel und im Feld stand). Geprüft werden nur Text- und
# Ganzzahlfelder mit mindestens drei Ziffern: Kennungen. Beträge und Datumsfelder stehen im Text in
# anderer Schreibweise, Wörter ohne Ziffern („VW Polo“) dürfen hergeleitet sein.
# Hart leeren wäre zu viel: gemessen an zwei Installationen fehlen je ~20 vermutlich richtige Nummern
# im OCR-Text (von Hand nachgetragen, anders gelesen). Deshalb: aus dem Titel der Nachricht nehmen,
# im Feld kennzeichnen, die Entscheidung bleibt bei der KI.
KENNUNG_FELDTYPEN = ("string", "longtext", "integer")
UNBELEGT_HINWEIS = ("(steht so NICHT im Text — vermutlich falsch; nur behalten, wenn er sich eindeutig aus dem "
                    "Dokument ergibt, sonst den Wert aus dem Text oder null)")


def text_schluessel(s):
    """Text ohne Schreibweise: nur Kleinbuchstaben und Ziffern, Umlaute gefaltet."""
    return norm(s).replace(" ", "")


def ist_kennung(wert):
    return len(re.findall(r"\d", str(wert or ""))) >= 3


def im_text_belegt(wert, schluessel):
    """Steht der Wert im Text (`schluessel` = text_schluessel(Inhalt))? Ein Lesefehler je acht
    Zeichen ist erlaubt — die OCR liest „J“ als „9“, und ein von Hand berichtigter Wert soll nicht
    als unbelegt gelten, nur weil der Text die Fehllesung trägt."""
    w = text_schluessel(str(wert or ""))
    if not w or w in schluessel:
        return True
    erlaubt, n = len(w) // 8, len(w)
    if not erlaubt:
        return False
    for i in range(len(schluessel) - n + 1):
        fehler = 0
        for a, b in zip(w, schluessel[i:i + n]):
            if a != b:
                fehler += 1
                if fehler > erlaubt:
                    break
        else:
            return True
    return False


def unbelegte_werte(cfields, cur_vals, fids, content):
    """{fid: wert} der Kennungsfelder unter `fids`, deren bisheriger Wert nicht im Text steht."""
    s = text_schluessel(content)
    typ = {f["id"]: f["data_type"] for f in cfields}
    return {fid: v for fid, v in cur_vals.items()
            if fid in fids and typ.get(fid) in KENNUNG_FELDTYPEN and ist_kennung(v) and not im_text_belegt(v, s)}


def titel_ohne_unbelegtes(title, content):
    """Der Titel für die Nachricht an Pass 1 ohne Kennungen, die im Text nicht vorkommen."""
    s = text_schluessel(content)
    teile = [t for t in str(title or "").split() if not (ist_kennung(t) and not im_text_belegt(t, s))]
    return re.sub(r"\s+", " ", " ".join(teile)).strip(" -–—:·|")

def titel_bilden(korrespondent, typ, kennung):
    """Der Titel aus dem Muster „Korrespondent – Dokumentart Kennung“ (PO 2026-09-27), etwa
    „Beispiel GmbH – Rechnung 12/2026“. Fehlt ein Teil, fällt er weg; ohne Dokumentart UND Kennung
    gibt es keinen Titel (None) — nur der Name wäre schlechter als der bisherige Titel.

    Die Kennung kommt von der KI; wiederholt sie Absender oder Dokumentart, fällt das weg (auch ein
    zusammengesetztes Wort wie „Ersatzteilrechnung“ bei einer Rechnung).
    Paperless erlaubt 128 Zeichen."""
    k = re.sub(r"\s+", " ", str(kennung or "")).strip(" -–—:·|")
    for vorn in (typ, korrespondent):
        if vorn and k.lower().startswith(str(vorn).lower()):
            k = k[len(vorn):].strip(" -–—:·|")
    # Wörter, die nur die Dokumentart wiederholen („Kaufvertrag“, „Ersatzteilrechnung“ bei Rechnung).
    t = str(typ or "").strip().lower()
    if t:
        k = " ".join(w for w in k.split() if not w.strip(",.;:").lower().endswith(t)).strip(" -–—:·|")
    rest = " ".join(x for x in (str(typ or "").strip(), k) if x)
    if not rest:
        return None
    t = f"{str(korrespondent).strip()} – {rest}" if str(korrespondent or "").strip() else rest
    return t[:128].rstrip()


# Der kleine Prompt von Pass 2 als Konstante: der Lauf benutzt ihn, und die Panel-Seite
# „Ablauf & Prompt" zeigt genau diesen Text. (Pass 0 entfiel am 2026-09-27.)
PASS2_SYSTEM = ('Du ordnest einen Absender bestehenden Korrespondenten zu. '
                'Antworte NUR JSON {"match": <exakter Name aus der Liste> ODER null}.')


def _aehnlich(a, b, grenze=0.85):
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= grenze


def _personenname(roh):
    """2–3 reine Wörter ohne Rechtsform — wie „Anna Zeller“, nicht „Klein Werkzeughandel GmbH“."""
    alle, kern = norm(roh).split(), ctoks(roh)
    return alle == kern and 2 <= len(kern) <= 3 and all(w.isalpha() and len(w) >= 2 for w in kern)


def _gleich(a, b):
    """Dasselbe Wort, Tippfehler nur bei langen Wörtern: ab 6 Zeichen reicht Ähnlichkeit 0,9
    („Neuhauserr“ = „Neuhauser“), kürzere müssen gleich sein — sonst wäre „Uber“ = „Huber“ und
    „Bundesnetzagentur“ = „Bundesagentur“ (gemessen 2026-09-27 an zwei echten Namenslisten)."""
    if a == b:
        return True
    return min(len(a), len(b)) >= 6 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


def _vorname_passt(a, b):
    """Gleicher Vorname, oder einer kürzt den anderen ab (Max/Maximilian, Alex/Alexander) — eine
    Abkürzung spart mindestens drei Buchstaben; „Engel“/„Engels“ ist keine."""
    k, l = sorted((a, b), key=len)
    return _gleich(a, b) or (len(k) >= 2 and l.startswith(k) and len(l) - len(k) >= 3)


def namens_aehnlichkeit(at, c, alias=None):
    """How close the proposed name (tokens `at`) is to correspondent `c`: word overlap or string similarity,
    the best over its name and its aliases. Until T-13 only the name counted: the OCR dropped the first letter of
    "Tabel Prozessdienste GmbH" (an alias of "Tabel GmbH"), the correspondent was not among the 20 closest names
    and a new one was created."""
    ak = " ".join(at)
    best = 0.0
    for nm in [c.get("name")] + [a for a in str((alias(c) if alias else "") or "").split(",") if a.strip()]:
        bt = ctoks(nm)
        if not at or not bt:
            continue
        ov = len(set(at) & set(bt)) / min(len(set(at)), len(set(bt)))
        best = max(best, ov, difflib.SequenceMatcher(None, ak, " ".join(bt)).ratio())
    return best


def pass2_plausibel(vorschlag, name, alias="", haeufigkeit=None):
    """Ist der Vorschlag eine Namensvariante dieses bestehenden Korrespondenten? (ja/nein, Grund)

    Seit 2026-09-27 (spät) entscheidet die Regel, OB Pass 2 überhaupt gefragt wird: nur Korrespondenten,
    die sie besteht, kommen in die Auswahl; besteht keiner, wird ohne zweiten KI-Aufruf neu angelegt.
    Allein zuordnen darf sie nicht — gemessen an zwei echten Namenslisten hätte sie 23 von 210 bzw. 37
    von 200 Namen einem anderen Korrespondenten zugeschlagen. Die Regeln, der Reihe nach:
      1. Steckt der Vorschlag im Kandidaten (jedes Wort; Tippfehler nur bei langen Wörtern): ja.
      2. Sind beide Personennamen: Nachname gleich UND Vorname gleich oder abgekürzt.
      3. Sonst: ein gemeinsames Wort ab 6 Zeichen, das selten ist — höchstens ein Korrespondent trägt
         es (`haeufigkeit`: Wort → Anzahl Korrespondenten). „Telekom“ ja, „Hamburg“, „Autohaus“ nein.
    Anlass: Pass 2 ordnete „Anna Berger“ „Anna Zeller“ zu und „Klein + Verbrauchsmaterial“ „Klein
    Werkzeughandel“; die Stammdaten-Erfassung trug dann IBAN, Mail und Adresse beim falschen ein."""
    a = ctoks(vorschlag)
    b = set(ctoks(name)) | {w for teil in str(alias or "").split(",") for w in ctoks(teil)}
    if not a or not b:
        return True, "nichts zu vergleichen"
    if all(any(_gleich(x, y) for y in b) for x in a):
        return True, "Vorschlag steckt im Namen"
    # The proposal starts with the whole name of the candidate (two words or more): the long form of a short
    # name, "Deutsche Bank Privat- und Geschäftskunden AG" for "Deutsche Bank" (T-13: rule 3 refused it, both
    # words are common, and a second Deutsche Bank was created). Pass 2 still decides.
    nb = ctoks(name)
    if len(nb) >= 2 and len(a) > len(nb) and all(_gleich(x, y) for x, y in zip(a, nb)):
        return True, "Name des Kandidaten steht am Anfang des Vorschlags"
    if _personenname(vorschlag) and _personenname(name):
        pa, pb = ctoks(vorschlag), ctoks(name)
        if not _gleich(pa[-1], pb[-1]):
            return False, "anderer Nachname"
        if not _vorname_passt(pa[0], pb[0]):
            return False, "anderer Vorname (nur der Nachname gleich)"
        return True, "gleicher Name"
    gemeinsam = sorted({y for x in a for y in b if _gleich(x, y)})
    if not gemeinsam:
        return False, "kein gemeinsames Wort"
    selten = [y for y in gemeinsam if len(y) >= 6 and (haeufigkeit is None or haeufigkeit.get(y, 0) <= 1)]
    if selten:
        return True, f"gemeinsam: {', '.join(selten)}"
    return False, f"nur kurzes oder häufiges gemeinsames Wort ({', '.join(gemeinsam)})"


# Words that say what someone is TO US, not who they are (T-15). On a page without a letterhead the model
# filled the gap with "Arbeitgeber", "PA" (Personalabteilung) or "AVG (Albatros Versicherungsdienst GmbH)"
# and a new correspondent was created each time. A new correspondent whose words are all of this list (legal
# forms and articles ignored) is not created; `allerweltsnamen` in the config extends the list.
ALLERWELTSNAMEN = frozenset("""
    absender abteilung adressat amt anwalt anwaeltin arbeitgeber arbeitgeberin arbeitnehmer arbeitsamt arzt aerztin
    auftraggeber auftragnehmer aussteller ausstellerin bank behoerde beratung betrieb buero dienstleister
    eigentuemer empfaenger empfaengerin familie finanzamt firma frau gemeinde gericht gesellschaft
    hausverwaltung haendler herr inkasso kanzlei kasse klinik krankenhaus krankenkasse krankenversicherung kunde
    kundin kundendienst kundenservice landkreis lieferant lieferantin lohnbuero mieter mieterin notar notariat
    partner personal personalabteilung personalbuero person post praxis privat privatperson rechtsanwalt
    rechtsanwaeltin rentenversicherung schule sparkasse stadt steuerberater steuerberaterin support team
    unbekannt unknown unternehmen vermieter vermieterin versicherer versicherung vertragspartner verwaltung
    verkaeufer zahlstelle
""".split())
# Articles and possessives around a role ("Mein Arbeitgeber", "Die Krankenkasse") carry no name either.
_FUELLWOERTER = frozenset("der die das den dem des ein eine einer eines mein meine meiner ihr ihre unser unsere "
                          "sein seine dein deine euer eure a an of my our your".split())
_RECHTSFORMEN = frozenset("gmbh ag kg ohg mbh ug kgaa se ev eg ltd llc inc sa srl sarl bv og gesmbh plc gbr".split())
_PLATZHALTER = re.compile(r"unbekannt|unknown|\bn\s*/\s*a\b|\?|^-+$|nicht\s+(?:erkennbar|lesbar|angegeben)", re.I)


def _flach(s):
    """`norm` with single spaces — for "does this phrase appear in the text"."""
    return " ".join(norm(s).split())


def klammer_erfunden(name, text):
    """A proposed name with a bracket the document does not print: (bracket, name without it), else None.

    "AVG (Albatros Versicherungsdienst GmbH)" — the model expanded a short name it found and invented the long
    form (T-15). The bracket goes; the short name is matched against the correspondents as usual. A bracket
    that IS in the text stays (a real name like "Concordia (Rechtsschutz)" printed so)."""
    m = re.search(r"\s*[(\[]([^()\[\]]*)[)\]]\s*", str(name or ""))
    if not m:
        return None
    innen = m.group(1).strip()
    if _flach(innen) and _flach(innen) in _flach(text):
        return None
    rest = re.sub(r"\s+", " ", (name[:m.start()] + " " + name[m.end():])).strip(" -–,")
    return innen, rest


def allerweltsname_grund(name, cfg):
    """Why `name` must not become a NEW correspondent (T-15), or None.

    Too short (fewer than `korrespondent_min_zeichen` letters/digits, default 3: "PA" — unless written with a legal
    form or a digit, "bc GmbH", "O2"), a
    placeholder ("unbekannt", "?"), or only a role or function ("Arbeitgeber", "Die Krankenkasse"; list
    ALLERWELTSNAMEN plus the config's `allerweltsnamen`, which may also hold whole names). Better no
    correspondent and a note than an invented one."""
    roh = str(name or "").strip()
    eigene = {_flach(x) for x in (cfg.get("allerweltsnamen") or []) if _flach(x)}
    if _PLATZHALTER.search(roh):
        return "Platzhalter statt Name"
    tok = [w for w in ctoks(roh) if w not in _FUELLWOERTER]
    try:
        mindest = int(cfg.get("korrespondent_min_zeichen", 3) or 0)
    except (TypeError, ValueError):
        mindest = 3
    # A short name with a legal form or a digit is a real one ("bc GmbH", "O2"); "PA" is not.
    if sum(len(w) for w in tok) < mindest and not (set(norm(roh).split()) & _RECHTSFORMEN or re.search(r"\d", roh)):
        return f"zu kurz (unter {mindest} Zeichen ohne Rechtsform)"
    if _flach(roh) in eigene or " ".join(tok) in eigene:
        return "steht auf der Liste allerweltsnamen"
    liste = ALLERWELTSNAMEN | {x for x in eigene if " " not in x}
    if all(w in liste for w in tok):
        return "nur eine Rolle oder Funktion, kein Name"
    # A role with an addition in brackets is still a role: "Vermieter (VE 38 Hebbelstraße 22)".
    aussen = [w for w in ctoks(re.sub(r"[(\[][^()\[\]]*[)\]]", " ", roh)) if w not in _FUELLWOERTER]
    if aussen and len(aussen) < len(tok) and all(w in liste for w in aussen):
        return "nur eine Rolle oder Funktion, der Klammerzusatz ist kein Name"
    return None


def namens_haeufigkeit(corrs, alias):
    """Wort → in wie vielen Korrespondenten (Name oder Alias) es vorkommt — für Regel 3 oben."""
    z = {}
    for c in corrs:
        for w in set(ctoks(c["name"])) | {w for teil in str(alias(c) or "").split(",") for w in ctoks(teil)}:
            z[w] = z.get(w, 0) + 1
    return z


def pass2_frage(name, kandidaten, beispiele=""):
    """Die Zuordnungsfrage, die an die Pass-1-Unterhaltung angehängt wird. `kandidaten`: je Kandidat
    eine Zeile mit Name, Aliasen und gespeichertem Kontext (seit 2026-09-27 — vorher nur Namen)."""
    liste = kandidaten if isinstance(kandidaten, str) else "\n".join("- " + k for k in kandidaten)
    return (f"{PASS2_SYSTEM}\nDein vorgeschlagener Absender: '{name}'.\n"
            f"Bestehende Korrespondenten, die in Frage kommen (Name exakt übernehmen):\n{liste}\n"
            "Welcher bezeichnet DIESELBE Firma/Behörde/Person wie im Dokument oben? Rechtsform/Zusätze "
            f"(GmbH/AG/OG) egal; auch OCR-/Tippfehler, Abkürzungen und Namensvarianten berücksichtigen{beispiele}. "
            "Namensvariante heisst: derselbe Name anders geschrieben — NICHT ein anderer Name mit gleichem "
            "Vornamen oder einem gleichen Allerweltswort (Anna Berger ist nicht Anna Zeller). "
            "Nur bei echter Übereinstimmung, sonst null.")


def _muster_trifft(muster, text):
    """A config pattern (regular expression, case-insensitive) in the text; a broken one counts as plain text."""
    try:
        return bool(re.search(muster, text, re.IGNORECASE))
    except re.error:
        return str(muster).lower() in text.lower()


def tag_ausschluss(tag_ids, vorhandene, tagid_by_norm, regeln, text):
    """The model's tags without those a rule excludes: (kept ids, {removed tag: excluding tag}).

    A rule {"tag": A, "ohne": [B, …], "ausser_text": [pattern, …]} drops B when A is on the document or among
    the model's tags, unless a pattern is in the text. Only the model's tags are dropped; what is already on
    the document stays (T-11: life and pension insurances got "Versicherungen" next to "Vorsorge")."""
    alle = set(tag_ids) | set(vorhandene or ())
    weg = {}
    for regel in regeln or ():
        if not isinstance(regel, dict):
            continue
        a = tagid_by_norm.get(norm(regel.get("tag") or ""))
        if not a or a not in alle:
            continue
        if any(_muster_trifft(m, str(text or "")) for m in _roh_liste(regel.get("ausser_text") or [])):
            continue
        for b in _roh_liste(regel.get("ohne") or []):
            bid = tagid_by_norm.get(norm(b))
            if bid and bid != a and bid in tag_ids:
                weg[bid] = regel.get("tag")
    return [t for t in tag_ids if t not in weg], weg


def reservierte_tags(cfg):
    """Tags, die die KI nie vergibt und die beim Schreiben erhalten bleiben (normalisiert):
    die konfigurierten plus Marker-, Unsicher- und Ausloeser-Tag."""
    reserved = {norm(x) for x in (cfg.get("reserved_tags") or [])}
    for extra in (cfg.get("marker_tag"), cfg.get("unsicher_tag"), cfg.get("kaputt_tag")):
        if extra:
            reserved.add(norm(extra))
    return reserved


FELD_ANWEISUNG = (
    "\nFülle im fields-Objekt JEDES unter VERFÜGBARE FELDER gelistete Feld mit GENAU einer Wahl: "
    "(a) korrekter Wert passend zum Typ; (b) null = leeren (Feld trifft sicher nicht zu ODER bestehender Wert ist falsch); "
    "(c) \"BEHALTEN\" = bestehenden Wert unverändert lassen, wenn du unsicher bist. "
    "Bei Auswahl-Feldern exakt ein gelistetes Label. "
    "needs_ocr NUR true, wenn der INHALT wirklich unlesbar ist (Zeichensalat, leer, offensichtlich kaputtes OCR); "
    "bei knappem, aber lesbarem Text (aus dem du Felder extrahieren konntest) IMMER false.")
ABSENDER_ANWEISUNG = (
    "\nGib ausserdem absender = Objekt mit den Kontaktdaten des GEGENÜBERS (der Partei, die nicht wir sind), "
    "so wie sie im Dokument stehen, sonst null je Feld: ustid, iban, email, telefon, adresse (einzeilig), "
    "kundennummer (die Nummer, unter der das Gegenüber UNS führt: Kunden-, Mitglieds-, Vertrags-, "
    "Versicherungs- oder Aktennummer — NICHT Personalnummer, Sozialversicherungsnummer oder "
    "Steuer-Identifikationsnummer). "
    "Und korrespondent_kontext = 1 kurzer Satz, was das Gegenüber ist (Art, Branche, Ort — etwa „Kfz-Werkstatt "
    "in Salzburg“), wenn es neu ist oder in den möglichen Korrespondenten kein [Kontext: …] trägt, sonst null.")


# Wer der Korrespondent ist, unabhängig vom eigenen Prompt (PO 2026-10-10): der, von dem das Dokument
# STAMMT — nicht jeder Name, der darin steht. Anlass: eine Zeugenaussage einer Privatperson, mit
# Google Docs geschrieben und über Documenso signiert, landete bei „Google“.
KORRESPONDENT_ANWEISUNG = (
    "\nWER IST DER KORRESPONDENT: der, von dem das Dokument STAMMT — in dessen Namen es geschrieben, ausgestellt "
    "oder verschickt wurde (Briefkopf, Absender, Aussteller, wer die Erklärung abgibt). Unterschreibt jemand für "
    "diese Stelle (Sachbearbeiter, Geschäftsführung, Ärztin einer Praxis), bleibt die Stelle der correspondent: "
    "ein Brief von Google mit der Unterschrift eines Mitarbeiters kommt von Google. Bei Firmen zählt die Marke, "
    "unter der sie auftreten (Logo, Website), nicht die Rechtsträgerin oder Mutterfirma dahinter. Wer im Text nur VORKOMMT, ist "
    "es nicht: das Werkzeug oder die Plattform, mit der das Dokument erstellt, signiert, gedruckt oder verschickt "
    "wurde (z. B. Google Docs, Word, Documenso, DocuSign, ein Mailprogramm), Empfänger, Zeugen, Dritte, Produkte, "
    "Zahlungswege und Firmen, über die nur berichtet wird. Ein Schreiben von jemand anderem, in dem „Google“ "
    "steht, ist kein Google-Dokument. Eine Erklärung, Zeugenaussage oder Bestätigung stammt von der Person, die "
    "sie abgibt und unterschreibt — auch wenn wir sie vorbereitet oder zur Unterschrift verschickt haben, etwa "
    "über eine Signaturplattform. Ebenso jedes Dokument, das wir selbst aufgesetzt haben und das eine andere "
    "Person unterschreibt oder mit uns schließt (Einverständniserklärung, Vereinbarung, Vertrag): correspondent ist "
    "diese andere Person, nicht wir — auch wenn wir im Kopf als Partei stehen. Lohn- und Gehaltsabrechnungen, "
    "Lohnsteuerbescheinigungen, Meldebescheinigungen zur Sozialversicherung und Arbeitszeitnachweise stammen vom "
    "ARBEITGEBER, auch wenn sein Name klein oder verstümmelt dasteht; Krankenkasse, Finanzamt oder "
    "Lohnbuchhaltungs-Software sind darin nur Angaben.")
# Das Dokumentdatum, ebenfalls unabhängig vom eigenen Prompt (PO 2026-10-10): Paperless setzt beim Import
# das erste Datum im Text — bei Erklärungen und Verträgen oft ein Geburtsdatum.
TYP_ANWEISUNG = (
    "\ndokumentart = wie das Dokument sich selbst nennt oder was es ist, in 1 bis 3 eigenen Wörtern "
    "(z. B. „Zeugenaussage“, „Stromrechnung“). Danach document_type = der Eintrag aus DOKUMENTTYPEN, der dieses "
    "Dokument am genauesten trifft: ein spezieller Typ — auch über seine Beschreibung — geht einem Oberbegriff vor, "
    "der Oberbegriff nur, wenn es keinen genaueren gibt; nie ein Typ, der nur ähnlich klingt; null, wenn keiner passt.")
DATUM_ANWEISUNG = (
    "\ndocument_date (oberste Ebene der Antwort, nicht in fields) = der Tag, an dem DIESES Dokument entstanden "
    "ist: das Datum im Briefkopf bzw. das Ausstellungsdatum; trägt das Dokument keines, das Datum der "
    "Unterschrift (bei mehreren Unterschriften die letzte). NIE ein Geburtsdatum, eine Frist, ein Leistungs- "
    "oder Lieferzeitraum oder ein Tag, über den das Dokument nur berichtet. null, wenn es kein solches Datum gibt.")

# Die eingebaute Regel zum Gegenüber — für eine Firma. {ERSTER} = der erste eigene Name.
# Aufgeweicht 2026-09-27 (PO, nach der Stichprobe): „nie die eigene Firma" liess die KI bei internen
# Dokumenten (Lohnabrechnung, Überweisungsliste) auf die Bank ausweichen, deren Bankverbindung
# darauf steht. Jetzt: das Gegenüber, wenn es eines gibt — sonst wir selbst; eine Bank nur als
# Ausstellerin. Eine Installation ohne Firma (Haushalt) ersetzt sie über `eigene_regel`.
EIGENE_REGEL = (
    "correspondent ist das GEGENÜBER: bei eingehenden Dokumenten der Absender, bei unseren Dokumenten an Kunden "
    "(Ausgangsrechnung, Angebot, Kaufvertrag) der Empfänger. NUR bei internen Dokumenten ohne externes Gegenüber "
    "(Lohnabrechnung, Überweisungsliste, interne Aufstellung) ist die eigene Firma der correspondent — dann unter "
    "dem Namen {ERSTER}. Eine Bank ist nur correspondent, wenn sie das Dokument selbst ausgestellt hat "
    "(Kontoauszug, Schreiben der Bank), nicht weil ihre Bankverbindung darauf steht.")


def eigene_firma_anweisung(cfg):
    """Wer „wir" sind — damit die KI das Gegenüber sucht und nicht uns selbst, deren Name, UID und
    IBAN auf fast jedem Dokument stehen (PO 2026-09-27). Leer ohne eigene Namen.

    Kopf (wer wir sind) und Schluss (absender nie mit unseren Daten) sind fest; die Regel dazwischen
    kommt aus `eigene_regel`, sonst EIGENE_REGEL. Der Schluss bleibt auch bei eigener Regel stehen:
    ohne ihn trüge die Stammdaten-Erfassung unsere eigene IBAN beim Absender ein."""
    e = cfg.get("eigene_kennungen") or {}
    namen = [str(n).strip() for n in (e.get("namen") or []) if str(n).strip()]
    if not namen:
        return ""
    kenn = [f"USt-ID {u}" for u in (e.get("ustid") or [])] + [f"IBAN {i}" for i in (e.get("iban") or [])]
    kenn += [f"Mail {m}" for m in (e.get("email") or [])] + [f"Domain {d}" for d in (e.get("domains") or [])]
    regel = str(cfg.get("eigene_regel") or "").strip() or EIGENE_REGEL
    if cfg.get("_konto"):
        kopf = ("\nWICHTIG: Dieses Dokument liegt im Konto von " + namen[0]
                + (" (" + ", ".join(kenn) + ")" if kenn else "") + " — das ist WIR. Andere Personen, auch aus "
                "demselben Haushalt, sind für dieses Dokument ein Gegenüber wie jedes andere. ")
    else:
        kopf = ("\nWICHTIG: Dieses Archiv gehört " + " / ".join(namen)
                + (" (" + ", ".join(kenn) + ")" if kenn else "") + " — das sind WIR. ")
    return kopf + regel.replace("{ERSTER}", namen[0]) + " absender enthält NIE unsere eigenen Stammdaten."
TITEL_ANWEISUNG = (
    "\nGib ausserdem titel_kennung = was DIESES Dokument von anderen desselben Absenders und derselben Art "
    "unterscheidet, 1 bis 5 Wörter, OHNE Absender und OHNE Dokumentart (auch kein Wort, das nur die Art umschreibt, "
    "wie Ersatzteilrechnung oder Zahlungserinnerung). Bevorzugt die Nummer (Rechnungs-, Vertrags-, Aktenzeichen) "
    "oder den Zeitraum („12/2026“, „Mai 2026“); Gegenstand oder Betreff nur, wenn es beides nicht gibt. "
    "null, wenn das Dokument nichts Eindeutiges hergibt.")
SUMMARY_ANWEISUNG = (
    "\nGib ausserdem summary = TLDR, Länge an das Dokument angepasst: Rechnung/Beleg/kurzer Bescheid → 1 knapper Satz; "
    "Vertrag/Brief → 2-3 Sätze; langer Bericht → 4-6 Sätze. Keine Floskeln, direkt zur Sache.")


def pass1_system(cfg, types, tags_all, reserved, mit_summary):
    """Der System-Prompt von Pass 1, genau so, wie er an das Modell geht.

    Eine Funktion fuer den Lauf UND die Vorschau im Panel: zeigte die Vorschau einen selbst
    nachgebauten Prompt, saehe man dort etwas anderes als das, was die KI bekommt.
    """
    return "".join(t for t, _ in pass1_system_teile(cfg, types, tags_all, reserved, mit_summary))


def pass1_system_teile(cfg, types, tags_all, reserved, mit_summary):
    """pass1_system() in Stuecken (Text, Name des eingesetzten Teils oder None) — fuers Panel."""
    if cfg.get("tagging_enabled"):
        td = {**TAG_DESC, **(cfg.get("tag_descriptions") or {})}
        taglines = "\n".join(f"- {t['name']}: {td.get(t['name'], t['name'])}"
                             for t in tags_all if norm(t["name"]) not in reserved)
    else:
        taglines = None
    tpl = cfg.get("system_prompt") or DEFAULT_PROMPT
    teile = baue_system_teile(tpl, types, taglines, cfg.get("type_descriptions"))
    system = "".join(t for t, _ in teile)
    if "VERFÜGBARE FELDER" not in system and "VERFUEGBARE FELDER" not in system:
        teile.append((FELD_ANWEISUNG, "Feld-Anweisung (automatisch angehängt)"))
    teile.append((KORRESPONDENT_ANWEISUNG, "Wer der Korrespondent ist (immer angehängt)"))
    teile.append((DATUM_ANWEISUNG, "Dokumentdatum (immer angehängt)"))
    teile.append((TYP_ANWEISUNG, "Dokumentart vor dem Typ (immer angehängt)"))
    if eigene_firma_anweisung(cfg):
        teile.append((eigene_firma_anweisung(cfg), "Wir und das Gegenüber (automatisch angehängt, aus „Eigene Namen“"
                      + (" und „Regel zum Gegenüber“" if str(cfg.get("eigene_regel") or "").strip() else "") + ")"))
    if cfg.get("stammdaten_erfassen", True):
        teile.append((ABSENDER_ANWEISUNG, "Absender-Stammdaten (automatisch angehängt, weil „Stammdaten erfassen“ an ist)"))
    if cfg.get("titel_setzen", True):
        teile.append((TITEL_ANWEISUNG, "Titel (automatisch angehängt, weil „Titel setzen“ an ist)"))
    if mit_summary:
        teile.append((SUMMARY_ANWEISUNG, "Zusammenfassung (automatisch angehängt, weil ein Zusammenfassungs-Feld eingestellt ist)"))
    return teile


# Bis 2026-09-27: „wähle GENAU einen dieser Namen; nur wenn wirklich keiner passt einen neuen“ —
# das drängte die KI zur Liste. Ein ähnlicher, aber falscher Name wurde dann exakt übernommen und
# direkt zugeordnet (Pass 2 prüft nur Namen, die NICHT exakt passen). Jetzt: Angebot, keine Pflicht.
# Seit 2026-10-10: „passt“ heißt, das Dokument stammt von ihm — die Vorsuche findet auch Namen, die nur
# erwähnt werden (Werkzeug, Zahlungsweg), und die KI übernahm sie.
KAND_KOPF = ("MÖGLICHE KORRESPONDENTEN (bekannte Korrespondenten, die passen könnten — stammt das Dokument von "
             "einem davon, übernimm seinen Namen exakt im Feld correspondent; dass sein Name im Text steht, reicht "
             "nicht; sonst nenne den tatsächlichen Absender):")


def pass1_nachricht_teile(hinweis, cname, chint, kand_lines, mail_ktx, added, created, dateiname,
                          fieldspec, title, content, typ_vorschlag=None):
    """Die Nachricht je Dokument an Pass 1, in Stuecken (Text, eingesetzter Wert oder None,
    Bedingung des Blocks oder None). Der Lauf fuegt sie zusammen; das Panel zeigt dieselben
    Stuecke mit Beispielwerten und markiert, was eingesetzt wird und welcher Block nur manchmal
    kommt."""
    T = []
    if hinweis:
        w = "nur mit Hinweis vom KI-Knopf"
        T += [("WICHTIGER NUTZER-HINWEIS (was zuletzt falsch war — bitte korrigieren):\n", None, w),
              (hinweis, "Hinweis vom KI-Knopf", w), ("\n\n", None, w)]
    if chint:
        w = "nur wenn das Dokument schon einen Korrespondenten mit Kontext hat"
        # Bis 2026-10-10 „HINWEIS zum Korrespondenten '…'“ — das las sich wie eine Vorgabe, und eine
        # Fehlzuordnung bestätigte sich bei jedem erneuten Lauf selbst.
        T += [("BISHER ZUGEORDNETER KORRESPONDENT (kann falsch sein — nur behalten, wenn das Dokument von ihm stammt): '",
               None, w), (cname, "bisheriger Korrespondent", w), ("' — ", None, w),
              (chint, "Kontext aus seinen Stammdaten", w), ("\n\n", None, w)]
    if kand_lines:
        w = "nur wenn die Suche im Text (oder die Absender-Mail) Korrespondenten gefunden hat"
        T += [(KAND_KOPF + "\n", None, w), (kand_lines, "bis zu 10 Kandidaten, je mit Aliasen, Kontext und Fundstelle", w),
              ("\n\n", None, w)]
    if mail_ktx:
        w = "nur bei Dokumenten aus einer Mail"
        T += [("HERKUNFT-KONTEXT (Nachricht/Anschreiben zu diesem Dokument — für Absender und Einordnung nutzen):\n", None, w),
              (mail_ktx, "Text der Mail", w), ("\n\n", None, w)]
    T += [("METADATEN:\n- Hinzugefügt am: ", None, None), (added, "Datum", None),
          ("\n- Von Paperless beim Import geratenes Datum (das erste Datum im Text, oft ein Geburtsdatum — kein Beleg, "
           "document_date selbst im Dokument bestimmen): ", None, None), (created, "Datum", None),
          ("\n- Originaldateiname: ", None, None), (dateiname, "Dateiname", None)]
    if typ_vorschlag:
        w = "nur wenn Paperless schon einen Dokumenttyp gesetzt hat (Automatik oder Workflow)"
        T += [("\n- Dokumenttyp, von Paperless vorbelegt (nur ein Vorschlag, kann falsch sein): ", None, w),
              (typ_vorschlag, "bisheriger Dokumenttyp", w)]
    T += [("\n\nVERFÜGBARE FELDER (im fields-Objekt je Feld: Wert / null=leeren / \"BEHALTEN\"=unsicher):\n", None, None),
          (fieldspec, "je Feld: Name (Art), aktueller Wert", None),
          ("\n\nTITEL: ", None, None), (title, "Titel", None), ("\n\nINHALT:\n", None, None),
          (content, "Text des Dokuments", None)]
    return [t for t in T if t[0]]


def prompt_vorschau():
    """Fuer das Panel: der fertig eingesetzte System-Prompt gegen den aktuellen Bestand,
    plus die Einstellungen, die den Ablauf steuern. Liest nur, schreibt nichts."""
    types = {t["name"]: t["id"] for t in get("/document_types/?page_size=1000")["results"]}
    tags_all = get("/tags/?page_size=1000")["results"]
    cfields = get("/custom_fields/?page_size=200")["results"]
    summary_fid = resolve_field(cfields, CFG["summary_field"])
    # Entwurf aus dem Panel-Editor: dieselbe Rechnung mit dem noch nicht gespeicherten Prompt.
    # Leer heisst „eingebauter Prompt“, wie beim Speichern.
    cfg = CFG
    if "CLASSIFY_PROMPT_ENTWURF" in os.environ:
        cfg = {**CFG, "system_prompt": os.environ["CLASSIFY_PROMPT_ENTWURF"]}
    sys_teile = pass1_system_teile(cfg, types, tags_all, reservierte_tags(cfg), bool(summary_fid))
    bsp = "‹{}›".format
    nachricht = pass1_nachricht_teile(
        bsp("Hinweis, den jemand beim KI-Knopf eingegeben hat"), bsp("Korrespondent"),
        bsp("Kontext aus den Stammdaten"),
        "- " + bsp("Name") + " (auch: " + bsp("Aliase") + ") [Kontext: " + bsp("Kontext") + "] [gefunden: " + bsp("USt-ID …, Name im Text") + "]\n- …",
        bsp("Text der Mail"), bsp("JJJJ-MM-TT"), bsp("JJJJ-MM-TT"), bsp("Dateiname"),
        "- " + bsp("Feld") + " (" + bsp("Art") + "), aktuell: " + bsp("Wert") + "\n- …",
        bsp("Titel"), bsp(f"Text des Dokuments, bis {CFG['content_max_len']} Zeichen: Anfang und die letzten "
                          f"{CFG.get('content_end_len', 1000)}"), typ_vorschlag=bsp("Dokumenttyp"))
    return {
        "system": "".join(t for t, _ in sys_teile),
        "system_teile": sys_teile,
        "nachricht_teile": nachricht,
        "platzhalter": PLATZHALTER,
        "vorlage": cfg.get("system_prompt") or DEFAULT_PROMPT,
        "standard": DEFAULT_PROMPT,
        "pass2_frage": pass2_frage(bsp("Absender laut Pass 1"), bsp("ähnliche Korrespondenten, höchstens 20"),
                                   beispiel_text(CFG["korrespondent_beispiele"])),
        "eigener_prompt": bool(CFG.get("system_prompt")),
        "typen": len(types), "tags": len(tags_all), "felder": len(cfields),
        "ki_felder": [f["name"] for f in cfields
                      if f["id"] != summary_fid and f["name"] not in (CFG.get("manual_fields") or [])
                      and f.get("data_type") != "documentlink"
                      and norm(f["name"]) not in {norm(CFG.get(k) or "") for k in
                                                   ("mail_context_field", "mail_from_field")}],
        "einstellungen": {k: CFG.get(k) for k in (
            "model", "ocr_model", "temperature", "content_max_len", "ocr_enabled", "ocr_always",
            "tagging_enabled", "marker_tag", "unsicher_tag", "summary_field",
            "manual_fields", "nachbearbeitung")},
        "ocr_regeln": {k: v for k, v in ocr_regeln(CFG).items() if k != "schluesselwoerter"},
        "pass2_system": PASS2_SYSTEM,
    }


def resolve_field(cfields, name):
    if not name:
        return None
    return next((f["id"] for f in cfields if norm(f["name"]) == norm(name)), None)


def main():
    did = os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID")
    if not did:
        return
    if not TOK:
        # Laut scheitern statt still zurueckzukehren: ein fehlender Token ist ein
        # Konfigurationsfehler, kein ueberspringbares Dokument. Exit 2 macht ihn im
        # post-consume-Log von Paperless sichtbar, statt ihn in einer Logzeile zu begraben.
        log("FEHLER: PAPERLESS_TOKEN nicht gesetzt (ENV)")
        raise SystemExit(2)
    if not CFG["enabled"] and not DRY:
        log(f"skip {did}: Klassifizierer im Panel deaktiviert"); return

    OCR_VERDACHT.clear()
    TRACE.pop("klassifiziert", None)      # set by THIS run only (save_trace keeps an earlier run's mark)
    doc = get(f"/documents/{did}/")
    global CFG_LAUF
    CFG_LAUF = konto_cfg(CFG, doc.get("owner"))
    if CFG_LAUF.get("_konto"):
        TRACE["konto"] = CFG_LAUF["_konto"]
    content = doc.get("content") or ""
    title = doc.get("title") or ""
    tag_ids_on = list(doc.get("tags", []))

    tags_all = get("/tags/?page_size=1000")["results"]
    tagname_by_id = {t["id"]: t["name"] for t in tags_all}
    tagid_by_norm = {norm(t["name"]): t["id"] for t in tags_all}

    marker_id = resolve_tag(tagid_by_norm, CFG["marker_tag"])
    unsicher_id = resolve_tag(tagid_by_norm, CFG["unsicher_tag"])
    kaputt_id = resolve_tag(tagid_by_norm, CFG.get("kaputt_tag"))

    # Ein Teil aus dem Aufteilen trägt Marker, Titel und Feldwerte seines Ausgangsdokuments (erbe_verwerfen).
    erbe = erbe_offen(doc, TRACE_DIR)
    wie_import = os.environ.get("CLASSIFY_WIE_IMPORT") == "1"
    if erbe or wie_import:
        TRACE["erbe"] = {"ausgangsdokument": teildokument_von(doc.get("original_file_name")),
                         "verworfen": {"titel": title or None, "korrespondent": doc.get("correspondent"),
                                       "typ": doc.get("document_type"), "datum": (doc.get("created") or "")[:10] or None,
                                       "felder": len(doc.get("custom_fields") or [])}}
        doc = erbe_verwerfen(doc)
        title = ""

    automatisch = not DRY and not FORCE and not FORCE_OCR
    if automatisch and not erbe and schon_klassifiziert(CFG, marker_id, tag_ids_on, did):
        log(f"skip {did}: schon klassifiziert ("
            + (f"Marker '{CFG['marker_tag']}')" if (CFG.get("marker_tag") or "").strip() else "Trace-Marke)")); return
    if automatisch and not SOURCE and CFG.get("mail_context_field") and any(
            c.get("value") in (None, "") for c in (doc.get("custom_fields") or [])) and wartet_auf_mail(
            doc, get("/custom_fields/?page_size=1000")["results"], CFG["mail_context_field"]):
        log(f"skip {did}: wartet auf den Nachlauf des Mail-Imports (Feld '{CFG['mail_context_field']}' leer)"); return
    mark_running(did, "Start")

    reserved = reservierte_tags(CFG)

    # --- OCR-Rescue: schwacher/Müll-Text → Mistral-OCR ---
    ocr_note = ""
    set_stage(did, "OCR-Rescue")
    TRACE["ocr"] = {"triggered": False, "grund": "Text ausreichend"}
    vorher = ocr_gruende(content, CFG)
    ocr_versucht = False
    # Blank pages BEFORE the OCR model sees them (T-10): on a blank page it invents text. Only when Paperless
    # read no text at all, and only where Ghostscript is at hand (in the Paperless container).
    leer = alle_seiten_leer(did, doc.get("page_count")) if len(content.strip()) < 20 else None
    if leer:
        TRACE["ocr"] = {"triggered": False, "grund": f"nicht nötig: {leer}"}
    elif CFG["ocr_enabled"] and not NO_OCR and (FORCE_OCR or CFG["ocr_always"] or vorher):
        ocr_versucht = True
        grund = ("KI-Knopf in Paperless" if FORCE_OCR and SOURCE == "knopf"
                 else "manuell erzwungen" if FORCE_OCR else "immer-OCR" if CFG["ocr_always"]
                 else "; ".join(vorher))
        try:
            new, erfunden = ocr_text_pruefen(mistral_ocr(did))
            if erfunden:
                OCR_VERDACHT.append(("alle", erfunden[0]))
            if not new:
                TRACE["ocr"] = {"triggered": True, "grund": grund, "verworfen": "OCR lieferte keinen echten Text"
                                + (f" ({erfunden[0]})" if erfunden else "")}
            elif FORCE_OCR or CFG["ocr_always"] or len(new) > max(len(content), 40) * 1.1 or (len(content) < 40 and len(new) > 40):
                if not DRY:
                    send(f"/documents/{did}/", {"content": new}, "PATCH")
                content = new; ocr_note = f"OCR-rescue({len(new)})"
                TRACE["ocr"] = {"triggered": True, "grund": grund, "chars": len(new), "excerpt": new[:8000]}
                log(f"OCR-rescue {did}: {len(new)} Zeichen")
            else:
                TRACE["ocr"] = {"triggered": True, "grund": grund, "verworfen": "neuer Text nicht besser", "chars": len(new)}
        except Exception as e:
            TRACE["ocr"] = {"triggered": True, "grund": grund, "error": repr(e)}
            log(f"OCR-rescue-fail {did}: {e!r}")

    if len(content.strip()) < 20:
        # No text, not even after OCR: a blank page or a broken scan. Until 0.4 the run ended here without a
        # trace on the document; now it is marked so that someone looks at it (T-10).
        log(f"skip {did}: kein Text nach OCR")
        befund = ({"leer": leer} if leer else
                  {"ocr_erfunden": "; ".join(f"{'OCR-Text' if n == 'alle' else f'Seite {n}'}: {g}" for n, g in OCR_VERDACHT)}
                  if OCR_VERDACHT else {"leer": "kein lesbarer Text, auch nicht nach OCR"})
        nur_markieren(did, doc, tag_ids_on, befund, marker_id, unsicher_id, kaputt_id)
        return

    types_roh = get("/document_types/?page_size=1000")["results"]
    types = {t["name"]: t["id"] for t in types_roh}
    corrs = get("/correspondents/?page_size=2000")["results"]
    cfields = get("/custom_fields/?page_size=200")["results"]
    cur_vals = {c["field"]: c.get("value") for c in doc.get("custom_fields", [])}

    summary_fid = resolve_field(cfields, CFG["summary_field"])
    mailctx_fid = resolve_field(cfields, CFG["mail_context_field"])
    mailfrom_fid = resolve_field(cfields, CFG["mail_from_field"])
    # Felder, die NICHT von der KI gesteuert werden (behalten): Sonderfelder + manuelle Felder
    manual_fids = {resolve_field(cfields, n) for n in (CFG.get("manual_fields") or [])}
    skip_fids = {x for x in (summary_fid, mailctx_fid, mailfrom_fid, *manual_fids) if x}

    # Take back what the previous run set, if nobody has touched the classification since (T-9). Before
    # the prompt: the model must not see the old run's values as "current" and keep them.
    vorlauf_tags, vorlauf_felder = {}, {}
    TRACE["vorlauf"] = None
    if not erbe:
        try:
            with open(os.path.join(TRACE_DIR, f"{did}.json"), encoding="utf-8") as f:
                alt_trace = json.load(f)
        except (OSError, ValueError):
            alt_trace = None
        geschuetzt = reserved | personen_tags(os.environ.get("PANEL_ROUTE_PERSONS"))
        k_tags, k_felder = vorlauf_kandidaten(alt_trace, set(tag_ids_on), cur_vals, tagid_by_norm,
                                              {f["name"]: f["id"] for f in cfields}, geschuetzt)
        k_felder = {fid: n for fid, n in k_felder.items() if fid not in skip_fids}
        if k_tags or k_felder:
            try:
                hist = get(f"/documents/{did}/history/")
            except Exception:
                hist = None
            gesichtet = nach_lauf_gesichtet(alt_trace, hist)
            if gesichtet is False:
                vorlauf_tags, vorlauf_felder = k_tags, k_felder
                tag_ids_on = [t for t in tag_ids_on if t not in vorlauf_tags]
                for fid in vorlauf_felder:
                    cur_vals.pop(fid, None)
                TRACE["vorlauf"] = {"entfernt": {"tags": sorted(vorlauf_tags.values()), "felder": sorted(vorlauf_felder.values())}}
            else:
                TRACE["vorlauf"] = {"behalten": "seit dem letzten Lauf von Hand geändert" if gesichtet
                                    else "Änderungshistorie nicht lesbar"}

    _NL = chr(10)
    mail_ktx = (cur_vals.get(mailctx_fid) or "").strip() if mailctx_fid else ""
    mail_from = (cur_vals.get(mailfrom_fid) or "").strip() if mailfrom_fid else ""
    TRACE["mail"] = ({"from": mail_from or None, "hat_kontext": bool(mail_ktx)} if (mail_ktx or mail_from) else None)

    # Der Hinweis kommt vom KI-Knopf in Paperless (über das Panel), nicht aus einem Feld.
    hinweis = os.environ.get("CLASSIFY_HINWEIS", "").strip()

    # Korrespondent-Metadaten (Panel-Store, per ID an Paperless gebunden) fürs Prompt
    _c_by_id = {c["id"]: c for c in corrs}
    _c_by_norm = {norm(c["name"]): c for c in corrs}
    def _khint(nm):
        c = _c_by_norm.get(norm(nm)) if nm else None
        return cfull_hint(c) if c else ""
    cname = (_c_by_id.get(doc.get("correspondent")) or {}).get("name") if doc.get("correspondent") else None
    chint = _khint(cname) if cname else ""
    TRACE["corr_hint"] = ({"korrespondent": cname, "hinweis": chint} if chint else None)

    # --- Vorsuche ohne KI: Kandidaten für Pass 1 (Pass 0 entfiel am 2026-09-27) ---
    # Pass 0 war ein eigener KI-Aufruf, nur um einen Absendernamen zu raten, aus dem dann
    # Kandidaten wurden. Die Kandidaten findet jetzt die Suche im Text selbst; den Absender
    # nennt Pass 1, und Abgleich/Pass 2 danach bleiben.
    set_stage(did, "Kandidaten")
    eigene = eigene_kennungen(CFG_LAUF)
    # 1. Passt die Absender-Mail zu genau einem Korrespondenten, ist er der stärkste Kandidat —
    #    aber keine Zuordnung: ein Portal verschickt Dokumente vieler Firmen von derselben Adresse
    #    (PO 2026-09-27). Entscheiden tut Pass 1 mit allen Funden.
    mail_corr, mail_grund = mail_zuordnung(corrs, cmeta, mail_from, eigene) if mail_from else (None, None)
    # 2. Trotzdem immer im Text suchen: Stammdaten (harte Kennungen), dann Namen und Aliase.
    _text = titel_ohne_eigenen_kopf(title, cname) + "\n" + content
    treffer = stammdaten_treffer(corrs, cmeta, _text, eigene)
    _text_namen = ohne_frankierung(_text)
    _gefunden = {}
    if mail_corr:
        _gefunden[mail_corr["id"]] = ["Absender-Mail"]
    for c, g in treffer[:6] + namens_treffer(corrs, calias, _text_namen, eigene["namen"])[:8]:
        _gefunden.setdefault(c["id"], []).extend(x for x in g if x not in _gefunden.get(c["id"], []))
    _by_id = {c["id"]: c for c in corrs}
    kand = [_by_id[i] for i in list(_gefunden)[:10]]
    def _kalias_c(c):
        a = calias(c)
        return (" (auch: " + a + ")") if a else ""
    def _im_dok(c):
        return (" [gefunden: " + ", ".join(_gefunden[c["id"]]) + "]") if c["id"] in _gefunden else ""
    kand_lines = _NL.join("- " + c["name"] + _kalias_c(c) + ((" [Kontext: " + cfull_hint(c) + "]") if cfull_hint(c) else "") + _im_dok(c) for c in kand)
    TRACE["vorsuche"] = {"mail": mail_grund, "mail_kandidat": mail_corr["name"] if mail_corr else None,
                         "kandidaten": {c["name"]: _gefunden[c["id"]] for c in kand} or None}
    TRACE["trigger"] = ("KI-Knopf mit Hinweis" if hinweis else "KI-Knopf in Paperless" if SOURCE == "knopf"
                        else "Bestands-Durchlauf" if SOURCE == "bulk"
                        else "Mail-Import (Nachlauf mit Mail-Kontext)" if SOURCE == "mail"
                        else "manuell (Panel)" if (FORCE or FORCE_OCR) else "automatisch (Post-Consume)")
    TRACE["hinweis"] = hinweis or None

    # KI-gesteuerte Felder (alles ausser documentlink + den optionalen Sonderfeldern)
    ai_flds = [f for f in cfields if f["id"] not in skip_fids and f["data_type"] != "documentlink"]
    # Kennungen, die nicht im Text stehen, als solche kennzeichnen (titel_ohne_unbelegtes). Sie bleiben
    # stehen, wenn die KI „BEHALTEN“ sagt: von Hand eingetragene Nummern fehlen oft im OCR-Text.
    unbelegt = unbelegte_werte(cfields, cur_vals, {f["id"] for f in ai_flds}, content)
    if unbelegt:
        _fname = {f["id"]: f["name"] for f in cfields}
        TRACE["unbelegt"] = {_fname[fid]: v for fid, v in unbelegt.items()}
    def fspec(f):
        t = f["data_type"]
        if t == "select":
            th = "Auswahl: " + " | ".join(o["label"] for o in (f.get("extra_data") or {}).get("select_options", []))
        else:
            th = {"string": "Text", "longtext": "Text", "integer": "Ganzzahl", "float": "Zahl",
                  "monetary": "Betrag mit der Währung des Dokuments als ISO-Code, z.B. EUR12.34 oder DEM1620.20 (DM)", "boolean": "true/false", "date": "YYYY-MM-DD", "url": "URL"}.get(t, t)
        cur = cur_vals.get(f["id"]); cur = sel_label(f, cur) if t == "select" else cur
        zusatz = f" {UNBELEGT_HINWEIS}" if f["id"] in unbelegt else ""
        return f"- {f['name']} ({th}), aktuell: {cur if cur not in (None, '') else '—'}{zusatz}"
    fieldspec = "\n".join(fspec(f) for f in ai_flds)

    set_stage(did, "Pass 1")
    system = pass1_system(CFG_LAUF, types, tags_all, reserved, bool(summary_fid))
    global CACHE_KEY
    CACHE_KEY = "paperlaiss-" + __import__("hashlib").sha256(system.encode("utf-8")).hexdigest()[:16]
    NUTZUNG.clear()
    TRACE["ki_nutzung"] = NUTZUNG
    schema1 = pass1_schema(types, [f["name"] for f in ai_flds], CFG["tagging_enabled"],
                           CFG.get("stammdaten_erfassen", True), bool(summary_fid), CFG.get("titel_setzen", True))
    _typ_bisher = next((n for n, i in types.items() if i == doc.get("document_type")), None)
    user_msg = "".join(t for t, _, _ in pass1_nachricht_teile(
        hinweis, cname, chint, kand_lines if kand else "", mail_ktx,
        (doc.get('added') or '')[:10], (doc.get('created') or '')[:10], dateiname_fuer_prompt(doc.get('original_file_name')),
        fieldspec, titel_ohne_unbelegtes(titel_ohne_eigenen_kopf(title, cname, _typ_bisher), content) or "—",
        text_kuerzen(ohne_frankierung(content), CFG['content_max_len'], CFG.get('content_end_len', 1000)),
        typ_vorschlag=_typ_bisher))
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user_msg}]
    prop, assistant_raw = mistral_chat(messages, 1200, schema1, "pass1")

    # OCR-Nachlauf: die KI hat den Text gesehen und haelt ihn fuer Muell (oder eine Regel nach
    # Pass 1 greift). Dann einmal per OCR neu lesen und Pass 1 in DERSELBEN Unterhaltung
    # wiederholen. Nur, wenn vor Pass 1 noch kein OCR lief — sonst zahlte man zweimal fuer
    # dasselbe Dokument. (Bis 2026-09-27 stand hier nur eine Meldung: der alte Zweig war
    # unerreichbar, weil er denselben Schalter pruefte, den der Lauf davor immer setzte.)
    nachher = ocr_nachhol_gruende(prop, CFG)
    if nachher:
        TRACE["ocr"]["nach_pass1"] = nachher
    if nachher and not ocr_versucht and CFG["ocr_enabled"] and not NO_OCR:
        set_stage(did, "OCR-Nachlauf")
        try:
            new, erfunden = ocr_text_pruefen(mistral_ocr(did))
            if erfunden:
                OCR_VERDACHT.append(("alle", erfunden[0]))
            if len(new) > 40:
                if not DRY:
                    send(f"/documents/{did}/", {"content": new}, "PATCH")
                content = new
                ocr_note = (ocr_note + " " if ocr_note else "") + f"OCR-nachgeholt({len(new)})"
                TRACE["ocr"].update({"triggered": True, "grund": "nach Pass 1: " + "; ".join(nachher),
                                     "chars": len(new), "excerpt": new[:8000]})
                log(f"OCR-nachgeholt {did}: {'; '.join(nachher)} → {len(new)} Zeichen")
                messages.append({"role": "assistant", "content": assistant_raw})
                messages.append({"role": "user", "content":
                    "Der Text war unbrauchbar. Hier der per OCR neu gelesene INHALT:\n"
                    f"{text_kuerzen(new, CFG['content_max_len'], CFG.get('content_end_len', 1000))}\n"
                    "Gib die vollständige Analyse (alle Felder, summary, document_date, correspondent, "
                    "tags) mit diesem Text erneut."})
                prop, assistant_raw = mistral_chat(messages, 1200, schema1, "pass1_nach_ocr")
            else:
                TRACE["ocr"]["nachlauf_verworfen"] = f"OCR lieferte nur {len(new)} Zeichen"
        except Exception as e:
            TRACE["ocr"]["nachlauf_fehler"] = repr(e)
            log(f"OCR-nachgeholt-fail {did}: {e!r}")
    TRACE["pass1"] = {"system": system, "user": user_msg[:4000], "response": prop}

    # --- Wir selbst als Korrespondent? Dann nach dem Empfänger fragen (2026-10-14) ---
    # Die eingebaute Regel sagt es schon („bei unseren Dokumenten an Kunden der Empfänger“), trotzdem nahm
    # die KI bei eigenen Ausgangsrechnungen 10 von 14 Mal uns selbst — der Briefkopf wiegt schwerer als die
    # Regel. Eine gezielte Rückfrage in derselben Unterhaltung trifft. Nur in diesem Fall, ein Aufruf mehr.
    if ist_eigener_name(prop.get("correspondent"), eigene["namen"]):
        frage = GEGENUEBER_FRAGE.format(NAME=prop.get("correspondent"))
        messages.append({"role": "assistant", "content": assistant_raw})
        messages.append({"role": "user", "content": frage})
        antwort, assistant_raw = mistral_chat(messages, 200, gegenueber_schema(), "gegenueber")
        # Die Anrede aus dem Adressblock („Herrn Max Muster“) gehört nicht zum Namen — die KI liess sie trotz
        # Anweisung einmal von 14 stehen, und „Frau X“ wäre ein zweiter Korrespondent neben „X“.
        emp = re.sub(r"^(?:Herrn?|Frau|Firma)\s+", "", ohne_tabellenrest(antwort.get("empfaenger")) or "").strip() or None
        TRACE["gegenueber"] = {"user": frage, "response": antwort}
        if emp and not ist_eigener_name(emp, eigene["namen"]):
            TRACE["gegenueber"]["vorher"] = prop.get("correspondent")
            prop["correspondent"] = emp
            # Der Absender aus Pass 1 beschreibt dann UNS (Briefkopf) — nie beim Kunden ablegen.
            prop["absender"] = {"adresse": antwort.get("adresse")} if antwort.get("adresse") else {}

    # --- Not the issuer: an own person (the addressee) or the health insurer named on an employer's form ---
    # One more question in the same conversation, as above (T-10: 21 payslips filed under the health insurer,
    # several forms under the owner). No answer → no correspondent from the model, and a finding.
    _typ_ki = prop.get("document_type") or prop.get("dokumentart")
    _nicht_aussteller = nicht_aussteller_grund(prop.get("correspondent"), _typ_ki, CFG_LAUF, CFG)
    _verworfen = None
    if _nicht_aussteller:
        frage = AUSSTELLER_FRAGE.format(NAME=prop.get("correspondent"), GRUND=_nicht_aussteller[1])
        messages.append({"role": "assistant", "content": assistant_raw})
        messages.append({"role": "user", "content": frage})
        antwort, assistant_raw = mistral_chat(messages, 200, aussteller_schema(), "aussteller")
        neu_k = re.sub(r"^(?:Herrn?|Frau|Firma)\s+", "", ohne_tabellenrest(antwort.get("aussteller")) or "").strip() or None
        TRACE["aussteller"] = {"vorher": prop.get("correspondent"), "grund": _nicht_aussteller[0], "user": frage,
                               "response": antwort}
        # The issuer data from pass 1 described the wrong party — never learn it for the new one.
        prop["absender"] = {}
        if neu_k and not nicht_aussteller_grund(neu_k, _typ_ki, CFG_LAUF, CFG):
            prop["correspondent"] = neu_k
        else:
            _verworfen = (_nicht_aussteller[0], f"„{prop.get('correspondent')}“ verworfen — {_nicht_aussteller[1]}")
            prop["correspondent"] = None

    # --- Korrespondent-Feedback-Loop ---
    set_stage(did, "Korrespondent")
    corr_name = ohne_tabellenrest(prop.get("correspondent"))
    corr_id = None; corr_info = "kein"; _gesperrt = None
    regel_k = korrespondent_aus_regel(corrs, content, eigene["namen"])
    if regel_k:
        # Feste Zuweisung gewinnt, VOR dem Abgleich — sonst legte der Lauf den Händler erst als neuen
        # Korrespondenten an. Was die KI vorschlug, bleibt im Trace.
        corr_id = regel_k["id"]; corr_info = f"zuweisung='{regel_k['name']}'"
        TRACE["correspondent"] = {"vorschlag": corr_name, "ergebnis": corr_info, "zuweisung": regel_k.get("match")}
        corr_name = regel_k["name"]
    elif corr_name:
        # An invented bracket ("AVG (Albatros Versicherungsdienst GmbH)", T-15) goes before matching — unless the
        # whole proposal is a known name or alias as it stands.
        _kl = klammer_erfunden(corr_name, content)
        if _kl and not any(_flach(c["name"]) == _flach(corr_name) for c in corrs) \
                and not alias_treffer(corr_name, corrs, calias):
            TRACE["klammer_verworfen"] = {"vorschlag": corr_name, "klammer": _kl[0], "weiter_mit": _kl[1]}
            corr_name = _kl[1] or None
    if not regel_k and corr_name:
        at = ctoks(corr_name); ak = " ".join(at)
        scored = sorted(((namens_aehnlichkeit(at, c, calias), c) for c in corrs), key=lambda x: -x[0])
        exact = next((c for s, c in scored if ak and " ".join(ctoks(c["name"])) == ak), None)
        # The name the model gave is a known ALIAS (T-10: a staffing agency's short name — the search had
        # found the correspondent by exactly that alias, the run still created a new one).
        per_alias = None if exact else alias_treffer(corr_name, corrs, calias)
        pass2 = None
        if exact:
            corr_id = exact["id"]; corr_info = f"exakt='{exact['name']}'"
        elif per_alias:
            corr_id = per_alias["id"]; corr_info = f"alias='{per_alias['name']}'"
        else:
            # Nur ähnliche Namen, die die Namensregel bestehen — sonst ohne zweiten KI-Aufruf neu anlegen
            # (bis 2026-09-27 fragte Pass 2 bei jeder Ähnlichkeit ab 0,28: 9 von 33 Läufen, davon 4 ohne
            # Treffer und 2 falsche Zuordnungen, die erst die Sperre danach abfing).
            _hf = namens_haeufigkeit(corrs, calias)
            aehnlich = [c for s, c in scored[:20] if s >= 0.28]
            cands, abgelehnt = [], []
            for c in aehnlich:
                ok, grund = pass2_plausibel(corr_name, c["name"], calias(c), _hf)
                (cands if ok else abgelehnt).append(c if ok else (c["name"], grund))
            if not cands and aehnlich:
                pass2 = {"uebersprungen": "kein ähnlicher Korrespondent besteht die Namensregel",
                         "abgelehnt": [f"{n} ({g})" for n, g in abgelehnt[:8]]}
            if cands:
                # Pass 2 als weitere Nachricht in DERSELBEN Unterhaltung wie Pass 1: die KI sieht
                # dabei das ganze Dokument und ihre eigene Analyse, nicht nur einen Namen. (Bis
                # 2026-09-27 ein eigener Aufruf mit nur dem Namen.) Die Schnittstelle hat kein
                # Gedächtnis — „dieselbe Unterhaltung" heißt: der Verlauf wird mitgeschickt.
                bsp_txt = beispiel_text(CFG["korrespondent_beispiele"])
                p2_usr = pass2_frage(corr_name, [c["name"] + _kalias_c(c) + ((" [Kontext: " + cfull_hint(c) + "]")
                                                                        if cfull_hint(c) else "") for c in cands], bsp_txt)
                messages.append({"role": "assistant", "content": assistant_raw})
                messages.append({"role": "user", "content": p2_usr})
                pick, assistant_raw = mistral_chat(messages, 200, pass2_schema(list(dict.fromkeys(c["name"] for c in cands))), "pass2")
                pass2 = {"user": p2_usr, "response": pick, "im_gespraech": True}
                pass2["abgelehnt"] = [f"{n} ({g})" for n, g in abgelehnt[:8]]
                m = pick.get("match")
                if m:
                    for c in cands:
                        if norm(c["name"]) == norm(m):
                            corr_id = c["id"]; corr_info = f"gewählt='{c['name']}'"
                            break
            if corr_id is None:
                # Kein erfundener Absender aus Zeichensalat: den bisherigen Korrespondenten nur
                # behalten, wenn die KI den Text SELBST als unlesbar meldet — sie hat ihn gelesen —
                # und niemand per Hinweis gesagt hat, wer es ist. Bis 2026-09-27 entschied das die
                # Faustregel bad_ocr() (Länge, Wortanteil): ein kurzer, frisch per OCR gelesener
                # Beleg (576 Zeichen) galt als „unsicher", der richtig erkannte neue Absender
                # wurde nicht angelegt — auch nicht mit ausdrücklichem Hinweis.
                if korrespondent_behalten(doc.get("correspondent"), prop.get("needs_ocr"), hinweis):
                    corr_id = doc["correspondent"]; corr_info = "bestehenden behalten (Text unsicher)"
                elif allerweltsname_grund(corr_name, CFG):
                    # Never create a role, a placeholder or two letters as a correspondent (T-15): none, and a note.
                    _grund = allerweltsname_grund(corr_name, CFG)
                    corr_info = f"gesperrt: {corr_name} ({_grund})"
                    _gesperrt = ("allerweltsname", f"Korrespondent „{corr_name}“ nicht angelegt — {_grund}; "
                                                   "bitte von Hand zuordnen")
                elif DRY:
                    corr_info = f"NEU='{corr_name}' (dry)"
                else:
                    nc = send("/correspondents/", {"name": corr_name}, "POST")
                    corr_id = nc["id"]; corr_info = f"NEU='{corr_name}'"
        TRACE["correspondent"] = {"vorschlag": corr_name, "ergebnis": corr_info, "pass2": pass2}

    # --- Tags (nur wenn Tagging aktiv) ---
    set_stage(did, "Tags & Schreiben")
    tag_ids, new_tags = [], []
    if CFG["tagging_enabled"]:
        for t in (prop.get("tags") or []):
            tid = tagid_by_norm.get(norm(t))
            if tid and norm(tagname_by_id[tid]) not in reserved:
                tag_ids.append(tid)
        new_tags = [t for t in (prop.get("new_tags") or []) if t and norm(t) not in tagid_by_norm]
        tag_ids, _tag_weg = tag_ausschluss(tag_ids, tag_ids_on, tagid_by_norm, CFG.get("tag_ausschluss"), content)
        if _tag_weg:
            TRACE["tags_verworfen"] = {tagname_by_id.get(t, t): f"schließt „{a}“ aus" for t, a in _tag_weg.items()}

    dt_id = typ_zuordnen(prop.get("document_type"), types) or typ_zuordnen(prop.get("dokumentart"), types)
    regel_typ = typ_aus_regel(types_roh, content)
    if regel_typ and regel_typ["id"] != dt_id:
        TRACE["typ_regel"] = {"typ": regel_typ["name"], "zuweisung": regel_typ["match"], "ki": prop.get("document_type")}
        dt_id = regel_typ["id"]
    dt = next((n for n, i in types.items() if i == dt_id), None) if dt_id else prop.get("document_type")
    summary = summary_aus(prop) if summary_fid else ""
    if new_tags and summary_fid:
        summary = (summary + f"\n\n[KI-Tag-Vorschlag: {', '.join(new_tags)}]").strip()

    # --- Stammdaten nachtragen: nur leere Felder, nur bei belastbarer Zuordnung ---
    stamm_info = ""
    pruefen = {}
    # Nicht bei fester Zuweisung: die KI beschreibt dann den Händler im Briefkopf, nicht die Plattform —
    # seine USt-ID und IBAN landeten sonst bei der Plattform.
    if (CFG.get("stammdaten_erfassen", True) and not corr_info.startswith("bestehenden behalten")
            and not corr_info.startswith("zuweisung")):
        quelle = f"KI · {datetime.date.today():%Y-%m-%d} · Dokument {did}"
        _mail = mail_from if mail_bestaetigt(mail_from, corr_id, mail_corr, _text, prop.get("absender")) else ""
        _anh = corr_info.startswith("exakt")
        _fremd = stammdaten_fremd(corrs, cmeta, corr_id)
        # Own persons are all of the household (the shared list), not only the owner of this document: the
        # entry of a household member collected 10 numbers from documents of the others (T-11).
        _wir_alle = {"namen": eigene_kennungen(CFG)["namen"] + eigene["namen"]}
        _belegt = stammdaten_belegt(corrs, cmeta, corr_id, _wir_alle)
        _eigen_person = bool(corr_id) and ist_eigene_person((_c_by_id.get(corr_id) or {}).get("name", ""), _wir_alle)
        # Count the spread of a new IBAN/phone number BEFORE taking the store lock: the search is an
        # HTTP call, and the panel waits on the same lock. A value not counted here counts as unknown.
        _verbr = {}
        _abs = prop.get("absender") if isinstance(prop.get("absender"), dict) else {}
        for _feld, _norm in (("iban", norm_iban), ("telefon", norm_telefon)):
            _roh = "" if is_null(_abs.get(_feld)) else ohne_tabellenrest(_abs.get(_feld))[:60]
            _w = _norm(_roh)
            _eigen = _w in eigene["iban"] or any(telefon_gleich(_w, x) for x in eigene.get("telefon", ()))
            if (_w and not _eigen
                    and not any(gleicher_wert(_feld, _w, x) for x in werte(cmeta(corr_id) if corr_id else {}, _feld))):
                _ids = korrespondenten_mit(_feld, _roh)
                _verbr[(_feld, _w)] = None if _ids is None else len(_ids | ({corr_id} if corr_id else set()))
        _verbreitet = lambda feld, w: _verbr.get((feld, norm_iban(w) if feld == "iban" else norm_telefon(w)))
        aenderung = lambda alt: stammdaten_nachtragen(alt, prop.get("absender"), _mail, eigene, quelle, _anh, _fremd,
                                                      prop.get("korrespondent_kontext"), _text, _verbreitet,
                                                      _belegt, _eigen_person)
        try:
            if corr_id and not DRY:
                g, v = stammdaten_schreiben(corr_id, aenderung)
            else:   # Trockenlauf oder neuer Korrespondent im Trockenlauf: nur zeigen
                _, g, v = aenderung(cmeta(corr_id) if corr_id else {})
            if mail_from and not _mail:
                v = {**v, "absender_mail": "nicht übernommen — gehört nicht erkennbar zu diesem Absender (Portal?)"}
            TRACE["stammdaten"] = {"geschrieben": g, "verworfen": v, "trocken": bool(DRY or not corr_id)}
            if g:
                stamm_info = " | stammdaten+" + ",".join(g)
            # Passen die Daten des Dokuments zum Korrespondenten? Eine Kennung, die einem ANDEREN gehört,
            # oder eine abweichende USt-ID spricht für eine Fehlzuordnung → zum Prüfen markieren (PO 2026-09-27).
            pruefen = {f: x for f, x in v.items() if x.startswith("gehört schon zu") or x.startswith("andere USt-ID")}
            TRACE["pruefen"] = pruefen or None
        except Exception as e:
            log(f"stammdaten-fail {did}: {e!r}")   # Klassifizierung läuft weiter
            TRACE["stammdaten"] = {"fehler": repr(e)}
    pruefen.update(pruef_befunde(did, doc, content, treffer, corr_id, dt))
    # The correspondent that will be on the document (also for the title below).
    if corr_id in _c_by_id:
        k_final = _c_by_id[corr_id]["name"]
    elif corr_id or corr_info.startswith("NEU"):
        k_final = corr_name
    else:
        k_final = cname
    ep = eigene_person_befund(k_final, dt, (CFG_LAUF.get("eigene_kennungen") or {}).get("namen"),
                              CFG.get("eigene_typen") or [])
    if ep:
        pruefen["eigene_person"] = ep
    fp = fremde_person_befund(content, (CFG_LAUF.get("eigene_kennungen") or {}).get("namen"),
                              CFG_LAUF.get("fremde_namen"))
    if fp:
        pruefen["fremde_person"] = fp
    for _b in (_verworfen, _gesperrt):
        if _b and _b[0] not in pruefen:
            pruefen[_b[0]] = _b[1]
    db = datum_befund(dokument_datum(prop), wirksames_datum(prop, content, doc), doc)
    if db:
        pruefen["datum"] = db
    TRACE["pruefen"] = pruefen or None

    # --- Titel: „Korrespondent – Dokumentart Kennung“, mit dem Korrespondenten und Typ, die tatsächlich
    # am Dokument stehen werden; überschrieben nur, wo auch der Typ überschrieben werden darf.
    titel_neu = None
    if CFG.get("titel_setzen", True) and (typ_ueberschreibbar(SOURCE, FORCE or FORCE_OCR) or erbe):
        _typ_id = typ_setzen(dt_id, doc.get("document_type"), True) or doc.get("document_type")
        titel_neu = titel_bilden(k_final, next((n for n, i in types.items() if i == _typ_id), None), prop.get("titel_kennung"))
        if titel_neu == doc.get("title"):
            titel_neu = None
        TRACE["titel"] = {"kennung": prop.get("titel_kennung"), "bisher": doc.get("title"), "neu": titel_neu}

    # The type that will be on the document decides which field proposals count (T-11).
    _typ_end = typ_setzen(dt_id, doc.get("document_type"), typ_ueberschreibbar(SOURCE, FORCE or FORCE_OCR)) \
        or doc.get("document_type")
    _typ_end_name = next((n for n, i in types.items() if i == _typ_end), None)
    flds, _feld_weg = felder_filtern(cfields, prop.get("fields") or {}, content, _typ_end_name, CFG)
    if _feld_weg:
        TRACE["fields_verworfen"] = _feld_weg
        log(f"felder-verworfen {did} | " + "; ".join(f"{k}: {x}" for k, x in _feld_weg.items()))

    if DRY:
        out = {"id": did, "title": titel_neu, "correspondent": corr_name, "corr_info": corr_info, "document_type": dt,
               "tags": [tagname_by_id.get(i) for i in tag_ids], "new_tags": new_tags,
               "summary": summary, "fields": flds, "fields_verworfen": _feld_weg or None,
               "tags_verworfen": TRACE.get("tags_verworfen"), "stammdaten": TRACE.get("stammdaten"),
               "document_date": wirksames_datum(prop, content, doc),
               "korrespondent_ergebnis": korrespondent_ergebnis(corr_info, cname), "datum_bisher": (doc.get("created") or "")[:10],
               "pruefen": pruefen or None, "vorlauf": TRACE.get("vorlauf"),
               "needs_ocr": prop.get("needs_ocr"), "ocr": ocr_note}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        log(f"DRY {did} | {corr_info} | typ={dt} | tags={[tagname_by_id.get(i) for i in tag_ids]} | {ocr_note}{stamm_info}"
            + (" | prüfen: " + "; ".join(f"{k} {x}" for k, x in pruefen.items()) if pruefen else ""))
        return

    # --- Zurückschreiben (KEIN owner/Rechte — macht post-consume.sh) ---
    extra = (([marker_id] if marker_id else []) + konto_tag_ids(CFG_LAUF, tagid_by_norm)
             + befund_tags(pruefen, unsicher_id, kaputt_id) + ([unsicher_id] if (new_tags and unsicher_id) else []))
    keep_tags = tag_ids_on + tag_ids + extra
    patch = {"tags": list(dict.fromkeys(keep_tags))}
    if corr_id:
        patch["correspondent"] = corr_id
    neuer_typ = typ_setzen(dt_id, doc.get("document_type"), typ_ueberschreibbar(SOURCE, FORCE or FORCE_OCR))
    if neuer_typ:
        patch["document_type"] = neuer_typ
    if titel_neu:
        patch["title"] = titel_neu

    date_note = None
    datum = wirksames_datum(prop, content, doc)
    if datum and (doc.get("created") or "")[:10] != datum:
        patch["created"] = f"{datum}T12:00:00+00:00"
        date_note = f"{(doc.get('created') or '?')[:10]} -> {datum}"
    code_flds = {}
    cfs, field_log = build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds)
    patch["custom_fields"] = cfs
    TRACE["writeback"] = {"document_type": dt, "title": patch.get("title"), "tags": [tagname_by_id.get(i) for i in tag_ids],
                          "new_tags": new_tags, "correspondent": corr_info,
                          "fields_ki": field_log, "summary": summary,
                          "document_date": patch.get("created"), "date_change": date_note}

    ok, err = patch_doc(did, patch)
    TRACE["repair"] = []; rounds = 0
    while not ok and not str(err).startswith(ZEIT) and rounds < 4:
        rounds += 1
        set_stage(did, f"Feld-Korrektur {rounds}")
        log(f"patch-fail {did} R{rounds}: {err[:100]}")
        messages.append({"role": "assistant", "content": assistant_raw})
        messages.append({"role": "user", "content":
            f"Beim Speichern nach Paperless kam dieser Fehler:\n{fehler_mit_feldnamen(err, cfs, cfields)}\n"
            "Korrigiere die betroffenen Feldwerte (nicht korrigierbare auf null) und gib NUR das JSON "
            "{\"fields\": {<Feldname>: <Wert|null>}} mit denselben Feldnamen zurück."})
        fix, assistant_raw = mistral_chat(messages, 900, name="korrektur")
        _fix, _fix_weg = felder_filtern(cfields, fix.get("fields") or {}, content, _typ_end_name, CFG)
        if _fix_weg:
            TRACE["fields_verworfen"] = {**(TRACE.get("fields_verworfen") or {}), **_fix_weg}
        flds = {**flds, **_fix}
        cfs, field_log = build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds)
        patch["custom_fields"] = cfs
        prev = err; ok, err = patch_doc(did, patch)
        TRACE["repair"].append({"round": rounds, "error": prev, "correction": fix.get("fields"), "ok": ok, "error_after": None if ok else err})
    TRACE["writeback"]["fields_ki"] = field_log
    repair_note = None
    if rounds:
        repair_note = f"repariert(R{rounds})" if ok else "repair-fehlgeschlagen"
        log(f"repariert {did} nach {rounds} Runde(n)" if ok else f"repair-fehlgeschlagen {did}")
    if not ok and not str(err).startswith(ZEIT):   # nach allen Runden Feldfehler → wenigstens ohne custom_fields
        patch.pop("custom_fields", None); patch_doc(did, patch)
    tg, fg = gesetzt(set(tag_ids_on), tag_ids, tagname_by_id, cur_vals, patch.get("custom_fields"),
                     {f["id"]: f["name"] for f in cfields})
    TRACE["writeback"].update({"tags_gesetzt": tg, "fields_gesetzt": fg,
                               "vorlauf_entfernt": (TRACE.get("vorlauf") or {}).get("entfernt")})
    if not ok and str(err).startswith(ZEIT):
        TRACE["writeback"]["fehler"] = err
        raise RuntimeError(f"Speichern nach Paperless nicht möglich: {err[:200]}")
    TRACE["klassifiziert"] = f"{datetime.datetime.now():%F %T}"

    log(f"OK {did} | {corr_info} id={corr_id} | typ={dt_id} | tags={[tagname_by_id.get(i) for i in tag_ids]} | new={new_tags} | {ocr_note}{stamm_info}"
        + (f" | datum {date_note}" if date_note else "")
        + (f" | typ per Zuweisung {TRACE['typ_regel']['typ']}" if TRACE.get("typ_regel") else "")
        + (f" | {repair_note}" if repair_note else ""))
    if pruefen:
        # Nach der OK-Zeile: die Aktivität zeigt es als „Prüfen“, bis ein späterer Lauf ohne Widerspruch folgt.
        log(f"PRÜFEN {did} | {corr_info} | " + "; ".join(f"{k} {x}" for k, x in pruefen.items()))
        if CFG.get("pruef_notiz"):
            try:
                notiz_setzen(did, befund_text(pruefen))
            except Exception as e:
                log(f"notiz-fail {did}: {e!r}")
    nachbearbeiten(did, patch, ok, TRACE.get("writeback") or {})
    TRACE["_stage"] = "fertig"
    save_trace(did)
    unmark_running(did)


# --- Master data from all documents of a correspondent (T-15, button in the correspondent dialog) ---
# paperlaiss learns master data only on the side, when a new document of the correspondent arrives; most
# correspondents of an existing collection stay empty. The button reads the documents, the model proposes, the
# rules of stammdaten_nachtragen decide, and the person confirms in the dialog — this mode writes nothing.

STAMM_DOKS = 30                 # documents read (newest first)
STAMM_KOPF, STAMM_FUSS = 2500, 600   # characters per document: letterhead and footer carry the master data
STAMM_GESAMT = 60000            # all excerpts together
STAMM_FELDER = ("adresse", "kontext", "aliase", "ustid", "iban", "email", "domains", "telefon", "kundennummer")
STAMM_FRAGE = (
    "Alle folgenden Dokumente stammen vom selben Absender: „{NAME}“. Ermittle seine Stammdaten.\n"
    "- Nur Werte, die WÖRTLICH in den Dokumenten stehen, und nur die des Absenders — nie die des Empfängers "
    "(wir: {WIR}), nie die einer Krankenkasse, Bank oder Behörde, die das Dokument nur nennt.\n"
    "- adresse: seine Postanschrift in einer Zeile. kontext: ein kurzer Satz, was das für eine Stelle ist "
    "(Branche, Ort, Rolle für uns). aliase: andere Schreibweisen SEINES Namens im Text (nicht der Name selbst).\n"
    "- kundennummer: Nummern, unter denen ER uns führt (Kunden-, Vertrags-, Mitgliedsnummer) — keine "
    "Personalnummer, keine Rechnungsnummer, keine Kostenstelle.\n"
    "- Was nicht im Text steht: null bzw. leere Liste. Antworte nur mit JSON.")


def stammdaten_schema():
    liste = {"type": "array", "items": {"type": "string"}}
    props = {"adresse": _NULLBAR("string"), "kontext": _NULLBAR("string"),
             **{f: liste for f in STAMM_FELDER if f not in ("adresse", "kontext")}}
    return {"type": "object", "properties": props, "required": list(STAMM_FELDER), "additionalProperties": False}


def stamm_auszuege(docs):
    """[(id, excerpt)] newest first: head and tail of each document, within STAMM_GESAMT."""
    aus, summe = [], 0
    for d in docs[:STAMM_DOKS]:
        t = str(d.get("content") or "").strip()
        if not t:
            continue
        a = t if len(t) <= STAMM_KOPF + STAMM_FUSS else t[:STAMM_KOPF] + "\n[…]\n" + t[-STAMM_FUSS:]
        if summe + len(a) > STAMM_GESAMT:
            break
        aus.append((d["id"], a)); summe += len(a)
    return aus


def _kompakt(s):
    return re.sub(r"[^0-9a-z@.]", "", unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower())


def stamm_fundstelle(wert, docs):
    """The first document whose text carries the value verbatim (spaces, line breaks and punctuation aside)."""
    k = _kompakt(wert)
    if len(k) < 3:
        return None
    return next((d for d in docs if k in _kompakt(d.get("content"))), None)


def alle_eigenen_kennungen(cfg):
    """Own identifiers of the whole household: the shared list plus every account (`konten`) — the button
    proposes for anyone's correspondent, and no account's own number may land at a counterpart."""
    e = {k: list(_roh_liste(v)) for k, v in (cfg.get("eigene_kennungen") or {}).items()}
    for konto in (cfg.get("konten") or {}).values():
        for k, v in (konto or {}).items():
            if k in ("namen", "email", "iban", "ustid", "domains", "telefon", "nummern"):
                e[k] = list(dict.fromkeys(e.get(k, []) + list(_roh_liste(v))))
    return eigene_kennungen({"eigene_kennungen": e})


def stammdaten_vorschlagen(korr, alt, antwort, docs, eigene, fremd=None, belegt=None, eigene_person=False):
    """The model's answer → proposals, by the rules of stammdaten_nachtragen. Pure.

    Each value must stand verbatim in one of the documents (that one is its source and its text decides —
    personnel number, VAT ID, IBAN check digit); own values of any account, values of another
    correspondent and values already stored are dropped. Single fields (address, context) already filled
    come as a replacement for the person to tick, never ticked in advance. Returns
    {"vorschlag": {feld: [{"wert", "dokument", "ersetzt"?}]}, "verworfen": {feld: [reason, …]}}."""
    acc, vorschlag, verworfen = dict(alt or {}), {}, {}
    ab = antwort if isinstance(antwort, dict) else {}

    def weg(feld, wert, grund):
        verworfen.setdefault(feld, []).append(f"{wert}: {grund}")

    def neu(feld, wert, d, ersetzt=None):
        if any(v["wert"] == wert for v in vorschlag.get(feld, [])):
            return
        vorschlag.setdefault(feld, []).append({"wert": wert, "dokument": d["id"], **({"ersetzt": ersetzt} if ersetzt else {})})

    for feld in STAMM_FELDER:
        roh = ab.get(feld)
        liste = [roh] if isinstance(roh, str) else (roh if isinstance(roh, list) else [])
        for w in (str(x).strip() for x in liste if not is_null(x)):
            if not w:
                continue
            if feld == "kontext":
                d0 = docs[0] if docs else {"id": None}
                if not str(acc.get("kontext") or "").strip():
                    neu("kontext", w[:300], d0)
                elif str(acc.get("kontext")).strip() != w:
                    neu("kontext", w[:300], d0, ersetzt=str(acc["kontext"]).strip())
                continue
            d = stamm_fundstelle(w if feld != "domains" else w.lower(), docs)
            if not d:
                weg(feld, w, "steht in keinem der Dokumente wörtlich")
                continue
            if feld == "aliase":
                if _flach(w) == _flach(korr.get("name")) or any(_flach(w) == _flach(a) for a in werte(acc, "aliase")):
                    continue
                if ist_eigene_person(w, eigene) or allerweltsname_grund(w, {}):
                    weg(feld, w, "eigener Name oder kein Name"); continue
                neu(feld, w, d); continue
            if feld == "domains":
                dom = w.lower().lstrip("@")
                if dom in FREEMAIL or _domain_passt(dom, eigene["domains"]):
                    weg(feld, w, "Freemail oder eigene Domain"); continue
                if any(dom == x.lower() for x in werte(acc, "domains")):
                    continue
                neu(feld, dom, d); continue
            if feld == "adresse" and str(acc.get("adresse") or "").strip():
                if _kompakt(acc["adresse"]) != _kompakt(w):
                    b = belegt("adresse", w) if belegt else None
                    if b:
                        weg(feld, w, b)
                    else:
                        neu(feld, w[:300], d, ersetzt=str(acc["adresse"]).strip())
                continue
            # The rules of the automatic run, with the source document's text.
            acc2, g, v = stammdaten_nachtragen(acc, {feld: w}, "", eigene, f"KI-Knopf · Dokument {d['id']}",
                                               anhaengen=True, fremd=fremd, text=d.get("content") or "",
                                               belegt=belegt, eigene_person=eigene_person)
            if g:
                acc = acc2
                for f2, w2 in g.items():                     # an e-mail brings its domain along
                    neu(f2, w2, d)
            elif v:
                for f2, grund in v.items():
                    weg(f2, w, grund)
    return {"vorschlag": vorschlag, "verworfen": verworfen}


def stammdaten_ermitteln(cid, doc_ids=None):
    """CLASSIFY_STAMMDATEN=<correspondent id> [CLASSIFY_STAMMDATEN_DOKS=<ids the person may see>]: read the
    documents, ask the model once, print the proposals as JSON. Writes nothing."""
    cid = int(cid)
    corrs = get("/correspondents/?page_size=2000")["results"]
    korr = next((c for c in corrs if c["id"] == cid), None)
    if not korr:
        return {"fehler": f"Korrespondent {cid} nicht gefunden"}
    if doc_ids is None:
        doc_ids = [d["id"] for d in get(f"/documents/?correspondent__id={cid}&ordering=-created&page_size={STAMM_DOKS}"
                                        "&fields=id")["results"]]
    docs = [get(f"/documents/{i}/") for i in list(doc_ids)[:STAMM_DOKS]]
    auszuege = stamm_auszuege(docs)
    if not auszuege:
        return {"korrespondent": korr["name"], "dokumente": 0, "vorschlag": {}, "verworfen": {}}
    eigene = alle_eigenen_kennungen(CFG)
    wir = ", ".join(n for n in (CFG.get("eigene_kennungen") or {}).get("namen") or []) or "—"
    frage = STAMM_FRAGE.format(NAME=korr["name"], WIR=wir)
    texte = "\n\n".join(f"=== Dokument {i} ===\n{a}" for i, a in auszuege)
    antwort, _ = mistral_chat([{"role": "system", "content": frage}, {"role": "user", "content": texte}],
                              1500, stammdaten_schema(), "stammdaten")
    erg = stammdaten_vorschlagen(korr, cmeta(cid), antwort, [d for d in docs if d["id"] in {i for i, _ in auszuege}],
                                 eigene, stammdaten_fremd(corrs, cmeta, cid),
                                 stammdaten_belegt(corrs, cmeta, cid, eigene), ist_eigene_person(korr["name"], eigene))
    return {"korrespondent": korr["name"], "dokumente": len(auszuege), **erg}


# --- Control run (T-10): the checks without the model, over documents already in Paperless ---
# A large manual review found by eye what the code can find alone: missing pages, blank pages, invented OCR
# text, copies, the owner as correspondent, the health insurer on a payslip. The control run looks for these
# on existing documents and flags them (kaputt/unsicher tag, note with the reason); it changes nothing else.

def kontroll_befunde(doc, korrespondent, typ, aehnliche, cfg_lauf, cfg):
    """Findings for one document as {key: reason}; empty when nothing is wrong. Pure (no I/O)."""
    b = {}
    content = str(doc.get("content") or "")
    if len(content.strip()) < 20:
        b["leer"] = "kein Text (leere Seite oder kaputter Scan?)"
    else:
        g = ocr_seite_verdaechtig(content, doc.get("page_count"))
        if g:
            b["ocr_erfunden"] = g
        t = teilstueck(content, doc.get("page_count"))
        if t:
            b["teilstueck"] = t
        andere = [x for x in aehnliche or () if x.get("id") != doc.get("id")]
        d = dublette(content, doc.get("page_count"), andere)
        if d:
            b["dublette"] = d
        tk = None if d else teilkopie(content, doc.get("page_count"), andere)
        if tk:
            b["teilkopie"] = tk
    fp = fremde_person_befund(content, (cfg_lauf.get("eigene_kennungen") or {}).get("namen"),
                              cfg_lauf.get("fremde_namen"))
    if fp:
        b["fremde_person"] = fp
    n = nicht_aussteller_grund(korrespondent, typ, cfg_lauf, cfg)
    if n:
        b[n[0]] = f"„{korrespondent}“ — {n[1]}"
    return b


def ids_lesen(text):
    """"1439-1442,1500" → [1439, 1440, 1441, 1442, 1500]."""
    ids = []
    for teil in str(text or "").replace(" ", "").split(","):
        if not teil:
            continue
        a, _, b = teil.partition("-")
        ids.extend(range(int(a), int(b) + 1) if b else [int(a)])
    return list(dict.fromkeys(ids))


def kontrolle(ids):
    """Run the checks over `ids`; flag what is found (not in a dry run). Returns {id: findings}."""
    tags_all = get("/tags/?page_size=1000")["results"]
    tagid_by_norm = {norm(t["name"]): t["id"] for t in tags_all}
    unsicher_id = resolve_tag(tagid_by_norm, CFG["unsicher_tag"])
    kaputt_id = resolve_tag(tagid_by_norm, CFG.get("kaputt_tag"))
    korr = {c["id"]: c["name"] for c in get("/correspondents/?page_size=2000")["results"]}
    typen = {t["id"]: t["name"] for t in get("/document_types/?page_size=1000")["results"]}
    konten, ergebnis = {}, {}
    for did in ids:
        try:
            doc = get(f"/documents/{did}/")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue            # deleted or in the trash
            raise
        aehnliche = aehnliche_holen(did, doc.get("content") or "")
        owner = doc.get("owner")
        if owner not in konten:
            konten[owner] = konto_cfg(CFG, owner)
        b = kontroll_befunde(doc, korr.get(doc.get("correspondent")), typen.get(doc.get("document_type")),
                             aehnliche, konten[owner], CFG)
        if not b:
            continue
        ergebnis[did] = b
        if DRY:
            continue
        neu = [t for t in befund_tags(b, unsicher_id, kaputt_id) if t not in (doc.get("tags") or [])]
        if neu:
            ok, err = patch_doc(did, {"tags": list(doc.get("tags") or []) + neu})
            if not ok:
                log(f"kontrolle-fail {did}: {str(err)[:200]}")
        if CFG.get("pruef_notiz"):
            notiz_setzen(did, befund_text(b))
        log(f"PRÜFEN {did} | Kontrolle | " + "; ".join(f"{k} {x}" for k, x in b.items()))
    return ergebnis


# Nur beim direkten Aufruf ausführen (Post-Consume / manuell / Panel). So bleibt das Modul
# importierbar — die Tests prüfen die reinen Hilfsfunktionen, ohne main() oder sys.exit auszulösen.
def ausfuehren():
    """Ein Lauf mit Fehlerbehandlung; liefert den Exit-Code.

    Ein Fehler wird immer protokolliert und im Trace vermerkt. Den Exit-Code bekommt er nur bei
    einem Aufruf mit CLASSIFY_DOC (Panel, KI-Knopf, Mail-Nachlauf): die werten ihn aus. Als
    Post-Consume-Skript (nur DOCUMENT_ID) bleibt es bei 0 — sonst meldete Paperless den Import als
    gescheitert, obwohl das Dokument längst gespeichert ist. Bis 2026-09-27 war es immer 0: ein
    gescheiterter KI-Knopf stand im Panel und in Paperless als „fertig" da."""
    try:
        main()
        return 0
    except Exception as e:
        eid = os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID") or "?"
        log(f"FEHLER {eid} | " + repr(e) + " | " + traceback.format_exc().replace("\n", " ")[:600])
        save_trace(None if eid == "?" else eid, {"error": repr(e), "traceback": traceback.format_exc()[:1500]})
        if voruebergehend(e) and eid != "?":
            abbruch_markieren(eid, e)
        return 2 if os.environ.get("CLASSIFY_DOC") else 0
    finally:
        unmark_running(os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID"))


if __name__ == "__main__":
    if os.environ.get("CLASSIFY_DUMP_CONFIG") == "1":
        wirksam = {k: v for k, v in CFG.items() if k in _BEKANNT and not k.startswith("api_key")}
        regeln = ocr_regeln(CFG)
        if (CFG.get("ocr_regeln") or {}).get("min_zeichen") is None:
            # Nicht eigens gesetzt: dann gilt ocr_min_len. Nicht als Wert ausgeben, sonst schriebe
            # ein Speichern im Panel die Zahl fest und ocr_min_len wirkte nie wieder.
            regeln.pop("min_zeichen")
        wirksam["ocr_regeln"] = regeln
        wirksam["eigene_kennungen"] = {"ustid": [], "iban": [], "domains": [], "email": [], "namen": [], **(CFG.get("eigene_kennungen") or {})}
        print(json.dumps(wirksam, ensure_ascii=False))
        sys.exit(0)
    if os.environ.get("CLASSIFY_PROMPT_VORSCHAU") == "1":
        print(json.dumps(prompt_vorschau(), ensure_ascii=False))
        sys.exit(0)
    if os.environ.get("CLASSIFY_DUMP_DEFAULTS") == "1":
        print(json.dumps({"system_prompt": DEFAULT_PROMPT, "tag_descriptions": TAG_DESC,
                          "model": CFG["model"], "ocr_model": CFG["ocr_model"], "ocr_min_len": CFG["ocr_min_len"],
                          "temperature": CFG["temperature"], "content_max_len": CFG["content_max_len"],
                          "ocr_always": CFG["ocr_always"], "tagging_enabled": CFG["tagging_enabled"]}, ensure_ascii=False))
        sys.exit(0)

    if os.environ.get("CLASSIFY_STAMMDATEN"):
        # CLASSIFY_STAMMDATEN=<correspondent> [CLASSIFY_STAMMDATEN_DOKS=1,2,3]: proposals only, nothing written (T-15).
        _doks = os.environ.get("CLASSIFY_STAMMDATEN_DOKS")
        print(json.dumps(stammdaten_ermitteln(os.environ["CLASSIFY_STAMMDATEN"],
                                              [int(x) for x in _doks.split(",") if x.strip().isdigit()] if _doks else None),
                         ensure_ascii=False))
        sys.exit(0)
    if os.environ.get("CLASSIFY_KONTROLLE"):
        # CLASSIFY_KONTROLLE="1439-1859,1900" [CLASSIFY_DRY=1]: checks only, no model (T-10).
        print(json.dumps(kontrolle(ids_lesen(os.environ["CLASSIFY_KONTROLLE"])), ensure_ascii=False, indent=1))
        sys.exit(0)

    sys.exit(ausfuehren())
    sys.exit(0)
