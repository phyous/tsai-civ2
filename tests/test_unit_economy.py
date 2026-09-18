"""Synthetic TEST contracts; operator calibration is separate from gameplay."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest import mock
from civ2 import unit_economy as e
from civ2.policy import unit_candidates,unit_request_for,dialog_request_for,validate_action,PolicyError
from civ2.dialogs import classify_dialog
from civ2.verify import _action_binding,_disband_confirmation_binding,VerificationError
from test_policy import fixture,rules
from test_herald import prepared
from test_session import session
from PIL import Image

GAME='@DISBAND\n@title=Warning!\nReally disband %STRING0?\n\nNo\nYes\n'


def state():
    s=fixture(1);u=s['units'][0];u.update(hp=10,hp_lost=0,home_city_id=0)
    s['cities']=[dict(id=0,owner=1,name='TEST Rome',x=6,y=8,size=3),
                 dict(id=1,owner=1,name='TEST Antium',x=8,y=8,size=2)]
    return s


def warning(s):
    s=deepcopy(s);a=unit_candidates(s,rules=rules())['request_disband']
    s['pending_disband']=e.request_context(a,s,12)
    o=dict(width=640,height=480,sha256='b'*64,lines=[
        prepared('Warning!',289,175,62,16),prepared('Really disband Warriors?',139,205,184,16),
        prepared('No',142,230,24,14),prepared('Yes',142,255,27,14),prepared('OK',308,288,24,14)])
    return s,o


class UnitEconomyTests(unittest.TestCase):
    def test_warning_pixel_reads_are_atomic_and_preserve_conflicting_read(self):
        image=Image.new('RGB',(640,480))
        original=[prepared('Warring!',290,178,58,18),prepared('Really dishand Warriors?',138,202,172,16),
            prepared(')No',158,230,38,12),prepared(') Yes',158,254,42,14),prepared('OK',308,286,24,16)]
        for mode in ('good','different_unit','disagreement','weak','moved','wrong_conflict'):
            rows=deepcopy(original);conflict=dict(text='Yes',bounds=[172,254,28,14],reason='contradictory overlapping native text')
            if mode=='wrong_conflict':conflict['text']='Cancel'
            evidence=dict(conflicts=[conflict],passes=[],fallback_errors=[])
            def crop(image,old,name,*args,**kwargs):
                new=deepcopy(old);new['text']={'Warring!':'Warning!','Really dishand Warriors?':'Really disband Warriors?',')No':'No',') Yes':'Yes'}[old['text']]
                new['provenance']=[{'preprocessing':name,'text':new['text']}]
                if mode=='different_unit' and 'body' in name:new['text']='Really disband Settlers?'
                if mode=='disagreement' and 'gray' in name:new['text']='Wrong text'
                if mode=='weak':new['confidence']=.3
                if mode=='moved':new['center'][1]+=20;new['bounds'][1]+=20
                return [new]
            with mock.patch('civ2.observe._crop_text',side_effect=crop):e.recover_disband_warning(image,rows,None,None,evidence)
            if mode in ('good','wrong_conflict'):
                self.assertEqual([r['text']for r in rows],['Warning!','Really disband Warriors?','No','Yes','OK'])
                self.assertEqual(rows[1]['provenance'][0]['text'],'Really dishand Warriors?')
                if mode=='good':self.assertEqual(evidence['resolved_control_conflicts'],[conflict]);self.assertEqual(evidence['conflicts'],[])
                else:self.assertEqual(evidence['conflicts'],[conflict])
            else:self.assertEqual(rows,original)

    def test_actual_operator_warning_reads_keep_real_type_and_both_alternatives(self):
        path=Path('.runtime/operator-unit-calibration/ui-0000028.png')
        source=Path('.runtime/operator-unit-calibration/after-h-state.json')
        if not path.exists() or not source.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private operator calibration absent')
        import json
        from civ2.observe import recognize
        from civ2.run import game_text
        s=json.loads(source.read_text());unit=next(u for u in s['units']if u['id']==s['selected_unit_id'])
        r={'units':[unit['specification']]};action=unit_candidates(s,rules=r)['request_disband']
        # Synthetic context for offline classification, not a model claim about
        # the operator-selected calibration input.
        s['pending_disband']=e.request_context(action,s,1);o=recognize(path)
        d=classify_dialog(o,game_text=game_text(),rules=r,state=s)
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'disband_confirmation')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([r['text']for r in d['options']],['No','Yes'])
        self.assertEqual(d['evidence']['disband_confirmation']['observed_body'],'Really disband Warriors?')
        self.assertEqual(o['ocr']['resolved_control_conflicts'][0]['text'],'Yes')
        body=next(r for r in o['lines']if r['text']=='Really disband Warriors?')
        self.assertEqual(body['provenance'][0]['text'],'Really dishand Warriors?')

    def test_public_unit_facts_equal_original_rules_when_available(self):
        path=Path('engine/game/civ2-win31.zip')
        if not path.exists():self.skipTest('Private original rules absent')
        from zipfile import ZipFile
        from civ2.save import parse_rules
        units=parse_rules(ZipFile(path).read('civ2/RULES.TXT').decode('cp1252'))['units']
        self.assertEqual(tuple(u['name']for u in units),e.STANDARD_NAMES)
        self.assertEqual(tuple(u['max_hp']for u in units),e.STANDARD_HP)
        self.assertEqual([u['id']for u in units if u['role']==7],[48,49])

    def test_original_commands_keep_existing_choices_and_expose_both_budgets(self):
        s=state();before=deepcopy(s);actions=unit_candidates(s,rules=rules())
        self.assertEqual(actions['request_disband']['parameters'],e.DISBAND_PARAMETERS)
        self.assertEqual(actions['set_home_city']['parameters']['key'],'KeyH')
        self.assertEqual(actions['set_home_city']['parameters']['new_home']['id'],1)
        self.assertEqual(actions['set_home_city']['parameters']['previous_home']['id'],0)
        self.assertTrue({'fortify','sentry','skip','move_e'}<=actions.keys())
        request=unit_request_for(s,actions,rules());context=request['state']['selected_unit_economy']
        self.assertEqual(context['recorded_home']['id'],0);self.assertEqual(context['offered_new_home']['id'],1)
        self.assertEqual(context['recorded_home']['observed_supported_unit_count'],1)
        self.assertEqual(s,before)

    def test_health_selected_actor_and_city_guards(self):
        for case in ('dead','lost','hp_bool','bad_hp','health_missing','foreign','same_home',
                     'no_home','foreign_city','duplicate_city','trade','role_bool','unoccupied'):
            s=state();u=s['units'][0]
            if case=='dead':u['hp']=0
            elif case=='lost':u['hp_lost']=10
            elif case=='hp_bool':u['hp']=True
            elif case=='bad_hp':u['hp_lost']=1
            elif case=='health_missing':u.pop('hp');u.pop('hp_lost')
            elif case=='foreign':u['owner']=2
            elif case=='same_home':u['home_city_id']=1
            elif case=='no_home':u['home_city_id']=None
            elif case=='foreign_city':s['cities'][1]['owner']=2
            elif case=='duplicate_city':s['cities'].append(deepcopy(s['cities'][1]))
            elif case=='trade':u['specification']['role']=7
            elif case=='role_bool':u['specification']['role']=True
            elif case=='unoccupied':u['x']=10
            with self.subTest(case=case):
                if case in ('foreign','role_bool'):
                    with self.assertRaises(PolicyError):unit_candidates(s,rules=rules())
                    continue
                a=unit_candidates(s,rules=rules());self.assertNotIn('set_home_city',a)
                if case in ('dead','lost','hp_bool','bad_hp','health_missing'):self.assertNotIn('request_disband',a)
        s=state();a=unit_candidates(s,rules=rules())['set_home_city'];s['units'][0]['home_city_id']=1
        with self.assertRaises(PolicyError):validate_action(a,s,rules())

    def test_warning_is_two_real_choices_bound_to_latest_request(self):
        s,o=warning(state());d=classify_dialog(o,game_text=GAME,state=s)
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual(d['kind'],'disband_confirmation');self.assertEqual([x['text']for x in d['options']],['No','Yes'])
        r,a=dialog_request_for(s,d,rules());proof=r['state']['mandatory_dialog']['disband_confirmation']
        self.assertEqual(proof['request'],s['pending_disband']);self.assertEqual(len(a),2)
        self.assertTrue(_disband_confirmation_binding(a['option_0'],r,s['pending_disband'],
            {o['sha256']:{'classification':'disband_confirmation','supported':True}}))
        with self.assertRaises(VerificationError):_disband_confirmation_binding(a['option_0'],r,None,{})

    def test_incomplete_unbound_or_different_warning_never_confirms(self):
        for case in ('no_pending','different_actor','different_year','different_type','title','source',
                     'missing_yes','only_yes','extra','extra_cancel','weak','row_order','stale_revision'):
            s,o=warning(state());source=GAME
            if case=='no_pending':s.pop('pending_disband')
            elif case=='different_actor':s['selected_unit_id']=88
            elif case=='different_year':s['turn']+=1
            elif case=='different_type':o['lines'][1]['text']='Really disband Settlers?'
            elif case=='title':o['lines'][0]['text']='Warning?'
            elif case=='source':source=source.replace('Really disband','Immediately delete')
            elif case=='missing_yes':o['lines'].pop(3)
            elif case=='only_yes':o['lines'].pop(2)
            elif case=='extra':o['lines'].append(prepared('Also abandon city?',300,219,140,14))
            elif case=='extra_cancel':o['lines'].append(prepared('Cancel',580,300,45,14))
            elif case=='weak':o['lines'][1]['confidence']=.4
            elif case=='row_order':o['lines'][2]['text']='Yes';o['lines'][3]['text']='No'
            else:s['pending_disband']['revision']['save_sha256']='c'*64
            with self.subTest(case=case):self.assertFalse(classify_dialog(o,game_text=source,state=s)['supported'])

    @mock.patch('civ2.session.time.sleep')
    def test_session_uses_chord_then_independent_confirmation_and_clears_context(self,sleep):
        ss=session();ss.state=state();ss.rules=rules();ss.planning=False
        a=unit_candidates(ss.state,rules=ss.rules)['request_disband'];ss._evaluate=mock.Mock(return_value=a)
        ss.decision=dict(id=ss.decisions,receipt='pending',selected_question='unit_action',answers={'unit_action':{'choice':a['id']}})
        ss.ui.observe.return_value={'sha256':'b'*64};ss.game.chord.return_value=[{'issued':True}]
        ss.choose_unit()
        ss.game.chord.assert_called_once_with('ShiftLeft','KeyD',hold_ms=120);ss.ui.key.assert_not_called()
        self.assertEqual(ss.pending_disband['decision'],ss.decisions)
        contextual,o=warning(ss.state);contextual['pending_disband']=deepcopy(ss.pending_disband)
        d=classify_dialog(o,game_text=GAME,state=contextual)
        _,choices=dialog_request_for(ss.state,d,ss.rules)
        ss._evaluate=mock.Mock(return_value=choices['option_0']);ss.decisions+=1
        ss.choose_dialog(d)
        ss.game.click.assert_called_once_with(*d['options'][0]['center'])
        ss.ui.key.assert_called_once_with('Enter');self.assertIsNone(ss.pending_disband)
        with self.assertRaises(RuntimeError):ss.choose_dialog(d)

    def test_public_replay_checks_standard_rules_and_exact_modifier_city_binding(self):
        from test_verify import initial_save
        from civ2.save import parse_save
        s=parse_save(initial_save(2));u=s['units'][0]
        spec=dict(id=2,name='Warriors',max_hp=10,domain=0,role=1,attack=1)
        u.update(type='Warriors',hp=10,specification=spec,home_city_id=0)
        s['cities']=deepcopy(state()['cities']);r=dict(units=[spec],terrain=[],advances=[])
        for name in ('request_disband','set_home_city'):
            a=unit_candidates(s,rules=r)[name]
            req={'state':{'turn':s['turn'],'selected_unit':deepcopy(u)}}
            _action_binding(a,req,'unit_action',{s['evidence']['save_sha256']:s})
            for mutation in ('key','modifier','actor','movement','home','dead','spec'):
                wrong=deepcopy(a);current=deepcopy(s);request=deepcopy(req)
                if mutation=='key':wrong['parameters']['key']='KeyX'
                elif mutation=='modifier':wrong['parameters']['modifiers']=['ControlLeft']
                elif mutation=='actor':wrong['actor']['id']=99
                elif mutation=='movement':wrong['preconditions']['movement_thirds_spent']=1
                elif mutation=='home':
                    if name=='request_disband':wrong['parameters']['confirm']=True
                    else:wrong['parameters']['new_home']['id']=99
                elif mutation=='dead':current['units'][0]['hp_lost']=10
                else:request['state']['selected_unit']['specification']['max_hp']=100
                with self.subTest(name=name,mutation=mutation),self.assertRaises(VerificationError):
                    _action_binding(wrong,request,'unit_action',{s['evidence']['save_sha256']:current})


if __name__=='__main__':unittest.main()
