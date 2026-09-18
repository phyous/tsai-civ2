"""Two-contact F3 choices stay separate; synthetic input and private pixel tests."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image
from civ2.dialogs import _rows
from civ2.foreign_report import SOURCE,TWO_FRAME,TWO_PIXELS,TWO_RADIOS,_two_pixels,classify_foreign_report
from civ2.policy import PolicyError,dialog_candidates,dialog_request_for,dialog_panel_signature,repeated_dialog_feedback
from civ2.verify import VerificationError,_action_binding,_dispatch,_foreign_contact_pixels
from test_foreign_report import fixture
from test_session import session


def two():
    o,resources,rules,labels=fixture()
    o['lines'][0].update(text='Foreign Ifinister',bounds=[270,178,102,16],center=[321,186])
    o['lines'][1].update(bounds=[30,202,386,18],center=[223,211])
    o['lines'][2].update(bounds=[66,230,470,18],center=[301,239])
    second=deepcopy(o['lines'][2]);second.update(text=second['text'].replace('TEST Leader','OTHER Leader').replace('TEST Tribe','OTHER Tribe'),bounds=[66,254,470,16],center=[301,262])
    rules['leaders'].append(dict(male='OTHER Leader',female='OTHER Other',tribe='OTHER Tribe'))
    o['lines'].insert(3,second)
    for row in o['lines'][4:]:row['bounds'][1]+=12;row['center'][1]+=12
    pixels=dict(frame_bounds=list(TWO_FRAME),selected_contact_index=0,radio_regions=[],pixel_regions=[])
    return o,resources,rules,labels,pixels


def classified():
    o,s,r,l,p=two()
    with mock.patch('civ2.foreign_report._two_pixels',return_value=p):d=classify_foreign_report(o,_rows(o),s,r,l)
    d.update(id=d['kind'],width=640,height=480,sha256=o['sha256'],supported=True,visible_text='\n'.join(x['text'] for x in o['lines']))
    return d


class ForeignContactTests(TestCase):
    def test_all_contacts_and_buttons_retained_with_explicit_current_selection(self):
        d=classified();req,actions=dialog_request_for({},d)
        self.assertEqual(len(actions),5)
        self.assertEqual([a['parameters'].get('selection_only') for a in actions.values()],[True,True,None,None,None])
        self.assertEqual(req['state']['mandatory_dialog']['foreign_contact_report']['selected_contact']['leader'],'TEST Leader')
        self.assertIn('does not send',req['state']['mandatory_dialog']['command_scope'])

    def test_incomplete_extra_duplicate_unknown_rows_and_geometry_refuse(self):
        for case in ('missing','extra','duplicate','unknown','button','geometry','overlap','bad_source','bad_pixels'):
            o,s,r,l,p=two()
            if case=='missing':o['lines'].pop(3)
            if case=='extra':o['lines'].append(deepcopy(o['lines'][3]))
            if case=='duplicate':o['lines'][3]['text']=o['lines'][2]['text']
            if case=='unknown':o['lines'][3]['text']+=' hidden'
            if case=='button':o['lines'][-1]['text']='OK'
            if case=='geometry':
                o['lines'][3]['center'][1]+=12;o['lines'][3]['bounds'][1]+=12
            if case=='overlap':o['lines'].append(dict(text='TEST near border',bounds=[100,308,90,12],center=[145,314],confidence=1))
            if case=='bad_source':s[0]['width']=320
            if case=='bad_pixels':p=None
            with self.subTest(case=case),mock.patch('civ2.foreign_report._two_pixels',return_value=p):
                self.assertIsNone(classify_foreign_report(o,_rows(o),s,r,l))

    def test_radio_semantics_require_exact_foreign_report(self):
        for field,value in (('id','diplomacy'),('resource_tag','EMISSARY'),('sha256','f'*64)):
            d=classified();d[field]=value
            with self.subTest(field=field),self.assertRaises(PolicyError):dialog_candidates({},d)
        d=classified();d['evidence']['foreign_report']['contacts'][1]['text']='TEST unobserved'
        with self.assertRaises(PolicyError):dialog_candidates({},d)

    @mock.patch('civ2.session.time.sleep')
    def test_contact_click_has_no_enter_and_button_requires_new_model_evaluation(self,sleep):
        s=session();d=classified();req,actions=dialog_request_for(s.state,d,s.rules)
        s._evaluate=mock.Mock(side_effect=[actions['option_1'],actions['option_3']])
        s.ui.observe.side_effect=[{'sha256':d['sha256']},{'sha256':'c'*64}]
        s.choose_dialog(d)
        s.game.click.assert_called_once_with(*actions['option_1']['parameters']['center'])
        s.ui.key.assert_not_called();self.assertEqual(s._evaluate.call_count,1)
        # The button is another actual choice, never an automatic continuation.
        s.ui.observe.side_effect=[{'sha256':d['sha256']},{'sha256':'c'*64}]
        s.choose_dialog(d)
        self.assertEqual(s._evaluate.call_count,2);s.ui.key.assert_not_called()

    def test_verifier_selector_binding_and_enter_rejection(self):
        s=session();d=classified();req,actions=dialog_request_for(s.state,d,s.rules);a=actions['option_1']
        saves={'a'*64:s.state}
        _action_binding(a,req,'dialog_action',saves)
        for case in ('source','image','selection','center','unbound','button'):
            request=deepcopy(req);action=deepcopy(a);p=request['state']['mandatory_dialog']['foreign_contact_report']
            if case=='source':p['resource_sha256']='f'*64
            if case=='image':p['image_sha256']='f'*64
            if case=='selection':p['pixels']['selected_contact_index']=True
            if case=='center':p['contacts'][1]['center'][1]+=10
            if case=='unbound':request['state']['mandatory_dialog'].pop('foreign_contact_report')
            if case=='button':action=deepcopy(actions['option_3']);action['parameters']['selection_only']=True
            with self.subTest(case=case),self.assertRaises(VerificationError):_action_binding(action,request,'dialog_action',saves)
        point=a['parameters']['center'];inputs=[dict(type='mouse',event=event,x=point[0],y=point[1],button=0,sequence=i+1)for i,event in enumerate(('mousedown','mouseup'))]
        payload=dict(action=a,receipt=dict(before=d['sha256'],point=point,target=a['label'],inputs=inputs),after='c'*64)
        files=mock.Mock()
        with mock.patch('civ2.foreign_report._two_pixels',return_value=two()[-1]):
            self.assertEqual(_dispatch(payload,a,'dialog_action',files),2)
            payload['receipt']['inputs']+= [dict(type='key',code='Enter',down=True,sequence=3,repeat=False),dict(type='key',code='Enter',down=False,sequence=4,repeat=False)]
            with self.assertRaises(VerificationError):_dispatch(payload,a,'dialog_action',files)

    @mock.patch('civ2.session.time.sleep')
    def test_repeated_report_feedback_retains_selected_contact_state(self,sleep):
        s=session();d=classified();a=dialog_candidates(s.state,d)['option_2']
        s._evaluate=mock.Mock(return_value=a)
        s.ui.observe.side_effect=[{'sha256':d['sha256']},{'sha256':'c'*64}]
        s.choose_dialog(d);s.observe_dialog_feedback(d)
        self.assertEqual(repeated_dialog_feedback(s.state,d,s._dialog_repeat_records)['completed_click_count'],1)
        changed=deepcopy(d);changed['evidence']['foreign_report']['pixels']['selected_contact_index']=1
        changed['evidence']['foreign_report']['selected_contact']={'leader':'OTHER Leader','tribe':'OTHER Tribe'}
        self.assertNotEqual(dialog_panel_signature(d),dialog_panel_signature(changed))
        s.observe_dialog_feedback(changed)
        self.assertIsNone(repeated_dialog_feedback(s.state,changed,s._dialog_repeat_records))

    def test_verifier_checks_actual_selected_radio_for_button_and_selector(self):
        d=classified();req,actions=dialog_request_for({},d);files=mock.Mock()
        proof=deepcopy(req['state']['mandatory_dialog']['foreign_contact_report']['pixels'])
        with mock.patch('civ2.foreign_report._two_pixels',return_value=proof):
            _foreign_contact_pixels(req,files)
            for field,value in (('selected_contact_index',1),('radio_regions',[{'test':'changed'}])):
                bad=deepcopy(req);bad['state']['mandatory_dialog']['foreign_contact_report']['pixels'][field]=value
                with self.subTest(field=field),self.assertRaises(VerificationError):_foreign_contact_pixels(bad,files)
        with mock.patch('civ2.foreign_report._two_pixels',return_value=None):
            with self.assertRaises(VerificationError):_foreign_contact_pixels(req,files)

    def test_actual_second_selected_contact_retains_misread_radio_marker(self):
        path=Path('runs/attempt-011/screens/ui-0002848.png')
        if not path.exists():self.skipTest('Private original selection capture unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        o=recognize(path);o['path']=str(path)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()))
        self.assertTrue(d['supported']);self.assertEqual(len(d['options']),5)
        self.assertEqual(d['evidence']['foreign_report']['selected_contact']['tribe'],'Spanish')
        self.assertTrue(d['options'][0]['text'].startswith('• Empress'))
        self.assertEqual(d['title'],'ForeignMfinister')
        self.assertEqual(d['evidence']['foreign_report']['pixels']['selected_contact_index'],1)

    def test_actual_two_contact_pixels_and_changed_selection(self):
        path=Path('runs/attempt-011/screens/ui-0002738.png')
        if not path.exists():self.skipTest('Private original frame unavailable')
        from civ2.observe import recognize
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        o=recognize(path);o['path']=str(path)
        d=classify_dialog(o,game_text=game_text(),labels_text=labels_text(),rules=parse_rules(original_rules()))
        self.assertTrue(d['supported']);self.assertEqual(len(d['options']),5)
        self.assertEqual(d['evidence']['foreign_report']['selected_contact']['tribe'],'Zulus')
        with TemporaryDirectory() as folder:
            for case in ('swap','both','neither','partial','border','extra_radio','hash'):
                image=Image.open(path).convert('RGB')
                if case in ('swap','both','neither','partial'):
                    for index,y in enumerate((235,260)):
                        color=(0,0,0) if case=='both' or case=='swap' and index==1 else (195,195,195)
                        for x in range(45,50):
                            for yy in range(y-1,y+2):image.putpixel((x,yy),color)
                    if case=='partial':image.putpixel((47,235),(0,0,0))
                if case=='border':image.putpixel((20,200),(1,0,0))
                if case=='extra_radio':image.paste(image.crop(TWO_RADIOS[0]),(100,226))
                target=Path(folder)/(case+'.png');image.save(target)
                obs=dict(path=str(target),sha256=hashlib.sha256(target.read_bytes()).hexdigest())
                if case=='hash':obs['sha256']='f'*64
                p=_two_pixels(obs)
                if case=='swap':self.assertEqual(p['selected_contact_index'],1)
                else:self.assertIsNone(p,case)
