#!/usr/bin/env python3
"""Inbox folder → Paperless: upload every finished file with the account's own API key.

Meant for one folder per account mirrored by a sync client (seaf-cli): whatever a person drops into it
lands in Paperless with HER key (so it belongs to her). Two layouts:

* **Inbox and archive** (`archiv` set, T-15): the client syncs a library with an `Inbox` and an `Archiv`
  folder. Only `Inbox` is imported. Once Paperless has consumed a file (task successful, or a duplicate —
  then it is in Paperless already), it moves to `Archiv/<YYYY.MM.DD> <original name>`, dated with the day of
  the import in `zeitzone` (default Europe/Berlin); a name already taken gets " (2)", " (3)" … A failed
  import stays in `Inbox`, with `<name>.fehler.txt` next to it saying why; it is tried again once the file
  changes or the note is deleted. Subfolders of the inbox are kept in the archive.
* **Delete after import** (no `archiv`, the layout up to 0.9): the file is removed after the import, a
  failed one moves to `_Fehler/` with the reason as a text file.

`tags` (IDs or names, per account or for all) are attached at the upload — Paperless workflows cannot
filter by owner, so an account's own uploads are tagged here.

Configuration (JSON, path in EINGANG_CONFIG):
  {"api": "https://paperless.example.com/api", "zeitzone": "Europe/Berlin",
   "eingang": "Inbox", "archiv": "Archiv",
   "konten": [{"name": "anna", "ordner": "/srv/eingang/anna", "token_env": "EINGANG_TOKEN_ANNA", "tags": ["Anna"]}],
   "ruhezeit_s": 30, "abfrage_s": 20, "zustand": "/var/lib/eingang/zustand.json"}
`eingang`, `archiv` and `tags` may also stand at an account (it wins). Keys come from the environment
(EnvironmentFile), never from the file. Standard library only.
"""
import datetime, json, os, sys, time, urllib.error, urllib.parse, urllib.request, uuid
from pathlib import Path

FEHLER_ORDNER = "_Fehler"
FEHLER_NOTIZ = ".fehler.txt"                # note next to a failed file in the inbox layout
IGNORIEREN = (".", "~$", "_")               # hidden, Office lock files, own folders (_Fehler)
TEMP_ENDUNGEN = (".tmp", ".part", ".crdownload", ".seafile-tmp")


def log(m):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {m}", flush=True)


def kandidaten(ordner):
    """All files in the folder (recursive), without hidden, lock and temp files, _Fehler/ and failure notes."""
    wurzel = Path(ordner)
    for p in sorted(wurzel.rglob("*")):
        teile = p.relative_to(wurzel).parts
        if not p.is_file() or any(t.startswith(IGNORIEREN) for t in teile) \
                or p.name.lower().endswith(TEMP_ENDUNGEN) or p.name.endswith(FEHLER_NOTIZ):
            continue
        yield p


def bereit(stat, vorher, jetzt, ruhezeit):
    """Finished writing? Older than the quiet time and the same size as in the last round."""
    return jetzt - stat.st_mtime >= ruhezeit and vorher == stat.st_size


def auswerten(task):
    """Paperless task → "laeuft" | "ok" | "dublette" | ("fehler", reason)."""
    status = str(task.get("status") or "").upper()
    if status in ("", "PENDING", "STARTED", "RETRY", "RECEIVED"):
        return "laeuft"
    if status == "SUCCESS":
        return "ok"
    grund = str(task.get("result") or "")
    if task.get("duplicate_of") or (task.get("result_data") or {}).get("duplicate_of") or "duplicate" in grund.lower():
        return "dublette"
    return ("fehler", grund[:500] or status)


def archiv_ziel(archiv, rel, datum):
    """Where a consumed file goes: `<archiv>/<subfolders>/<YYYY.MM.DD> <name>`, with " (n)" on a clash."""
    ordner = Path(archiv) / Path(rel).parent
    name = Path(rel).name
    stamm, endung = (name.rsplit(".", 1)[0], "." + name.rsplit(".", 1)[1]) if "." in name.lstrip(".") else (name, "")
    ziel = ordner / f"{datum:%Y.%m.%d} {name}"
    n = 2
    while ziel.exists():
        ziel = ordner / f"{datum:%Y.%m.%d} {stamm} ({n}){endung}"
        n += 1
    return ziel


