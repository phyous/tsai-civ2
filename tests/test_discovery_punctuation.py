"""Punctuation correction requires two same-name reads of original pixels."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2 import observe


def rows():
    def row(text,x,y,w):
        return dict(text=text,confidence=1.,bounds=[x,y,w,16],center=[x+w//2,y+8],provenance=[dict(text=text)])
    return [row('Civilization Advance',240,194,160),
            row('TEST wise men discover the secret of',200,220,260),
            row('TEST Currency:',202,240,120),row('OK',308,270,24)]


class DiscoveryPunctuationTests(TestCase):
    def test_only_two_agreeing_same_name_crops_change_punctuation(self):
        for mode in ('good','different_name','disagree','low_confidence','elsewhere','partial_body','extra_control'):
            with self.subTest(mode=mode):
                original=rows();a=deepcopy(original[2]);a['text']='TEST Currency.';b=deepcopy(a)
                if mode=='different_name':a['text']=b['text']='TEST Writing.'
                elif mode=='disagree':b['text']='TEST Currency:'
                elif mode=='low_confidence':b['confidence']=.5
                elif mode=='elsewhere':b['bounds'][1]+=40;b['center'][1]+=40
                elif mode=='partial_body':original[1]['text']='TEST incomplete'
                elif mode=='extra_control':original.append(dict(original[-1],text='Cancel'))
                with mock.patch.object(observe,'_research_names',return_value={'test currency'}), \
                     mock.patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                    observe._recover_discovery_punctuation(Image.new('RGB',(640,480)),original,None,None,{})
                self.assertEqual(original[2]['text'],'TEST Currency.' if mode=='good' else 'TEST Currency:')

    def test_actual_currency_discovery_reads_original_period(self):
        p=Path('runs/attempt-011/screens/ui-0000906.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original discovery unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);r=classify_dialog(o,game_text=game_text())
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'CIVADVANCE')
        line=next(x for x in o['lines'] if x['text']=='Currency.')
        self.assertIn('Currency:',[x['text'] for x in line['provenance']])
        self.assertEqual([x['preprocessing'] for x in line['provenance'][-2:]],
                         ['discovery_period_rgb2','discovery_period_gray2'])
