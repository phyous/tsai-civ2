"""Synthetic TEST map-edge fixtures; private original calibration is optional."""
import copy
import json
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_dialogs import native_map,row,ROMAN_STATE

class MapEdges(unittest.TestCase):
    def state(self):
        s=copy.deepcopy(ROMAN_STATE);s['evidence']={'save_sha256':'b'*64}
        s['cities']=[{'id':0,'owner':1,'name':'Antium','x':4,'y':4}]
        return s
    def test_unique_known_edge_fragment_is_layout_only(self):
        for text,x in [('ium',21),('Ant',439)]:
            o=native_map();r=row(text,x=x,y=214,w=34);o['lines'].append(r)
            got=classify_dialog(o,state=self.state())
            self.assertEqual(got['kind'],'normal_map',got)
            self.assertEqual(r['text'],text)
            self.assertFalse(got['requires_model'])
            s=self.state();s['cities'].append({'name':'Anfium'})
            self.assertEqual(classify_dialog(o,state=s)['kind'],'normal_map')
    def test_nonedge_ambiguous_short_or_unbound_fragments_reject(self):
        for case in ('middle','ambiguous','short','hash','unknown','control','lowconfidence'):
            s=self.state();o=native_map();r=row('ium',x=21,y=214,w=34)
            if case=='middle':r=row('ium',x=200,y=214,w=34)
            if case=='ambiguous':s['known_cities']=[{'name':'Byzantium','x':8,'y':8}]
            if case=='short':r['text']='um'
            if case=='hash':s.pop('evidence')
            if case=='unknown':r['text']='xyz'
            if case=='control':r['text']='exit';s['cities'][0]['name']='TESTexit'
            if case=='lowconfidence':r['confidence']=.5
            o['lines'].append(r)
            self.assertFalse(classify_dialog(o,state=s)['supported'],case)
    def test_live_revision_is_supported_without_save_alias(self):
        s=self.state();s['evidence']={'kind':'live_memory','observation_sha256':'b'*64}
        o=native_map();o['lines'].append(row('ium',x=21,y=214,w=34))
        self.assertEqual(classify_dialog(o,state=s)['kind'],'normal_map')
    def test_optional_original_left_edge(self):
        root=Path(__file__).resolve().parents[1];run=root/'runs/attempt-005';p=run/'screens/ui-0001189.png'
        if not p.exists() or not(root/'.runtime/ocr').exists():self.skipTest('private original image unavailable')
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_save
        cp=None
        for line in (run/'events.jsonl').read_text().splitlines():
            e=json.loads(line)
            if e['kind']=='checkpoint':cp=e['payload']['artifact']['path']
            if e['kind']=='screen_observed' and e['payload'].get('path')=='screens/ui-0001189.png':break
        self.assertIsNotNone(cp)
        s=parse_save((run/cp).read_bytes(),rules_text=original_rules())
        got=classify_dialog(recognize(p),state=s)
        self.assertEqual(got['kind'],'normal_map',got)

if __name__=='__main__':unittest.main()
