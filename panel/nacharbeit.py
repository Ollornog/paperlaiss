"""Nacharbeit: was Menschen nach einem KI-Lauf geändert haben (Backlog T-6).

Zwei Quellen, beide gibt es schon:
  * der Trace eines Laufs — WAS die KI geschrieben hat (`writeback`) und WANN (`ts_utc`, bei
    alten Traces `ts` in Ortszeit),
  * die Änderungshistorie von Paperless (`/api/documents/<id>/history/`, Audit-Log) — WER danach
    WAS geändert hat. Paperless schreibt dort nur echte Änderungen, mit Benutzer und Zeit.

Eine Korrektur ist ein Feld, das ein angemeldeter Mensch nach dem Lauf geändert hat und dessen
Wert danach anders ist als der, den die KI hinterlassen hat. Einträge ohne Benutzer (Workflows,
Skripte) zählen nicht. Einträge in den ersten Sekunden nach dem Lauf auch nicht: das sind noch
Schreibvorgänge des Laufs selbst (der Klassifizierer schreibt unter dem Token-Benutzer, und der
kann ein Mensch sein).

Reine Logik ohne Netz und ohne FastAPI — `tests/test_nacharbeit.py` prüft sie direkt. Das Holen
und Speichern steht in `app.py`.
"""
from __future__ import annotations

import datetime
import zoneinfo
from collections import Counter

# Paperless-Feldname → Anzeigename. Nur diese vier Grundfelder; Rechte, Ablagepfad, Notizen und
# ASN setzt die KI nicht, ihre Änderung wäre keine Korrektur.
GRUNDFELDER = {"title": "Titel", "correspondent": "Korrespondent",
               "document_type": "Dokumenttyp", "created": "Datum"}
TAGS = "Tags"
# Was ein Lauf noch selbst schreibt, nachdem der Trace-Zeitstempel gesetzt ist, bzw. was um den
# Zeitstempel herum gleichzeitig passiert (Post-Consume, Uhrabweichung).
GNADE_S = 15


def _utc(text: str) -> datetime.datetime | None:
    try:
        d = datetime.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else None


