"""Exact sprite pixels never justify ignoring arbitrary numeric list rows."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,mock
from PIL import Image
from civ2 import production_artwork as art
from civ2.dialogs import _production_icon_rows,_normal
from tests.test_herald import prepared


class ProductionSpriteFragment(TestCase):
    def test_exact_pixels_and_complete_adjacent_label_stat_pair_required(self):
        with TemporaryDirectory() as temp:
            image=Image.new('RGB',(640,480),(123,100,70));path=Path(temp)/'frame.png';image.save(path)
            digest=hashlib.sha256(image.crop((152,149,173,176)).tobytes()).hexdigest()
            o={'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
            rows=[prepared('94',152,149,21,27),prepared('TEST Unit',178,154,58,14),
                  prepared('(3 Turns, ADM: 1/2/1 HP: 1/1)',326,154,198,16)]
            rows=[dict(r,normal=_normal(r['text']),source_line=i) for i,r in enumerate(rows)]
            for mode in ('valid','missing_stat','wrong_label','bounds','stale','pixels','no_path'):
                with self.subTest(mode=mode):
                    body=deepcopy(rows);source=deepcopy(o)
                    if mode=='missing_stat':body.pop()
                    if mode=='wrong_label':body[1]['normal']='unobserved unit'
                    if mode=='bounds':body[0]['bounds'][0]+=1
                    if mode=='stale':source['sha256']='0'*64
                    if mode=='no_path':source.pop('path')
                    expected=digest if mode!='pixels' else '0'*64
                    with mock.patch.object(art,'REGION_SHA256',expected):
                        result=_production_icon_rows(body,{'test unit'},source)
                    self.assertEqual(len(result),1 if mode=='valid' else 0)
                    if mode=='valid':self.assertEqual(result[0]['text'],'94');self.assertIn('production_artwork_pixels',result[0])
