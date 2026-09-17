from copy import deepcopy
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2.observe import _recover_history_title,recognize
from civ2.dialogs import classify_dialog
from civ2.run import game_text,labels_text


def row(text,x,y,w=82,h=17):
    return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1,provenance=[{'pass':'TEST'}])


class HistoryTitlePixelsTests(TestCase):
    def fixture(self):
        rows=[row('Cimdivaition Д',280,176),row('Toynbee completes his epic history:',200,200,240,14),
              row('The WEAL THIEST Civilizations in the World',170,220,300,14),row('OK',300,290,40,14)]
        candidate=row('Cinlization I',280,176,83,15)
        return rows,candidate
    def recover(self,rows,a,b):
        with mock.patch('civ2.observe._crop_text',side_effect=[a,b,[],[]]) as crop:
            _recover_history_title(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        return crop
    def test_pair_preserves_actual_reading_and_both_sources(self):
        rows,candidate=self.fixture();self.recover(rows,[deepcopy(candidate)],[deepcopy(candidate)])
        self.assertEqual(rows[0]['text'],'Cinlization I');self.assertEqual(len(rows[0]['provenance']),3)
    def test_disagreement_or_single_read_does_not_recover(self):
        for value in ([],[dict(self.fixture()[1],text='Civilization II')]):
            rows,candidate=self.fixture();before=deepcopy(rows)
            self.recover(rows,[candidate],value);self.assertEqual(rows,before)
    def test_missing_history_context_never_reads_title(self):
        rows,candidate=self.fixture();rows.pop(2)
        self.recover(rows,[candidate],[candidate]).assert_not_called()
    def test_actual_private_history_is_source_bound_information(self):
        p=Path('runs/attempt-010/screens/ui-0000439.png')
        if not p.exists():self.skipTest('Private original screenshot absent')
        o=recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertEqual(d['kind'],'information');self.assertEqual(d['resource_tag'],'HISTORY')
        self.assertEqual(d['mechanical_action'],'acknowledge_information')

    def test_original_second_scale_keeps_actual_rank_and_historian(self):
        p=Path('runs/attempt-012/screens/ui-0000494.png')
        if not p.exists():self.skipTest('Private original screenshot absent')
        o=recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertEqual(d['kind'],'information');self.assertEqual(d['resource_tag'],'HISTORY')
        self.assertIn('St. Augustine completes his epic history:',d['visible_text'])
        self.assertIn('5. The Puny Civilization of the Romans',d['visible_text'])
        title=next(r for r in o['lines'] if r['text']=='Cinlization I')
        self.assertTrue({'history_title_rgb3','history_title_gray3'}<={p.get('preprocessing') for p in title['provenance']})
