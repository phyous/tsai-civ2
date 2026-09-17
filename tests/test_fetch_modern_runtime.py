import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('fetch_modern_runtime',Path(__file__).resolve().parents[1]/'scripts/fetch_modern_runtime.py')
fetch=importlib.util.module_from_spec(spec);spec.loader.exec_module(fetch)

class ModernFetchTests(unittest.TestCase):
    def fixture(self, *, symlink=False, duplicate=False):
        data=b'public runtime';out=io.BytesIO()
        with tarfile.open(fileobj=out,mode='w:gz') as archive:
            for _ in range(2 if duplicate else 1):
                member=tarfile.TarInfo('package/dist/runtime.js')
                if symlink:member.type=tarfile.SYMTYPE;member.linkname='/etc/passwd'
                else:member.size=len(data)
                archive.addfile(member,None if symlink else io.BytesIO(data))
        raw=out.getvalue()
        measure=lambda b:dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
        return raw,{'archive':measure(raw),'files':[dict(member='package/dist/runtime.js',path='vendor/modern/runtime.js',**measure(data))]}

    def test_verified_bytes_only_and_other_files_untouched(self):
        raw,m=self.fixture()
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);(root/'game').mkdir();(root/'game/original').write_bytes(b'game')
            fetch.install(raw,root,m)
            self.assertEqual((root/'vendor/modern/runtime.js').read_bytes(),b'public runtime')
            self.assertEqual((root/'game/original').read_bytes(),b'game')
            with self.assertRaises(ValueError):fetch.install(raw+b'changed',root,m)
            self.assertEqual((root/'vendor/modern/runtime.js').read_bytes(),b'public runtime')

    def test_unsafe_members_and_destinations_rejected(self):
        for kwargs in ({'symlink':True},{'duplicate':True}):
            raw,m=self.fixture(**kwargs)
            with tempfile.TemporaryDirectory() as t,self.assertRaises(ValueError):fetch.install(raw,Path(t),m)
        raw,m=self.fixture();m['files'][0]['path']='../escape'
        with tempfile.TemporaryDirectory() as t,self.assertRaises(ValueError):fetch.install(raw,Path(t),m)

    def test_checked_manifest_matches_actual_optional_download(self):
        root=Path(__file__).resolve().parents[1];m=json.loads((root/'engine/modern-manifest.json').read_text())
        self.assertEqual(m['version'],'8.4.2');self.assertEqual(m['license'],'GPL-2.0')
        for entry in m['files']:
            p=root/'engine'/entry['path']
            if not p.exists():self.skipTest('Optional runtime has not been fetched')
            self.assertTrue(fetch.checked(p.read_bytes(),entry))

if __name__=='__main__':unittest.main()