def zone(name):
    """The time zone for the archive date; without zoneinfo data the local time of the service."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name or "Europe/Berlin")
    except Exception:
        return None


def importtag(seit, tz):
    """Day of the import (the upload) in the zone of the configuration."""
    return datetime.datetime.fromtimestamp(seit, tz) if tz else datetime.datetime.fromtimestamp(seit)


class Api:
    def __init__(self, basis, token):
        self.basis, self.token = basis.rstrip("/"), token
        self._tags = {}

    def _req(self, pfad, daten=None, kopf=None, methode="GET", timeout=120):
        h = {"Authorization": f"Token {self.token}", "Accept": "application/json; version=9", **(kopf or {})}
        return json.load(urllib.request.urlopen(urllib.request.Request(self.basis + pfad, data=daten, headers=h,
                                                                       method=methode), timeout=timeout))

    def tag_ids(self, tags):
        """IDs for tags given as IDs or names (looked up once per name with this account's key)."""
        ids = []
        for t in tags or ():
            if isinstance(t, int) or str(t).strip().isdigit():
                ids.append(int(t)); continue
            if t not in self._tags:
                r = self._req("/tags/?page_size=10&name__iexact=" + urllib.parse.quote(str(t)))
                treffer = [x["id"] for x in r.get("results", []) if str(x.get("name", "")).lower() == str(t).lower()]
                self._tags[t] = treffer[0] if treffer else None
                if not treffer:
                    log(f"Tag „{t}“ nicht gefunden — Upload ohne ihn")
            if self._tags[t]:
                ids.append(self._tags[t])
        return ids

    def hochladen(self, pfad, tags=()):
        grenze = uuid.uuid4().hex
        felder = b"".join(f"--{grenze}\r\nContent-Disposition: form-data; name=\"tags\"\r\n\r\n{i}\r\n".encode()
                          for i in self.tag_ids(tags))
        rumpf = felder + (f"--{grenze}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{pfad.name}\"\r\n"
                          "Content-Type: application/octet-stream\r\n\r\n").encode() + pfad.read_bytes() \
            + f"\r\n--{grenze}--\r\n".encode()
        return self._req("/documents/post_document/", rumpf, {"Content-Type": f"multipart/form-data; boundary={grenze}"},
                         "POST", 300)

    def task(self, tid):
        r = self._req(f"/tasks/?task_id={tid}")
        r = r.get("results", r) if isinstance(r, dict) else r
        return r[0] if r else {}


def nach_fehler(pfad, wurzel, grund):
    """Layout without archive: move the file to _Fehler/, the reason next to it as .txt."""
    ziel = Path(wurzel) / FEHLER_ORDNER / pfad.relative_to(wurzel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pfad.replace(ziel)
    ziel.with_name(ziel.name + ".txt").write_text(f"Import nach Paperless gescheitert ({time.strftime('%Y-%m-%d %H:%M')}):\n{grund}\n",
                                                encoding="utf-8")
    return ziel


def notiz_pfad(pfad):
    return pfad.with_name(pfad.name + FEHLER_NOTIZ)


def fehler_notieren(pfad, grund):
    """Inbox layout: the file stays, a note next to it says why — the person sees both in the sync folder."""
    notiz_pfad(pfad).write_text(
        f"Import nach Paperless gescheitert ({time.strftime('%Y-%m-%d %H:%M')}):\n{grund}\n\n"
        "Die Datei bleibt hier. Neuer Versuch, sobald sie sich ändert oder diese Notiz gelöscht wird.\n",
        encoding="utf-8")
    st = pfad.stat()
    return {"fehler": grund[:500], "groesse": st.st_size, "mtime": st.st_mtime}


def konto_wert(k, cfg, schluessel, vorgabe=None):
    return k[schluessel] if schluessel in k else cfg.get(schluessel, vorgabe)


def eintrag_lesen(e):
    """A state entry: task ID (up to 0.9 a bare string) or {"task", "seit"} or a failure {"fehler", …}."""
    return {"task": e, "seit": None} if isinstance(e, str) else dict(e)


def runde(konten, apis, zustand, groessen, jetzt, ruhezeit, cfg=None):
    """One round: finish open tasks, upload new finished files. Returns the events."""
    cfg = cfg or {}
    tz = zone(cfg.get("zeitzone"))
    ereignisse = []
    for k in konten:
        name, wurzel = k["name"], Path(k["ordner"])
        archiv_rel = konto_wert(k, cfg, "archiv")
        eingang = wurzel / (konto_wert(k, cfg, "eingang") or "") if archiv_rel else wurzel
        archiv = wurzel / archiv_rel if archiv_rel else None
        tags = konto_wert(k, cfg, "tags") or []
        offen = zustand.setdefault(name, {})
        for pfad_s, roh in list(offen.items()):
            e_alt, pfad = eintrag_lesen(roh), Path(pfad_s)
            if "fehler" in e_alt:
                continue
            try:
                e = auswerten(apis[name].task(e_alt["task"]))
            except Exception as ex:
                ereignisse.append((name, pfad.name, f"task-fehler {ex!r}")); continue
            if e == "laeuft":
                continue
            if e in ("ok", "dublette"):
                del offen[pfad_s]
                if pfad.exists():
                    if archiv:
                        ziel = archiv_ziel(archiv, pfad.relative_to(eingang), importtag(e_alt.get("seit") or jetzt, tz))
                        ziel.parent.mkdir(parents=True, exist_ok=True)
                        pfad.replace(ziel)
                        ereignisse.append((name, pfad.name, f"{e} → {ziel.relative_to(wurzel)}"))
                        continue
                    pfad.unlink()
                ereignisse.append((name, pfad.name, e))
            elif archiv:
                if pfad.exists():
                    offen[pfad_s] = fehler_notieren(pfad, e[1])
                else:
                    del offen[pfad_s]
                ereignisse.append((name, pfad.name, f"fehler: {e[1][:120]} (bleibt im Eingang)"))
            else:
                del offen[pfad_s]
                if pfad.exists():
                    nach_fehler(pfad, wurzel, e[1])
                ereignisse.append((name, pfad.name, f"fehler: {e[1][:120]}"))
        if not eingang.is_dir():
            continue
        if archiv:
            for notiz in eingang.rglob("*" + FEHLER_NOTIZ):     # note of a file the person removed
                if not notiz.with_name(notiz.name[:-len(FEHLER_NOTIZ)]).exists():
                    notiz.unlink()
        for pfad in kandidaten(eingang):
            if archiv and (pfad == archiv or archiv in pfad.parents):
                continue                                        # inbox = library root: never re-import the archive
            s = str(pfad)
            st = pfad.stat()
            if s in offen:
                e_alt = eintrag_lesen(offen[s])
                if "fehler" not in e_alt:
                    continue
                if notiz_pfad(pfad).exists() and (e_alt.get("groesse"), e_alt.get("mtime")) == (st.st_size, st.st_mtime):
                    continue                                    # failed, unchanged: wait for the person
                del offen[s]                                    # changed or note deleted: try again
                if notiz_pfad(pfad).exists():
                    notiz_pfad(pfad).unlink()
            vorher, groessen[s] = groessen.get(s), st.st_size
            if not bereit(st, vorher, jetzt, ruhezeit):
                continue
            try:
                offen[s] = {"task": apis[name].hochladen(pfad, tags), "seit": jetzt}
                ereignisse.append((name, pfad.name, "hochgeladen"))
            except urllib.error.HTTPError as ex:
                grund = f"HTTP {ex.code}: {ex.read()[:300]!r}"
                if archiv:
                    offen[s] = fehler_notieren(pfad, grund)
                else:
                    nach_fehler(pfad, wurzel, grund)
                ereignisse.append((name, pfad.name, f"abgelehnt HTTP {ex.code}"))
            except Exception as ex:
                ereignisse.append((name, pfad.name, f"upload-fehler {ex!r} (nächste Runde neu)"))
    return ereignisse


def main():
    cfg = json.load(open(os.environ.get("EINGANG_CONFIG", "/etc/paperless-eingang.json"), encoding="utf-8"))
    konten = cfg["konten"]
    apis = {k["name"]: Api(cfg["api"], os.environ[k["token_env"]]) for k in konten}
    zpfad = Path(cfg.get("zustand", "/var/lib/paperless-eingang/zustand.json"))
    zustand = json.loads(zpfad.read_text()) if zpfad.exists() else {}
    groessen = {}
    log("Eingang läuft: " + ", ".join(
        f"{k['name']} → {Path(k['ordner']) / (konto_wert(k, cfg, 'eingang') or '')}"
        + (f" (Archiv {konto_wert(k, cfg, 'archiv')})" if konto_wert(k, cfg, "archiv") else "") for k in konten))
    while True:
        for name, datei, was in runde(konten, apis, zustand, groessen, time.time(), cfg.get("ruhezeit_s", 30), cfg):
            log(f"{name}: {datei}: {was}")
        zpfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = zpfad.with_suffix(".tmp"); tmp.write_text(json.dumps(zustand)); tmp.replace(zpfad)
        time.sleep(cfg.get("abfrage_s", 20))


if __name__ == "__main__":
    sys.exit(main())
