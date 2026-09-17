"""Account for both original crop components; never discard unknown text."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe,map_badges
from tests.test_herald import prepared


class MergedMapBadge(unittest.TestCase):
    def test_requires_two_city_reads_every_rgb_component_and_exact_badge(self):
        old=prepared('Antum TEST',76,218,122,32)
        city=prepared('Antium',76,220,60,18);digit=prepared('3',186,237,9,10)
        menu=[prepared(t,10+i*60,20,45,14)for i,t in enumerate(('Game','Kingdom','View','Orders'))]
        for case in ('valid','extra','disagree','badge','shift','control'):
            a=[deepcopy(city),deepcopy(digit)];b=[deepcopy(city)];rows=[*deepcopy(menu),deepcopy(old)]
            if case=='extra':a.append(prepared('Cancel',100,240,30,12))
            if case=='disagree':b[0]['text']='Antina'
            if case=='shift':a[1]['bounds'][0]+=30;a[1]['center'][0]+=30
            if case=='control':rows.append(prepared('OK',300,300,25,15))
            with patch.object(observe,'_crop_text',side_effect=[a,b,a,b]),patch.object(map_badges,'occluded_badge_bounds',return_value=None if case=='badge' else [186,234,11,15]):
                observe._recover_merged_city_badge(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual([r['text']for r in rows[-2:]],['Antium','3'])
                for r in rows[-2:]:self.assertEqual(r['provenance'][0]['text'],'Antum TEST')
            else:self.assertIn('Antum TEST',[r['text']for r in rows],case)

    def test_private_original_badge_exact_pixels_and_proof_tampering(self):
        p=Path('runs/attempt-011/screens/ui-0001917.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),map_badges.OCCLUDED_SOURCE_SHA256)
        image=Image.open(p).convert('RGB');row=prepared('3',186,237,9,10)
        self.assertEqual(map_badges.occluded_badge_bounds(image,row),[186,234,11,15])
        map_badges.annotate_badges(image,[row],'a'*64)
        self.assertTrue(map_badges.proven_badge(row,'a'*64))
        for key,value in (('crop_rgb_sha256','b'*64),('source_sha256','b'*64),
                          ('reference_image_sha256','b'*64),('bounds',[300,234,11,15]),('row_bounds',[185,237,9,10])):
            bad=deepcopy(row);bad['map_badge_pixels'][key]=value
            self.assertFalse(map_badges.proven_badge(bad,'a'*64),key)
        image.putpixel((190,240),(1,2,3))
        self.assertIsNone(map_badges.occluded_badge_bounds(image,row))

    def test_actual_map_still_requires_owned_names_and_all_original_layout_guards(self):
        p=Path('runs/attempt-011/screens/ui-0001917.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        o=observe.recognize(p)
        state={'evidence':{'kind':'live_memory','observation_sha256':'a'*64},'player':{'id':1,'tribe_id':0},
               'cities':[dict(id=i,owner=1,name=name,x=10+2*i,y=10)for i,name in enumerate(('Rome','Veii','Antium','Cumae','Neapolis'))]}
        kwargs=dict(rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        d=classify_dialog(o,state=state,**kwargs)
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'end_turn')
        self.assertNotIn('native_map_context',d.get('evidence',{}))
        self.assertTrue(any(r.get('map_badge_pixels',{}).get('crop_rgb_sha256')==map_badges.OCCLUDED_CROP_SHA256 for r in o['lines']))
        peers=[*p.parent.glob('native-map-003161*-1.png'),*p.parent.glob('native-map-current-003177*')]
        for peer in peers:
            result=classify_dialog(observe.recognize(peer),state=state,**kwargs)
            self.assertTrue(result['supported'],(peer,result));self.assertEqual(result['kind'],'end_turn')
        state['cities']=[];self.assertFalse(classify_dialog(o,state=state,**kwargs)['supported'])


if __name__=='__main__':unittest.main()
