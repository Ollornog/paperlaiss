#!/usr/bin/env python3
"""Reine Logik des Export-Knopfs — ohne Netz, ohne PDF-Bibliothek, ohne FastAPI.

Der Export fügt die in Paperless markierten Dokumente zu einem PDF zusammen oder legt sie einzeln
ab (optional als ZIP), jeweils mit Inhaltsverzeichnis. Alles, was dabei eine Entscheidung trifft —
Auftrag prüfen, Leserechte auswerten, Dateinamen aus einer Vorlage bilden und entschärfen,
Kollisionen auflösen, sortieren, das Inhaltsverzeichnis auf Seiten verteilen —, steht hier. So
prüft es die stdlib-only-Suite (`tests/test_export.py`); `exportpdf.py` zeichnet und fügt nur noch
zusammen, `app.py` holt die Daten.
"""
import re
import unicodedata
from urllib.parse import quote, urlsplit

# Variablen der Dateinamen-Vorlage: Name, Beschreibung für den Dialog. Dazu {feld:Name} für
# benutzerdefinierte Felder aus Paperless.
VARIABLEN = (
    ("titel", "Titel"),
    ("korrespondent", "Korrespondent"),
    ("typ", "Dokumenttyp"),
    ("datum", "Ausstellungsdatum (JJJJ-MM-TT)"),
    ("jahr", "Jahr des Ausstellungsdatums"),
    ("monat", "Monat des Ausstellungsdatums (MM)"),
    ("hinzugefuegt", "Importdatum (JJJJ-MM-TT)"),
    ("id", "Paperless-ID"),
    ("asn", "Archivnummer (ASN)"),
    ("seiten", "Seitenzahl"),
    ("original", "Originaldateiname ohne Endung"),
)
VARIABLEN_NAMEN = tuple(n for n, _ in VARIABLEN)
FELD = "feld:"
NUMERISCH = ("id", "asn", "seiten")
FELD_NUMERISCH = ("integer", "float", "monetary")
VORLAGE_STANDARD = "{datum} {titel}"
VORLAGE_MAX = 300
ARTEN = ("ein", "einzeln")

# Längste Dateinamen-Stämme in Bytes (UTF-8). ext4 und die meisten Dateisysteme erlauben 255 Bytes
# je Name; mit Nummer („001_"), Kollisionszusatz („ (12)") und „.pdf" bleibt so Luft, und ein ZIP
# lässt sich auch unter Windows noch in einen nicht allzu tiefen Ordner entpacken.
MAX_STAMM_BYTES = 150
# Unter Windows verboten, und ein ZIP wird oft dort entpackt.
WINDOWS_ZEICHEN = '<>:"|?*'
WINDOWS_RESERVIERT = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                      *(f"LPT{i}" for i in range(1, 10))}

