"""F12 opens only an observed report; it never binds a launch action."""
from copy import deepcopy
import struct
import unittest
from unittest import mock
from civ2.empire import empire_candidates,empire_request_for,validate_empire_action,EmpireError
from civ2.save import parse_save
from civ2.spaceship_report import space_review_available
from civ2.verify import _action_binding,VerificationError
from tests.test_empire import inputs
from tests.test_verify import initial_save
from tests.test_run import frame,session
from civ2.run import controller_context


class SpaceEmpire(unittest.TestCase):
    def test_observed_public_apollo_or_current_owned_part_exposes_only_f12(self):
        for mode in ('early','apollo','ownedpart','foreignpart','notbuilt','bloodlust'):
            s,screen,r=inputs()
            if mode in ('apollo','notbuilt','bloodlust'):s['wonders']=[dict(improvement_id=64,status='not_built' if mode=='notbuilt' else 'built')]
            if mode=='bloodlust':s['settings']['bloodlust']=True
            if mode=='ownedpart':s['cities'][0]['production']=dict(kind='improvement',id=36)
            if mode=='foreignpart':s['known_cities']=[dict(owner=2,production=dict(kind='improvement',id=36))]
            actions=empire_candidates(s,screen,rules=r)
            with self.subTest(mode=mode):self.assertEqual('open_spaceships' in actions,mode in ('apollo','ownedpart'))
            if 'open_spaceships' not in actions:continue
            a=actions['open_spaceships'];self.assertEqual(a['parameters']['key'],'F12')
            self.assertTrue(a['parameters']['only_open_menu']);self.assertTrue(a['parameters']['confirmation_requires_separate_choice'])
            validate_empire_action(a,s,screen,rules=r)
            self.assertNotIn('open_spaceships',empire_candidates(s,screen,{'open_spaceships'},r))
            req=empire_request_for(s,screen,actions,rules=r)
            self.assertIn('open_spaceships',req['questions']['empire_action']['criteria'])

    def test_independent_audit_uses_actual_native_city_production_and_rejects_forged_launch(self):
        data=bytearray(initial_save());base=13432+14+13*2000+2*20*13+1024+26
        struct.pack_into('<H',data,60,1);struct.pack_into('<hh',data,base,8,8)
        data[base+8]=1;data[base+9]=2;data[base+12]=2;data[base+14]=2;data[base+32:base+41]=b'TEST Rome'
        data[base+50]=16;data[base+51]=8
        struct.pack_into('<b',data,base+57,-36)
        state=parse_save(bytes(data));s,screen,r=inputs();state['selected_unit_id']=None
        action=empire_candidates(state,screen,rules=r)['open_spaceships']
        request=empire_request_for(state,screen,rules=r);saved=deepcopy(state)
        _action_binding(action,request,'empire_action',{state['evidence']['save_sha256']:saved})
        for mode in ('key','confirmation','effect','native','bloodlust','actor'):
            a=deepcopy(action);native=deepcopy(saved)
            if mode=='key':a['parameters']['key']='Enter'
            elif mode=='confirmation':a['parameters']['confirmation_requires_separate_choice']=False
            elif mode=='effect':a['parameters']['only_open_menu']=False
            elif mode=='native':native['cities'][0]['production']['id']=2
            elif mode=='bloodlust':native['settings']['bloodlust']=True
            else:a['actor']['player_id']=2
            with self.subTest(mode=mode),self.assertRaises(VerificationError):
                _action_binding(a,request,'empire_action',{state['evidence']['save_sha256']:native})

    def test_no_spaceships_notice_completes_the_menu_review_only(self):
        notice=frame(1,'information',resource_tag='NOSPACESHIPS',mechanical_action='acknowledge_information')
        end=frame(2,'end_turn');s=session([notice,end,end]);s.mechanical=mock.Mock();s.checkpoint=mock.Mock()
        controller_context(s)['pending_empire']={'id':'open_spaceships'}
        def choose(dialog,reviewed):
            self.assertIn('open_spaceships',reviewed['actions']);s.decisions+=1
            return {'id':'finish_turn'},frame(3,'normal_map')
        s.choose_empire=mock.Mock(side_effect=choose)
        with mock.patch('civ2.run.Session.remember_public_notice'):
            from tests.test_run import ControllerTests
            ControllerTests().run_fake(s)
        s.mechanical.assert_called_once_with('acknowledge_information');s.choose_dialog.assert_not_called()


if __name__=='__main__':unittest.main()
