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
  CLASSIFY_FORCE=1             auch schon-klassifizierte (Marker-Tag) neu machen
  CLASSIFY_FORCE_OCR=1         Mistral-OCR erzwingen (+ content immer ersetzen)
  CLASSIFY_NO_OCR=1            OCR komplett aus (günstiger Bestandslauf)
  CLASSIFY_HINWEIS=<text>      Freitext des Nutzers, wenn der Anstoss ihn schon gelesen hat
  CLASSIFY_SOURCE=knopf|manual|bulk  Herkunft des Laufs (Trace/Log) — entscheidet auch, ob ein schon
                               gesetzter Dokumenttyp ersetzt werden darf: knopf/manual ja, leer (Import) nur
                               ohne CLASSIFY_FORCE, bulk und Handaufrufe mit CLASSIFY_FORCE nein
  CLASSIFY_DUMP_DEFAULTS=1     Default-Prompt/Config als JSON ausgeben (fürs Panel)
  CLASSIFY_PROMPT_VORSCHAU=1   fertig eingesetzten Pass-1-Prompt als JSON ausgeben (fürs Panel)
  CLASSIFY_DUMP_CONFIG=1       wirksame Config (Datei + Vorgaben, ohne Schlüssel) als JSON (fürs Panel)
"""
import os, sys, json, re, unicodedata, urllib.request, urllib.error, difflib, datetime, base64, traceback, tempfile, subprocess

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
    "marker_tag": "ai-processed",      # gesetzt nach Klassifizierung + Skip-Signal
    "unsicher_tag": "",                # optional: Flag-Tag bei Unsicherheit / KI-Tag-Vorschlag
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
    # Kennungen der eigenen Firma. Sie stehen auf fast jedem eingehenden Dokument (Empfänger-
    # block, Lastschrift) und dürfen nie einem Absender zugeschlagen werden; eine Mail von einer
    # eigenen Domain ist eine Weiterleitung und ordnet nichts zu.
    "eigene_kennungen": {"ustid": [], "iban": [], "domains": [], "email": [], "namen": []},
    "tag_descriptions": {},            # merged über TAG_DESC (nur relevant wenn tagging_enabled)
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
for _f in _STORE_FEHLER:
    log(f"STORE: {_f}")


def cmeta(cid):
    m = CORR_META.get(str(cid))
    return m if isinstance(m, dict) else {}


def cfull_hint(c):  # Kontext + harte Kennungen (Kundennr/UID) fürs KI-Grounding
    m = cmeta(c["id"]); parts = []
    if m.get("kontext"):
        parts.append(str(m["kontext"]).strip())
    if m.get("kundennummer"):
        parts.append("Kundennr " + str(m["kundennummer"]).strip())
    ustid = m.get("ustid") or m.get("uid")     # uid = Altname vor 2026-09-21
    if ustid:
        parts.append("UID " + str(ustid).strip())
    return "; ".join(p for p in parts if p)


def calias(c):
    return str(cmeta(c["id"]).get("aliase") or "").strip()


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


def norm_iban(v):
    s = re.sub(r"\s", "", str(v or "")).upper()
    return s if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s) else ""


def norm_mail(v):
    m = re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", str(v or ""))
    return m.group(0).lower() if m else ""


def eigene_kennungen(cfg):
    e = cfg.get("eigene_kennungen") or {}
    return {"ustid": {norm_ustid(x) for x in _liste(e.get("ustid"))} - {""},
            "iban": {norm_iban(x) for x in (e.get("iban") or []) if norm_iban(x)},
            "domains": set(_liste(e.get("domains"))),
            # Volle Adressen — für eine eigene Freemail-Adresse, deren Domain man nicht sperren kann.
            "email": {norm_mail(x) for x in _liste(e.get("email"))} - {""},
            # Namen der eigenen Firma: stehen im Empfängerblock jedes Dokuments. Ein Korrespondent,
            # dessen Name sie enthält, ist bei der Namenssuche kein Kandidat. Gemessen 2026-09-27 an
            # 16 Dokumenten: markiert statt ausgeschlossen füllte er fast jede Kandidatenliste, und die
            # KI griff öfter daneben; ausgeschlossen traf sie so oft wie mit Pass 0.
            "namen": [set(ctoks(n)) for n in (e.get("namen") or []) if ctoks(n)]}


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
    aus = []
    for c in corrs:
        m = meta(c["id"])
        gruende = []
        u = norm_ustid(m.get("ustid") or m.get("uid"))
        if u and u not in eigene["ustid"] and u in kompakt:
            gruende.append(f"USt-ID {u}")
        i = norm_iban(m.get("iban"))
        if i and i not in eigene["iban"] and i in kompakt:
            gruende.append("IBAN")
        for e in _liste(m.get("email")):
            if (norm_mail(e) and e in klein and e not in eigene["email"]
                    and not _domain_passt(e.split("@")[1], eigene["domains"])):
                gruende.append(f"Mail {e}")
        for d in _liste(m.get("domains")):
            if (d and "." in d and d not in FREEMAIL and not _domain_passt(d, eigene["domains"])
                    and re.search(r"(?:@|www\.|//)" + re.escape(d) + r"(?![a-z0-9-])", klein)):
                gruende.append(f"Domain {d}")
        k = str(m.get("kundennummer") or "").strip()
        if len(re.sub(r"\W", "", k)) >= 5 and re.search(r"(?<![0-9A-Za-z])" + re.escape(k) + r"(?![0-9A-Za-z])", str(text or "")):
            gruende.append(f"Kundennummer {k}")
        if gruende:
            aus.append((c, list(dict.fromkeys(gruende))))
    return sorted(aus, key=lambda x: -len(x[1]))


def namens_treffer(corrs, alias, text, eigene_namen=()):
    """Korrespondenten, deren Name oder Alias im Text steht: [(korrespondent, [Grund])].

    Alle Wörter des Namens (ohne Rechtsform, ab 3 Zeichen) müssen im Briefkopf vorkommen (den
    ersten 1000 Zeichen): unten stehen Bankverbindung und Zahlungsdienste, deren Namen sonst jede
    Rechnung zur Rechnung der Bank machten (2026-09-27, Stichprobe). Schwächer als eine Kennung,
    deshalb nur Kandidat für Pass 1. Längere Namen zuerst: „Muster Autoteile" sagt mehr als „Muster"."""
    # Zeilen mit Bankdaten zählen nicht: „Bank: Raiffeisenbank …" nennt, wo gezahlt wird, nicht wer
    # schreibt — bei kurzen Dokumenten rutscht die Fusszeile sonst in den Briefkopf (2026-09-27).
    kopf = "\n".join(z for z in str(text or "")[:1000].splitlines()
                     if not re.search(r"\b(IBAN|BIC|SWIFT|Bank|Bankverbindung|Konto|Kto)\b", z, re.IGNORECASE))
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


def stammdaten_nachtragen(alt, absender, mail_from, eigene, quelle):
    """Leere Stammdaten eines Korrespondenten aus dem Dokument füllen.

    Rein: bekommt den alten Eintrag, gibt (neuer Eintrag, geschrieben, verworfen) zurück.
    Überschreibt nie, übernimmt keine eigene Kennung und kein kaputtes Format, und merkt sich
    in `erfasst`, woher ein Wert stammt."""
    alt = dict(alt or {})
    neu, erfasst = dict(alt), dict(alt.get("erfasst") or {})
    geschrieben, verworfen = {}, {}
    ab = absender if isinstance(absender, dict) else {}
    wert = lambda k: "" if is_null(ab.get(k)) else str(ab.get(k)).strip()

    def leer(feld):
        if feld == "ustid":
            return not (alt.get("ustid") or alt.get("uid"))
        return not str(alt.get(feld) or "").strip()

    def setze(feld, w):
        if w and leer(feld) and feld not in geschrieben:
            neu[feld] = geschrieben[feld] = w
            erfasst[feld] = quelle

    roh = wert("ustid")
    if roh:
        u = norm_ustid(roh)
        if not u:
            verworfen["ustid"] = "kein USt-ID-Format"
        elif u in eigene["ustid"]:
            verworfen["ustid"] = "eigene USt-ID"
        else:
            setze("ustid", u)
    roh = wert("iban")
    if roh:
        i = norm_iban(roh)
        if not i:
            verworfen["iban"] = "kein IBAN-Format"
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
    tel = wert("telefon")[:60]
    if tel and len(re.sub(r"\D", "", tel)) >= 6:
        setze("telefon", tel)
    setze("adresse", wert("adresse")[:300])
    setze("kundennummer", wert("kundennummer")[:60])
    if geschrieben:
        neu["erfasst"] = erfasst
    return neu, geschrieben, verworfen


def stammdaten_schreiben(cid, aenderung):
    """correspondents.json unter Sperre neu lesen, ändern, atomar schreiben.

    Das Panel schreibt dieselbe Datei (Korrespondenten-Dialog), und mehrere Läufe können
    parallel laufen: ohne Sperre gewinnt, wer zuletzt schreibt, und die anderen Änderungen sind
    weg. Die Sperre ist flock auf einer Nachbardatei — sie gilt auch über Container hinweg,
    solange beide dasselbe Verzeichnis sehen. Eine kaputte Datei wird NICHT überschrieben."""
    import fcntl
    pfad = os.path.join(SCRIPT_DIR, "correspondents.json")
    with open(pfad + ".lock", "a") as sperre:
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

TRACE_DIR = os.path.join(os.path.dirname(LOG), "traces")
RUN_DIR = os.path.join(os.path.dirname(LOG), "running")
TRACE = {}


def schreibe_json(pfad, daten):
    """JSON atomar schreiben: erst in eine Nachbardatei, dann umbenennen.

    `json.dump(d, open(pfad, "w"))` kürzt die Zieldatei sofort auf null; bricht der Vorgang
    danach ab, steht dort eine halbe Datei. Bei einem Trace heisst das: die Panel-Ansicht
    zeigt kaputtes JSON statt des letzten brauchbaren Standes.
    """
    ordner = os.path.dirname(os.path.abspath(pfad)) or "."
    fd, tmp = tempfile.mkstemp(dir=ordner, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(daten, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
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
        if extra:
            t.update(extra)
        schreibe_json(os.path.join(TRACE_DIR, f"{did}.json"), t)
    except Exception as e:
        # NICHT still verschlucken. Bis 2026-09-21 stand hier `pass` — auf einer Instanz
        # entstanden dadurch ueber zwei Monate keine Traces, ohne dass es jemandem auffiel.
        # Ein Trace ist Diagnose, kein Selbstzweck: faellt er aus, muss man es SEHEN.
        log(f"trace-fail {did}: {e!r}")


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


def get(path, raw=False):
    req = urllib.request.Request(BASE + path, headers={"Authorization": f"Token {TOK}"})
    r = urllib.request.urlopen(req, timeout=45)
    return r.read() if raw else json.load(r)


def send(path, data, method="PATCH"):
    req = urllib.request.Request(BASE + path, data=json.dumps(data).encode("utf-8"),
        headers={"Authorization": f"Token {TOK}", "Content-Type": "application/json"}, method=method)
    return json.load(urllib.request.urlopen(req, timeout=45))


# Cache-Schlüssel für Mistrals Prompt-Caching (`prompt_cache_key`): zwischengespeicherte
# Präfix-Tokens kosten 10 % (https://docs.mistral.ai/studio-api/conversations/advanced/prompt-caching).
# Ein Schlüssel je System-Prompt —
# so trifft der Cache über Dokumente hinweg (gleicher System-Prompt) und innerhalb einer
# Unterhaltung (Pass 1 → OCR-Nachlauf → Pass 2 → Korrektur schicken denselben Anfang erneut).
CACHE_KEY = ""
# Nutzung je Aufruf (prompt/cached/completion) — fürs Trace, damit man sieht, ob der Cache trifft.
NUTZUNG = []


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
    r = json.load(urllib.request.urlopen(req, timeout=120))
    u = r.get("usage") or {}
    NUTZUNG.append({"name": name, "prompt": u.get("prompt_tokens"), "completion": u.get("completion_tokens"),
                    "cached": (u.get("prompt_tokens_details") or {}).get("cached_tokens")})
    raw = r["choices"][0]["message"]["content"]
    return json.loads(raw), raw


_NULLBAR = lambda t: {"type": [t, "null"]}


def pass1_schema(typen, feldnamen, mit_tags, mit_absender, mit_summary):
    """JSON-Schema der Pass-1-Antwort. Dokumenttyp als Auswahlliste (plus null), Felder als
    bekannte Schlüssel. `additionalProperties` bleibt offen: eigene Prompts verlangen teils
    weitere Schlüssel (summary_long, korrespondent_kontext), die sonst wegfielen. Ein gültiges
    Schema heisst nicht, dass die Werte stimmen — es garantiert den Aufbau."""
    wert = {"type": ["string", "number", "boolean", "null"]}
    props = {
        "document_type": {"type": ["string", "null"], "enum": sorted(typen) + [None]},
        "correspondent": _NULLBAR("string"),
        "fields": {"type": "object", "properties": {f: wert for f in feldnamen}, "additionalProperties": True},
        "document_date": _NULLBAR("string"),
        "needs_ocr": {"type": "boolean"},
    }
    pflicht = ["document_type", "correspondent", "fields", "needs_ocr"]
    if mit_summary:
        props["summary"] = _NULLBAR("string")
    if mit_tags:
        props["tags"] = {"type": "array", "items": {"type": "string"}}
        props["new_tags"] = {"type": "array", "items": {"type": "string"}}
    if mit_absender:
        props["absender"] = {"type": "object", "additionalProperties": False, "properties": {
            k: _NULLBAR("string") for k in ("ustid", "iban", "email", "telefon", "adresse", "kundennummer")}}
        pflicht.append("absender")
    return {"type": "object", "properties": props, "required": pflicht, "additionalProperties": True}


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


def mistral_ocr(did):
    pdf = get(f"/documents/{did}/download/", raw=True)  # Archiv = immer PDF (auch bei Bild-Originalen)
    b64 = base64.b64encode(pdf).decode()
    body = {"model": OCR_MODEL, "document": {"type": "document_url", "document_url": f"data:application/pdf;base64,{b64}"}}
    req = urllib.request.Request(MISTRAL_OCR, data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {KEY_OCR}", "Content-Type": "application/json"})
    resp = json.load(urllib.request.urlopen(req, timeout=180))
    return "\n\n".join(p.get("markdown", "") for p in resp.get("pages", [])).strip()


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
    "korrespondent_kontext (1 kurzer Satz: was ist dieser Absender / welche Dokumente kommen von ihm — nur bei NEUEM Korrespondent, sonst null), "
    "needs_ocr (true wenn Text unbrauchbar/Müll), "
    "fields (Objekt, siehe VERFÜGBARE FELDER). "
    "Ein Feld nur füllen, wenn das Dokument den Wert konkret hergibt — nichts hineinraten; im Zweifel null lassen. "
    "document_date = tatsächliches Ausstellungs-/Erstellungsdatum des Dokuments 'YYYY-MM-DD', NICHT nur im Text erwähnte/referenzierte Daten; null wenn unklar."
)


def is_null(raw):
    return raw is None or (isinstance(raw, str) and raw.strip().lower() in ("", "null", "none", "-", "—", "n/a", "kein", "unbekannt"))


def sel_label(f, val):
    for o in (f.get("extra_data") or {}).get("select_options", []):
        if o.get("id") == val:
            return o.get("label")
    return val


def coerce_field(f, v):
    t = f["data_type"]
    try:
        if t == "integer":
            s = re.sub(r"[^\d-]", "", str(v)); return int(s) if s not in ("", "-") else None
        if t == "float":
            return float(str(v).replace(",", ".").strip())
        if t == "monetary":
            m = re.search(r"\d+[.,]?\d*", str(v)); return "EUR" + m.group(0).replace(",", ".") if m else None
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


def patch_doc(did, patch):
    try:
        send(f"/documents/{did}/", patch, "PATCH")
        return True, None
    except urllib.error.HTTPError as e:
        try:
            return False, e.read().decode("utf-8", "replace")[:900]
        except Exception:
            return False, repr(e)
    except Exception as e:
        return False, repr(e)


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


def baue_system_teile(tpl, types, taglines):
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
    werte = {"TYPES": ", ".join(sorted(types)), "TAGBLOCK": tagblock, "TAGS": taglines}
    teile = []
    for i, stueck in enumerate(re.split(r"\{(TYPES|TAGBLOCK|TAGS)\}", tpl)):
        if i % 2:
            teile.append((werte[stueck], stueck))
        elif stueck:
            teile.append((stueck, None))
    if tagblock and "{TAGBLOCK}" not in tpl and "{TAGS}" not in tpl:
        teile.append(("\n" + tagblock, "TAGBLOCK (angehängt, weil der Prompt keinen Platzhalter hat)"))
    return teile


def typ_ueberschreibbar(source, force):
    """Darf dieser Lauf einen schon gesetzten Dokumenttyp ersetzen? Siehe typ_setzen().

    Ja beim KI-Knopf (`knopf`) und im Panel (`manual`), und beim echten Import: keine Quelle
    UND kein CLASSIFY_FORCE — nur dort kann der Typ ausschliesslich von der Paperless-Automatik
    stammen. Nein bei allem anderen: dem Bestands-Durchlauf (`bulk`) und jedem Handaufruf mit
    CLASSIFY_FORCE über vorhandene Dokumente, deren Typ ein Mensch gesetzt haben kann. Die sichere
    Seite ist „stehen lassen": eine unbekannte Aufrufart überschreibt nie (Prüfrunde 2026-09-27 —
    „alles ausser bulk" hätte den dokumentierten Handaufruf in einer Schleife überschreiben lassen)."""
    return source in ("knopf", "manual") or (source == "" and not force)


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


