"""Synthetic TEST map artwork and optional original image regressions."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


class CompoundMapLabelTests(unittest.TestCase):
    def test_only_paired_contained_label_over_colored_art_is_recovered(self):
        menu=[prepared(t,10+i*60,22,40,12) for i,t in enumerate(('Game','Kingdom','View','Orders'))]
        original=prepared('-rTESTCITY',148,188,82,34,.3)
        first=prepared('TESTCITY',174,204,56,16)
        for case in ('valid','confidence_half','gray','different','extra','control','not_suffix','outside','overlap','weak','strong_native'):
            image=Image.new('RGB',(640,480),'gray' if case=='gray' else (20,160,30))
            old=copy.deepcopy(original);a=copy.deepcopy(first);b=copy.deepcopy(first)
            if case=='confidence_half':old['confidence']=.5
            if case=='strong_native':old['confidence']=.8
            if case=='different':b['text']='OTHERCITY'
            if case=='control':old['text']='-rContinue';a['text']=b['text']='Continue'
            if case=='not_suffix':old['text']='unrelated'
            if case=='outside':a['bounds'][0]=b['bounds'][0]=130
            if case=='weak':b['confidence']=.5
            rows=copy.deepcopy(menu)+[old]
            if case=='overlap':rows.append(prepared('TEST other',170,204,60,16))
            if case=='extra':rows.append(prepared('OK',300,300,30,16))
            with patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                observe._recover_compound_map_label(image,rows,None,None,{'passes':[]})
            self.assertEqual(rows[4]['text'],'TESTCITY' if case in ('valid','confidence_half') else old['text'],case)
            if case in ('valid','confidence_half'):
                self.assertEqual(rows[4]['provenance'][0]['text'],'-rTESTCITY')
                self.assertGreater(rows[4]['provenance'][-1]['compound_map_artwork']['discarded_pixels'],0)

    def test_low_confidence_letters_require_independent_strong_reads(self):
        menu=[prepared(t,10+i*60,22,40,12) for i,t in enumerate(('Game','Kingdom','View','Orders'))]
        original=prepared('ten',250,238,30,14,.3);fresh=prepared('Test',249,235,35,18)
        for match in (True,False):
            rows=copy.deepcopy(menu+[original]);second=copy.deepcopy(fresh)
            if not match:second['text']='Tent'
            with patch.object(observe,'_crop_text',side_effect=[[fresh],[second],[],[],[],[]]):
                observe._recover_map_labels(Image.new('RGB',(640,480),'gray'),rows,None,None,{'passes':[]})
            self.assertEqual(rows[-1]['text'],'Test' if match else 'ten')

    def test_optional_original_label_and_artwork_keep_native_provenance(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0001893.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original frame unavailable')
        o=observe.recognize(p)
        antium=next(r for r in o['lines'] if r['text']=='Antium')
        veii=next(r for r in o['lines'] if r['provenance'][0]['text']=='ven')
        self.assertEqual(antium['provenance'][0]['text'],'-rAntium')
        self.assertEqual(veii['text'],'Veil')
        from civ2.dialogs import classify_dialog
        from civ2.save import parse_save
        run=p.parent.parent;checkpoint=None
        for line in (run/'events.jsonl').read_text().splitlines():
            e=json.loads(line)
            if e['kind']=='checkpoint':checkpoint=e['payload']['artifact']['path']
            if e['kind']=='screen_observed' and e['payload'].get('path')==str(p.relative_to(run)):break
        self.assertIsNotNone(checkpoint)
        state=parse_save((run/checkpoint).read_bytes())
        self.assertEqual(classify_dialog(o,state=state)['kind'],'normal_map')

    def test_optional_half_confidence_same_original_sprite(self):
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0001921.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original frame unavailable')
        o=observe.recognize(p);r=next(r for r in o['lines'] if r['text']=='Antium')
        self.assertEqual(r['provenance'][0]['text'],'FCAntium')
        self.assertEqual(r['provenance'][0]['confidence'],.5)


if __name__=='__main__':unittest.main()
