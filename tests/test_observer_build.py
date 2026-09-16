"""Build packaging checks use synthetic files, not proprietary game assets."""
import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
import zipfile

spec=importlib.util.spec_from_file_location('observer_build',Path(__file__).resolve().parents[1]/'scripts/build-observer.py')
build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)


class ObserverBuildTests(TestCase):
    def fixture(self,directory,ini=b'[windows]\r\nload=\r\nrun=c:\\civ2\\CIV2.EXE\r\n'):
        root=Path(directory);original=root/'original.zip';helper=root/'civ2obs.exe'
        exe=b'TEST ORIGINAL GAME';helper.write_bytes(b'TEST READONLY HELPER')
        with zipfile.ZipFile(original,'w') as z:
            z.writestr('civ2/CIV2.EXE',exe);z.writestr('WINDOWS/WIN.INI',ini)
            z.writestr('civ2/RULES.TXT',b'TEST original rules')
            z.writestr('WINDOWS/SYSTEM.DRV',b'TEST unchanged Windows')
        return root,original,helper,build.sha(exe)

    def test_only_helper_and_exact_startup_line_differ(self):
        with TemporaryDirectory() as directory:
            root,original,helper,exe_hash=self.fixture(directory);original_bytes=original.read_bytes()
            with mock.patch.object(build,'ROOT',root),mock.patch.object(build,'ORIGINAL_EXE_SHA256',exe_hash),\
                 mock.patch.object(build,'HELPER_SHA256',build.sha(helper.read_bytes())):
                report=build.make_overlay(original,helper,root/'derived.zip',original_sha256=build.sha(original_bytes))
            self.assertEqual(original.read_bytes(),original_bytes)
            with zipfile.ZipFile(original) as a,zipfile.ZipFile(root/'derived.zip') as b:
                self.assertEqual(set(b.namelist())-set(a.namelist()),{'CIV2OBS.EXE'})
                self.assertEqual([n for n in a.namelist() if a.read(n)!=b.read(n)],['WINDOWS/WIN.INI'])
                self.assertEqual(b.read('CIV2OBS.EXE'),helper.read_bytes())
                self.assertIn(b'load=c:\\CIV2OBS.EXE\r\n',b.read('WINDOWS/WIN.INI'))
            self.assertEqual(report['original_exe_sha256'],exe_hash)

    def test_hash_mismatch_or_ambiguous_startup_fails_without_output(self):
        for case in ('archive','helper','exe','startup'):
            with self.subTest(case=case),TemporaryDirectory() as directory:
                root,original,helper,exe_hash=self.fixture(directory,b'load=other.exe\r\n' if case=='startup' else b'load=\r\n')
                with mock.patch.object(build,'ROOT',root),\
                     mock.patch.object(build,'ORIGINAL_EXE_SHA256','0'*64 if case=='exe' else exe_hash),\
                     mock.patch.object(build,'HELPER_SHA256','0'*64 if case=='helper' else build.sha(helper.read_bytes())):
                    with self.assertRaises(RuntimeError):
                        build.make_overlay(original,helper,root/'derived.zip',original_sha256='0'*64 if case=='archive' else build.sha(original.read_bytes()))
                self.assertFalse((root/'derived.zip').exists())
                self.assertFalse(list(root.glob('.observer-*')))

    def test_refuses_replacing_original_or_running_changed_source(self):
        with TemporaryDirectory() as directory:
            root,original,helper,_=self.fixture(directory)
            with self.assertRaises(RuntimeError):build.make_overlay(original,helper,original,original_sha256=build.sha(original.read_bytes()))
            source=root/'changed.c';source.write_text('TEST changed source')
            with mock.patch.object(build.subprocess,'run') as run:
                with self.assertRaises(RuntimeError):build.build_helper(root/'missing-compiler',root/'cache',source)
            run.assert_not_called()

    def test_toolchain_extraction_denies_selected_path_traversal(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);archive=root/'compiler.zip'
            with zipfile.ZipFile(archive,'w') as z:z.writestr('binl64/../../escaped',b'TEST')
            with self.assertRaises(RuntimeError):build.extract_toolchain(archive,root/'tools')
            self.assertFalse((root/'escaped').exists())
