from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from civ2.run import (_await_turn_resolution,_checkpoint_token,_map_selection_ready,
                      controller_context,run_steps)
from test_run import session,frame


def state(selected=83,owner=0):
    return dict(turn=149,year_raw=960,player={'id':1},selected_unit_id=selected,
                units=[dict(id=83,owner=owner,hp=5)],cities=[],
                evidence={'kind':'live_memory','observation_sha256':'a'*64})


class TurnSelectionReadiness(TestCase):
    def test_null_or_unique_living_owned_selection_only(self):
        for mode in ('none','owned','foreign','missing','dead','unknown_hp','duplicate','boolean'):
            s=state(owner=1)
            if mode=='none':s['selected_unit_id']=None
            if mode=='foreign':s['units'][0]['owner']=0
            if mode=='missing':s['units']=[]
            if mode=='dead':s['units'][0]['hp']=0
            if mode=='unknown_hp':s['units'][0]['hp']=None
            if mode=='duplicate':s['units']*=2
            if mode=='boolean':s['selected_unit_id']=True
            self.assertEqual(bool(_map_selection_ready(s)),mode in ('none','owned'),mode)

    def test_later_turn_foreign_selection_still_waits_without_issuing_input(self):
        for settle in (False,True):
            s=session([]);s.state=state();ctx=controller_context(s)
            ctx['pending_turn']={'decision':663,'source_turn':148}
            s.checkpoint=mock.Mock();s.pending_decisions=[]
            end=frame(1,'end_turn')
            def checkpoint():
                if settle and s.checkpoint.call_count==2:s.state['selected_unit_id']=None
            s.checkpoint.side_effect=checkpoint
            with mock.patch('civ2.run.observe_ready',return_value=(end,end['classified'])),mock.patch('civ2.run.time.sleep'):
                _,_,error=_await_turn_resolution(s,ctx,end,end['classified'],'TEST')
            self.assertEqual(ctx['pending_turn'] is None,settle)
            self.assertEqual(error is None,settle)
            self.assertEqual(s.checkpoint.call_count,2 if settle else 41)
            self.assertTrue(all(c.args[0] in ('resume','pause') for c in s.game.rpc.call_args_list))
            s.ui.key.assert_not_called();s.ui.select_text.assert_not_called();s.game.key.assert_not_called()
            s.choose_dialog.assert_not_called()

    def test_foreign_selection_cannot_create_reuse_token(self):
        s=session([]);s.state=state();s.checkpoints=515;s.pending_decisions=[];s.journal.sequence=4703
        self.assertIsNone(_checkpoint_token(s))
        s.state['selected_unit_id']=None
        self.assertEqual(_checkpoint_token(s)['checkpoint'],515)

    def test_post_dispatch_fast_path_does_not_clear_foreign_turn_or_reuse_it(self):
        end=frame(1,'end_turn');s=session([end,end]);s.state=state(selected=None)
        s.state['turn']=148;checks=0
        def checkpoint():
            nonlocal checks
            checks+=1
            if checks==2:s.state.update(state())
        s.checkpoint=mock.Mock(side_effect=checkpoint)
        def choose(*args):s.decisions+=1;return {'id':'finish_turn'},end
        s.choose_empire=mock.Mock(side_effect=choose)
        with mock.patch('civ2.run.game_text',return_value='TEST'), \
             mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
             mock.patch('civ2.run.time.sleep'):
            run_steps(s,max_decisions=1)
        self.assertEqual(controller_context(s)['pending_turn'],{'decision':1,'source_turn':148})
        self.assertEqual(s.choose_empire.call_count,1)
        self.assertFalse(any(c.args[0]=='checkpoint_reused' for c in s.journal.append.call_args_list))

    def test_actual_012_foreign_selection_abstains_but_later_unselected_state_passes(self):
        from civ2.memory import parse_memory
        from civ2.boot import original_rules
        first=Path('runs/attempt-012/observations/d000515.json')
        after=Path('runs/attempt-012/observations/d000516.json')
        if not first.exists() or not after.exists():self.skipTest('Private native capsules unavailable')
        a=parse_memory(first.read_bytes(),rules_text=original_rules());b=parse_memory(after.read_bytes(),rules_text=original_rules())
        self.assertEqual(a['turn'],149);self.assertEqual(a['selected_unit_id'],83)
        foreign=next(u for u in a['visible_units'] if u['id']==83)
        self.assertEqual(foreign['owner'],0);self.assertEqual(foreign['type'],'Horsemen')
        self.assertFalse(_map_selection_ready(a))
        self.assertEqual(b['turn'],149);self.assertIsNone(b['selected_unit_id']);self.assertTrue(_map_selection_ready(b))
