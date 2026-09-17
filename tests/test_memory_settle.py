"""Phase variation occurs inside the actual image/native-read bracket only."""
import tempfile
from pathlib import Path
from unittest import TestCase,mock
from civ2 import memory
from test_memory import wire
from test_verify import picture


class MemorySettleTests(TestCase):
    def observer(self,directory,events):
        game=mock.Mock()
        def rpc(name,*args):
            events.append(name)
            if name=='listSaves':return []
            if name=='observerProvenance':return dict(original_exe_sha256=memory.EXE_SHA256,helper_sha256=memory.HELPER_SHA256)
            return dict(inputSequence=7)
        game.rpc.side_effect=rpc
        def capture(path):
            events.append('capture');Path(path).write_bytes(picture())
        game.capture.side_effect=capture
        observer=memory.LiveMemoryObserver(game,directory)
        def read_wire(sequence):
            events.append('wire')
            return wire(nonce=('a' if events.count('wire')==1 else 'b')*32)
        observer._read_wire=mock.Mock(side_effect=read_wire)
        return observer

    def test_optional_wait_is_between_middle_picture_and_second_wire_only(self):
        for delay in (0.,.25,.5):
            with self.subTest(delay=delay),tempfile.TemporaryDirectory() as directory:
                events=[];observer=self.observer(directory,events)
                with mock.patch('civ2.memory.time.sleep',side_effect=lambda seconds:events.append(('sleep',seconds))):
                    result=observer.read(middle_settle=delay)
                inside=[e for e in events if e in ('capture','wire') or isinstance(e,tuple)]
                self.assertEqual(inside,['capture','wire','capture']+([('sleep',delay)] if delay else [])+['wire','capture'])
                self.assertEqual(events[-1],'pause')
                self.assertEqual(result['state']['evidence']['kind'],'live_memory')
                self.assertFalse({'key','chord','readSave','importSave'}&set(e for e in events if isinstance(e,str)))

    def test_invalid_wait_rejected_before_runtime_or_capture(self):
        for delay in (-.1,.501,float('inf'),float('nan'),True,'0'):
            with self.subTest(delay=delay),tempfile.TemporaryDirectory() as directory:
                events=[];observer=self.observer(directory,events);events.clear()
                with self.assertRaises(memory.MemoryObservationError):observer.read(middle_settle=delay)
                self.assertEqual(events,[])
                observer.game.capture.assert_not_called()
