from io import BytesIO
import unittest
from unittest.mock import patch
from PIL import Image

from civ2.cursor import CONSTRAINTS, CursorError, locate_cursor, move_and_click, move_cursor


def picture(*positions):
    image = Image.new('RGB',(640,480),(131,118,93))
    for x,y in positions:
        for dx,dy,value in CONSTRAINTS:
            image.putpixel((x+dx,y+dy),value)
    return image


class FakeGame:
    def __init__(self, *, stalled=False, paused=False):
        self.host=(300,250)
        self.cursor=(400,320)
        self.inputs=[]
        self.stalled=stalled
        self.paused=paused
    def request(self,path,binary=False):
        assert path=='/bridge/capture/game' and binary
        out=BytesIO();picture(self.cursor).save(out,format='PNG');return out.getvalue()
    def rpc(self,cmd,*args):
        if cmd=='inputDiagnostics':return {'paused':self.paused,'lastMouse':dict(zip(('x','y'),self.host)),
                                          'sdlMouse':dict(zip(('x','y'),self.host))}
        if cmd=='moveRelative':
            dx,dy=args
            event={'type':'mousemove','dx':dx,'dy':dy}
            self.inputs.append(event.copy())
            if not self.stalled:
                # Emulate different axis gains and acceleration for larger moves.
                gx=2 if abs(dx)>4 else 1
                gy=2 if abs(dy)>6 else 1
                self.cursor=(max(0,min(620,self.cursor[0]+gx*dx)),max(0,min(455,self.cursor[1]+gy*dy)))
            self.host=(max(0,min(639,self.host[0]+dx)),max(0,min(479,self.host[1]+dy)))
        else:
            assert cmd=='mouse'
            event=args[0];self.inputs.append(event.copy())
        return {'type':'mouse',**event}


class CursorTests(unittest.TestCase):
    def test_exact_arrow_and_unconstrained_background(self):
        self.assertEqual(locate_cursor(picture((403,337))),(403,337))
    def test_absent_ambiguous_or_scaled_cursor_is_refused(self):
        for image in (picture(),picture((10,20),(403,337)),picture((10,20)).resize((1280,960))):
            with self.assertRaises(CursorError):locate_cursor(image)
    @patch('civ2.cursor.time.sleep')
    def test_feedback_corrects_nonlinear_relative_motion_before_click(self,_):
        game=FakeGame()
        result=move_and_click(game,247,377)
        self.assertTrue(result['issued'])
        self.assertLessEqual(max(abs(game.cursor[0]-247),abs(game.cursor[1]-377)),3)
        self.assertEqual([event['type'] for event in game.inputs[-2:]],['mousedown','mouseup'])
        self.assertNotEqual([game.host[0],game.host[1]],[247,377])
        self.assertGreater(result['movement_steps'],1)
    @patch('civ2.cursor.time.sleep')
    def test_guest_can_move_when_host_is_already_at_its_edge(self,_):
        game=FakeGame();game.host=(0,479)
        result=move_and_click(game,200,420)
        self.assertTrue(result['issued'])
        self.assertLessEqual(abs(game.cursor[1]-420),3)
    @patch('civ2.cursor.time.sleep')
    def test_no_click_when_guest_does_not_acknowledge(self,_):
        game=FakeGame(stalled=True)
        with self.assertRaisesRegex(CursorError,'acknowledge'):move_and_click(game,247,377)
        self.assertTrue(all(event['type']=='mousemove' for event in game.inputs))
    @patch('civ2.cursor.time.sleep')
    def test_cursor_parking_never_presses_a_button(self,_):
        game=FakeGame();result=move_cursor(game,620,410)
        self.assertFalse(result['issued'])
        self.assertTrue(all(e['type']=='mousemove' for e in game.inputs))
        self.assertLessEqual(abs(game.cursor[0]-620),3)

    def test_invalid_targets_or_paused_game_emit_no_input(self):
        game=FakeGame(paused=True)
        with self.assertRaises(CursorError):move_and_click(game,247,377)
        for target in ((True,1),(639,479),(-1,20),(10.5,20)):
            with self.assertRaises(ValueError):move_and_click(game,*target)
        self.assertEqual(game.inputs,[])


if __name__=='__main__':unittest.main()