# Der kleine Prompt von Pass 2 als Konstante: der Lauf benutzt ihn, und die Panel-Seite
# „Ablauf & Prompt" zeigt genau diesen Text. (Pass 0 entfiel am 2026-09-27.)
PASS2_SYSTEM = ('Du ordnest einen Absender bestehenden Korrespondenten zu. '
                'Antworte NUR JSON {"match": <exakter Name aus der Liste> ODER null}.')


def pass2_frage(name, kandidaten, beispiele=""):
    """Die Zuordnungsfrage, die an die Pass-1-Unterhaltung angehängt wird."""
    return (f"{PASS2_SYSTEM}\nDein vorgeschlagener Absender: '{name}'.\n"
            f"Bestehende Korrespondenten, die in Frage kommen: {kandidaten}.\n"
            "Welcher bezeichnet DIESELBE Firma/Behörde/Person wie im Dokument oben? Rechtsform/Zusätze "
            f"(GmbH/AG/OG) egal; auch OCR-/Tippfehler, Abkürzungen und Namensvarianten berücksichtigen{beispiele}. "
            "Nur bei echter Übereinstimmung, sonst null.")


def reservierte_tags(cfg):
    """Tags, die die KI nie vergibt und die beim Schreiben erhalten bleiben (normalisiert):
    die konfigurierten plus Marker-, Unsicher- und Ausloeser-Tag."""
    reserved = {norm(x) for x in (cfg.get("reserved_tags") or [])}
    for extra in (cfg.get("marker_tag"), cfg.get("unsicher_tag")):
        if extra:
            reserved.add(norm(extra))
    return reserved


