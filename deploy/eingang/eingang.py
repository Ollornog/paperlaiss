#!/usr/bin/env python3
"""Eingangsordner → Paperless: jede fertig geschriebene Datei hochladen und danach aus dem Ordner entfernen.

Gedacht für einen per Seafile (seaf-cli) gespiegelten Ordner je Konto: Was jemand in seine Bibliothek
„Paperless-Eingang“ legt, landet mit SEINEM API-Schlüssel in Paperless (gehört also ihm) und verschwindet
danach aus dem Ordner — das Löschen synchronisiert der Client zurück. Scheitert der Import, wandert die
Datei nach `_Fehler/` samt Textdatei mit dem Grund; nichts geht still verloren. Eine Dublette gilt als
erledigt (sie ist schon in Paperless) und wird entfernt.

Konfiguration (JSON, Pfad in EINGANG_CONFIG): {"api": "https://paperless.example.com/api",
  "konten": [{"name": "anna", "ordner": "/srv/eingang/anna", "token_env": "EINGANG_TOKEN_ANNA"}],
  "ruhezeit_s": 30, "abfrage_s": 20, "zustand": "/var/lib/eingang/zustand.json"}
Die Schlüssel kommen aus der Umgebung (EnvironmentFile), nie aus der Datei. Nur Standardbibliothek.
"""
import json, os, sys, time, urllib.error, urllib.request, uuid
from pathlib import Path

FEHLER_ORDNER = "_Fehler"
IGNORIEREN = (".", "~$", "_")               # versteckt, Office-Sperrdatei, eigene Ordner (_Fehler)
TEMP_ENDUNGEN = (".tmp", ".part", ".crdownload", ".seafile-tmp")


def log(m):
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {m}", flush=True)


def kandidaten(ordner):
    """Alle Dateien im Ordner (rekursiv), ohne versteckte, Sperr- und Temp-Dateien und ohne _Fehler/."""
    wurzel = Path(ordner)
    for p in sorted(wurzel.rglob("*")):
        teile = p.relative_to(wurzel).parts
        if not p.is_file() or any(t.startswith(IGNORIEREN) for t in teile) or p.name.lower().endswith(TEMP_ENDUNGEN):
            continue
        yield p


def bereit(stat, vorher, jetzt, ruhezeit):
    """Fertig geschrieben? Älter als die Ruhezeit und Größe seit der letzten Runde unverändert."""
    return jetzt - stat.st_mtime >= ruhezeit and vorher == stat.st_size


def auswerten(task):
    """Paperless-Task → "laeuft" | "ok" | "dublette" | ("fehler", Grund)."""
    status = str(task.get("status") or "").upper()
    if status in ("", "PENDING", "STARTED", "RETRY", "RECEIVED"):
        return "laeuft"
    if status == "SUCCESS":
        return "ok"
    grund = str(task.get("result") or "")
    if task.get("duplicate_of") or "duplicate" in grund.lower():
        return "dublette"
    return ("fehler", grund[:500] or status)


class Api:
    def __init__(self, basis, token):
        self.basis, self.token = basis.rstrip("/"), token

    def _req(self, pfad, daten=None, kopf=None, methode="GET", timeout=120):
        h = {"Authorization": f"Token {self.token}", "Accept": "application/json; version=9", **(kopf or {})}
        return json.load(urllib.request.urlopen(urllib.request.Request(self.basis + pfad, data=daten, headers=h,
                                                                       method=methode), timeout=timeout))

    def hochladen(self, pfad):
        grenze = uuid.uuid4().hex
        rumpf = (f"--{grenze}\r\nContent-Disposition: form-data; name=\"document\"; filename=\"{pfad.name}\"\r\n"
                 "Content-Type: application/octet-stream\r\n\r\n").encode() + pfad.read_bytes() + f"\r\n--{grenze}--\r\n".encode()
        return self._req("/documents/post_document/", rumpf, {"Content-Type": f"multipart/form-data; boundary={grenze}"}, "POST", 300)

    def task(self, tid):
        r = self._req(f"/tasks/?task_id={tid}")
        r = r.get("results", r) if isinstance(r, dict) else r
        return r[0] if r else {}


def nach_fehler(pfad, wurzel, grund):
    """Datei nach _Fehler/ verschieben, Grund daneben als .txt — der Nutzer sieht beides in Seafile."""
    ziel = Path(wurzel) / FEHLER_ORDNER / pfad.relative_to(wurzel)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    pfad.replace(ziel)
    ziel.with_name(ziel.name + ".txt").write_text(f"Import nach Paperless gescheitert ({time.strftime('%Y-%m-%d %H:%M')}):\n{grund}\n",
                                                encoding="utf-8")
    return ziel


def runde(konten, apis, zustand, groessen, jetzt, ruhezeit):
    """Eine Runde: offene Tasks abschließen, fertige neue Dateien hochladen. Gibt die Ereignisse zurück."""
    ereignisse = []
    for k in konten:
        name, wurzel = k["name"], k["ordner"]
        offen = zustand.setdefault(name, {})
        for pfad_s, tid in list(offen.items()):
            pfad = Path(pfad_s)
            try:
                e = auswerten(apis[name].task(tid))
            except Exception as ex:
                ereignisse.append((name, pfad.name, f"task-fehler {ex!r}")); continue
            if e == "laeuft":
                continue
            del offen[pfad_s]
            if e in ("ok", "dublette"):
                if pfad.exists():
                    pfad.unlink()
                ereignisse.append((name, pfad.name, e))
            else:
                if pfad.exists():
                    nach_fehler(pfad, wurzel, e[1])
                ereignisse.append((name, pfad.name, f"fehler: {e[1][:120]}"))
        for pfad in kandidaten(wurzel):
            s = str(pfad)
            if s in offen:
                continue
            st = pfad.stat()
            vorher, groessen[s] = groessen.get(s), st.st_size
            if not bereit(st, vorher, jetzt, ruhezeit):
                continue
            try:
                offen[s] = apis[name].hochladen(pfad)
                ereignisse.append((name, pfad.name, "hochgeladen"))
            except urllib.error.HTTPError as ex:
                nach_fehler(pfad, wurzel, f"HTTP {ex.code}: {ex.read()[:300]!r}")
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
    log(f"Eingang läuft: {', '.join(k['name'] + ' → ' + k['ordner'] for k in konten)}")
    while True:
        for name, datei, was in runde(konten, apis, zustand, groessen, time.time(), cfg.get("ruhezeit_s", 30)):
            log(f"{name}: {datei}: {was}")
        zpfad.parent.mkdir(parents=True, exist_ok=True)
        tmp = zpfad.with_suffix(".tmp"); tmp.write_text(json.dumps(zustand)); tmp.replace(zpfad)
        time.sleep(cfg.get("abfrage_s", 20))


if __name__ == "__main__":
    sys.exit(main())