# Seitenaufbau des Inhaltsverzeichnisses (A4 hochkant, Maße in Punkt). Hier und nicht im
# Zeichenmodul, weil die Zahl der Verzeichnisseiten VOR dem Zeichnen feststehen muss: von ihr hängt
# ab, auf welcher Seite jedes Dokument im zusammengefügten PDF beginnt — und damit jeder Sprung.
SEITE_BREITE, SEITE_HOEHE = 595.28, 841.89
RAND = 50.0
KOPF_HOEHE = 64.0            # Überschrift und Unterzeile, nur auf der ersten Seite
ZEILE_HOEHE = 30.0           # Titelzeile und Zeile mit Angaben je Eintrag
ZEILEN_ERSTE = int((SEITE_HOEHE - 2 * RAND - KOPF_HOEHE) // ZEILE_HOEHE)
ZEILEN_FOLGE = int((SEITE_HOEHE - 2 * RAND) // ZEILE_HOEHE)


# ---------------------------------------------------------------- Auftrag und Rechte

def _wahr(v):
    return v is True or str(v).strip().lower() in ("1", "true", "ja", "on")


def export_auftrag(body, max_dokumente=1000):
    """Den Auftrag aus dem Knopf prüfen: (auftrag, fehler).

    Die Reihenfolge der Dokumente bleibt erhalten (Doppelte fallen weg) — sie ist die Sortierung
    „wie ausgewählt". Mehr als `max_dokumente` ist ein Fehler mit Zahl, keine stille Kürzung.
    """
    body = body if isinstance(body, dict) else {}
    fehler = []
    ids, gesehen = [], set()
    for x in body.get("docs") or []:
        s = str(x).strip()
        if s.isdigit() and int(s) > 0 and int(s) not in gesehen:
            gesehen.add(int(s))
            ids.append(int(s))
    if not ids:
        fehler.append("Keine Dokumente gewählt")
    elif len(ids) > max_dokumente:
        fehler.append(f"Höchstens {max_dokumente} Dokumente je Export — gewählt sind {len(ids)}")
    art = str(body.get("art") or "ein")
    if art not in ARTEN:
        fehler.append(f"Unbekannte Exportart {art!r} (erlaubt: ein, einzeln)")
    vorlage = str(body.get("vorlage") or "").strip() or VORLAGE_STANDARD
    sortierung = str(body.get("sortierung") or "").strip()
    auftrag = {
        "docs": ids, "art": art,
        "seitenzahlen": _wahr(body.get("seitenzahlen")),
        "inhalt": _wahr(body.get("inhalt")),
        "zip": _wahr(body.get("zip")),
        "nummerieren": _wahr(body.get("nummerieren")),
        "vorlage": vorlage,
        "sortierung": sortierung,
        "absteigend": _wahr(body.get("absteigend")),
        "basis": str(body.get("basis") or "").strip()[:500],
    }
    if art == "einzeln":
        fehler += vorlage_fehler(vorlage)
    if sortierung and not _gueltiger_schluessel(sortierung):
        fehler.append(f"Unbekannte Sortierung {sortierung!r}")
    return auftrag, fehler


def lese_rechte(antwort, gewuenscht):
    """Welche der gewünschten Dokumente darf der angemeldete Paperless-Nutzer LESEN?

    `antwort` ist die JSON-Antwort von `GET /api/documents/?id__in=…`, abgefragt MIT der Sitzung des
    Nutzers: Paperless liefert nur, was er sehen darf. Was fehlt, zählt als verweigert — ein Export
    darf nichts enthalten, was der Nutzer in Paperless nicht selbst öffnen könnte.
    Rückgabe: (lesbar, verweigert), beide in der gewünschten Reihenfolge.
    """
    da = {int(d["id"]) for d in (antwort or {}).get("results", []) if str(d.get("id", "")).isdigit()}
    return [d for d in gewuenscht if d in da], [d for d in gewuenscht if d not in da]


def speicher_ueberlauf(fertige, grenze_bytes):
    """Welche fertigen Exporte weg müssen, damit alle zusammen unter `grenze_bytes` bleiben.

    `fertige` = [(auftrag, ende_zeitpunkt, bytes)]. Die ältesten fallen zuerst — bei 24 Stunden
    Aufbewahrung und bis zu 2 GB je Export liefe die Platte sonst voll, bevor der Zeitgeber greift."""
    summe = sum(b for _, _, b in fertige)
    weg = []
    for auftrag, _, b in sorted(fertige, key=lambda x: x[1]):
        if summe <= grenze_bytes:
            break
        weg.append(auftrag)
        summe -= b
    return weg


def groesse_fehler(summe_bytes, grenze_bytes):
    """Meldung, sobald die heruntergeladenen PDFs zusammen die Grenze überschreiten — sonst None."""
    if summe_bytes > grenze_bytes:
        return (f"Export zu groß: die PDFs haben zusammen mehr als {grenze_bytes // (1024 * 1024)} MB "
                "(EXPORT_MAX_MB) — weniger Dokumente wählen")
    return None


def pdf_quelle(dok):
    """Woher das PDF kommt: ("archiv"|"original", None) oder (None, Grund).

    Das Archiv-PDF von Paperless (durchsuchbar, PDF/A) zuerst; ohne Archiv das Original, sofern es
    ein PDF ist. Alles andere (Bild ohne Archiv, Text, Mail) wird übersprungen und gemeldet.
    """
    if dok.get("archived_file_name"):
        return "archiv", None
    mime = str(dok.get("mime_type") or "")
    if mime == "application/pdf":
        return "original", None
    return None, f"kein PDF (Original: {mime or 'unbekannt'}, kein Archiv-PDF)"


# ---------------------------------------------------------------- Paperless-Adresse

def _http_basis(url):
    """Normalisierte http(s)-Adresse ohne Query/Fragment und ohne Schrägstrich am Ende — oder ""."""
    try:
        t = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if t.scheme not in ("http", "https") or not t.hostname or t.query or t.fragment or t.username:
        return ""
    if not re.fullmatch(r"[A-Za-z0-9._~/%-]*", t.path or ""):
        return ""
    return f"{t.scheme}://{t.netloc}{t.path.rstrip('/')}"


def paperless_basis(konfig, origin, vorschlag):
    """Die Adresse von Paperless für die Links im Inhaltsverzeichnis — keine Adresse im Code.

    1. `PAPERLESS_PUBLIC_URL` aus der Umgebung, wenn gesetzt;
    2. sonst die Basis, die das Knopf-Skript aus der Seite liest (`<base href>` — berücksichtigt
       Paperless unter einem Unterpfad), aber nur vom selben Ursprung wie die Anfrage;
    3. sonst der Ursprung der Anfrage (`Origin`).
    Nichts davon brauchbar: "" — dann enthält das Verzeichnis keine Paperless-Links.
    """
    k = _http_basis(konfig)
    if k:
        return k
    o = _http_basis(origin)
    o = o if o and not urlsplit(o).path else ""      # ein Origin hat nie einen Pfad
    v = _http_basis(vorschlag)
    if v and (not o or v.startswith(o + "/") or v == o):
        return v
    return o


def paperless_link(basis, doc_id):
    return f"{basis}/documents/{int(doc_id)}/details" if basis else ""


# ---------------------------------------------------------------- Variablen aus Paperless

def _datum(wert):
    s = str(wert or "")
    return s[:10] if re.match(r"\d{4}-\d{2}-\d{2}", s) else ""


def _feldwert(wert, definition):
    """Wert eines benutzerdefinierten Felds als Text — typgerecht, wie Paperless ihn anzeigt."""
    if wert is None or wert == "":
        return ""
    art = (definition or {}).get("data_type", "")
    if art == "boolean":
        return "ja" if wert is True or str(wert).lower() == "true" else "nein"
    if art == "monetary":
        m = re.fullmatch(r"([A-Z]{3})?(-?\d+(?:\.\d+)?)", str(wert))
        return f"{m.group(2)} {m.group(1)}".strip() if m else str(wert)
    if art == "select":
        # Paperless ≥ 2.14: Optionen als {id, label}, der Wert ist die id; davor Liste + Index.
        optionen = ((definition or {}).get("extra_data") or {}).get("select_options") or []
        for i, o in enumerate(optionen):
            if isinstance(o, dict) and str(o.get("id")) == str(wert):
                return str(o.get("label") or "")
            if isinstance(o, str) and str(i) == str(wert):
                return o
        return str(wert)
    if isinstance(wert, list):
        return ",".join(str(x) for x in wert)
    return str(wert)


def dokument_variablen(dok, namen):
    """Die Variablen eines Dokuments aus der Paperless-API.

    `dok` ist ein Eintrag aus `/api/documents/`, `namen` die mit der Sitzung des Nutzers geholten
    Namen: {"korrespondenten": {id: name}, "typen": {id: name}, "felder": {id: definition}}. Was
    der Nutzer nicht sehen darf (ein Korrespondent ohne Leserecht), fehlt dort und bleibt leer.
    Rückgabe: {"werte": {variable: text}, "felder": {feldname: text}, "feldtypen": {feldname: typ}}.
    """
    namen = namen or {}
    datum = _datum(dok.get("created_date") or dok.get("created"))
    original = str(dok.get("original_file_name") or "")
    werte = {
        "titel": str(dok.get("title") or ""),
        "korrespondent": str((namen.get("korrespondenten") or {}).get(dok.get("correspondent"), "")),
        "typ": str((namen.get("typen") or {}).get(dok.get("document_type"), "")),
        "datum": datum,
        "jahr": datum[:4],
        "monat": datum[5:7],
        "hinzugefuegt": _datum(dok.get("added")),
        "id": str(dok.get("id") or ""),
        "asn": "" if dok.get("archive_serial_number") in (None, "") else str(dok["archive_serial_number"]),
        "seiten": "" if dok.get("page_count") in (None, "") else str(dok["page_count"]),
        "original": original.rsplit(".", 1)[0] if "." in original else original,
    }
    felder, feldtypen = {}, {}
    definitionen = namen.get("felder") or {}
    for f in dok.get("custom_fields") or []:
        d = definitionen.get(f.get("field"))
        if not d or not d.get("name"):
            continue
        felder[d["name"]] = _feldwert(f.get("value"), d)
        feldtypen[d["name"]] = d.get("data_type", "")
    return {"werte": werte, "felder": felder, "feldtypen": feldtypen}


def _feld_finden(name, feldnamen):
    """Feldname wie geschrieben, sonst ohne Rücksicht auf Groß-/Kleinschreibung — oder None."""
    if name in feldnamen:
        return name
    klein = {n.casefold(): n for n in feldnamen}
    return klein.get(name.casefold())


# ---------------------------------------------------------------- Dateinamen

_PLATZHALTER = re.compile(r"\{([^{}]*)\}")


def _gueltiger_schluessel(name):
    n = name.strip()
    if n.lower().startswith(FELD):
        return bool(n[len(FELD):].strip())
    return n.lower() in VARIABLEN_NAMEN


def vorlage_fehler(vorlage, feldnamen=None):
    """Was an einer Dateinamen-Vorlage falsch ist — leere Liste, wenn sie taugt.

    `feldnamen` (die benutzerdefinierten Felder in Paperless) prüft {feld:Name} gegen den Bestand;
    ohne sie wird nur die Form geprüft. Ein unbekanntes Feld ist ein Fehler, kein leerer Wert —
    sonst hießen alle Dateien gleich und niemand wüsste, warum.
    """
    fehler = []
    if len(vorlage) > VORLAGE_MAX:
        fehler.append(f"Vorlage länger als {VORLAGE_MAX} Zeichen")
    if "{" in _PLATZHALTER.sub("", vorlage) or "}" in _PLATZHALTER.sub("", vorlage):
        fehler.append("Geschweifte Klammer ohne Gegenstück in der Vorlage")
    for roh in _PLATZHALTER.findall(vorlage):
        n = roh.strip()
        if n.lower().startswith(FELD):
            feld = n[len(FELD):].strip()
            if not feld:
                fehler.append("{feld:…} ohne Feldnamen")
            elif feldnamen is not None and _feld_finden(feld, feldnamen) is None:
                fehler.append(f"Benutzerdefiniertes Feld {feld!r} gibt es in Paperless nicht")
        elif n.lower() not in VARIABLEN_NAMEN:
            fehler.append(f"Unbekannte Variable {{{n}}} — erlaubt: "
                          + ", ".join("{" + v + "}" for v in VARIABLEN_NAMEN) + ", {feld:Name}")
    return fehler


def sicherer_name(roh, max_bytes=MAX_STAMM_BYTES, ersatz="dokument"):
    """Einen Text zu einem harmlosen Dateinamen-Stamm machen (ohne Endung).

    Kein Pfadtrenner (aus „A/B" wird „A-B", nie ein Unterordner), keine Steuer- und Formatzeichen
    (auch keine Richtungsumkehr U+202E, mit der sich „fdp.exe" als „exe.pdf" tarnt), keine unter
    Windows verbotenen Zeichen, kein Punkt oder Leerzeichen am Rand (kein „..", keine versteckte
    Datei), kein reservierter Windows-Name, Länge in Bytes begrenzt. Leer wird zu `ersatz`.
    """
    s = unicodedata.normalize("NFC", str(roh or ""))
    teile = []
    for ch in s:
        kat = unicodedata.category(ch)
        if ch in "/\\":
            teile.append("-")
        elif ch in WINDOWS_ZEICHEN:
            teile.append("_")
        elif kat[0] == "C":                      # Cc, Cf, Cs, Co, Cn
            teile.append(" " if ch in "\t\n\r\x0b\x0c" else "")
        elif kat[0] == "Z" or ch.isspace():
            teile.append(" ")
        else:
            teile.append(ch)
    s = re.sub(r" +", " ", "".join(teile)).strip(" .")
    b = s.encode("utf-8")
    if len(b) > max_bytes:
        s = b[:max_bytes].decode("utf-8", "ignore").rstrip(" .")
    if not s:
        s = ersatz
    if s.split(".", 1)[0].strip().upper() in WINDOWS_RESERVIERT:
        s = "_" + s
    return s


# Trennzeichen zwischen Platzhaltern. Fällt ein Platzhalter leer aus, verschwindet mit ihm das
# Trennzeichen daneben — sonst hieße die Datei „__Rechnung" oder „- Rechnung ()".
_TRENNER = r"[\s_\-.,;:+~|·–—]"
_LEER = "\x00"            # Marke für einen leeren Platzhalter; kommt in keinem entschärften Wert vor
_LEER_LAUF = re.compile(f"{_TRENNER}*{_LEER}(?:{_TRENNER}*{_LEER})*{_TRENNER}*")
_LEER_KLAMMER = re.compile(r"[(\[]" + f"{_TRENNER}*{_LEER}(?:{_TRENNER}*{_LEER})*{_TRENNER}*" + r"[)\]]")


def _leere_wegraeumen(text):
    """Leere Platzhalter samt Trennzeichen und leerer Klammer entfernen.

    Am Anfang und Ende fällt der ganze Trennzeichen-Lauf weg; in der Mitte bleibt EIN Trenner —
    der links vom leeren Platzhalter, sonst der rechts davon („A_{leer}_B" → „A_B",
    „A {leer}- B" → „A B")."""
    text = _LEER_KLAMMER.sub(_LEER, text)

    def ersetzen(m):
        if m.start() == 0 or m.end() == len(text):
            return ""
        lauf = m.group(0)
        links = re.match(f"{_TRENNER}*", lauf).group(0)
        rechts = re.search(f"{_TRENNER}*$", lauf).group(0)
        return links or rechts
    return _LEER_LAUF.sub(ersetzen, text)


def vorlage_fuellen(vorlage, variablen):
    """Die Vorlage mit den Werten eines Dokuments füllen → Dateiname-Stamm (ohne Endung).

    Jeder Wert wird VOR dem Einsetzen entschärft (ein Titel „2025/26" legt keinen Ordner an), das
    Ergebnis danach noch einmal als Ganzes. Ein leerer Wert nimmt sein Trennzeichen und eine leere
    Klammer mit („{datum}_{titel} ({feld:Projekt})" ohne Datum und Projekt → „Rechnung").
    Leer bleibt nie: dann „dokument-<id>".
    """
    werte = variablen.get("werte", {})
    felder = variablen.get("felder", {})
    vorlage = vorlage.replace(_LEER, "")

    def ersetzen(m):
        n = m.group(1).strip()
        if n.lower().startswith(FELD):
            feld = _feld_finden(n[len(FELD):].strip(), felder)
            wert = felder.get(feld, "") if feld else ""
        else:
            wert = werte.get(n.lower(), "")
        return (sicherer_name(wert, ersatz="") if wert else "") or _LEER

    return sicherer_name(_leere_wegraeumen(_PLATZHALTER.sub(ersetzen, vorlage)),
                         ersatz=f"dokument-{werte.get('id', '')}".rstrip("-"))


def nummer(i, anzahl):
    """Präfix der Durchnummerierung: 001_, 002_ … — breiter, wenn es mehr als 999 sind."""
    return f"{i:0{max(3, len(str(anzahl)))}d}_"


def eindeutig(namen, belegt=()):
    """Kollisionen auflösen: der zweite „a.pdf" wird „a (2).pdf", der dritte „a (3).pdf".

    Verglichen wird ohne Groß-/Kleinschreibung und in NFC — Windows und macOS unterscheiden „A.pdf"
    und „a.pdf" nicht, und ein ZIP mit beiden verlöre dort still eine Datei. `belegt` sind Namen,
    die schon vergeben sind (etwa das Inhaltsverzeichnis).
    """
    schon = {unicodedata.normalize("NFC", n).casefold() for n in belegt}
    out = []
    for name in namen:
        stamm, punkt, endung = name.rpartition(".")
        if not punkt:
            stamm, endung = name, ""
        kandidat, k = name, 1
        while unicodedata.normalize("NFC", kandidat).casefold() in schon:
            k += 1
            kandidat = f"{stamm} ({k})" + (f".{endung}" if punkt else "")
        schon.add(unicodedata.normalize("NFC", kandidat).casefold())
        out.append(kandidat)
    return out


def dateinamen(eintraege, vorlage, nummerieren, inhalt_name=None):
    """Die Dateinamen für den Einzel-Export, in der Reihenfolge der (schon sortierten) Einträge."""
    roh = []
    for i, e in enumerate(eintraege, 1):
        stamm = vorlage_fuellen(vorlage, e)
        roh.append((nummer(i, len(eintraege)) if nummerieren else "") + stamm + ".pdf")
    return eindeutig(roh, belegt=[inhalt_name] if inhalt_name else ())


def inhalt_dateiname(nummerieren, anzahl):
    """Name der Inhaltsverzeichnis-Datei beim Einzel-Export — mit Nummer steht sie vorn."""
    return (nummer(0, anzahl) if nummerieren else "") + "Inhaltsverzeichnis.pdf"


def export_dateiname(endung, anzahl, zeitpunkt):
    """Name des Downloads: „Export 2026-09-27 1530 (12 Dokumente).pdf" bzw. „….zip"."""
    return sicherer_name(f"Export {zeitpunkt} ({anzahl} Dokument{'e' if anzahl != 1 else ''})") + "." + endung


# ---------------------------------------------------------------- Sortierung

def _natuerlich(text):
    """Sortierschlüssel für Text: ä wie a (DIN 5007-1), Zahlen als Zahlen („Rechnung 9" vor „10")."""
    t = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    t = t.replace("ß", "ss").casefold()
    return [(0, int(x), "") if x.isdigit() else (1, 0, x) for x in re.split(r"(\d+)", t) if x]


def _zahl(text):
    m = re.search(r"-?\d+(?:[.,]\d+)?", text or "")
    return float(m.group(0).replace(",", ".")) if m else None


def sortwert(variablen, schluessel):
    """Wert eines Eintrags für die Sortierung — None heißt „fehlt" und steht immer hinten."""
    n = schluessel.strip()
    if n.lower().startswith(FELD):
        feld = _feld_finden(n[len(FELD):].strip(), variablen.get("felder", {}))
        text = variablen.get("felder", {}).get(feld, "") if feld else ""
        numerisch = (variablen.get("feldtypen", {}).get(feld) in FELD_NUMERISCH) if feld else False
    else:
        text = variablen.get("werte", {}).get(n.lower(), "")
        numerisch = n.lower() in NUMERISCH
    if text == "":
        return None
    if numerisch:
        z = _zahl(text)
        return None if z is None else (z,)
    return (_natuerlich(text),)


def sortieren(eintraege, schluessel="", absteigend=False):
    """Einträge nach einer Variable sortieren, auf- oder absteigend.

    Ohne Schlüssel bleibt die Reihenfolge der Auswahl (umgedreht bei absteigend). Einträge ohne
    Wert stehen in beiden Richtungen hinten; bei Gleichstand entscheidet die Reihenfolge der
    Auswahl (die Sortierung ist stabil).
    """
    liste = list(eintraege)
    if not schluessel:
        return list(reversed(liste)) if absteigend else liste
    mit = [e for e in liste if sortwert(e, schluessel) is not None]
    ohne = [e for e in liste if sortwert(e, schluessel) is None]
    mit.sort(key=lambda e: sortwert(e, schluessel), reverse=absteigend)
    return mit + ohne


# ---------------------------------------------------------------- Inhaltsverzeichnis

def toc_seiten(zeilen, erste=ZEILEN_ERSTE, folge=ZEILEN_FOLGE):
    """Wie viele Seiten ein Inhaltsverzeichnis mit `zeilen` Zeilen braucht (mindestens eine)."""
    if zeilen <= erste:
        return 1
    return 1 + -(-(zeilen - erste) // folge)


def toc_verteilen(zeilen, erste=ZEILEN_ERSTE, folge=ZEILEN_FOLGE):
    """Die Zeilen auf Seiten verteilen: [[zeilen der Seite 1], [Seite 2], …]."""
    seiten = [list(zeilen[:erste])]
    rest = list(zeilen[erste:])
    while rest:
        seiten.append(rest[:folge])
        rest = rest[folge:]
    return seiten


def startseiten(vorne, seitenzahlen):
    """Erste Seite (0-basiert) jedes Dokuments im zusammengefügten PDF, wenn `vorne` Seiten
    (das Inhaltsverzeichnis) davor stehen."""
    out, seite = [], vorne
    for n in seitenzahlen:
        out.append(seite)
        seite += n
    return out


def _meta(e, mit_seiten=True):
    w = e.get("werte", {})
    teile = [w.get("korrespondent"), w.get("typ"), w.get("datum")]
    if w.get("asn"):
        teile.append(f"ASN {w['asn']}")
    if mit_seiten and e.get("seitenzahl"):
        teile.append(f"{e['seitenzahl']} Seite{'n' if e['seitenzahl'] != 1 else ''}")
    teile.append(f"#{w.get('id')}")
    return " · ".join(t for t in teile if t)


def toc_zeilen(enthalten, fehlen, basis, sprungziele=None, dateien=None):
    """Die Zeilen des Inhaltsverzeichnisses — was drinsteht und wohin jede Zeile verlinkt.

    `enthalten` sind die Einträge im Export, `fehlen` die übersprungenen (mit `grund`). Beim
    zusammengefügten PDF gibt `sprungziele` je Eintrag die Seite (0-basiert) an, beim Einzel-Export
    `dateien` den Dateinamen. Jede Zeile trägt zusätzlich den Link zum Dokument in Paperless, sofern
    dessen Adresse bekannt ist. Übersprungene stehen am Ende unter „Nicht enthalten".
    """
    zeilen = []
    for i, e in enumerate(enthalten):
        w = e.get("werte", {})
        z = {"art": "dok", "nr": f"{i + 1}.", "titel": (w.get("titel") or "").strip() or f"Dokument {w.get('id')}",
             "meta": _meta(e), "rechts": "", "sprung": None, "datei": None,
             "paperless": paperless_link(basis, w.get("id")) if w.get("id") else ""}
        if sprungziele is not None:
            z["sprung"] = sprungziele[i]
            z["rechts"] = f"Seite {sprungziele[i] + 1}"
        if dateien is not None:
            z["datei"] = dateien[i]
            z["meta"] = f"Datei: {dateien[i]} · " + z["meta"]
        zeilen.append(z)
    if fehlen:
        zeilen.append({"art": "ueberschrift", "titel": f"Nicht enthalten ({len(fehlen)})"})
        for e in fehlen:
            w = e.get("werte", {})
            zeilen.append({"art": "fehlt", "nr": "–", "titel": (w.get("titel") or "").strip() or f"Dokument {w.get('id')}",
                           "meta": " · ".join(t for t in (e.get("grund"), _meta(e, mit_seiten=False)) if t),
                           "rechts": "", "sprung": None, "datei": None,
                           "paperless": paperless_link(basis, w.get("id")) if w.get("id") else ""})
    return zeilen


def lesezeichen(e):
    """Titel des Lesezeichens (PDF-Outline) für ein Dokument im zusammengefügten PDF."""
    w = e.get("werte", {})
    titel = (w.get("titel") or "").strip() or f"Dokument {w.get('id')}"
    return f"{titel} ({w['datum']})" if w.get("datum") else titel


def relativer_link(dateiname):
    """Relativer URI-Verweis auf eine Datei im selben Ordner („./001_A%20B.pdf").

    PDF 1.7, Abschnitt 12.6.4.7: ein URI ohne Basis wird relativ zum Ort des Dokuments aufgelöst —
    also zur Datei daneben, wenn das ZIP entpackt ist. URIs sind 7-Bit-ASCII, daher kodiert.
    """
    return "./" + quote(dateiname, safe="")
