"""Synthetic dates exercise interpretation only; no state-derived OCR repairs."""
from copy import deepcopy
from pathlib import Path
import unittest
from civ2.dates import date_parts,date_year,date_key,city_date_match
from civ2.run import observed_city_identity
from civ2.dialogs import classify_dialog,_recent_founded_name
from civ2.gdi_titles import _names
from civ2.city_controls import city_control_candidates,city_control_request_for,CityControlError
from civ2.verify import _action_binding,VerificationError
from test_city_controls import inputs
from test_city_header import screen
from test_dialogs import row,observation


class NativeDateTests(unittest.TestCase):
    def test_explicit_era_positions_punctuation_and_whitespace_are_equivalent(self):
        for forms,year,key in ((('4000 B.C.','4000BC','B.C. 4000','bc4000'),-4000,'4000BC'),
                               (('A.D. 1','AD1','1 A.D.','1AD'),1,'1AD'),
                               (('a. d. 125','125 a.d.'),125,'125AD')):
            for text in forms:
                with self.subTest(text=text):
                    self.assertEqual(date_year(text),year);self.assertEqual(date_key(text),key)
                    self.assertEqual(date_parts(text)[0],str(abs(year)))

    def test_incomplete_ambiguous_zero_and_unreadable_dates_reject(self):
        for text in (None,1,'AD','1','1 AD BC','AD1BC','A.D. J','1 A.C.','0 AD','0 BC',
                     '-1AD','+1AD','1.5 AD','A.D. 100000','1 B.C.D','1 В.С.','AD 1 trailing'):
            with self.subTest(text=text):self.assertIsNone(date_parts(text))
        for text in ('City of TEST Rome, AD 1BC','City of TEST Rome, 1 B.C.D',
                     'City of TEST Rome, AD 1 BC','City of TEST Rome, AD J'):
            self.assertIsNone(city_date_match(text))

    def test_city_identity_preserves_title_and_legacy_review_token(self):
        for text,key in (('4000 B.C.','4000BC'),('A.D. 1','1AD'),('1 A.D.','1AD')):
            title=f'City of TEST Rome, {text}, Population 10,000'
            dialog={'title':title};before=deepcopy(dialog)
            self.assertEqual(observed_city_identity(dialog),('TEST Rome',key));self.assertEqual(dialog,before)

    def test_current_city_controls_and_verifier_use_same_numeric_date(self):
        for text,year in (('4000 B.C.',-4000),('A.D. 1',1),('1 A.D.',1),('AD 250',250)):
            state,dialog,rules=inputs();state['year_raw']=year
            dialog['title']=f'City of TEST Rome, {text}, Population 20,000'
            actions=city_control_candidates(state,dialog,rules=rules)
            action=actions['change_production'];request=city_control_request_for(state,dialog,actions,rules=rules)
            _action_binding(action,request,'city_action',{'a'*64:state})
            self.assertEqual(action['preconditions']['observed_city_title'],dialog['title'])
            bad=deepcopy(action);bad['preconditions']['observed_city_title']='City of TEST Rome, A.D. 2'
            with self.assertRaises(VerificationError):_action_binding(bad,request,'city_action',{'a'*64:state})
            wrong=deepcopy(state);wrong['year_raw']=-year
            with self.assertRaises(CityControlError):city_control_candidates(wrong,dialog,rules=rules)

    def test_founding_notice_and_header_bind_equivalent_dates_without_actor_inference(self):
        state={'recent_founding_notices':[{'name':'Veii','year_text':'A.D. 1','source_tag':'FOUNDED','image_sha256':'a'*64}]}
        o=screen();o['lines'][0]['text']=o['lines'][0]['text'].replace('3000 B.C.','1 A.D.')
        result=classify_dialog(o,state=state)
        self.assertTrue(result['supported'],result);self.assertEqual(result['observed_city_name'],'Veii')
        self.assertEqual(observed_city_identity(result),('Veii','1AD'))
        self.assertEqual(_recent_founded_name('Vei','1 A.D.',state),state['recent_founding_notices'][0])
        self.assertIsNone(_recent_founded_name('Vei','1 B.C.',state))
        self.assertNotIn('city_id',result['city_name_recovery'])
        rows=[dict(text='City of Vei, 1 A.D.',confidence=1,bounds=[50,40,250,16])]
        self.assertEqual(_names(state,rows)[0][0],'Veii')
        rows[0]['text']='City of Vei, 1 B.C.';self.assertEqual(_names(state,rows),[])

    def test_founding_dialog_keeps_actual_ad_text(self):
        for date in ('A.D. 1','1 A.D.','4000 B.C.'):
            o=observation(row('Found New City',y=175,w=120),
                          row('TEST Rome founded: '+date,y=210,w=240),row('OK',y=260,w=24))
            result=classify_dialog(o)
            self.assertTrue(result['supported'],result);self.assertEqual(result['resource_tag'],'FOUNDED')
            self.assertEqual(result['founded_city']['year_text'],date)
            self.assertEqual(result['visible_text'], '\n'.join(r['text'] for r in o['lines']))
