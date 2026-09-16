"""Native city-review transaction tests; all observations are synthetic TEST."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
import unittest

from civ2.city_controls import city_control_candidates
from civ2.run import controller_context, run_steps, observed_city_identity, city_control_review
from test_city_controls import inputs


def frame(number,kind='city_screen',**changes):
    _,city,_=inputs()
    digest=f'{number:064x}'
    dialog={**city,'kind':kind,'sha256':digest,'mechanical_action':None,
            'requires_model':False,'resource_tag':None}
    if kind!='city_screen':dialog.update(title=kind,options=[],buttons=[])
    dialog.update(changes)
    return {'sha256':digest,'path':f'/tmp/TEST-city/screens/{number}.png',
            'text':dialog['title'],'classified':dialog}


def session(observations,choices):
    state,_,rules=inputs()
    s=SimpleNamespace(state=state,rules=rules,decisions=0,recorder=None,game=mock.Mock(),
        ui=mock.Mock(),journal=mock.Mock(),publish=mock.Mock(),checkpoint=mock.Mock())
    s.journal.directory=Path('/tmp/TEST-city');s.ui.observe.side_effect=observations
    wanted=iter(choices)
    def choose(screen,reviewed):
        actions=city_control_candidates(s.state,screen,reviewed,s.rules)
        if len(actions)>1:s.decisions+=1
        return actions[next(wanted)],frame(100,'unknown')
    s.choose_city_control=mock.Mock(side_effect=choose)
    s.choose_dialog=mock.Mock(side_effect=lambda d:setattr(s,'decisions',s.decisions+1))
    s.mechanical=mock.Mock()
    controller_context(s)['graphics_configured']=True
    controller_context(s)['throne_presentation_disabled']=True
    return s


def events(s,kind):
    return [call.kwargs for call in s.journal.append.call_args_list if call.args[0]==kind]


def run(s,limit):
    with mock.patch('civ2.run.game_text',return_value='TEST'), \
         mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kw:o['classified']), \
         mock.patch('civ2.run.time.sleep'):
        return run_steps(s,max_decisions=limit)


class RunCityControlsTests(unittest.TestCase):
    def test_production_review_requires_choice_and_return_to_same_city(self):
        production=frame(2,'production_choice',requires_model=True,options=[{},{}])
        s=session([frame(1),production,frame(3)],['change_production','exit_city'])
        run(s,3);ctx=controller_context(s)
        record=next(iter(ctx['city_controls_reviewed'].values()))
        self.assertEqual(record['actions'],['change_production'])
        self.assertIn(('TEST Rome','3700BC'),ctx['production_reviewed'])
        event=events(s,'city_control_review_completed')[0]
        self.assertEqual(event['decision'],1);self.assertEqual(event['response_decision'],2)
        self.assertEqual(event['completion_screen'],frame(3)['sha256'])
        self.assertEqual(ctx['pending_city_control']['action']['id'],'exit_city')

    def test_dispatched_choice_without_return_has_not_completed_review(self):
        production=frame(2,'production_choice',requires_model=True,options=[{},{}])
        s=session([frame(1),production],['change_production'])
        run(s,2);ctx=controller_context(s)
        self.assertEqual(next(iter(ctx['city_controls_reviewed'].values()))['actions'],[])
        self.assertEqual(ctx['production_reviewed'],set())
        self.assertTrue(ctx['pending_city_control']['response_dispatched'])
        self.assertEqual(events(s,'city_control_review_completed'),[])

    def test_buy_requires_separate_quote_choice_then_observed_city_return(self):
        quote=frame(2,'buy_quote',resource_tag='COMPLETE1',requires_model=True,
                    options=[{'text':'Complete it.'},{'text':'Never mind.'}],quote={'cost':100,'treasury':150})
        s=session([frame(1),quote,frame(3)],['open_buy_quote','exit_city'])
        run(s,3);s.choose_dialog.assert_called_once_with(quote['classified'])
        event=events(s,'city_control_review_completed')[0]
        self.assertEqual(event['action_id'],'open_buy_quote')
        self.assertEqual(event['observed_dialog']['resource_tag'],'COMPLETE1')
        self.assertEqual(event['response_decision'],2)
        self.assertEqual(event['reviewed']['actions'],['open_buy_quote'])
        self.assertEqual(controller_context(s)['production_reviewed'],set())

    def test_unaffordable_quote_acknowledgment_is_a_review_not_purchase(self):
        quote=frame(2,'buy_quote',resource_tag='COMPLETE0',mechanical_action='acknowledge_information',
                    options=[{'text':'OK'}],quote={'cost':100,'treasury':2})
        s=session([frame(1),quote,frame(3)],['open_buy_quote','exit_city'])
        run(s,2);s.mechanical.assert_called_once_with('acknowledge_information')
        s.choose_dialog.assert_not_called()
        event=events(s,'city_control_review_completed')[0]
        self.assertIsNone(event['response_decision'])
        self.assertEqual(event['observed_dialog']['resource_tag'],'COMPLETE0')

    def test_control_with_no_followup_and_wrong_city_return_pause_without_review(self):
        for next_frame in (frame(2),frame(2,title='City of TEST Veii, 3700 B.C.')):
            s=session([frame(1),next_frame],['change_production'])
            outcome=run(s,5)
            self.assertEqual(outcome['status'],'paused')
            self.assertEqual(s.choose_city_control.call_count,1)
            self.assertEqual(next(iter(controller_context(s)['city_controls_reviewed'].values()))['actions'],[])
            self.assertEqual(events(s,'city_control_review_completed'),[])

    def test_quote_still_present_after_response_is_not_repeated(self):
        quote=frame(2,'buy_quote',resource_tag='COMPLETE1',requires_model=True,options=[{},{}])
        s=session([frame(1),quote,quote],['open_buy_quote'])
        result=run(s,5)
        self.assertIn('remained after',result['reason']);s.choose_dialog.assert_called_once()
        self.assertEqual(events(s,'city_control_review_completed'),[])

    def test_exit_closure_preserves_empire_city_inspection_transaction(self):
        end=frame(2,'end_turn')
        s=session([frame(1),end,end],['exit_city']);ctx=controller_context(s)
        ctx['pending_empire']={'id':'inspect_city_0'};ctx['pending_city']={'name':'TEST Rome'}
        def finish(*args):
            s.decisions+=1
            return {'id':'finish_turn'},frame(3,'normal_map')
        s.choose_empire=mock.Mock(side_effect=finish)
        run(s,2)
        self.assertIsNone(ctx['pending_city_control']);self.assertIsNone(ctx['pending_city'])
        self.assertIn('inspect_city_0',ctx['reviewed']['actions'])
        self.assertEqual(events(s,'city_control_closed')[0]['city'],{'id':0,'name':'TEST Rome','year_raw':-3700})

    def test_same_year_prior_production_review_is_synced_before_city_choice(self):
        s=session([frame(1)],['exit_city']);ctx=controller_context(s)
        ctx['production_reviewed'].add(('TEST Rome','3700BC'))
        run(s,1)
        self.assertEqual(s.choose_city_control.call_args.args[1]['actions'],['change_production'])

    def test_automatic_new_year_city_uses_legacy_observed_production_flow(self):
        city=frame(1,title='City of TEST Rome, 3650 B.C.')
        production=frame(2,'production_choice',requires_model=True,options=[{},{}])
        s=session([city,production],[])
        run(s,1);s.choose_city_control.assert_not_called()
        s.ui.select_text.assert_called_once()
        self.assertEqual(s.ui.select_text.call_args.args[1],'Change')
        self.assertIn(('TEST Rome','3650BC'),controller_context(s)['production_reviewed'])

    def test_new_turn_checkpoint_keeps_production_review_done_in_automatic_window(self):
        end=frame(1,'end_turn');s=session([end,end],[]);ctx=controller_context(s)
        ctx['production_reviewed']={('TEST Rome','3650BC'),('TEST Rome','3700BC')}
        def checkpoint():s.state.update(turn=8,year_raw=-3650)
        s.checkpoint.side_effect=checkpoint
        def finish(*args):s.decisions+=1;return {'id':'finish_turn'},frame(3,'normal_map')
        s.choose_empire=mock.Mock(side_effect=finish)
        run(s,1)
        self.assertEqual(ctx['production_reviewed'],{('TEST Rome','3650BC')})

    def test_recovered_name_retains_provenance_in_identity(self):
        d=frame(1,title='City of TEST Rone, 3700 B.C.')['classified']
        d['observed_city_name']='TEST Rome'
        self.assertIsNone(observed_city_identity(d))
        d['city_name_recovery']=dict(ocr_text='TEST Rone',canonical_name='TEST Rome',
            source='Unique one-edit match to owned city in original save')
        self.assertEqual(observed_city_identity(d),('TEST Rome','3700BC'))


if __name__=='__main__':unittest.main()
