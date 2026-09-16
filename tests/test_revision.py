import unittest

from civ2.revision import (RevisionError, observation_digest, observation_key,
                           prefixed_revision, revision, revision_digest, revision_key)


class RevisionTests(unittest.TestCase):
    def test_historic_save_schema_is_unchanged(self):
        state = {"turn": 4, "evidence": {"save_sha256": "a" * 64}}
        self.assertEqual(revision(state), {"save_sha256": "a" * 64, "turn": 4})
        self.assertEqual(prefixed_revision(state, "current_"), {"current_save_sha256": "a" * 64})

    def test_live_hash_is_never_labeled_a_save(self):
        state = {"turn": 4, "evidence": {"kind": "live_memory", "observation_sha256": "b" * 64}}
        self.assertEqual(revision(state), {"observation_sha256": "b" * 64, "turn": 4})
        self.assertEqual(observation_key(state), "observation_sha256")
        self.assertEqual(observation_digest(state), "b" * 64)
        fields = prefixed_revision(state, "before_")
        self.assertEqual(revision_digest(fields, "before_"), "b" * 64)
        self.assertEqual(revision_key(fields, "before_"), "before_observation_sha256")

    def test_dual_keys_rejected_even_if_one_is_invalid(self):
        for second in ("a" * 64, None, "bad"):
            with self.subTest(second=second), self.assertRaises(RevisionError):
                revision_digest({"save_sha256": "a" * 64, "observation_sha256": second})

    def test_source_must_agree_with_hash_name(self):
        for evidence in (
            {"kind": "live_memory", "save_sha256": "a" * 64},
            {"observation_sha256": "a" * 64},
            {"kind": "native_save", "observation_sha256": "a" * 64},
            {"kind": "unknown", "save_sha256": "a" * 64},
        ):
            with self.subTest(evidence=evidence), self.assertRaises(RevisionError):
                observation_digest({"evidence": evidence})

    def test_malformed_hashes_and_turns_rejected(self):
        for digest in ("a" * 63, "A" * 64, 42, None):
            with self.subTest(digest=digest), self.assertRaises(RevisionError):
                revision({"turn": 1, "evidence": {"save_sha256": digest}})
        for turn in (-1, True, "1", None):
            with self.subTest(turn=turn), self.assertRaises(RevisionError):
                revision({"turn": turn, "evidence": {"save_sha256": "a" * 64}})
