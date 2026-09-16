from io import BytesIO
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image

from civ2.cursor import CONSTRAINTS, CursorError, locate_cursor, locate_clipped_cursor, move_and_click, move_cursor


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


class MeasuredEdgeGame(FakeGame):
    """Measured native gain2, retaining the real screen's clipped-arrow region.

    The earlier fake's y455/x620 clamps concealed the actual guest behavior:
    DOSBox/Windows can put the arrow hotspot beyond its fully visible bounds.
    """
    def __init__(self,position):
        super().__init__();self.cursor=position;self.positions=[position]
    def request(self,path,binary=False):
        assert path=='/bridge/capture/game' and binary
        image=Image.new('RGB',(640,480),(131,118,93))
        x,y=self.cursor
        for dx,dy,value in CONSTRAINTS:
            if 0<=x+dx<640 and 0<=y+dy<480:image.putpixel((x+dx,y+dy),value)
        out=BytesIO();image.save(out,format='PNG');return out.getvalue()
    def rpc(self,cmd,*args):
        if cmd=='moveRelative':
            dx,dy=args;event={'type':'mousemove','dx':dx,'dy':dy};self.inputs.append(event)
            self.cursor=(max(0,min(639,self.cursor[0]+2*dx)),max(0,min(479,self.cursor[1]+2*dy)))
            self.positions.append(self.cursor)
            return event
        return super().rpc(cmd,*args)


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

    @patch('civ2.cursor.time.sleep')
    def test_measured_gain_two_reproduces_old_bottom_overshoot_without_click(self,_):
        game=MeasuredEdgeGame((500,447))
        with patch('civ2.cursor.INITIAL_GAIN',1.0):
            with self.assertRaisesRegex(CursorError,'not fully visible'):
                move_and_click(game,500,458)
        self.assertEqual(game.cursor,(500,469))
        self.assertTrue(all(event['type']=='mousemove' for event in game.inputs))

    @patch('civ2.cursor.time.sleep')
    def test_conservative_first_step_keeps_measured_bottom_and_right_arrows_visible(self,_):
        for start,target in (((500,447),(500,458)),((619,410),(627,410))):
            game=MeasuredEdgeGame(start)
            receipt=move_and_click(game,*target)
            self.assertTrue(receipt['issued'])
            self.assertTrue(all(x<=627 and y<=460 for x,y in game.positions))
            self.assertLessEqual(max(abs(a-b) for a,b in zip(game.cursor,target)),3)
            self.assertEqual(receipt['observed_cursor'],list(game.cursor))
            self.assertEqual([event['type'] for event in game.inputs[-2:]],['mousedown','mouseup'])

    def test_optional_actual_clipped_arrow_remains_unsupported(self):
        path=Path(__file__).resolve().parents[1]/'.runtime/headless-benchmark/exit-probe2.png'
        if not path.exists():self.skipTest('private original clipped-arrow image unavailable')
        with Image.open(path) as image:
            with self.assertRaisesRegex(CursorError,'not fully visible'):locate_cursor(image)

    @patch('civ2.cursor.time.sleep')
    def test_clipped_right_arrow_is_restored_before_any_button_press(self,_):
        game=MeasuredEdgeGame((631,425))
        result=move_and_click(game,280,110)
        self.assertEqual(result['edge_recovery']['clipped_cursor'],[631,425])
        self.assertEqual(result['edge_recovery']['delta'],[-8,0])
        self.assertEqual(result['edge_recovery']['restored_full_cursor'],[615,425])
        self.assertFalse(result['edge_recovery']['button_pressed'])
        self.assertEqual([e['type'] for e in game.inputs[-2:]],['mousedown','mouseup'])
        self.assertTrue(all(e['type']=='mousemove' for e in game.inputs[:-2]))

    @patch('civ2.cursor.time.sleep')
    def test_tiny_arrow_fragment_or_missing_cursor_never_moves_or_clicks(self,_):
        for position in ((638,425),(500,475)):
            game=MeasuredEdgeGame(position)
            with self.assertRaises(CursorError):move_and_click(game,280,110)
            self.assertEqual(game.inputs,[])
        with self.assertRaises(CursorError):locate_clipped_cursor(picture())

    @patch('civ2.cursor.time.sleep')
    def test_edge_motion_must_restore_full_arrow_before_click(self,_):
        game=MeasuredEdgeGame((631,425))
        original=game.rpc
        def stalled(command,*args):
            if command=='moveRelative':
                event={'type':'mousemove','dx':args[0],'dy':args[1]}
                game.inputs.append(event);return event
            return original(command,*args)
        game.rpc=stalled
        with self.assertRaises(CursorError):move_and_click(game,280,110)
        self.assertEqual(len(game.inputs),1)
        self.assertEqual(game.inputs[0]['type'],'mousemove')


if __name__=='__main__':unittest.main()
