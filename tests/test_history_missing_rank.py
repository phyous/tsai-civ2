"""Read printed historian ranks without filling the report's real gaps."""
from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared

class MissingHistoryRank(TestCase):
    def test_only_two_agreeing_aligned_fragments_can_add_a_printed_rank(self):
        for case in ('valid','disagree','name','punctuation','gap','baseline','control'):
            rows=[prepared('Bede completes his epic history:',210,180,220,18),
                  prepared('The Mediocre Civilization of the TEST',94,280,280,20),
                  prepared('OK',309,310,24,13)]
            a=[prepared('4.',80,280,15,15),prepared(rows[1]['text'],97,279,277,18)];b=deepcopy(a)
            if case=='disagree':b[0]['text']='3.'
            if case=='name':a[1]['text']=b[1]['text']='The Mediocre Civilization of the OTHER'
            if case=='punctuation':a[0]['text']=b[0]['text']='4'
            if case=='gap':a[0]['bounds'][0]=b[0]['bounds'][0]=50
            if case=='baseline':a[0]['center'][1]=b[0]['center'][1]=260
            if case=='control':rows.append(prepared('Cancel',270,310,30,13))
            old=deepcopy(rows)
            with mock.patch.object(observe,'_crop_text',side_effect=[a,b]):
                observe._recover_missing_history_rank(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
            if case=='valid':
                self.assertEqual(rows[1]['text'],'4. '+old[1]['text'])
                self.assertEqual(len(rows[1]['provenance']),5)
            else:self.assertEqual(rows,old,case)

    def test_original_report_keeps_missing_second_place_unknown(self):
        p=Path('runs/attempt-012/screens/ui-0002700.png')
        if not p.exists():self.skipTest('Private original image unavailable')
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        o=observe.recognize(p);d=classify_dialog(o,game_text=game_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        ranks=[r['text'] for r in o['lines'] if 'Civilization of the' in r['text']]
        self.assertEqual([r[0] for r in ranks],['1','3','4'])
        row=next(r for r in o['lines'] if r['text'].startswith('4. The'))
        self.assertTrue(row['provenance'][0]['text'].startswith('The Mediocre'))
        self.assertEqual([r['text'] for r in row['provenance'][1::2]],['4.','4.'])
