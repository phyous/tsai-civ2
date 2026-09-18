"""Foreign Find City rows cannot become owned-city navigation targets."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image
from civ2 import city_locator
from civ2.dialogs import classify_dialog,_normal
from tests.test_herald import prepared

GAME='@FINDCITY\n@width=360\n@title=Where in the heck is . . .\n@button=Zoom To City\n@listbox\n\n'


class ForeignCityLocator(TestCase):
    def test_original_source_shape(self):
        from civ2.dialogs import dialog_resources
        from civ2.evidence import canonical
        self.assertEqual(hashlib.sha256(canonical(dialog_resources(GAME)[0])).hexdigest(),city_locator.SOURCE_SHA256)

    def test_complete_geometry_source_and_owned_target_scope(self):
        with TemporaryDirectory() as temp:
            path=Path(temp)/'locator.png';image=Image.new('RGB',(640,480),(207,207,207))
            for box in ((130,70,512,71),(130,70,131,412),(511,70,512,412),(130,411,512,412)):
                image.paste((0,0,0),box)
            pins={box:hashlib.sha256(image.crop(box).tobytes()).hexdigest() for box in city_locator.LIST_BORDERS}
            rows=[prepared('Where in the heck is.',246,78,138,14),
                  prepared('TEST Rome',144,104,80,14),prepared('TEST Paris (French)',144,121,140,14),
                  prepared('TEST Ravenna',144,138,90,14),prepared('Zoom To City',152,386,88,17),
                  prepared('OK',308,387,24,13),prepared('Cancel',424,386,42,14)]
            image.save(path)
            o=dict(width=640,height=480,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),lines=rows)
            state={'cities':[{'name':'TEST Rome'},{'name':'TEST Ravenna'}]};rules={'leaders':[{'adjective':'French'}]}
            for mode in ('valid','foreign_plain','unknown_nation','own_missing','gap','duplicate','cancel_missing','source','no_path','stale_image','frame','tail_ink'):
                with self.subTest(mode=mode):
                    current=deepcopy(o);text=GAME
                    if mode=='foreign_plain':current['lines'][2]['text']='TEST Paris'
                    if mode=='unknown_nation':current['lines'][2]['text']='TEST Paris (Unknown)'
                    if mode=='own_missing':current['lines'][3]['text']='TEST Unknown'
                    if mode=='gap':
                        current['lines'][3]['bounds'][1]+=17
                        current['lines'][3]['center'][1]+=17
                        current['lines'][3]['y']+=17/480
                    if mode=='duplicate':current['lines'][3]['text']='TEST Rome'
                    if mode=='cancel_missing':current['lines'].pop()
                    if mode=='source':text=text.replace('360','380')
                    if mode=='no_path':current.pop('path')
                    if mode=='stale_image':current['sha256']='0'*64
                    if mode in ('frame','tail_ink'):
                        changed=image.copy();changed.putpixel((130,90) if mode=='frame' else (200,280),(255,255,255))
                        other=Path(temp)/(mode+'.png');changed.save(other)
                        current['path']=str(other);current['sha256']=hashlib.sha256(other.read_bytes()).hexdigest()
                    with mock.patch.dict(city_locator.LIST_BORDERS,pins,clear=True):
                        d=classify_dialog(current,state=state,rules=rules,game_text=text)
                    if mode=='valid':
                        self.assertTrue(d['supported'],d)
                        self.assertEqual([r['text'] for r in d['options']],['TEST Rome','TEST Ravenna'])
                        self.assertFalse(d['requires_model']);self.assertIsNone(d['mechanical_action'])
                        proof=d['evidence']['foreign_locator_context']
                        self.assertEqual([r['text'] for r in proof['observed_rows']],['TEST Rome','TEST Paris (French)','TEST Ravenna'])
                        self.assertEqual([r['text'] for r in proof['foreign_context_rows']],['TEST Paris (French)'])
                    else:self.assertFalse(d['supported'],d)

    def test_actual_complete_locator_keeps_all_rows_and_only_eight_owned_targets(self):
        p=Path('runs/attempt-011/screens/ui-0003101.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original locator absent')
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text
        o=recognize(p);o['path']=str(p)
        names=['Rome','Veii','Antium','Cumae','Neapolis','Pompeii','Pisae','Ravenna']
        d=classify_dialog(o,state={'cities':[{'name':n} for n in names]},rules=parse_rules(original_rules()),game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual([r['text'] for r in d['options']],names)
        proof=d['evidence']['foreign_locator_context'];self.assertEqual(len(proof['observed_rows']),11)
        self.assertEqual([r['text'] for r in proof['foreign_context_rows']],['Paris (French)','Madrid (Spanish)','Toledo (Spanish)'])
        self.assertEqual(proof['source_image_sha256'],o['sha256'])
        self.assertIsNone(d['mechanical_action']);self.assertFalse(d['requires_model'])
