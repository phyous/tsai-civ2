from copy import deepcopy
import hashlib
from pathlib import Path
from zipfile import ZipFile
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from civ2.dialogs import classify_dialog,dialog_resources
from civ2.evidence import canonical
from civ2.native_events import ORDER_NOTICE_RESOURCES
from civ2.verify import PUBLIC_NOTICE_RESOURCES
from tests.test_herald import prepared


class FortressOrderNotice(unittest.TestCase):
    def test_pixel_pairs_do_not_supply_missing_or_conflicting_text(self):
        for case in ('valid','mismatch','weak','displaced','missing_end'):
            rows=[prepared('New Order: Fortress',240,160,160,16),
                  prepared('and prevent more than one unit at a fime from',196,250,308,16),
                  prepared('being lost in combat.',240,270,160,16),prepared('OK',308,300,24,16)]
            old=deepcopy(rows[1]);a=deepcopy(old);a['text']='and prevent more than one unit at a time from';b=deepcopy(a)
            if case=='mismatch':b['text']=old['text']
            if case=='weak':b['confidence']=.5
            if case=='displaced':b.update(bounds=[100,350,308,16],center=[254,358])
            if case=='missing_end':rows.pop(2)
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_fortress_order_body(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            self.assertEqual(rows[1]['text'],a['text'] if case=='valid' else old['text'])
            self.assertEqual(rows[1]['provenance'][0]['text'],old['text'])

    def test_original_complete_notice_and_source_pin(self):
        image=Path('runs/attempt-012/screens/ui-0001963.png');archive=Path('engine/game/civ2-win31.zip')
        if not image.exists() or not archive.exists():self.skipTest('Private original unavailable')
        with ZipFile(archive) as z:game=z.read('civ2/GAME.TXT').decode('cp1252')
        source=next(r for r in dialog_resources(game) if r['tag']=='NEWFORTRESS')
        self.assertEqual(hashlib.sha256(canonical(source)).hexdigest(),ORDER_NOTICE_RESOURCES['NEWFORTRESS'])
        self.assertEqual(ORDER_NOTICE_RESOURCES['NEWFORTRESS'],PUBLIC_NOTICE_RESOURCES['NEWFORTRESS'])
        o=observe.recognize(image);d=classify_dialog(o,game_text=game)
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'NEWFORTRESS')
        self.assertEqual([r['text'] for r in d['options']],['OK']);self.assertFalse(d['requires_model'])
        for case in ('body','source','choice'):
            changed=deepcopy(o);text=game
            if case=='body':changed['lines']=[r for r in changed['lines'] if r['text']!='being lost in combat.']
            if case=='source':text=game.replace('double the defense of units defending within,','triple the defense of units defending within,')
            if case=='choice':changed['lines'].append(prepared('Cancel',270,285,45,16))
            self.assertFalse(classify_dialog(changed,game_text=text)['supported'],case)

if __name__=='__main__':unittest.main()
