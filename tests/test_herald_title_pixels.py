"""The emissary suffix needs two actual readings; other title words are fixed."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import _recover_herald_title,recognize


def row(text,x=390,y=262,w=158,h=14):
    return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1,
                provenance=[{'pass':'TEST original'}])


class HeraldTitleTests(unittest.TestCase):
    def fixture(self):
        return [row('Neutral TEST Enussary'),row('OK',456,454,26,16)]

    def test_two_reads_preserve_prefix_and_provenance(self):
        rows=self.fixture();a=deepcopy(rows[0]);a['text']='Neutral TEST Emissary'
        a['provenance']=[{'pass':'TEST RGB pixels'}];b=deepcopy(a);b['provenance']=[{'pass':'TEST gray pixels'}]
        with patch('civ2.observe._crop_text',side_effect=[[a],[b]]) as crop:
            _recover_herald_title(Image.new('RGB',(640,480)),rows,None,None,{})
        self.assertEqual(rows[0]['text'],'Neutral TEST Emissary')
        self.assertEqual(len(rows[0]['provenance']),3)
        self.assertEqual(crop.call_count,2)

    def test_disagreement_nation_change_wrong_location_and_controls_reject(self):
        for mode in ('disagree','nation','weak','location','duplicate','button','already_exact'):
            rows=self.fixture();a=deepcopy(rows[0]);a['text']='Neutral TEST Emissary';b=deepcopy(a)
            if mode=='disagree':b['text']='Neutral TEST Enussary'
            elif mode=='nation':a['text']=b['text']='Neutral OTHER Emissary'
            elif mode=='weak':b['confidence']=.5
            elif mode=='location':b['center'][1]+=35;b['bounds'][1]+=35
            elif mode=='duplicate':rows.append(deepcopy(rows[0]))
            elif mode=='button':rows.append(row('Cancel',400,454,35,16))
            else:rows[0]['text']='Neutral TEST Emissary'
            before=deepcopy(rows)
            with self.subTest(mode=mode),patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                _recover_herald_title(Image.new('RGB',(640,480)),rows,None,None,{})
                self.assertEqual(rows,before)

    def test_original_spanish_exchange_keeps_three_actual_model_options(self):
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        path=Path('runs/attempt-011/screens/ui-0001198.png')
        if not path.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original calibration absent')
        original=path.read_bytes();o=recognize(path);o['path']=str(path)
        d=classify_dialog(o,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'EXCHANGE0')
        self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
        self.assertEqual([x['text'] for x in d['options']],['"No. We do not need Warrior Code."',
            '"Okay, let\'s exchange knowledge."','"Will you accept Monarchy instead?"'])
        self.assertIn('secret of Writing.',o['text'])
        self.assertTrue(any(p.get('preprocessing')=='herald_title_rgb2' for p in o['lines'][0]['provenance']))
        self.assertEqual(path.read_bytes(),original)


if __name__=='__main__':unittest.main()