def lauf_zeit(trace: dict, zone: str = "") -> datetime.datetime | None:
    """Ende des Laufs in UTC. Neue Traces tragen `ts_utc`; alte nur `ts` in der Ortszeit des
    Klassifizierers (= Zeitzone der Paperless-Installation)."""
    d = _utc(trace.get("ts_utc") or "")
    if d:
        return d
    try:
        naiv = datetime.datetime.strptime(str(trace.get("ts") or ""), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    try:
        tz = zoneinfo.ZoneInfo(zone) if zone else datetime.timezone.utc
    except (zoneinfo.ZoneInfoNotFoundError, ValueError):
        tz = datetime.timezone.utc
    return naiv.replace(tzinfo=tz).astimezone(datetime.timezone.utc)


def ki_lauf(trace: dict) -> bool:
    """Nur fertige Läufe, die geschrieben haben, zählen (kein Abbruch, kein Speicherfehler)."""
    wb = trace.get("writeback")
    return isinstance(wb, dict) and not wb.get("fehler") and trace.get("_stage") in (None, "fertig")


def _wert(v) -> str:
    """Werte vergleichbar machen: Audit-Log schreibt „None", Zahlen kommen als Zahl oder Text."""
    if v is None:
        return ""
    s = " ".join(str(v).split())
    return "" if s == "None" else s


def ki_feldwerte(writeback: dict) -> dict:
    """Eigenes Feld → Wert, den die KI hinterlassen hat. None = unbekannt (behalten)."""
    aus = {}
    for name, v in (writeback.get("fields_ki") or {}).items():
        if isinstance(v, str) and v.startswith("behalten"):
            aus[name] = None
        elif v in ("geleert", "entfernt"):
            aus[name] = ""
        else:
            aus[name] = _wert(v)
    return aus


def _art(ki: str | None, neu: str) -> str:
    if ki is None:                  # KI hat den alten Wert behalten, welcher es war, ist unbekannt
        return "geändert" if neu else "geleert"
    if not ki and neu:
        return "ergänzt"
    if ki and not neu:
        return "geleert"
    return "geändert"


def korrekturen(trace: dict, historie: list, namen: dict | None = None, zone: str = "") -> dict:
    """Ein Lauf und die Historie seines Dokuments → was danach von Hand geändert wurde.

    `namen` übersetzt IDs der Historie: {"correspondent": {"12": "Name"}, "document_type": {...}}.
    Ergebnis: {"felder": [...], "angefasst": bool, "korrekturen": [{feld, ki, neu, art, wer, wann}]}.
    """
    namen = namen or {}
    wb = trace.get("writeback") or {}
    ende = lauf_zeit(trace, zone)
    ki_felder = ki_feldwerte(wb)
    ki_tags = {t for t in (wb.get("tags") or []) if t}
    felder = list(GRUNDFELDER.values()) + sorted(ki_felder) + ([TAGS] if ki_tags else [])
    if ende is None:
        return {"felder": felder, "angefasst": False, "korrekturen": []}
    grenze = ende + datetime.timedelta(seconds=GNADE_S)

    # Historie kommt neueste zuerst; chronologisch abarbeiten.
    spaeter = []
    for e in historie or []:
        t = _utc(e.get("timestamp") or "")
        wer = (e.get("actor") or {}).get("username")
        if t and wer and t > grenze:
            spaeter.append((t, wer, e))
    spaeter.sort(key=lambda x: x[0])

    def name(feld, v):
        s = _wert(v)
        return namen.get(feld, {}).get(s, s) if s else ""

    erst: dict = {}      # Feld → (KI-Wert, erste Änderung)
    zuletzt: dict = {}   # Feld → (neuer Wert, wer, wann)
    tags_weg: dict = {}
    for t, wer, e in spaeter:
        wann = t.isoformat(timespec="seconds")
        for feld, aend in (e.get("changes") or {}).items():
            if feld in GRUNDFELDER and isinstance(aend, list) and len(aend) == 2:
                anzeige = GRUNDFELDER[feld]
                erst.setdefault(anzeige, name(feld, aend[0]))
                zuletzt[anzeige] = (name(feld, aend[1]), wer, wann)
            elif feld == "custom_fields" and isinstance(aend, dict):
                fname = aend.get("field")
                if fname not in ki_felder:
                    continue        # Feld, das die KI nicht gesetzt hat (z. B. Bezahlt-Am)
                neu = "" if e.get("action") == "delete" else _wert(aend.get("value"))
                erst.setdefault(fname, ki_felder[fname])
                zuletzt[fname] = (neu, wer, wann)
            elif feld == "tags" and isinstance(aend, dict) and aend.get("operation") == "delete":
                for tag in aend.get("objects") or []:
                    if tag in ki_tags:
                        tags_weg[tag] = (wer, wann)
            elif feld == "tags" and isinstance(aend, dict) and aend.get("operation") == "add":
                for tag in aend.get("objects") or []:
                    tags_weg.pop(tag, None)     # wieder dazu → keine Korrektur

    aus = []
    for feld, (neu, wer, wann) in zuletzt.items():
        ki = erst.get(feld)
        if ki is not None and ki == neu:
            continue                            # hin und zurück geändert
        aus.append({"feld": feld, "ki": ki, "neu": neu, "art": _art(ki, neu), "wer": wer, "wann": wann})
    for tag, (wer, wann) in sorted(tags_weg.items()):
        aus.append({"feld": TAGS, "ki": tag, "neu": "", "art": "entfernt", "wer": wer, "wann": wann})
    return {"felder": felder, "angefasst": bool(spaeter), "korrekturen": aus}


def _quote(teil: int, basis: int) -> float:
    return round(100.0 * teil / basis, 1) if basis else 0.0


def _gruppen(laeufe: list, schluessel: str, mindestens: int = 1, grenze: int = 20) -> list:
    n, k = Counter(), Counter()
    for l in laeufe:
        g = l.get(schluessel) or "—"
        n[g] += 1
        k[g] += bool(l["korrekturen"])
    zeilen = [{"name": g, "laeufe": n[g], "nachgearbeitet": k[g], "quote": _quote(k[g], n[g])}
              for g in n if n[g] >= mindestens]
    zeilen.sort(key=lambda z: (-z["nachgearbeitet"], -z["quote"], z["name"]))
    return zeilen[:grenze]


def auswertung(laeufe: list, jetzt: datetime.datetime, tage: int = 90, feld: str = "",
               korrespondent: str = "", typ: str = "", faelle_max: int = 200) -> dict:
    """Kennzahlen und Fallliste über gespeicherte Läufe.

    Jeder Lauf: {doc, ts (UTC, ISO), quelle, korrespondent, typ, felder, angefasst, korrekturen}.
    Die Quote zählt Läufe mit mindestens einer Korrektur je Lauf, in dem die KI das Feld gesetzt
    hat. Dokumente, die nie jemand angefasst hat, zählen als richtig — die Quote ist eine
    Untergrenze, solange nicht alles gesichtet ist.
    """
    if tage > 0:
        ab = jetzt - datetime.timedelta(days=tage)
        laeufe = [l for l in laeufe if (_utc(l.get("ts") or "") or ab) >= ab]
    alle = len(laeufe)
    if korrespondent:
        laeufe = [l for l in laeufe if (l.get("korrespondent") or "—") == korrespondent]
    if typ:
        laeufe = [l for l in laeufe if (l.get("typ") or "—") == typ]

    basis, treffer, arten = Counter(), Counter(), {}
    for l in laeufe:
        for f in l.get("felder") or []:
            basis[f] += 1
        for f in {k["feld"] for k in l["korrekturen"]}:
            treffer[f] += 1
        for k in l["korrekturen"]:
            arten.setdefault(k["feld"], Counter())[k["art"]] += 1
    je_feld = [{"feld": f, "korrigiert": treffer[f], "basis": basis[f] or treffer[f],
                "quote": _quote(treffer[f], basis[f] or treffer[f]),
                "arten": dict(arten.get(f, {}))} for f in set(basis) | set(treffer)]
    je_feld.sort(key=lambda z: (-z["quote"], -z["korrigiert"], z["feld"]))

    wochen: dict = {}
    for l in laeufe:
        d = _utc(l.get("ts") or "")
        if not d:
            continue
        j, w, _ = d.isocalendar()
        z = wochen.setdefault(f"{j}-W{w:02d}", {"woche": f"{j}-W{w:02d}", "laeufe": 0, "nachgearbeitet": 0})
        z["laeufe"] += 1
        z["nachgearbeitet"] += bool(l["korrekturen"])
    for z in wochen.values():
        z["quote"] = _quote(z["nachgearbeitet"], z["laeufe"])

    faelle = []
    for l in laeufe:
        for k in l["korrekturen"]:
            if feld and k["feld"] != feld:
                continue
            faelle.append({**k, "doc": l["doc"], "lauf": l.get("ts"), "quelle": l.get("quelle"),
                           "korrespondent": l.get("korrespondent"), "typ": l.get("typ")})
    faelle.sort(key=lambda f: (f.get("wann") or "", f["doc"]), reverse=True)

    nach = sum(1 for l in laeufe if l["korrekturen"])
    return {
        "laeufe": len(laeufe), "alle_laeufe": alle,
        "angefasst": sum(1 for l in laeufe if l.get("angefasst")),
        "nachgearbeitet": nach, "quote": _quote(nach, len(laeufe)),
        "korrekturen": sum(len(l["korrekturen"]) for l in laeufe),
        "je_feld": je_feld,
        "je_korrespondent": _gruppen(laeufe, "korrespondent", mindestens=2),
        "je_typ": _gruppen(laeufe, "typ"),
        "je_woche": sorted(wochen.values(), key=lambda z: z["woche"]),
        "faelle": faelle[:faelle_max], "faelle_gesamt": len(faelle),
    }


# Felder, die eval.py prüft: Anzeigename hier → Schlüssel der Sollliste.
EVAL_FELDER = {"Korrespondent": "korrespondent", "Dokumenttyp": "typ", "Datum": "datum"}


def sollliste(laeufe: list, jetzt: datetime.datetime, tage: int = 0) -> list:
    """Nachgearbeitete Läufe → Sollliste für eval.py: [{"id", "korrespondent", "typ", "datum", "notiz"}].

    Je Dokument zählt nur der jüngste Lauf: Ist das Dokument danach noch einmal gelaufen, gilt der
    neue Stand, eine ältere Korrektur ist dann überholt. Aufgenommen wird ein Dokument nur, wenn ein
    Mensch mindestens eines der drei geprüften Felder korrigiert hat. Korrespondent und Typ kommen
    aus dem Stand beim letzten Abgleich (was der Mensch beim Korrigieren stehen ließ, gilt als
    bestätigt), das Datum nur, wenn es korrigiert wurde — der Lauf speichert es sonst nicht.
    Ein von Hand geleerter Korrespondent oder Typ wird null („keiner erwartet“).
    """
    if tage > 0:
        ab = jetzt - datetime.timedelta(days=tage)
        laeufe = [l for l in laeufe if (_utc(l.get("ts") or "") or ab) >= ab]
    juengster: dict = {}
    for l in laeufe:
        alt = juengster.get(l["doc"])
        if alt is None or (l.get("ts") or "") > (alt.get("ts") or ""):
            juengster[l["doc"]] = l
    aus = []
    for doc, l in sorted(juengster.items()):
        korr = {k["feld"]: k for k in l.get("korrekturen") or [] if k["feld"] in EVAL_FELDER}
        if not korr:
            continue
        soll: dict = {"id": doc}
        for feld, schluessel in (("Korrespondent", "korrespondent"), ("Dokumenttyp", "typ")):
            k = korr.get(feld)
            if k and k["art"] == "geleert":
                soll[schluessel] = None
            elif l.get(schluessel):
                soll[schluessel] = l[schluessel]
        datum = str((korr.get("Datum") or {}).get("neu") or "")[:10]
        if len(datum) == 10 and datum[4] == "-" and datum[7] == "-":
            soll["datum"] = datum
        if len(soll) == 1:
            continue                    # nichts, was eval.py prüfen könnte
        soll["notiz"] = "; ".join(
            f"{f}: {'?' if k['ki'] is None else k['ki'] or 'leer'} → {k['neu'] or 'leer'} ({k['wer']}, {str(k['wann'])[:10]})"
            for f, k in korr.items())
        aus.append(soll)
    return aus


def zusammenfuehren(alt: dict, neu: dict, behalten: int = 20000) -> dict:
    """Gespeicherte Läufe mit frisch berechneten mischen.

    Ein Trace wird beim nächsten Lauf desselben Dokuments überschrieben. Der alte Lauf bleibt
    deshalb mit dem Stand stehen, den er beim letzten Abgleich hatte — sonst verschwände jede
    Korrektur, sobald jemand den KI-Knopf noch einmal drückt.
    """
    aus = {**(alt or {}), **(neu or {})}
    if len(aus) > behalten:
        for k in sorted(aus, key=lambda k: aus[k].get("ts") or "")[:len(aus) - behalten]:
            del aus[k]
    return aus
