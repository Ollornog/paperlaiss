#!/usr/bin/env python3
"""Unit test: owner-aware routing by person tags (panel/routing.py)."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "panel"))
sys.path.insert(0, str(ROOT / "tests"))

import routing  # noqa: E402
from _kit.report import Report  # noqa: E402

r = Report("Unit test — panel/routing.py")


def chk(name, passed, info=""):
    return r.check(name, bool(passed), str(info))


HUB, ALICE, BOB, CAROL = 3, 4, 5, 7
EMPTY = {"view": {"users": [], "groups": []}, "change": {"users": [], "groups": []}}


def perms(view=(), change=(), vg=(), cg=()):
    return {"view": {"users": list(view), "groups": list(vg)},
            "change": {"users": list(change), "groups": list(cg)}}


# ---- parse_persons
chk("persons: tag lower-cased, username kept",
        routing.parse_persons("Alice=alice, Bobby = Bob") == {"alice": "alice", "bobby": "Bob"})
chk("persons: broken entries are ignored",
        routing.parse_persons("x, =a, b=, ,c=d") == {"c": "d"})
chk("persons: empty text gives nothing", routing.parse_persons("") == {} and routing.parse_persons(None) == {})

# ---- targets
_persons = routing.parse_persons("Alice=alice,Bobby=bob,Ghost=ghost")
_ids = {"alice": ALICE, "bob": BOB, "hub": HUB}
chk("targets: tag names case-insensitive, other tags ignored",
        routing.targets(["ALICE", "Rechnung", "bobby"], _persons, _ids) == [ALICE, BOB])
chk("targets: person without a Paperless account is skipped",
        routing.targets(["Ghost"], _persons, _ids) == [])
chk("targets: no tags gives nothing", routing.targets([], _persons, _ids) == [])

# ---- rule 1: hub document with one person tag is handed over, hub keeps view and change
patch, why = routing.plan(HUB, [ALICE], EMPTY, HUB)
chk("hand-over: owner becomes the person", patch is not None and patch["owner"] == ALICE, patch)
chk("hand-over: hub keeps view and change",
        patch["set_permissions"]["view"]["users"] == [HUB] and patch["set_permissions"]["change"]["users"] == [HUB],
        patch)
chk("hand-over: reason says so", why == "handed over", why)

# ---- rule 2: someone else's document with another person's tag is shared, owner stays
patch, why = routing.plan(ALICE, [BOB], EMPTY, HUB)
chk("share: owner is not written (stays as it is)", patch is not None and "owner" not in patch, patch)
chk("share: tagged person and hub get view",
        patch["set_permissions"]["view"]["users"] == [HUB, BOB], patch)
chk("share: tagged person and hub get change",
        patch["set_permissions"]["change"]["users"] == [HUB, BOB], patch)
chk("share: reason", why == "shared", why)

# ---- own document with own tag: owner stays, the owner is never put into its own rights
patch, why = routing.plan(ALICE, [ALICE], EMPTY, HUB)
chk("own tag: owner stays, only the hub is added",
        patch is not None and "owner" not in patch
        and patch["set_permissions"]["view"]["users"] == [HUB]
        and ALICE not in patch["set_permissions"]["change"]["users"], patch)
patch, why = routing.plan(ALICE, [ALICE], perms([HUB], [HUB]), HUB)
chk("own tag, hub already in: nothing to do", patch is None and why == "already in place", (patch, why))

# ---- idempotence: the state after a hand-over gives no second change
first, _ = routing.plan(HUB, [ALICE], EMPTY, HUB)
again, why = routing.plan(first["owner"], [ALICE], first["set_permissions"], HUB)
chk("idempotent: second run after hand-over is a no-op", again is None and why == "already in place",
        (again, why))
first, _ = routing.plan(ALICE, [BOB], perms(vg=[9], cg=[9]), HUB)
again, _ = routing.plan(first.get("owner", ALICE), [BOB], first["set_permissions"], HUB)
chk("idempotent: second run after share is a no-op", again is None, again)

# ---- several persons on a hub document: no hand-over (ambiguous), everyone shared
patch, why = routing.plan(HUB, [ALICE, BOB], EMPTY, HUB)
chk("two persons: hub stays owner", patch is not None and "owner" not in patch, patch)
chk("two persons: both get view and change",
        patch["set_permissions"]["view"]["users"] == [ALICE, BOB]
        and patch["set_permissions"]["change"]["users"] == [ALICE, BOB], patch)
chk("two persons: reason names it", "several" in why, why)
patch, why = routing.plan(HUB, [HUB, ALICE], EMPTY, HUB)
chk("hub tag plus one person still hands over", patch is not None and patch["owner"] == ALICE, patch)

# ---- nothing is ever removed, groups are carried over
patch, _ = routing.plan(HUB, [ALICE], perms([CAROL], [CAROL], [8], [9]), HUB)
chk("existing user rights stay", CAROL in patch["set_permissions"]["view"]["users"]
        and CAROL in patch["set_permissions"]["change"]["users"], patch)
chk("groups are carried over unchanged", patch["set_permissions"]["view"]["groups"] == [8]
        and patch["set_permissions"]["change"]["groups"] == [9], patch)

# ---- edges
chk("no person tag: nothing", routing.plan(HUB, [], EMPTY, HUB) == (None, "no person tag"))
chk("no owner: left alone", routing.plan(None, [ALICE], EMPTY, HUB) == (None, "document has no owner"))
patch, why = routing.plan(HUB, [ALICE], EMPTY, None)
chk("without a hub nothing is handed over", patch is not None and "owner" not in patch
        and patch["set_permissions"]["view"]["users"] == [ALICE], patch)
chk("missing permissions are treated as empty", routing.plan(BOB, [ALICE], None, HUB)[0] is not None)

# ---- race: the owner that was read is never written back
# An uploader hands the document over (owner 6 -> ALICE) between the webhook's read and its write. The
# webhook read owner 6 (not the hub), so it shares. Its patch must not carry owner 6, or it undoes the
# hand-over. Simulated: apply the patch onto the state after the uploader's change.
UPLOADER = 6
patch, why = routing.plan(UPLOADER, [ALICE], EMPTY, HUB)
after = {"owner": ALICE}
after.update({k: v for k, v in (patch or {}).items() if k == "owner"})
chk("race: a stale owner is not written back", why == "shared" and after["owner"] == ALICE, (patch, after))
patch, _ = routing.plan(UPLOADER, [ALICE], EMPTY, HUB)
chk("race: the tagged person and the hub still get view and change",
        patch["set_permissions"]["view"]["users"] == [HUB, ALICE]
        and patch["set_permissions"]["change"]["users"] == [HUB, ALICE], patch)

# ---- upload account: a scanner uploads as itself and sets the owner afterwards (T-12: it lost the network after
# the upload, ten scans stayed with the upload account). Its documents are handed over like the hub's.
patch, why = routing.plan(UPLOADER, [ALICE], EMPTY, HUB, frozenset({UPLOADER}))
chk("uploader: the one tagged person becomes owner", patch is not None and patch.get("owner") == ALICE
        and why == "handed over from the upload account", (patch, why))
chk("uploader: the hub gets view and change, the upload account nothing",
        patch["set_permissions"]["view"]["users"] == [HUB] and patch["set_permissions"]["change"]["users"] == [HUB], patch)
patch, why = routing.plan(UPLOADER, [ALICE, BOB], EMPTY, HUB, frozenset({UPLOADER}))
chk("uploader: several persons tagged are shared, the owner is not written",
        patch is not None and "owner" not in patch and why == "several persons tagged, shared instead of handed over"
        and patch["set_permissions"]["view"]["users"] == [HUB, ALICE, BOB], (patch, why))
patch, why = routing.plan(UPLOADER, [ALICE], EMPTY, None, frozenset({UPLOADER}))
chk("uploader: without a hub it is handed over too", patch is not None and patch.get("owner") == ALICE, (patch, why))
patch, why = routing.plan(ALICE, [BOB], EMPTY, HUB, frozenset({UPLOADER}))
chk("uploader: other owners are still only shared", patch is not None and "owner" not in patch and why == "shared", (patch, why))
patch, _ = routing.plan(ALICE, [ALICE], perms([HUB], [HUB]), HUB, frozenset({UPLOADER}))
chk("uploader: after the hand-over a second call is a no-op", patch is None, patch)

chk("uploader: env list parsed, looked up with persons and hub, unknown names skipped",
        routing.parse_users(" scanner, ,mailbot ") == ["scanner", "mailbot"]
        and routing.wanted_users({"alice": "alice"}, "hub", ["scanner"]) == ["alice", "hub", "scanner"]
        and routing.wanted_users({"alice": "alice"}, "", []) == ["alice"]
        and routing.uploader_ids(["scanner", "ghost"], {"scanner": UPLOADER, "alice": ALICE}) == frozenset({UPLOADER}))

sys.exit(r.done())
