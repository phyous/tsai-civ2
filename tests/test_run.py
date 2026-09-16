"""Controller transaction regressions. Synthetic screens; no game/model calls."""
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from civ2.run import classification_state, controller_context, observe_ready, observed_city_identity, run_steps, _await_diplomatic_followup


def frame(number, kind, title='', **extra):
    result = dict(kind=kind,title=title,supported=True,mechanical_action=None,
                  requires_model=False,options=[],buttons=[])
    result.update(extra)
    return dict(path=f'/tmp/TEST-run/screens/{number}.png',sha256=str(number)*64,
                text=title,classified=result)


def session(observations):
    s = SimpleNamespace(state={'turn':1,'cities':[]},rules={},decisions=0,recorder=None,
                        game=mock.Mock(),ui=mock.Mock(),journal=mock.Mock(),publish=mock.Mock())
    s.journal.directory=Path('/tmp/TEST-run')
    s.ui.observe.side_effect=observations
    s.choose_dialog=mock.Mock(side_effect=lambda dialog: setattr(s,'decisions',s.decisions+1))
    controller_context(s)['graphics_configured']=True
    controller_context(s)['throne_presentation_disabled']=True
    return s


class ControllerTests(TestCase):
    def test_new_city_identity_accepts_complete_same_year_founding_proof_only(self):
        import copy
        d=dict(title='City of Comae, 2900 B.C., Population 10,000',observed_city_name='Cumae',
            city_name_recovery=dict(source='Unique same-year original founding notice label; no native actor binding',
                ocr_text='Comae',canonical_name='Cumae',year_text='2900 b.c',
                notice_image_sha256='a'*64,source_line=4))
        self.assertEqual(observed_city_identity(d),('Cumae','2900BC'))
        for key,value in (('ocr_text','Rome'),('canonical_name','Veii'),('year_text','2950 b.c'),
                          ('notice_image_sha256','bad'),('source_line',True),('source','unverified')):
            invalid=copy.deepcopy(d);invalid['city_name_recovery'][key]=value
            self.assertIsNone(observed_city_identity(invalid))
        d['city_name_recovery']=None
        self.assertIsNone(observed_city_identity(d))

    def run_fake(self,s,limit=1):
        with mock.patch('civ2.run.game_text',return_value='TEST'), \
             mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kwargs:o['classified']), \
             mock.patch('civ2.run.time.sleep'):
            return run_steps(s,max_decisions=limit)

    def test_agreed_audience_waits_through_map_without_checkpoint_or_repeated_choice(self):
        audience=frame(1,'diplomacy','Neutral TEST Emissary',resource_tag='EMISSARY',requires_model=True,
                       options=[{'text':'"Yes. I will grant an audience."'},{'text':'"No. Send him away."'}])
        transient=frame(2,'end_turn')
        greeting=frame(3,'information','Neutral TEST Emissary',resource_tag='GREETINGS02',
                       mechanical_action='acknowledge_information',buttons=[{'text':'OK'}])
        s=session([transient,greeting]);s.checkpoint=mock.Mock();ctx=controller_context(s)
        ctx['pending_diplomatic_followup']={'decision':4,'source_hash':audience['sha256'],'title':audience['classified']['title']}
        with mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kwargs:o['classified']),mock.patch('civ2.run.time.sleep'):
            observed,classified,error=_await_diplomatic_followup(s,ctx,transient,transient['classified'],'TEST')
        self.assertIs(observed,greeting);self.assertIsNone(error);self.assertIsNone(ctx['pending_diplomatic_followup'])
        self.assertEqual(s.game.rpc.call_args_list,[mock.call('resume'),mock.call('pause')]*2)
        s.checkpoint.assert_not_called();s.choose_dialog.assert_not_called();s.ui.key.assert_not_called()

    def test_audience_wait_timeout_and_unexpected_screen_preserve_pending_across_return(self):
        for kind,supported in (('end_turn',True),('city_screen',True),('diplomacy',True),('unknown',False)):
            current=frame(2,kind,supported=supported)
            s=session([current]*20);s.checkpoint=mock.Mock();ctx=controller_context(s)
            pending={'decision':4,'source_hash':'a'*64,'title':'Neutral TEST Emissary'}
            ctx['pending_diplomatic_followup']=pending
            with mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kwargs:o['classified']),mock.patch('civ2.run.time.sleep'):
                observed,classified,error=_await_diplomatic_followup(s,ctx,current,current['classified'],'TEST')
            self.assertIs(controller_context(s)['pending_diplomatic_followup'],pending)
            self.assertEqual(error is not None,supported)
            self.assertEqual(s.game.rpc.call_count,40 if kind=='end_turn' else 0)
            s.checkpoint.assert_not_called();s.choose_dialog.assert_not_called();s.ui.key.assert_not_called()

    def test_only_source_bound_yes_audience_choice_starts_pending_transaction(self):
        for tag,index in (('EMISSARY',0),('EMISSARY',1),('TESTOFFER',0)):
            d=frame(1,'diplomacy','Neutral TEST Emissary',resource_tag=tag,requires_model=True,
                    options=[{'text':'"Yes. I will grant an audience."'},{'text':'"No. Send him away."'}])
            s=session([d]);ctx=controller_context(s)
            def choose(dialog):
                s.decisions+=1
                return {'kind':'dialog_choice','parameters':{'option_index':index,'observed_text':dialog['options'][index]['text']}},frame(2,'end_turn')
            s.choose_dialog=mock.Mock(side_effect=choose)
            self.run_fake(s)
            self.assertEqual(ctx['pending_diplomatic_followup'] is not None,tag=='EMISSARY' and index==0)

    def test_review_of_one_city_cannot_skip_other_city(self):
        controls=[{'text':'Exit'},{'text':'Change'}]
        a=frame(1,'city_screen','City of TEST Rome, 4000 B.C.',buttons=controls)
        b=frame(2,'city_screen','City of TEST Veii, 4000 B.C.',buttons=controls)
        prod=frame(3,'production_choice',requires_model=True,options=[{},{}])
        s=session([a,b,prod]);ctx=controller_context(s)
        ctx['production_reviewed'].add(('TEST Rome','4000BC'))
        self.run_fake(s)
        self.assertEqual([c.args[1] for c in s.ui.select_text.call_args_list],['Change'])
        s.ui.key.assert_called_once_with('Escape')
        self.assertIn(('TEST Veii','4000BC'),ctx['production_reviewed'])

    def test_pausing_on_unknown_preserves_target_city_transaction(self):
        unknown=frame(1,'unknown',supported=False)
        s=session([unknown]*11)
        ctx=controller_context(s);ctx['pending_city']={'name':'TEST Rome'}
        ctx['pending_empire']={'id':'inspect_city_0'}
        self.assertEqual(self.run_fake(s)['status'],'paused')
        self.assertIs(controller_context(s),ctx)
        wrong=frame(2,'city_screen','City of TEST Veii, 4000 B.C.',buttons=[{'text':'Change'}])
        s.ui.observe.side_effect=[wrong]
        self.assertIn('does not match',self.run_fake(s)['reason'])
        s.ui.select_text.assert_not_called()
        self.assertFalse(ctx['pending_empire_confirmed'])

    def test_visible_pending_city_name_does_not_modify_native_state(self):
        s=session([]);ctx=controller_context(s)
        ctx['observed_city_names'].add('TEST Rome')
        result=classification_state(s)
        self.assertEqual(result['cities'],[{'name':'TEST Rome'}])
        self.assertEqual(s.state['cities'],[])
        self.assertNotIn('units',result)

    def test_actual_founding_notice_context_is_bounded_and_not_native_state(self):
        founding=frame(1,'information',mechanical_action='acknowledge_information',
            resource_tag='FOUNDED',founded_city={'name':'TEST Veii','year_text':'3950 B.C.',
                                               'source':'Original founding notice text'})
        unknown=frame(2,'unknown',supported=False)
        s=session([founding,founding]+[unknown]*9);s.mechanical=mock.Mock()
        ctx=controller_context(s)
        ctx['recent_founding_notices']=[{'name':f'TEST Old {i}','year_text':'4000 B.C.',
            'source_tag':'FOUNDED','image_sha256':'f'*64} for i in range(4)]
        self.run_fake(s)
        self.assertEqual(len(ctx['recent_founding_notices']),4)
        self.assertEqual(ctx['recent_founding_notices'][-1],{'name':'TEST Veii','year_text':'3950 B.C.',
            'source_tag':'FOUNDED','image_sha256':founding['sha256']})
        projection=classification_state(s)
        projection['recent_founding_notices'][-1]['name']='TEST changed copy'
        self.assertEqual(ctx['recent_founding_notices'][-1]['name'],'TEST Veii')
        self.assertEqual(s.state['cities'],[])
        self.assertNotIn('recent_founding_notices',s.state)

    def test_return_to_end_turn_without_menu_does_not_count_as_review(self):
        end=frame(1,'end_turn')
        s=session([end]);s.checkpoint=mock.Mock()
        ctx=controller_context(s);ctx['pending_empire']={'id':'open_tax'}
        self.assertIn('did not have an observed',self.run_fake(s)['reason'])
        self.assertEqual(ctx['reviewed']['actions'],[])

    def test_gray_blink_after_checkpoint_waits_for_observed_cue_before_choice(self):
        end=frame(1,'end_turn')
        gray=frame(2,'unknown',supported=False)
        s=session([end,gray,end]);s.checkpoint=mock.Mock()
        def choose(dialog,reviewed):
            self.assertEqual(dialog['kind'],'end_turn')
            s.decisions += 1
            return {'id':'finish_turn'},frame(3,'normal_map')
        s.choose_empire=mock.Mock(side_effect=choose)
        self.run_fake(s)
        s.choose_empire.assert_called_once()
        s.ui.key.assert_not_called()
        s.ui.select_text.assert_not_called()
        self.assertEqual(s.game.rpc.call_args_list,
                         [mock.call('pause'),mock.call('resume'),mock.call('pause')])

    def test_finish_can_advance_to_another_end_turn_when_no_units_are_active(self):
        for advances in (True,False):
            end=frame(1,'end_turn')
            s=session([end,end])
            count=0
            def checkpoint():
                nonlocal count
                count+=1
                if count==2 and advances:s.state['turn']=2
            s.checkpoint=mock.Mock(side_effect=checkpoint)
            def choose(dialog,reviewed):
                s.decisions+=1
                return {'id':'finish_turn'},frame(2,'end_turn')
            s.choose_empire=mock.Mock(side_effect=choose)
            result=self.run_fake(s)
            self.assertEqual(s.checkpoint.call_count,2)
            self.assertEqual('no confirmed transition' in result['reason'],not advances)
            s.choose_empire.assert_called_once()

    def observe_fake(self,s):
        with mock.patch('civ2.run.classify_dialog',side_effect=lambda o,**kwargs:o['classified']), \
             mock.patch('civ2.run.time.sleep') as sleep:
            result=observe_ready(s,'TEST')
        return result,sleep

    def test_native_map_can_paint_after_the_old_eight_retry_window(self):
        gray=frame(1,'unknown',supported=False,
            reason='Native moving-unit or end-of-turn status is not uniquely observed')
        end=frame(2,'end_turn')
        s=session([gray]*11+[end])
        (observed,dialog),sleep=self.observe_fake(s)
        self.assertIs(observed,end)
        self.assertEqual(dialog['kind'],'end_turn')
        self.assertEqual(sleep.call_count,11)
        s.ui.key.assert_not_called();s.ui.select_text.assert_not_called()

    def test_map_paint_retries_remain_bounded_and_never_accept_unknown(self):
        unknown=frame(1,'unknown',supported=False,
            reason='Unexpected text over the native map playfield; possible unrecognized modal')
        s=session([unknown]*21)
        (_,dialog),sleep=self.observe_fake(s)
        self.assertFalse(dialog['supported'])
        self.assertEqual(s.ui.observe.call_count,21)
        self.assertEqual(sleep.call_count,20)
        self.assertAlmostEqual(sum(c.args[0] for c in sleep.call_args_list),9.72)
        s.ui.key.assert_not_called();s.ui.select_text.assert_not_called()

    def test_unrecognized_modal_does_not_get_extended_map_wait(self):
        unknown=frame(1,'unknown',supported=False,reason='Unrecognized foreground dialog controls')
        s=session([unknown]*9)
        (_,dialog),sleep=self.observe_fake(s)
        self.assertFalse(dialog['supported'])
        self.assertEqual(sleep.call_count,8)

    def reusable_session(self,observations):
        s=session(observations)
        s.state.update(year_raw=-4000,evidence={'save_sha256':'a'*64})
        s.checkpoints=0;s.pending_decisions=[];s.journal.sequence=0
        def append(*args,**kwargs):s.journal.sequence+=1
        s.journal.append.side_effect=append
        def checkpoint():
            s.checkpoints+=1
            if s.checkpoints==2:s.state.update(turn=2,year_raw=-3950)
            s.state['evidence']['save_sha256']=f'{s.checkpoints:064x}'
            s.pending_decisions=[]
            s.journal.append('checkpoint')
        s.checkpoint=mock.Mock(side_effect=checkpoint)
        def choose(dialog,reviewed):
            s.decisions+=1;s.pending_decisions.append(s.decisions)
            s.journal.append('empire_command_dispatched')
            return {'id':'finish_turn'},frame(9,'end_turn' if s.decisions==1 else 'normal_map')
        s.choose_empire=mock.Mock(side_effect=choose)
        return s

    def test_fresh_verified_turn_checkpoint_is_reused_once_without_new_input(self):
        end=frame(1,'end_turn')
        s=self.reusable_session([end,end,end])
        self.run_fake(s,limit=2)
        self.assertEqual(s.checkpoint.call_count,2)
        reused=[c.kwargs for c in s.journal.append.call_args_list if c.args[0]=='checkpoint_reused']
        self.assertEqual(len(reused),1)
        self.assertEqual(reused[0]['save_sha256'],f'{2:064x}')
        self.assertEqual(reused[0]['checkpoint'],2)
        self.assertEqual(reused[0]['turn'],2)
        self.assertFalse(reused[0]['ordinary_inputs_since_checkpoint'])

    def test_pointer_parking_invalidates_the_no_input_checkpoint_token(self):
        end=frame(1,'end_turn')
        unknown=frame(2,'unknown',supported=False)
        unknown['cursor_hotspot']=[100,100]
        s=self.reusable_session([end,end,unknown,end,end])
        self.run_fake(s,limit=2)
        self.assertEqual(s.checkpoint.call_count,3)
        self.assertFalse(any(c.args[0]=='checkpoint_reused' for c in s.journal.append.call_args_list))
        s.ui.park_pointer.assert_called_once()

    def test_checkpoint_reuse_never_survives_a_development_pause(self):
        end=frame(1,'end_turn')
        s=self.reusable_session([end,end])
        self.run_fake(s,limit=1)
        self.assertEqual(s.checkpoint.call_count,2)
        s.ui.observe.side_effect=[end,end]
        self.run_fake(s,limit=2)
        self.assertEqual(s.checkpoint.call_count,3)
        self.assertFalse(any(c.args[0]=='checkpoint_reused' for c in s.journal.append.call_args_list))

    def test_changed_native_revision_invalidates_checkpoint_reuse(self):
        end=frame(1,'end_turn')
        s=self.reusable_session([]);calls=0
        def observe():
            nonlocal calls
            calls+=1
            if calls==3:s.state['evidence']['save_sha256']='f'*64
            return end
        s.ui.observe.side_effect=observe
        self.run_fake(s,limit=2)
        self.assertEqual(s.checkpoint.call_count,3)
        self.assertFalse(any(c.args[0]=='checkpoint_reused' for c in s.journal.append.call_args_list))

    def test_presentation_acknowledges_only_the_observed_prompt(self):
        presentation=frame(1,'presentation',mechanical_action='acknowledge_presentation',
            resource_tag='THRONE',buttons=[{'text':'(Click mouse to continue...)'}],
            acknowledgement_point=[320,135])
        unknown=frame(2,'unknown',supported=False)
        s=session([presentation]+[unknown]*10)
        self.run_fake(s)
        s.game.click.assert_called_once_with(320,135)
        s.ui.select_text.assert_not_called()
        s.ui.key.assert_not_called();s.choose_dialog.assert_not_called()
        event=next(c.kwargs for c in s.journal.append.call_args_list
                   if c.args[0]=='native_presentation_acknowledged')
        self.assertEqual(event['source_hash'],presentation['sha256'])
        self.assertEqual(event['resource_tag'],'THRONE')
        self.assertEqual(event['receipt']['point'],[320,135])
        self.assertEqual(event['receipt']['selected_frame'],unknown['sha256'])

    def test_ambiguous_presentation_prompt_remains_paused(self):
        presentation=frame(1,'presentation',mechanical_action='acknowledge_presentation',
            resource_tag='THRONE',buttons=[{'text':'one'},{'text':'two'}])
        s=session([presentation])
        self.assertIn('not uniquely observed',self.run_fake(s)['reason'])
        s.ui.select_text.assert_not_called()

    def test_missing_observed_presentation_point_remains_paused(self):
        presentation=frame(1,'presentation',mechanical_action='acknowledge_presentation',
            resource_tag='THRONE',buttons=[{'text':'(Click mouse to continue...)'}])
        s=session([presentation])
        self.assertIn('not observed',self.run_fake(s)['reason'])
        s.game.click.assert_not_called()