FELD_ANWEISUNG = (
    "\nFülle im fields-Objekt JEDES unter VERFÜGBARE FELDER gelistete Feld mit GENAU einer Wahl: "
    "(a) korrekter Wert passend zum Typ; (b) null = leeren (Feld trifft sicher nicht zu ODER bestehender Wert ist falsch); "
    "(c) \"BEHALTEN\" = bestehenden Wert unverändert lassen, wenn du unsicher bist. "
    "Bei Auswahl-Feldern exakt ein gelistetes Label. Zusätzlich document_date 'YYYY-MM-DD' = tatsächliches "
    "Dokumentdatum (NICHT nur referenzierte Daten); null wenn unklar. "
    "needs_ocr NUR true, wenn der INHALT wirklich unlesbar ist (Zeichensalat, leer, offensichtlich kaputtes OCR); "
    "bei knappem, aber lesbarem Text (aus dem du Felder extrahieren konntest) IMMER false.")
ABSENDER_ANWEISUNG = (
    "\nGib ausserdem absender = Objekt mit den Kontaktdaten des GEGENÜBERS (der Partei, die nicht wir sind), "
    "so wie sie im Dokument stehen, sonst null je Feld: ustid, iban, email, telefon, adresse (einzeilig), "
    "kundennummer (die Kundennummer, unter der das Gegenüber UNS führt).")


