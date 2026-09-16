"""Fresh no-save boot retains ordinary settings and exact original evidence."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image

from civ2.boot import load_setup_report,new_game
from civ2.preferences import GAME_LABELS
from test_session import state as fixture


class BootObserverTests(TestCase):
    def fixtures(self,directory):
        directory=Path(directory)
        original=directory/'ui-0000001.png'
        Image.new('RGB',(640,480),(41,51,61)).save(original)
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        image={'text':'Start a New Game Moving units','sha256':digest,'lines':[]}
        ui=mock.Mock();ui.directory=directory
        ui.observe.return_value=image;ui.wait.return_value=image;ui.wait_text.return_value=image
        ui.key.return_value=[{'type':'key','event':'keydown','code':'Enter'}]
        ui.acknowledge_information.return_value=False
        ui.save_native.side_effect=AssertionError('Native Save is forbidden in this test')
        states=dict.fromkeys(GAME_LABELS,False);states['Always wait at end of turn']=True
        pref={'before':digest,'opening':digest,'after':digest,'verified_image':digest,
              'autosave_disabled':True,'checkbox_before':dict(states),'checkbox_after':dict(states),
              'changes':[{'label':label,'before':states[label],'after':states[label],'verified_image':digest}
                         for label in ('Always wait at end of turn','Instant advice','Autosave each turn')],
              'other_checkboxes_unchanged':True}
        campaign={'phase':'after_verified_autosave_off_before_first_observation',
                  'startup_inventory':[],'campaign_inventory':[],'startup_changes':[],
                  'preferences_sha256':hashlib.sha256(json.dumps(pref,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
        data=json.dumps({'TEST':'read-only observation capsule','proof':{'campaign_start':campaign}}).encode()
        state=fixture();state['player'].update(tribe_id=0,gender='male')
        state['evidence']={'kind':'live_memory','observation_sha256':hashlib.sha256(data).hexdigest()}
        observer=mock.Mock();observer.begin_campaign.return_value=campaign;observer.read.return_value={'state':state,'data':data,'receipt':{
            'kind':'live_memory','source_images':[str(original)]*3,
            'proof':{'image_sha256':[digest]*3,'campaign_start':campaign},'campaign_start':campaign}}
        return ui,pref,observer

    def run_boot(self,ui,pref,observer):
        with mock.patch('civ2.preferences.configure_preferences',return_value=pref),\
             mock.patch('civ2.boot.original_rules',return_value='TEST original rules'),\
             mock.patch('civ2.boot.time.sleep'),mock.patch('civ2.boot.parse_save') as parser:
            result=new_game(ui,observer=observer)
        parser.assert_not_called();return result

    def test_fresh_observer_boot_issues_no_save_and_keeps_all_settings_receipts(self):
        with TemporaryDirectory() as directory:
            ui,pref,observer=self.fixtures(directory)
            state=self.run_boot(ui,pref,observer)
            ui.save_native.assert_not_called()
            observer.begin_campaign.assert_called_once_with(pref)
            observer.read.assert_called_once_with(rules_text='TEST original rules')
            with mock.patch('civ2.memory.parse_memory',return_value=state) as parser:
                report=load_setup_report(directory,require_no_saves=True)
            self.assertEqual(parser.call_args.args[0],observer.read.return_value['data'])
            self.assertTrue(all(report['checks'].values()))
            self.assertEqual(report['save_policy'],'no_saves_during_playthrough')
            self.assertNotIn('save_receipt',report);self.assertNotIn('initial_save_sha256',report)
            self.assertEqual(report['initial_observation_sha256'],state['evidence']['observation_sha256'])
            self.assertEqual(report['observation_receipt']['source_images'],[f'initial-observer-{n}.png' for n in range(3)])
            self.assertTrue(set(report['observation_receipt']['source_images']).issubset({i['path']for i in report['images']}))
            self.assertEqual([r['target']for r in report['receipts']][1:8],
                             ['Small','Prince','5 Civilizations','Restless Tribes','Use Standard Rules','Male','Romans'])
            self.assertFalse(list(Path(directory).glob('*.sav')))
            self.assertNotIn('ControlLeft',[call.args[0]for call in ui.key.call_args_list])
            ui.game.rpc.assert_called_with('pause')

    def test_autosave_or_observer_failure_has_no_fallback_save(self):
        for failure in ('autosave','read','hash','source','image','settings'):
            with self.subTest(failure=failure),TemporaryDirectory() as directory:
                ui,pref,observer=self.fixtures(directory)
                if failure=='autosave':pref['checkbox_after']['Autosave each turn']=True
                if failure=='read':observer.read.side_effect=RuntimeError('TEST unavailable observer')
                if failure=='hash':observer.read.return_value['state']['evidence']['observation_sha256']='0'*64
                if failure=='source':observer.read.return_value['state']['evidence']['save_sha256']='0'*64
                if failure=='image':observer.read.return_value['receipt']['proof']['image_sha256'][0]='0'*64
                if failure=='settings':observer.read.return_value['state']['settings']['difficulty']='Chieftain'
                with self.assertRaises((ValueError,RuntimeError)):self.run_boot(ui,pref,observer)
                ui.save_native.assert_not_called()
                self.assertFalse((Path(directory)/'setup.json').exists())

    def test_packaging_rejects_image_tamper_missing_receipt_image_and_traversal(self):
        for failure in ('tamper','missing','traversal'):
            with self.subTest(failure=failure),TemporaryDirectory() as directory:
                ui,pref,observer=self.fixtures(directory);self.run_boot(ui,pref,observer)
                path=Path(directory)/'setup.json';report=json.loads(path.read_text())
                if failure=='tamper':(Path(directory)/report['images'][0]['path']).write_bytes(b'changed')
                if failure=='missing':report['images'].pop()
                if failure=='traversal':report['images'][0]['path']='../elsewhere.png'
                path.write_text(json.dumps(report))
                with self.assertRaises(ValueError):load_setup_report(directory,require_no_saves=True)


class BootReportClaimTests(BootObserverTests):
    def test_claims_must_match_parsed_capsule_and_all_preferences(self):
        for field in ('settings','checks','player','map','unrelated','missing','change_receipt'):
            with self.subTest(field=field),TemporaryDirectory() as directory:
                ui,pref,observer=self.fixtures(directory);state=self.run_boot(ui,pref,observer)
                path=Path(directory)/'setup.json';report=json.loads(path.read_text())
                if field=='settings':report['settings']['difficulty']='Chieftain'
                elif field=='checks':report['checks']['Prince']=False
                elif field=='player':report['player']['treasury']=10000
                elif field=='map':report['map_dimensions']=[100,100]
                elif field=='unrelated':report['preferences']['checkbox_after']['Music']=True
                elif field=='missing':report['preferences']['checkbox_before'].pop('Music')
                else:report['preferences']['changes'].pop()
                path.write_text(json.dumps(report))
                with mock.patch('civ2.memory.parse_memory',return_value=state):
                    with self.assertRaises(ValueError):load_setup_report(directory,require_no_saves=True)
