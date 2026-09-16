"""Offline launcher ownership tests: never start Chrome, servers, or game inputs."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from civ2 import launcher as L


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(mock.patch.object(L, 'ROOT', self.root))
        self.stack.enter_context(mock.patch.object(L, 'LAUNCHES', self.root / '.runtime' / 'launchers'))
        self.addCleanup(self.stack.close)

    def manifest(self, name='test-launch'):
        directory = L._directory(name, create=True)
        (directory / 'chrome-profile').mkdir()
        commands = L.commands(directory, 3975, '/test/chrome')
        value = dict(version=1, id=name, repository=str(self.root), directory=str(directory),
            profile=str(directory / 'chrome-profile'), port=3975, commands=commands,
            watch_url='http://127.0.0.1:3975/web/watch.html', status='connected',
            processes={role:dict(pid=10001+i, pgid=10001+i, command=' '.join(argv),
                process_sha256=str(i+1)*64) for i,(role,argv) in enumerate(commands.items())})
        L._write(directory, value)
        return directory, value

    def test_fresh_profile_has_no_normal_profile_or_remote_debugging_flags(self):
        directory = L._directory('isolated-test', create=True)
        commands = L.commands(directory, 3975, '/Applications/TEST Chrome')
        self.assertIn(f'--user-data-dir={directory}/chrome-profile', commands['chrome'])
        self.assertIn('--disable-background-timer-throttling', commands['chrome'])
        self.assertIn('--headless=new', commands['chrome'])
        self.assertFalse(any('remote-debugging' in argument for argument in commands['chrome']))
        self.assertIn('isolated-test', commands['server'])
        self.assertEqual(commands['chrome'][-1], 'http://127.0.0.1:3975/')
        with self.assertRaises(L.LauncherError):L._directory('isolated-test', create=True)

    def test_profile_paths_reject_traversal_and_symlink(self):
        for name in ('../outside','/tmp/outside','.', 'a/b', 'a b'):
            with self.assertRaises(L.LauncherError):L._directory(name, create=True)
        (self.root / '.runtime').symlink_to(self.root)
        with self.assertRaises(L.LauncherError):L._directory('test', create=True)

    def test_reserved_or_occupied_ports_never_launch(self):
        for port in (*range(3920,3925),80,65536,True):
            with self.assertRaises(L.LauncherError):L.select_port(port)
        with mock.patch.object(L,'_port_available',return_value=False):
            with self.assertRaises(L.LauncherError):L.select_port(3975)
        with mock.patch.object(L,'_port_available',side_effect=lambda p:p==3932):
            self.assertEqual(L.select_port(),3932)

    def test_pid_reuse_refuses_all_signals_including_other_owned_process(self):
        _, value = self.manifest()
        records = {v['pid']:v for v in value['processes'].values()}
        reused = value['processes']['chrome']['pid']
        def lookup(pid):
            record = dict(records[pid])
            if pid==reused:record['process_sha256']='f'*64
            return record
        with mock.patch.object(L,'process_identity',side_effect=lookup), mock.patch.object(L.os,'killpg') as kill:
            with self.assertRaisesRegex(L.LauncherError,'identity changed'):L.stop('test-launch')
            kill.assert_not_called()

    def test_edited_profile_or_process_command_cannot_authorize_stop(self):
        directory,value = self.manifest()
        for field in ('profile','command'):
            modified=json.loads(json.dumps(value))
            if field=='profile':modified['profile']='/Users/TEST/Normal Chrome Profile'
            else:modified['processes']['chrome']['command']='/other/chrome --normal-profile'
            L._write(directory,modified)
            with mock.patch.object(L.os,'killpg') as kill:
                with self.assertRaises(L.LauncherError):L.stop('test-launch')
                kill.assert_not_called()

    def test_clean_stop_signals_only_owned_groups_preserves_profile_and_receipts(self):
        directory,value = self.manifest()
        records={record['pid']:record for record in value['processes'].values()}
        signals=[]
        def terminate(pgid,sig):
            signals.append((pgid,sig));records.pop(pgid,None)
        with mock.patch.object(L,'process_identity',side_effect=lambda pid:records.get(pid)), \
             mock.patch.object(L.os,'killpg',side_effect=terminate):
            result=L.stop('test-launch')
        self.assertEqual(signals,[(10002,signal.SIGTERM),(10001,signal.SIGTERM)])
        self.assertEqual(result['processes'],{'server':'stopped','chrome':'stopped'})
        self.assertEqual(result['status'],'stopped')
        self.assertTrue((directory/'chrome-profile').is_dir())
        self.assertTrue((directory/'processes.json').is_file())

    def test_missing_process_is_not_signaled(self):
        self.manifest()
        with mock.patch.object(L,'process_identity',return_value=None), mock.patch.object(L.os,'killpg') as kill:
            L.stop('test-launch');kill.assert_not_called()

    def test_symbolic_manifest_is_rejected_without_signals(self):
        directory,_=self.manifest()
        manifest=directory/'processes.json';copy=directory/'old.json';manifest.rename(copy);manifest.symlink_to(copy)
        with mock.patch.object(L.os,'killpg') as kill:
            with self.assertRaises(L.LauncherError):L.stop('test-launch')
            kill.assert_not_called()

    def test_start_uses_fresh_owned_groups_without_model_key(self):
        children=[];seen=[]
        def spawn(argv,**kwargs):
            child=mock.Mock(pid=11001+len(children));child.poll.return_value=None
            children.append(child);seen.append((argv,kwargs));return child
        def identity(pid):
            argv=seen[pid-11001][0]
            return dict(pid=pid,pgid=pid,command=' '.join(argv),process_sha256='a'*64)
        with mock.patch.object(L,'select_port',return_value=3975), \
             mock.patch.object(L,'_chrome_path',return_value='/test/chrome'), \
             mock.patch.object(L.subprocess,'Popen',side_effect=spawn), \
             mock.patch.object(L,'process_identity',side_effect=identity), \
             mock.patch.object(L,'_wait_ready'), \
             mock.patch.dict(os.environ,{'TYPESAFE_API_KEY':'TEST-NONSECRET-DO-NOT-INHERIT'}):
            result=L.start(identifier='test-start')
        self.assertEqual(result['status'],'connected')
        self.assertEqual(len(children),2)
        for _,kwargs in seen:
            self.assertTrue(kwargs['start_new_session'])
            self.assertNotIn('TYPESAFE_API_KEY',kwargs['env'])
        self.assertTrue(Path(result['profile']).is_dir())
        self.assertNotIn('TEST-NONSECRET',Path(result['directory'],'processes.json').read_text())

    def test_exited_chrome_cleanup_race_does_not_leave_owned_server(self):
        children=[];seen=[]
        def spawn(argv,**kwargs):
            child=mock.Mock(pid=11001+len(children));child.poll.return_value=None
            children.append(child);seen.append(argv);return child
        def identity(pid):
            return dict(pid=pid,pgid=pid,command=' '.join(seen[pid-11001]),process_sha256='a'*64)
        def group(pid):
            if pid==11002:raise ProcessLookupError()
            return pid
        with mock.patch.object(L,'select_port',return_value=3975), \
             mock.patch.object(L,'_chrome_path',return_value='/test/chrome'), \
             mock.patch.object(L.subprocess,'Popen',side_effect=spawn), \
             mock.patch.object(L,'process_identity',side_effect=identity), \
             mock.patch.object(L,'_wait_ready',side_effect=[None,L.LauncherError('TEST startup failure')]), \
             mock.patch.object(L.os,'getpgid',side_effect=group), \
             mock.patch.object(L.os,'killpg') as kill:
            with self.assertRaisesRegex(L.LauncherError,'TEST startup failure'):
                L.start(identifier='test-failure')
            kill.assert_called_once_with(11001,signal.SIGTERM)
        self.assertEqual(json.loads((L.LAUNCHES/'test-failure'/'processes.json').read_text())['status'],'failed')

    def test_process_identity_reads_real_owned_child_not_environment(self):
        # A harmless Python sleeper validates the actual ps format on this OS.
        code='import time; print("ready",flush=True); time.sleep(30)'
        argv=[sys.executable,'-c',code]
        child=subprocess.Popen(argv,start_new_session=True,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'ready')
            identity=L.process_identity(child.pid)
            self.assertEqual(identity['pid'],child.pid)
            self.assertEqual(identity['pgid'],child.pid)
            self.assertTrue(identity['command'].endswith(' -c '+code))
            self.assertEqual(identity,L.process_identity(child.pid))
            self.assertEqual(len(identity['process_sha256']),64)
        finally:
            child.terminate();child.wait(timeout=5);child.stdout.close()

    def test_identity_is_captured_after_owned_child_finishes_framework_exec(self):
        children=[];ready=set();arguments={}
        def spawn(argv,**kwargs):
            child=mock.Mock(pid=11001+len(children));child.poll.return_value=None
            children.append(child);arguments[child.pid]=list(argv);return child
        def wait(port,processes,**kwargs):ready.add(processes[-1].pid)
        def identity(pid):
            self.assertIn(pid,ready)
            argv=arguments[pid]
            if pid==11001:argv=['/framework/interpreter',*argv[1:]]
            return dict(pid=pid,pgid=pid,command=' '.join(argv),process_sha256='a'*64)
        with mock.patch.object(L,'select_port',return_value=3975), \
             mock.patch.object(L,'_chrome_path',return_value='/test/chrome'), \
             mock.patch.object(L.subprocess,'Popen',side_effect=spawn), \
             mock.patch.object(L,'process_identity',side_effect=identity), \
             mock.patch.object(L,'_wait_ready',side_effect=wait):
            result=L.start(identifier='test-framework-exec')
        self.assertTrue(result['processes']['server']['command'].startswith('/framework/interpreter -m civ2.launcher _serve'))
        self.assertEqual(result['commands']['server'][0],'/framework/interpreter')
        self.assertEqual(L._load('test-framework-exec')[1],result)


if __name__=='__main__':unittest.main()
