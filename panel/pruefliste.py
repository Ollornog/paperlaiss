"""Prüfen: which documents are flagged and why, and which identifiers are probably our own (T-9 items 1 and 7).

Two lists for the page `/pruefen`:

  * the documents that carry the flag tag (`unsicher_tag`, `kaputt_tag`) now, each with the reasons of its last
    run from the trace (`pruefen`) — so nobody has to open every document to see why it is there;
  * identifiers that are probably ours: an IBAN or phone number the classifier did not learn because it is printed
    on documents of several correspondents (classify.py writes `eigene_vorschlaege.json`), and values in the master
    data store that are already listed as our own (learned before they were configured). Taking one over adds it to
    `eigene_kennungen` and removes it from every correspondent in the store.

Pure logic without network and without FastAPI — `tests/test_pruefliste.py` checks it directly. Fetching and
writing stay in `app.py`.
"""
from __future__ import annotations

from kern import _einheitlich, _liste_von

# Fields an own identifier can come from; the same names as in `eigene_kennungen`.
KENNUNG_FELDER = ("iban", "telefon", "email", "ustid")
# Reasons without a run behind them: the flag was set by hand or by a run without findings in its trace.
OHNE_GRUND = "kein Grund im Trace (von Hand markiert oder älterer Lauf)"


def schluessel(feld: str, wert) -> str:
    """Comparable form of an identifier: IBAN and VAT ID without spaces, upper case; phone normalised; mail lower."""
    w = _einheitlich(feld, str(wert or "").strip())
    return w.replace(" ", "").upper() if feld in ("iban", "ustid") else w


def gruende(trace: dict) -> list[dict]:
    """The findings of a run as a list [{art, text}] (`pruefen` is {art: text} in the trace)."""
    p = (trace or {}).get("pruefen")
    if not isinstance(p, dict) or not p:
        return []
    return [{"art": str(k), "text": str(v)} for k, v in p.items() if v]


def dokumente(doks: list, traces: dict, namen: dict | None = None) -> list[dict]:
    """Rows of the flagged documents, newest run first.

    `doks` are Paperless documents (id, title, correspondent, document_type, tags), `traces` maps the id to its
    trace (missing = none), `namen` translates ids like in nacharbeit.py."""
    namen = namen or {}
    zeilen = []
    for d in doks:
        t = traces.get(d.get("id")) or {}
        zeilen.append({
            "doc": d.get("id"), "titel": d.get("title") or "",
            "korrespondent": namen.get("correspondent", {}).get(str(d.get("correspondent")), ""),
            "typ": namen.get("document_type", {}).get(str(d.get("document_type")), ""),
            "lauf": t.get("ts_utc") or t.get("ts") or "",
            "gruende": gruende(t) or [{"art": "", "text": OHNE_GRUND}],
        })
    zeilen.sort(key=lambda z: (z["lauf"], z["doc"] or 0), reverse=True)
    return zeilen


def eigene_schluessel(eigene: dict) -> set[tuple[str, str]]:
    """(feld, key) of every own identifier in `eigene_kennungen`."""
    return {(f, schluessel(f, w)) for f in KENNUNG_FELDER for w in _liste_von((eigene or {}).get(f))
            if schluessel(f, w)}


def fundstellen(store: dict, feld: str, wert) -> list[str]:
    """Ids (as text) of the store entries that hold this value."""
    k = schluessel(feld, wert)
    return sorted((cid for cid, e in (store or {}).items()
                   if isinstance(e, dict) and any(schluessel(feld, x) == k for x in _liste_von(e.get(feld)))),
                  key=lambda c: int(c) if c.isdigit() else 0)


def kennungen(vorschlaege: dict, store: dict, eigene: dict) -> list[dict]:
    """Identifiers to show: open proposals of the classifier, and own values still stored at a correspondent.

    A proposal that is already own (configured after it was recorded) is left out unless the store still holds
    it; a dismissed one is left out. Each row: {feld, wert, grund, korrespondenten, dokumente, bei, schon_eigen}."""
    eigen = eigene_schluessel(eigene)
    zeilen, gesehen = [], set()
    for v in (vorschlaege or {}).values():
        if not isinstance(v, dict) or v.get("verworfen") or v.get("feld") not in KENNUNG_FELDER:
            continue
        k = (v["feld"], schluessel(v["feld"], v.get("wert")))
        bei = fundstellen(store, v["feld"], v.get("wert"))
        if k in eigen and not bei:
            continue
        gesehen.add(k)
        zeilen.append({"feld": v["feld"], "wert": v.get("wert"), "korrespondenten": v.get("korrespondenten"),
                       "dokumente": list(v.get("dokumente") or []), "zuletzt": v.get("zuletzt"), "bei": bei,
                       "schon_eigen": k in eigen,
                       "grund": f"steht auf Dokumenten von {v.get('korrespondenten')} Korrespondenten"})
    for cid, e in sorted((store or {}).items()):
        if not isinstance(e, dict):
            continue
        for f in KENNUNG_FELDER:
            for w in _liste_von(e.get(f)):
                k = (f, schluessel(f, w))
                if k in eigen and k not in gesehen:
                    gesehen.add(k)
                    zeilen.append({"feld": f, "wert": w, "korrespondenten": None, "dokumente": [], "zuletzt": None,
                                   "bei": fundstellen(store, f, w), "schon_eigen": True,
                                   "grund": "schon eigene Kennung, steht aber noch in den Stammdaten"})
    return zeilen


def store_raeumen(store: dict, feld: str, wert) -> tuple[dict, list[str]]:
    """The store without this value at any correspondent → (new store, ids it was removed from).

    The provenance note (`erfasst`) of the value goes with it; an entry that keeps nothing else stays (aliases,
    address and context are no identifiers)."""
    k = schluessel(feld, wert)
    neu, weg = {}, []
    for cid, e in (store or {}).items():
        if not isinstance(e, dict) or feld not in e:
            neu[cid] = e
            continue
        alt = _liste_von(e.get(feld))
        bleibt = [x for x in alt if schluessel(feld, x) != k]
        if len(bleibt) == len(alt):
            neu[cid] = e
            continue
        weg.append(cid)
        e = dict(e)
        if bleibt:
            e[feld] = bleibt if isinstance(e.get(feld), list) else ", ".join(bleibt)
        else:
            e.pop(feld)
        erf = dict(e.get("erfasst") or {})
        if isinstance(erf.get(feld), dict):
            erf[feld] = {w: q for w, q in erf[feld].items() if schluessel(feld, w) != k}
            if not erf[feld]:
                erf.pop(feld)
        elif feld in erf and not bleibt:
            erf.pop(feld)
        if erf:
            e["erfasst"] = erf
        else:
            e.pop("erfasst", None)
        neu[cid] = e
    return neu, weg


def eigene_ergaenzen(eigene: dict, feld: str, wert) -> dict:
    """`eigene_kennungen` with the value added to its field (unchanged if it is already there)."""
    aus = {k: list(_liste_von(v)) if k in KENNUNG_FELDER or isinstance(v, list) else v
           for k, v in (eigene or {}).items()}
    liste = aus.setdefault(feld, [])
    if schluessel(feld, wert) not in {schluessel(feld, x) for x in liste}:
        liste.append(_einheitlich(feld, str(wert).strip()))
    return aus