def eigene_firma_anweisung(cfg):
    """Wer „wir" sind — damit die KI das Gegenüber sucht und nicht die eigene Firma, deren Name,
    UID und IBAN auf fast jedem Dokument stehen (PO 2026-09-27). Leer ohne eigene Firmennamen."""
    e = cfg.get("eigene_kennungen") or {}
    namen = [str(n).strip() for n in (e.get("namen") or []) if str(n).strip()]
    if not namen:
        return ""
    kenn = [f"USt-ID {u}" for u in (e.get("ustid") or [])] + [f"IBAN {i}" for i in (e.get("iban") or [])]
    kenn += [f"Mail {m}" for m in (e.get("email") or [])] + [f"Domain {d}" for d in (e.get("domains") or [])]
    # Aufgeweicht 2026-09-27 (PO, nach der Stichprobe): „nie die eigene Firma" liess die KI bei internen
    # Dokumenten (Lohnabrechnung, Überweisungsliste) auf die Bank ausweichen, deren Bankverbindung
    # darauf steht. Jetzt: das Gegenüber, wenn es eines gibt — sonst wir selbst; eine Bank nur als
    # Ausstellerin.
    return ("\nWICHTIG: Dieses Archiv gehört " + " / ".join(namen)
            + (" (" + ", ".join(kenn) + ")" if kenn else "") + " — das sind WIR. correspondent ist das GEGENÜBER: "
            "bei eingehenden Dokumenten der Absender, bei unseren Dokumenten an Kunden (Ausgangsrechnung, Angebot, "
            "Kaufvertrag) der Empfänger. NUR bei internen Dokumenten ohne externes Gegenüber (Lohnabrechnung, "
            "Überweisungsliste, interne Aufstellung) ist die eigene Firma der correspondent — dann unter dem Namen "
            + namen[0] + ". Eine Bank ist nur correspondent, wenn sie das Dokument selbst ausgestellt hat "
            "(Kontoauszug, Schreiben der Bank), nicht weil ihre Bankverbindung darauf steht. "
            "absender enthält NIE unsere eigenen Stammdaten.")
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
    teile = baue_system_teile(tpl, types, taglines)
    system = "".join(t for t, _ in teile)
    if "VERFÜGBARE FELDER" not in system and "VERFUEGBARE FELDER" not in system:
        teile.append((FELD_ANWEISUNG, "Feld-Anweisung (automatisch angehängt)"))
    if eigene_firma_anweisung(cfg):
        teile.append((eigene_firma_anweisung(cfg), "Eigene Firma (automatisch angehängt, aus „Eigene Firmennamen“)"))
    if cfg.get("stammdaten_erfassen", True):
        teile.append((ABSENDER_ANWEISUNG, "Absender-Stammdaten (automatisch angehängt, weil „Stammdaten erfassen“ an ist)"))
    if mit_summary:
        teile.append((SUMMARY_ANWEISUNG, "Zusammenfassung (automatisch angehängt, weil ein Zusammenfassungs-Feld eingestellt ist)"))
    return teile


