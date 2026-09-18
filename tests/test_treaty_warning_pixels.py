"""The complete original peace warning always requires a model choice."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile
from PIL import Image
from civ2.observe import _recover_treaty_warning,recognize
from civ2.dialogs import classify_dialog
from civ2.save import parse_rules
from test_native_choices import source_text,RULES
from test_treaty_reminder import row


def fixture():
    return dict(width=640,height=480,sha256='a'*64,lines=[
        row('Foreign Mfinister',270,158,102),
        row('We have signed a peace treaty withthe',196,184,264),
        row('TEST Greeks! Our reputation will be damaged if we',196,204,306),
        row('break it!',196,224,58),row('Cancel action.',234,249,94),
        row('Break treaty.',234,274,90),row('OK',310,306,22)])


class TreatyWarningTests(unittest.TestCase):
    def test_break_spacing_requires_two_reads_of_exact_warning(self):
        for mode in ('valid','disagree','different_warning','missing_option'):
            rows=fixture()['lines'];rows[1]['text']='We have signed a peace treaty with the'
            rows[3]['text']='breakit!';rows[3]['provenance']=[{'text':'breakit!'}]
            a=deepcopy(rows[3]);a['text']='break it!';b=deepcopy(a)
            if mode=='disagree':b['text']='breakit!'
            if mode=='different_warning':a['text']=b['text']='keep it!'
            if mode=='missing_option':rows.pop(5)
            with patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                _recover_treaty_warning(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[3]['text'],'break it!' if mode=='valid' else 'breakit!',mode)
            self.assertEqual(rows[3]['provenance'][0]['text'],'breakit!')

    def test_actual_ad100_warning_keeps_both_choices(self):
        p=Path('runs/attempt-012/screens/ui-0001749.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        from civ2.boot import original_rules
        from civ2.run import game_text
        o=recognize(p);d=classify_dialog(o,game_text=game_text(),rules=parse_rules(original_rules()))
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual([x['text'] for x in d['options']],['Cancel action.','Break treaty.'])
        recovered=next(r for r in o['lines'] if r['text']=='break it!')
        self.assertEqual([p['text'] for p in recovered['provenance']],['breakit!','break it!','break it!'])

    def test_period_requires_paired_pixels_and_unchanged_warning_and_options(self):
        for mode in ('valid','disagreement','different_option','missing_warning'):
            o=fixture();rows=o['lines'];rows[1]['text']='We have signed a peace treaty with the'
            rows[5]['text']='Break treaty';rows[5]['provenance']=[{'preprocessing':'native','text':'Break treaty'}]
            a=deepcopy(rows[5]);a['text']='Break treaty.';a['provenance']=[{'preprocessing':'rgb2','text':a['text']}]
            b=deepcopy(a)
            if mode=='disagreement':b['text']='Break treaty'
            elif mode=='different_option':a['text']=b['text']='Cancel action.'
            elif mode=='missing_warning':rows[3]['text']='Different words!'
            before=deepcopy(rows)
            with self.subTest(mode=mode),patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                _recover_treaty_warning(Image.new('RGB',(640,480)),rows,None,None,{})
            if mode=='valid':
                self.assertEqual(rows[5]['text'],'Break treaty.')
                self.assertEqual(rows[5]['provenance'][0]['text'],'Break treaty')
                self.assertEqual(len(rows[5]['provenance']),3)
            else:self.assertEqual(rows,before)

    def test_recovery_needs_paired_pixels_and_every_warning_and_option(self):
        for mode in ('valid','disagreement','weak','location','missing_warning','missing_option','other_nation'):
            o=fixture();rows=o['lines'];before=deepcopy(rows)
            a=deepcopy(rows[1]);a['text']='We have signed a peace treaty with the';b=deepcopy(a)
            if mode=='disagreement':b['text']=rows[1]['text']
            elif mode=='weak':b['confidence']=.6
            elif mode=='location':b['bounds'][0]+=100;b['center'][0]+=100
            elif mode=='missing_warning':rows[3]['text']='Arbitrary words!';before=deepcopy(rows)
            elif mode=='missing_option':rows.pop(5);before=deepcopy(rows)
            elif mode=='other_nation':a['text']=b['text']='We have signed a peace treaty with OTHER';
            with self.subTest(mode=mode),patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                _recover_treaty_warning(Image.new('RGB',(640,480)),rows,None,None,{})
                if mode=='valid':
                    self.assertEqual(rows[1]['text'],a['text']);self.assertEqual(len(rows[1]['provenance']),3)
                else:self.assertEqual(rows,before)

    def test_measured_icon_layout_and_title_still_need_complete_source_and_counterparty(self):
        o=fixture();o['lines'][1]['text']='We have signed a peace treaty with the'
        d=classify_dialog(o,game_text=source_text('ANNOYPEACE'),rules=RULES)
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'treaty_break_choice')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([x['text'] for x in d['options']],['Cancel action.','Break treaty.'])
        self.assertEqual(d['evidence']['title_recovery']['raw'],'Foreign Mfinister')
        for mode in ('unknown_nation','missing_warning','extra_button','outside_panel','different_body'):
            bad=deepcopy(o)
            if mode=='unknown_nation':bad['lines'][2]['text']=bad['lines'][2]['text'].replace('TEST Greeks','OTHER nation')
            elif mode=='missing_warning':bad['lines'].pop(3)
            elif mode=='extra_button':bad['lines'].append(row('Cancel',390,306,40))
            elif mode=='outside_panel':bad['lines'][2]['bounds'][2]=340
            else:bad['lines'][2]['text']=bad['lines'][2]['text'].replace('damaged','improved')
            with self.subTest(mode=mode):self.assertFalse(classify_dialog(bad,game_text=source_text('ANNOYPEACE'),rules=RULES)['supported'])

    def test_actual_original_warning_retains_both_model_options_and_every_term(self):
        p=Path('runs/attempt-011/screens/ui-0001596.png');bundle=Path('engine/game/civ2-win31.zip')
        if not p.exists() or not bundle.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original assets absent')
        with zipfile.ZipFile(bundle) as z:
            rules=parse_rules(z.read('civ2/RULES.TXT').decode('cp1252'));game=z.read('civ2/GAME.TXT').decode('cp1252')
        data=p.read_bytes();o=recognize(p);d=classify_dialog(o,game_text=game,rules=rules)
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual(d['resource_tag'],'ANNOYPEACE');self.assertEqual(d['evidence']['observed_counterparty'],'Spanish')
        self.assertIn('reputation will be damaged',d['visible_text'])
        self.assertEqual([x['text'] for x in d['options']],['Cancel action.','Break treaty.'])
        self.assertEqual(p.read_bytes(),data)

    def test_actual_german_warning_option_final_period(self):
        p=Path('runs/attempt-010/screens/ui-0001905.png');bundle=Path('engine/game/civ2-win31.zip')
        if not p.exists() or not bundle.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original assets absent')
        with zipfile.ZipFile(bundle) as z:
            rules=parse_rules(z.read('civ2/RULES.TXT').decode('cp1252'));game=z.read('civ2/GAME.TXT').decode('cp1252')
        o=recognize(p);d=classify_dialog(o,game_text=game,rules=rules)
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual(d['resource_tag'],'ANNOYPEACE')
        self.assertEqual([x['text'] for x in d['options']],['Cancel action.','Break treaty.'])
        recovered=next(r for r in o['lines'] if r['text']=='Break treaty.')
        self.assertEqual([r['text'] for r in recovered['provenance']],['Break treaty','Break treaty.','Break treaty.'])


if __name__=='__main__':unittest.main()
