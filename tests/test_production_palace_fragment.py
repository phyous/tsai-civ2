from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image
from civ2 import production_artwork as art
from civ2.dialogs import _production_icon_rows,_normal,classify_dialog
from tests.test_herald import prepared


class PalaceFragmentTests(TestCase):
    def test_exact_fragment_needs_same_png_and_complete_touching_palace_pair(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'frame.png';image=Image.new('RGB',(640,480),(123,100,70));image.save(path)
            digest=hashlib.sha256(image.crop((150,292,178,310)).tobytes()).hexdigest()
            source={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            rows=[prepared('nill',150,292,28,18),prepared('Palace',178,290,46,12),
                  prepared('(100 Turns)',444,289,78,16)]
            rows[0]['confidence']=.3
            rows=[dict(r,normal=_normal(r['text']),source_line=i)for i,r in enumerate(rows)]
            for mode in ('valid','missing_stat','bad_stat','wrong_label','duplicate_label','label_overlap','label_gap','bounds','strong_text','other_word','control','also_option','stale','pixels','no_path'):
                with self.subTest(mode=mode):
                    body=deepcopy(rows);o=deepcopy(source);names={'palace'}
                    if mode=='missing_stat':body.pop()
                    elif mode=='bad_stat':body[-1]['normal']='(unknown Turns)'
                    elif mode=='wrong_label':body[1]['normal']='barracks'
                    elif mode=='duplicate_label':body.insert(2,deepcopy(body[1]))
                    elif mode=='label_overlap':body[1]['bounds'][0]-=1
                    elif mode=='label_gap':body[1]['bounds'][0]+=1
                    elif mode=='bounds':body[0]['bounds'][0]-=1
                    elif mode=='strong_text':body[0]['confidence']=.8
                    elif mode=='other_word':body[0]['text']='nil'
                    elif mode=='control':body[0]['text']=body[0]['normal']='No'
                    elif mode=='also_option':names.add('nill')
                    elif mode=='stale':o['sha256']='b'*64
                    elif mode=='no_path':o.pop('path')
                    expected=digest if mode!='pixels'else'0'*64
                    with mock.patch.object(art,'PALACE_REGION_SHA256',expected):
                        icons=_production_icon_rows(body,names,o)
                    self.assertEqual(len(icons),1 if mode=='valid' else 0,mode)
                    if icons:
                        self.assertEqual(icons[0]['text'],'nill')
                        self.assertEqual(icons[0]['production_artwork_pixels']['calibration'],
                                         'original-production-palace-sprite-fragment-v1')

    def test_actual_brundisium_preserves_sixteen_choices_and_raw_fragment(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        if not Path('.runtime/ocr').exists():self.skipTest('Private original OCR absent')
        rules=parse_rules(original_rules());state={'recent_founding_notices':[dict(name='Brundisium',year_text='A.D. 840',source_tag='FOUNDED',image_sha256='a'*64)]}
        for number in (3537,3538):
            with self.subTest(number=number):
                path=Path(f'runs/attempt-010/screens/ui-{number:07}.png')
                if not path.exists():self.skipTest('Private original production frame absent')
                original=path.read_bytes();self.assertEqual(hashlib.sha256(original).hexdigest(),art.PALACE_CALIBRATION_IMAGE)
                o=recognize(path);o['path']=str(path);before=deepcopy(o)
                d=classify_dialog(o,state=state,rules=rules,game_text=game_text(),labels_text=labels_text())
                self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
                self.assertEqual(len(d['options']),16);self.assertEqual(d['title'],'What shall we build in Brundisium?')
                self.assertEqual(d['options'][11]['text'],'Palace')
                proof=next(p for p in d['evidence']['production_artwork']if p['text']=='nill')
                self.assertEqual(proof['bounds'],art.PALACE_BOUNDS)
                self.assertEqual(o,before);self.assertEqual(path.read_bytes(),original)
                for mode in ('missing_palace','missing_stat','extra_control','stale_path_hash'):
                    bad=deepcopy(o)
                    if mode=='missing_palace':bad['lines']=[r for r in bad['lines']if r['text']!='Palace']
                    elif mode=='missing_stat':bad['lines']=[r for r in bad['lines']if r['text']!='(100 Turns)']
                    elif mode=='extra_control':bad['lines'].append(prepared('Cancel',410,350,50,16))
                    else:bad['sha256']='b'*64
                    self.assertFalse(classify_dialog(bad,state=state,rules=rules,game_text=game_text(),labels_text=labels_text())['supported'],mode)