# Bis 2026-09-27: „wähle GENAU einen dieser Namen; nur wenn wirklich keiner passt einen neuen“ —
# das drängte die KI zur Liste. Ein ähnlicher, aber falscher Name wurde dann exakt übernommen und
# direkt zugeordnet (Pass 2 prüft nur Namen, die NICHT exakt passen). Jetzt: Angebot, keine Pflicht.
KAND_KOPF = ("MÖGLICHE KORRESPONDENTEN (bekannte Korrespondenten, die passen könnten — passt einer, "
             "übernimm seinen Namen exakt im Feld correspondent; sonst nenne den tatsächlichen Absender):")


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
        T += [("HINWEIS zum Korrespondenten '", None, w), (cname, "bisheriger Korrespondent", w), ("': ", None, w),
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
          ("\n- Aktuelles Dokumentdatum (evtl. falsch): ", None, None), (created, "Datum", None),
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

    doc = get(f"/documents/{did}/")
    content = doc.get("content") or ""
    title = doc.get("title") or ""
    tag_ids_on = list(doc.get("tags", []))

    tags_all = get("/tags/?page_size=1000")["results"]
    tagname_by_id = {t["id"]: t["name"] for t in tags_all}
    tagid_by_norm = {norm(t["name"]): t["id"] for t in tags_all}

    marker_id = resolve_tag(tagid_by_norm, CFG["marker_tag"])
    unsicher_id = resolve_tag(tagid_by_norm, CFG["unsicher_tag"])

    if marker_id in tag_ids_on and not DRY and not FORCE and not FORCE_OCR:
        log(f"skip {did}: schon klassifiziert (Marker '{CFG['marker_tag']}')"); return
    mark_running(did, "Start")

    reserved = reservierte_tags(CFG)

    # --- OCR-Rescue: schwacher/Müll-Text → Mistral-OCR ---
    ocr_note = ""
    set_stage(did, "OCR-Rescue")
    TRACE["ocr"] = {"triggered": False, "grund": "Text ausreichend"}
    vorher = ocr_gruende(content, CFG)
    ocr_versucht = False
    if CFG["ocr_enabled"] and not NO_OCR and (FORCE_OCR or CFG["ocr_always"] or vorher):
        ocr_versucht = True
        grund = ("KI-Knopf in Paperless" if FORCE_OCR and SOURCE == "knopf"
                 else "manuell erzwungen" if FORCE_OCR else "immer-OCR" if CFG["ocr_always"]
                 else "; ".join(vorher))
        try:
            new = mistral_ocr(did)
            if FORCE_OCR or CFG["ocr_always"] or len(new) > max(len(content), 40) * 1.1 or (len(content) < 40 and len(new) > 40):
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
        log(f"skip {did}: kein Text nach OCR"); return

    types = {t["name"]: t["id"] for t in get("/document_types/?page_size=1000")["results"]}
    corrs = get("/correspondents/?page_size=2000")["results"]
    cfields = get("/custom_fields/?page_size=200")["results"]
    cur_vals = {c["field"]: c.get("value") for c in doc.get("custom_fields", [])}

    summary_fid = resolve_field(cfields, CFG["summary_field"])
    mailctx_fid = resolve_field(cfields, CFG["mail_context_field"])
    mailfrom_fid = resolve_field(cfields, CFG["mail_from_field"])
    # Felder, die NICHT von der KI gesteuert werden (behalten): Sonderfelder + manuelle Felder
    manual_fids = {resolve_field(cfields, n) for n in (CFG.get("manual_fields") or [])}
    skip_fids = {x for x in (summary_fid, mailctx_fid, mailfrom_fid, *manual_fids) if x}

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
    eigene = eigene_kennungen(CFG)
    # 1. Passt die Absender-Mail zu genau einem Korrespondenten, ist er der stärkste Kandidat —
    #    aber keine Zuordnung: ein Portal verschickt Dokumente vieler Firmen von derselben Adresse
    #    (PO 2026-09-27). Entscheiden tut Pass 1 mit allen Funden.
    mail_corr, mail_grund = mail_zuordnung(corrs, cmeta, mail_from, eigene) if mail_from else (None, None)
    # 2. Trotzdem immer im Text suchen: Stammdaten (harte Kennungen), dann Namen und Aliase.
    _text = title + "\n" + content
    treffer = stammdaten_treffer(corrs, cmeta, _text, eigene)
    _gefunden = {}
    if mail_corr:
        _gefunden[mail_corr["id"]] = ["Absender-Mail"]
    for c, g in treffer[:6] + namens_treffer(corrs, calias, _text, eigene["namen"])[:8]:
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
                        else "manuell (Panel)" if (FORCE or FORCE_OCR) else "automatisch (Post-Consume)")
    TRACE["hinweis"] = hinweis or None

    # KI-gesteuerte Felder (alles ausser documentlink + den optionalen Sonderfeldern)
    ai_flds = [f for f in cfields if f["id"] not in skip_fids and f["data_type"] != "documentlink"]
    def fspec(f):
        t = f["data_type"]
        if t == "select":
            th = "Auswahl: " + " | ".join(o["label"] for o in (f.get("extra_data") or {}).get("select_options", []))
        else:
            th = {"string": "Text", "longtext": "Text", "integer": "Ganzzahl", "float": "Zahl",
                  "monetary": "Betrag z.B. EUR12.34", "boolean": "true/false", "date": "YYYY-MM-DD", "url": "URL"}.get(t, t)
        cur = cur_vals.get(f["id"]); cur = sel_label(f, cur) if t == "select" else cur
        return f"- {f['name']} ({th}), aktuell: {cur if cur not in (None, '') else '—'}"
    fieldspec = "\n".join(fspec(f) for f in ai_flds)

    set_stage(did, "Pass 1")
    system = pass1_system(CFG, types, tags_all, reserved, bool(summary_fid))
    global CACHE_KEY
    CACHE_KEY = "paperlaiss-" + __import__("hashlib").sha256(system.encode("utf-8")).hexdigest()[:16]
    NUTZUNG.clear()
    TRACE["ki_nutzung"] = NUTZUNG
    schema1 = pass1_schema(types, [f["name"] for f in ai_flds], CFG["tagging_enabled"],
                           CFG.get("stammdaten_erfassen", True), bool(summary_fid))
    user_msg = "".join(t for t, _, _ in pass1_nachricht_teile(
        hinweis, cname, chint, kand_lines if kand else "", mail_ktx,
        (doc.get('added') or '')[:10], (doc.get('created') or '')[:10], doc.get('original_file_name') or '—',
        fieldspec, title, text_kuerzen(content, CFG['content_max_len'], CFG.get('content_end_len', 1000)),
        typ_vorschlag=next((n for n, i in types.items() if i == doc.get("document_type")), None)))
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
            new = mistral_ocr(did)
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

    # --- Korrespondent-Feedback-Loop ---
    set_stage(did, "Korrespondent")
    corr_name = (prop.get("correspondent") or "").strip()
    corr_id = None; corr_info = "kein"
    if corr_name:
        at = ctoks(corr_name); ak = " ".join(at)
        def cscore(c):
            bt = ctoks(c["name"])
            if not at or not bt:
                return 0.0
            ov = len(set(at) & set(bt)) / min(len(set(at)), len(set(bt)))
            return max(ov, difflib.SequenceMatcher(None, ak, " ".join(bt)).ratio())
        scored = sorted(((cscore(c), c) for c in corrs), key=lambda x: -x[0])
        exact = next((c for s, c in scored if ak and " ".join(ctoks(c["name"])) == ak), None)
        pass2 = None
        if exact:
            corr_id = exact["id"]; corr_info = f"exakt='{exact['name']}'"
        else:
            cands = [c for s, c in scored[:20] if s >= 0.28]
            if cands:
                # Pass 2 als weitere Nachricht in DERSELBEN Unterhaltung wie Pass 1: die KI sieht
                # dabei das ganze Dokument und ihre eigene Analyse, nicht nur einen Namen. (Bis
                # 2026-09-27 ein eigener Aufruf mit nur dem Namen.) Die Schnittstelle hat kein
                # Gedächtnis — „dieselbe Unterhaltung" heißt: der Verlauf wird mitgeschickt.
                bsp_txt = beispiel_text(CFG["korrespondent_beispiele"])
                p2_usr = pass2_frage(corr_name, [c["name"] for c in cands], bsp_txt)
                messages.append({"role": "assistant", "content": assistant_raw})
                messages.append({"role": "user", "content": p2_usr})
                pick, assistant_raw = mistral_chat(messages, 200, pass2_schema(list(dict.fromkeys(c["name"] for c in cands))), "pass2")
                pass2 = {"user": p2_usr, "response": pick, "im_gespraech": True}
                m = pick.get("match")
                if m:
                    for c in cands:
                        if norm(c["name"]) == norm(m):
                            corr_id = c["id"]; corr_info = f"gewählt='{c['name']}'"; break
            if corr_id is None:
                if doc.get("correspondent") and bad_ocr(content):   # kein Halluzinat bei Müll-Text
                    corr_id = doc["correspondent"]; corr_info = "bestehenden behalten (Text unsicher)"
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

    dt = prop.get("document_type")
    dt_id = types.get(dt) or (next((v for k, v in types.items() if norm(k) == norm(dt)), None) if dt else None)
    summary = summary_aus(prop) if summary_fid else ""
    if new_tags and summary_fid:
        summary = (summary + f"\n\n[KI-Tag-Vorschlag: {', '.join(new_tags)}]").strip()

    # --- Stammdaten nachtragen: nur leere Felder, nur bei belastbarer Zuordnung ---
    stamm_info = ""
    if CFG.get("stammdaten_erfassen", True) and not corr_info.startswith("bestehenden behalten"):
        quelle = f"KI · {datetime.date.today():%Y-%m-%d} · Dokument {did}"
        _mail = mail_from if mail_bestaetigt(mail_from, corr_id, mail_corr, _text, prop.get("absender")) else ""
        aenderung = lambda alt: stammdaten_nachtragen(alt, prop.get("absender"), _mail, eigene, quelle)
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
        except Exception as e:
            log(f"stammdaten-fail {did}: {e!r}")   # Klassifizierung läuft weiter
            TRACE["stammdaten"] = {"fehler": repr(e)}

    if DRY:
        out = {"id": did, "correspondent": corr_name, "corr_info": corr_info, "document_type": dt,
               "tags": [tagname_by_id.get(i) for i in tag_ids], "new_tags": new_tags,
               "summary": summary, "fields": prop.get("fields"), "needs_ocr": prop.get("needs_ocr"), "ocr": ocr_note}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        log(f"DRY {did} | {corr_info} | typ={dt} | tags={[tagname_by_id.get(i) for i in tag_ids]} | {ocr_note}{stamm_info}")
        return

    # --- Zurückschreiben (KEIN owner/Rechte — macht post-consume.sh) ---
    extra = ([marker_id] if marker_id else []) + ([unsicher_id] if ((new_tags) and unsicher_id) else [])
    keep_tags = tag_ids_on + tag_ids + extra
    patch = {"tags": list(dict.fromkeys(keep_tags))}
    if corr_id:
        patch["correspondent"] = corr_id
    neuer_typ = typ_setzen(dt_id, doc.get("document_type"), typ_ueberschreibbar(SOURCE, FORCE or FORCE_OCR))
    if neuer_typ:
        patch["document_type"] = neuer_typ

    flds = prop.get("fields") or {}
    date_note = None
    dm = re.match(r"(\d{4})-(\d{2})-(\d{2})$", str(flds.get("document_date") or "").strip())
    if dm and 1950 <= int(dm.group(1)) <= 2035 and (doc.get("created") or "")[:10] != dm.group(0):
        patch["created"] = f"{dm.group(0)}T12:00:00+00:00"
        date_note = f"{(doc.get('created') or '?')[:10]} -> {dm.group(0)}"
    code_flds = {}
    cfs, field_log = build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds)
    patch["custom_fields"] = cfs
    TRACE["writeback"] = {"document_type": dt, "tags": [tagname_by_id.get(i) for i in tag_ids],
                          "new_tags": new_tags, "correspondent": corr_info,
                          "fields_ki": field_log, "summary": summary,
                          "document_date": patch.get("created"), "date_change": date_note}

    ok, err = patch_doc(did, patch)
    TRACE["repair"] = []; rounds = 0
    while not ok and rounds < 4:
        rounds += 1
        set_stage(did, f"Feld-Korrektur {rounds}")
        log(f"patch-fail {did} R{rounds}: {err[:100]}")
        messages.append({"role": "assistant", "content": assistant_raw})
        messages.append({"role": "user", "content":
            f"Beim Speichern nach Paperless kam dieser Fehler:\n{fehler_mit_feldnamen(err, cfs, cfields)}\n"
            "Korrigiere die betroffenen Feldwerte (nicht korrigierbare auf null) und gib NUR das JSON "
            "{\"fields\": {<Feldname>: <Wert|null>}} mit denselben Feldnamen zurück."})
        fix, assistant_raw = mistral_chat(messages, 900, name="korrektur")
        flds = {**flds, **(fix.get("fields") or {})}
        cfs, field_log = build_cfs(cfields, cur_vals, flds, summary, summary_fid, skip_fids, code_flds)
        patch["custom_fields"] = cfs
        prev = err; ok, err = patch_doc(did, patch)
        TRACE["repair"].append({"round": rounds, "error": prev, "correction": fix.get("fields"), "ok": ok, "error_after": None if ok else err})
    TRACE["writeback"]["fields_ki"] = field_log
    repair_note = None
    if rounds:
        repair_note = f"repariert(R{rounds})" if ok else "repair-fehlgeschlagen"
        log(f"repariert {did} nach {rounds} Runde(n)" if ok else f"repair-fehlgeschlagen {did}")
    if not ok:   # nach allen Runden weiter Fehler → wenigstens ohne custom_fields speichern
        patch.pop("custom_fields", None); patch_doc(did, patch)

    log(f"OK {did} | {corr_info} id={corr_id} | typ={dt_id} | tags={[tagname_by_id.get(i) for i in tag_ids]} | new={new_tags} | {ocr_note}{stamm_info}" + (f" | {repair_note}" if repair_note else ""))
    nachbearbeiten(did, patch, ok, TRACE.get("writeback") or {})
    TRACE["_stage"] = "fertig"
    save_trace(did)
    unmark_running(did)


# Nur beim direkten Aufruf ausführen (Post-Consume / manuell / Panel). So bleibt das Modul
# importierbar — die Tests prüfen die reinen Hilfsfunktionen, ohne main() oder sys.exit auszulösen.
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

    try:
        main()
    except Exception as e:
        eid = os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID") or "?"
        log(f"FEHLER {eid} | " + repr(e) + " | " + traceback.format_exc().replace("\n", " ")[:600])
        save_trace(None if eid == "?" else eid, {"error": repr(e), "traceback": traceback.format_exc()[:1500]})
    finally:
        unmark_running(os.environ.get("CLASSIFY_DOC") or os.environ.get("DOCUMENT_ID"))
    sys.exit(0)
