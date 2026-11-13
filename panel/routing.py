#!/usr/bin/env python3
"""Owner-aware routing by person tags — pure logic, no network, no FastAPI.

Paperless workflows can match tags, types and correspondents, but not the owner of a document.
That makes one common household rule impossible to express with workflows alone:

* a document of the *hub* account (the one who files most papers) that carries the tag of a
  person is handed over: the person becomes owner, the hub keeps view and change rights;
* a document of anyone else that carries the tag of another person is *shared*: the owner stays,
  the tagged person gets view and change rights;
* a document still owned by an *upload account* (a scanner that uploads as itself and sets the owner
  afterwards) is handed over like a hub document: the uploader may never get to set the owner (it lost
  the network after the upload, and ten scans stayed with the upload account).

A Paperless workflow with a webhook action sends the document id to the panel (`POST /route`);
the panel reads the document and applies `plan()`. The webhook carries no decision, only the id:
the configuration lives in the panel's environment, so whoever can call the endpoint can only
make a document converge to the rules, never pick a new owner.

`plan()` only ever adds rights and changes the owner in the hand-over case. It never removes a
right, so a manual grant survives and running it twice changes nothing the second time (the
PATCH it causes triggers the workflow again; that second call must be a no-op).
"""
from __future__ import annotations


def parse_persons(text: str) -> dict[str, str]:
    """`"Alice=alice, Bob = bob"` → `{"alice": "alice", "bob": "bob"}` (tag name lower-cased → username).

    Tag names are compared case-insensitively, usernames exactly as Paperless stores them.
    Entries without `=` or with an empty side are ignored.
    """
    persons: dict[str, str] = {}
    for part in (text or "").split(","):
        tag, sep, user = part.partition("=")
        tag, user = tag.strip(), user.strip()
        if sep and tag and user:
            persons[tag.casefold()] = user
    return persons


def _users(perms: dict | None, kind: str) -> list[int]:
    return [int(u) for u in ((perms or {}).get(kind) or {}).get("users") or []]


def _groups(perms: dict | None, kind: str) -> list[int]:
    return [int(g) for g in ((perms or {}).get(kind) or {}).get("groups") or []]


def parse_users(text: str) -> list[str]:
    """`"scanner, mailbot"` → `["scanner", "mailbot"]` (usernames as Paperless stores them; empty entries dropped)."""
    return [u.strip() for u in (text or "").split(",") if u.strip()]


def wanted_users(persons: dict[str, str], hub: str, uploaders: list[str]) -> list[str]:
    """Usernames whose ids the webhook has to look up: the persons, the hub and the upload accounts."""
    return sorted(set(persons.values()) | ({hub} if hub else set()) | set(uploaders))


def uploader_ids(uploaders: list[str], user_ids: dict[str, int]) -> frozenset[int]:
    """Ids of the upload accounts that exist; an unknown name is skipped."""
    return frozenset(user_ids[u] for u in uploaders if u in user_ids)


def targets(tag_names: list[str], persons: dict[str, str], user_ids: dict[str, int]) -> list[int]:
    """User ids of the persons whose tags the document carries. Unknown usernames are skipped."""
    found = set()
    for name in tag_names:
        user = persons.get(str(name).casefold())
        if user and user in user_ids:
            found.add(user_ids[user])
    return sorted(found)


def plan(owner: int | None, tagged: list[int], perms: dict | None, hub: int | None,
         uploaders: frozenset[int] | set[int] = frozenset()) -> tuple[dict | None, str]:
    """Decide the change for one document.

    owner   current owner id (None = no owner)
    tagged  user ids of the persons whose tags the document carries (see `targets()`)
    perms   Paperless `permissions` of the document (`full_perms=true`):
            {"view": {"users": [...], "groups": [...]}, "change": {...}}
    hub     user id of the hub account, or None (then documents are only ever shared)
    uploaders  user ids of upload accounts; their documents are handed over like the hub's

    Returns (patch, reason). `patch` is the body for `PATCH /api/documents/<id>/` or None when
    nothing has to change.
    """
    if not tagged:
        return None, "no person tag"
    if owner is None:
        # An unowned document is visible to everyone who may view documents. Handing it to a person
        # would narrow that down; that is a decision for a human, not for a tag.
        return None, "document has no owner"
    others = [u for u in tagged if u != hub]
    new_owner = owner
    if owner in uploaders and len(tagged) == 1:
        new_owner = tagged[0]
        reason = "handed over from the upload account"
    elif owner in uploaders:
        reason = "several persons tagged, shared instead of handed over"
    elif hub is not None and owner == hub and len(others) == 1:
        new_owner = others[0]
        reason = "handed over"
    elif hub is not None and owner == hub and len(others) > 1:
        reason = "several persons tagged, shared instead of handed over"
    else:
        reason = "shared"
    grant = set(tagged)
    if hub is not None:
        grant.add(hub)
    grant.discard(new_owner)
    view = _users(perms, "view")
    change = _users(perms, "change")
    new_view = sorted(set(view) | grant)
    new_change = sorted(set(change) | grant)
    if new_owner == owner and set(new_view) == set(view) and set(new_change) == set(change):
        return None, "already in place"
    patch = {
        # set_permissions replaces the whole set: groups are carried over unchanged.
        "set_permissions": {
            "view": {"users": new_view, "groups": sorted(_groups(perms, "view"))},
            "change": {"users": new_change, "groups": sorted(_groups(perms, "change"))},
        },
    }
    # The owner goes into the patch only when it changes. Writing back the owner that was read would
    # undo a hand-over another client made between our read and our write (an uploader that sets the
    # owner right after the import raced the workflow webhook and lost the document to itself).
    if new_owner != owner:
        patch["owner"] = new_owner
    return patch, reason
