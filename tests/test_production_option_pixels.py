"""Complete production rows must be read independently, without losing choices."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2 import observe
from tests.test_herald import prepared


NAMES={'warriors','phalanx','archers','horsemen','catapult','library','courthouse'}


def panel(text='TA Courthouse',x=164):
    rows=[prepared('What shall me bold in Ravenna?',224,80,196,14)]
    rows += [prepared(t,x,390,40,16) for t,x in [('Auto',150),('Help',300),('OK',450)]]
    for i,name in enumerate(('Warriors','Phalanx','Archers','Horsemen')):
        rows += [prepared(name,180,110+i*17,64,14),prepared('(20 Turns)',400,110+i*17,110,14)]
    rows += [prepared(text,x,200,254-x,14),prepared('(80 Turns)',400,200,110,14)]
    return rows


class ProductionOptionPixels(unittest.TestCase):
    def test_original_art_prefix_requires_actual_whole_row_pair(self):
        for mutation in ('valid','disagree','low_confidence','shift','other_name','extra'):
            rows=panel();a=prepared('Courthouse',179,200,75,14);b=deepcopy(a)
            if mutation=='disagree':b['text']='A Courthouse'
            if mutation=='low_confidence':b['confidence']=.5
            if mutation=='shift':b['center'][1]+=30;b['bounds'][1]+=30
            if mutation=='other_name':a['text']=b['text']='Library'
            def crop(*args,**kwargs):
                result=deepcopy(b if kwargs.get('grayscale') else a)
                return [result,deepcopy(result)] if mutation=='extra' else [result]
            with patch.object(observe,'_production_names',return_value=NAMES),patch.object(observe,'_crop_text',side_effect=crop):
                observe._recover_production_option_rows(Image.new('RGB',(640,480)),rows,None,None,{})
            self.assertEqual(rows[-2]['text'],'Courthouse' if mutation=='valid' else 'TA Courthouse',mutation)
            self.assertEqual(rows[-2]['provenance'][0]['text'],'TA Courthouse')

    def test_missing_layout_or_unproved_prefix_does_not_read(self):
        for mutation in ('no_stat','few_names','no_control','not_left','negative','long_prefix'):
            rows=panel()
            if mutation=='no_stat':rows.pop()
            if mutation=='few_names':rows[4]['text']='Unknown'
            if mutation=='no_control':rows.pop(3)
            if mutation=='not_left':rows[-2]=prepared('TA Courthouse',180,200,90,14)
            if mutation=='negative':rows[-2]['text']='No Courthouse'
            if mutation=='long_prefix':rows[-2]['text']='Other Courthouse'
            with patch.object(observe,'_production_names',return_value=NAMES),patch.object(observe,'_crop_text') as crop:
                observe._recover_production_option_rows(Image.new('RGB',(640,480)),rows,None,None,{})
            crop.assert_not_called()

    def test_actual_ravenna_full_original_choices_and_raw_provenance(self):
        path=Path('runs/attempt-010/screens/ui-0002275.png')
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text,labels_text
        o=observe.recognize(path);o['path']=str(path.resolve())
        state={'cities':[],'recent_founding_notices':[{'name':'Ravenna','year_text':'200 B.C.',
            'source_tag':'FOUNDED','image_sha256':'e2cb887b3dd701d926cde63e6f43418440076421e193857f5f8f702282422eb5'}]}
        d=classify_dialog(o,state=state,rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'production_choice')
        self.assertEqual([r['text'] for r in d['options']],['Settlers','Warriors','Phalanx','Archers','Horsemen',
            'Catapult','Trireme','Diplomat','Caravan','Palace','Barracks','Granary','Temple','MarketPlace','Library','Courthouse'])
        for actual,raw in [('Catapult',',Catapult'),('Library','Librarv'),('Courthouse','TA Courthouse'),
                           ('What shall me bold in Ravenna?','What chall me bodd in Ravenna?')]:
            row=next(r for r in o['lines'] if r['text']==actual)
            self.assertEqual(row['provenance'][0]['text'],raw)
            self.assertEqual(len(row['provenance']),3)


if __name__=='__main__':unittest.main()
