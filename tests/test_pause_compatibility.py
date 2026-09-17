import unittest
from civ2.engine import Game

class FakeGame(Game):
    def __init__(self,paused=False,backend='js-dos-worker',version=0):
        self.calls=[];self.status={'paused':paused,'pauseBackend':backend,'pauseFence':'worker-two-roundtrips-v1' if version==2 else None}
    def request(self,path,payload):
        command=payload['command'];self.calls.append(command)
        if command=='pause':self.status['paused']=True
        if command=='resume':self.status['paused']=False
        return {'result':[] if command=='listSaves' else dict(self.status)}

class PauseCompatibilityTests(unittest.TestCase):
    def test_existing_worker_gets_read_only_fence_even_if_already_paused(self):
        for paused in (True,False):
            game=FakeGame(paused=paused)
            self.assertTrue(game.rpc('pause')['paused'])
            self.assertEqual(game.calls,['status']+([] if paused else ['pause'])+['listSaves','listSaves','status'])
    def test_legacy_and_new_fenced_worker_do_not_get_extra_reads(self):
        for backend,version in [('emterpreter',0),('js-dos-worker',2)]:
            game=FakeGame(backend=backend,version=version);game.rpc('pause')
            self.assertEqual(game.calls,['status','pause'])
    def test_resume_never_uses_pause_fence(self):
        game=FakeGame(paused=True);game.rpc('resume')
        self.assertEqual(game.calls,['status','resume'])
