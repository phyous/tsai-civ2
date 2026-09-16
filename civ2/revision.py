"""Source-aware hashes for immutable observations and command preconditions.

Historic save observations retain their exact public schema. A live-memory
observation never acquires a ``save_sha256`` alias: a hash identifies the actual
recorded snapshot, not a file that the game did not save.
"""
from __future__ import annotations

import re


class RevisionError(ValueError):
    """Missing, ambiguous, or mislabeled observation provenance."""


_SHA = re.compile(r"[0-9a-f]{64}")
_KEYS = ("save_sha256", "observation_sha256")


def revision_key(mapping, prefix=""):
    """Return the sole valid revision field, rejecting even invalid dual keys."""
    if not isinstance(mapping, dict) or not isinstance(prefix, str):
        raise RevisionError("An observation revision mapping is required")
    keys = [prefix + key for key in _KEYS if prefix + key in mapping]
    if len(keys) != 1:
        raise RevisionError("Exactly one observation revision is required")
    value = mapping[keys[0]]
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise RevisionError("Observation revision must be an exact SHA-256 hash")
    return keys[0]


def revision_digest(mapping, prefix=""):
    return mapping[revision_key(mapping, prefix)]


def observation_key(state):
    if not isinstance(state, dict) or not isinstance(state.get("evidence"), dict):
        raise RevisionError("Observation evidence is required")
    evidence = state["evidence"]
    key = revision_key(evidence)
    kind = evidence.get("kind")
    if kind not in (None, "native_save", "live_memory"):
        raise RevisionError("Unknown observation source")
    expected = "observation_sha256" if kind == "live_memory" else "save_sha256"
    if key != expected:
        raise RevisionError("Observation hash does not match its declared source")
    return key


def observation_digest(state):
    key = observation_key(state)
    return state["evidence"][key]


def prefixed_revision(state, prefix=""):
    if not isinstance(prefix, str):
        raise RevisionError("Revision prefix must be text")
    return {prefix + observation_key(state): observation_digest(state)}


def revision(state):
    fields = prefixed_revision(state)
    turn = state.get("turn")
    if type(turn) is not int or turn < 0:
        raise RevisionError("Observation requires a nonnegative integer turn")
    return {**fields, "turn": turn}
