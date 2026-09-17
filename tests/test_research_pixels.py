"""Synthetic TEST selected-label checks plus optional retained original pixels."""
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


def rows():
    return [prepared('Whait discovery shall our wise men porsue?',190,78,263,14),
            prepared('Ceremonial Bunal',248,103,118,13),
            prepared('Map Making',248,121,88,13),prepared('Masonry',248,140,67,13),
            prepared('Help',201,384,30,14),prepared('Goal',301,384,30,14),prepared('OK',414,384,20,14)]


class ResearchPixels(unittest.TestCase):
    def test_only_matching_exact_pixel_reads_replace_unknown_selected_label(self):
        good=prepared('Ceremonial Burial',249,104,116,12)
        names=frozenset(('ceremonial burial','map making','masonry'))
        for case in ('valid','disagreement','far_geometry','unknown_name','low_confidence','no_selected_pixels'):
            with self.subTest(case=case):
                data=rows();a=copy.deepcopy(good);b=copy.deepcopy(good)
                if case=='disagreement':b['text']='Ceremonial Bunial'
                if case=='far_geometry':b=prepared('Ceremonial Burial',440,203,118,13)
                if case=='unknown_name':a['text']=b['text']='Ceremonial Bunal'
                if case=='low_confidence':b['confidence']=.5
                image=Image.new('RGB',(640,480),'black' if case=='no_selected_pixels' else 'white')
                with patch.object(observe,'_research_names',return_value=names),patch.object(observe,'_crop_text',side_effect=[[a],[b]]):
                    observe._recover_research_rows(image,data,None,None,{'passes':[]})
                self.assertEqual(data[1]['text'],'Ceremonial Burial' if case=='valid' else 'Ceremonial Bunal')
                if case=='valid':
                    self.assertEqual(len(data[1]['provenance']),3)
                    self.assertEqual(data[1]['center'],rows()[1]['center'])
                    self.assertEqual(data[1]['bounds'],rows()[1]['bounds'])

    def test_missing_controls_or_exact_peer_options_prevent_any_crop(self):
        for case in ('control','peers','title'):
            data=rows()
            if case=='control':data.pop()
            if case=='peers':data[2]['text']='Unrecognized';data[3]['text']='Unrecognized'
            if case=='title':data[0]['text']='What secret should we reveal?'
            with patch.object(observe,'_research_names',return_value=frozenset(('ceremonial burial','map making','masonry'))),patch.object(observe,'_crop_text') as crop:
                observe._recover_research_rows(Image.new('RGB',(640,480),'white'),data,None,None,{'passes':[]})
                crop.assert_not_called()

    def test_exact_original_options_are_not_rewritten(self):
        data=rows();data[1]['text']='Ceremonial Burial'
        with patch.object(observe,'_research_names',return_value=frozenset(('ceremonial burial','map making','masonry'))),patch.object(observe,'_crop_text') as crop:
            observe._recover_research_rows(Image.new('RGB',(640,480),'white'),data,None,None,{'passes':[]})
            crop.assert_not_called()

    def test_optional_actual_009_research_selected_ceremonial_burial(self):
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-009/screens/ui-0000265.png'
        if not path.exists() or not(root/'.runtime/ocr').exists():self.skipTest('Private original research frame unavailable')
        observation=observe.recognize(path)
        row=next(r for r in observation['lines'] if r['text']=='Ceremonial Burial')
        self.assertEqual(row['provenance'][0]['text'],'Ceremonial Bunal')
        self.assertEqual(sum(p['preprocessing'].startswith('research_name_') for p in row['provenance']),2)
        dialog=classify_dialog(observation,rules=parse_rules(original_rules()),game_text=game_text())
        self.assertTrue(dialog['supported'],dialog)
        self.assertEqual(dialog['kind'],'research_choice')
        self.assertEqual([r['text'] for r in dialog['options']],['Ceremonial Burial','Map Making','Masonry','Pottery','Warrior Code','Writing'])

if __name__=='__main__':unittest.main()
