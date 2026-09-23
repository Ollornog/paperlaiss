---
id: T-3
type: Task
title: Python-Untergrenze bewusst setzen statt von der Testmatrix schieben lassen
status: offen
milestone: M-1
tags: [kompatibilitaet, release, wartbarkeit]
created: 2026-09-23
---

# T-3 — Python-Untergrenze bewusst setzen statt von der Testmatrix schieben lassen

`pyproject.toml` sagt `requires-python = ">=3.12"`. Diese Zahl steht dort nicht, weil jemand sie
entschieden hat, sondern weil eine Kit-Prüfung sie an die **Untergrenze der Testmatrix** bindet
(`requires-python nennt die Untergrenze der Matrix`). Die Matrix wiederum ist als „die letzten
drei stable Minors" definiert und wandert von selbst.

**Warum das jetzt auffällt:** Python 3.15 erscheint am 01.10.2026. Sobald es in die Matrix
rückt, wird daraus 3.13 / 3.14 / 3.15 — und die Untergrenze des **veröffentlichten Pakets**
steigt im selben Zug auf 3.13. Für die Testmatrix ist das richtig: ein EOL-Python soll kein Gate
mehr sein. Für ein Werkzeug, das auf **fremden Paperless-Hosts** läuft, ist es etwas anderes,
nämlich eine bruchartige Änderung — und sie fällt einmal im Jahr ohne Beschluss an.

**Was hier vermischt ist, sind zwei verschiedene Zahlen:**

| | Frage | heute |
|---|---|---|
| Testmatrix | Gegen welche Versionen prüfen wir? | 3.12 / 3.13 / 3.14, rollend |
| `requires-python` | Welche Version braucht ein Nutzer mindestens? | `>=3.12`, abgeleitet |

Die zweite ist ein **Versprechen an fremde Installationen**, die erste eine Aussage über unser
Gate. Sie dürfen übereinstimmen, aber nicht deshalb, weil ein Wächter sie verkoppelt hat.

**Es spricht einiges dafür, dass die echte Untergrenze tiefer liegt:**

- `classify.py` ist stdlib-only. Die tatsächliche Grenze ist die jüngste Syntax bzw. das jüngste
  stdlib-Verhalten, das er nutzt — nicht die Zahl in der Matrix. Das ist messbar, nicht Meinung.
- Die Abhängigkeiten des Panels sind es nicht: FastAPI 0.141 und uvicorn 0.53 verlangen `>=3.10`.
- Das Panel läuft ohnehin im Abbild und bringt seinen Python selbst mit — dessen Untergrenze
  berührt keinen Nutzer.
- Verbreitete Distributionen liefern: Debian 12 → 3.11, Ubuntu 24.04 → 3.12, Debian 13 → 3.13.
  Jeder Schritt nach oben schließt eine dieser Umgebungen aus, ohne dass der Code es verlangt.

**Zu tun:**

1. Messen, welche Version `classify.py` wirklich braucht (älteste Fassung, unter der die Suite
   durchläuft) — nicht schätzen.
2. Entscheiden und begründen: Untergrenze = gemessene Grenze, oder bewusst höher.
3. Die Kopplung auflösen oder ausdrücklich bestätigen. Wenn `requires-python` unter der
   Matrix-Untergrenze liegen darf, muss die Kit-Prüfung das zulassen — **nicht abschalten,
   sondern die Regel richtig formulieren**. Betrifft repokit, nicht dieses Repo.
4. Die Entscheidung in `pyproject.toml` und README festhalten, damit die nächste Matrix-Rolle
   sie nicht stillschweigend überschreibt.

**Fertig, wenn** die Untergrenze eine begründete Zahl ist, die Begründung neben ihr steht, und
das Erscheinen von Python 3.15 sie nicht von allein anhebt.
