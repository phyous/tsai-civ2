import json
from pathlib import Path
import tempfile
import unittest
from civ2.evidence import Journal, verify_chain


class EvidenceTests(unittest.TestCase):
    def test_chain_and_modified_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary)/'attempt')
            journal.append('setup', difficulty='Prince')
            journal.append('decision', choice='settle')
            journal.close()
            self.assertEqual(verify_chain(journal.path)['events'], 2)
            source = journal.path.read_text().replace('Prince', 'Chieftain')
            journal.path.write_text(source)
            with self.assertRaises(ValueError):
                verify_chain(journal.path)

    def test_cannot_overwrite_or_escape_artifacts(self):
        with tempfile.TemporaryDirectory() as temporary:
            journal = Journal(Path(temporary)/'attempt')
            artifact = journal.artifact('screens/start.png', b'real-bytes')
            self.assertEqual(artifact['bytes'], 10)
            with self.assertRaises(ValueError):
                journal.artifact('screens/start.png', b'replacement')
            with self.assertRaises(ValueError):
                journal.artifact('../outside', b'outside')
            journal.close()


if __name__ == '__main__':
    unittest.main()
