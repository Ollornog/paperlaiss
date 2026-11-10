#!/usr/bin/env python3
"""Owner-aware routing by person tags — pure logic, no network, no FastAPI.

Paperless workflows can match tags, types and correspondents, but not the owner of a document.
That makes one common household rule impossible to express with workflows alone:

* a document of the *hub* account (the one who files most papers) that carries the tag of a
  person is handed over: the person becomes owner, the hub keeps view and change rights;
* a document of anyone else that carries the tag of another person is *shared*: the owner stays,
  the tagged person gets view and change rights.

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


def targets(tag_names: list[str], persons: dict[str, str], user_ids: dict[str, int]) -> list[int]:
    """User ids of the persons whose tags the document carries. Unknown usernames are skipped."""
    found = set()
    for name in tag_names:
        user = persons.get(str(name).casefold())
        if user and user in user_ids:
            found.add(user_ids[user])
    return sorted(found)


def plan(owner: int | None, tagged: list[int], perms: dict | None, hub: int | None) -> tuple[dict | None, str]:
    """Decide the change for one document.

    owner   current owner id (None = no owner)
    tagged  user ids of the persons whose tags the document carries (see `targets()`)
    perms   Paperless `permissions` of the document (`full_perms=true`):
            {"view": {"users": [...], "groups": [...]}, "change": {...}}
    hub     user id of the hub account, or None (then documents are only ever shared)

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
    if hub is not None and owner == hub and len(others) == 1:
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
        "owner": new_owner,
        # set_permissions replaces the whole set: groups are carried over unchanged.
        "set_permissions": {
            "view": {"users": new_view, "groups": sorted(_groups(perms, "view"))},
            "change": {"users": new_change, "groups": sorted(_groups(perms, "change"))},
        },
    }
    return patch, reason
