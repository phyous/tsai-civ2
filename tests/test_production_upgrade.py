from copy import deepcopy
from pathlib import Path
import unittest
from civ2.production_upgrade import SOURCE,classify_production_upgrade
from civ2.dialogs import _rows,classify_dialog
from tests.test_native_events import row


def fixture():
    o=dict(width=640,height=480,sha256='a'*64,lines=[
        row('Domestic Advisor',x=320,y=170,width=112),
        row('Production orders in TEST Town upgraded from',x=355,y=195,width=250),
        row('Warriors to Pikemen.',x=300,y=215,width=144),
        row('Zoom to City',x=307,y=245,width=88),row('Continue',x=292,y=269,width=70),
        row('O',x=246,y=269,width=18),row('OK',x=320,y=305,width=24)])
    state={'player':{'id':1},'cities':[dict(owner=1,name='TEST Town')]}
    rules={'units':[{'name':'Warriors'},{'name':'Pikemen'}]}
    labels='\n'.join(['']*48+['Zoom to City','Continue'])
    return o,state,rules,labels


class ProductionUpgradeTests(unittest.TestCase):
    def classify(self,o,state,rules,labels,source=None):
        return classify_production_upgrade(o,_rows(o),[SOURCE if source is None else source],rules,state,labels)

    def test_real_alternatives_and_raw_radio_text_are_preserved(self):
        args=fixture();before=deepcopy(args);d=self.classify(*args)
        self.assertIsNotNone(d);self.assertEqual([x['text']for x in d['options']],['Zoom to City','Continue'])
        self.assertEqual(d['kind'],'production_upgrade_notice');self.assertEqual(args,before)

    def test_missing_or_unbound_body_controls_sources_and_conflicts_fail_closed(self):
        for case in ('body','city','unit','option','extra','button','title','source','labels','conflict','radio'):
            o,s,r,l=fixture();source=deepcopy(SOURCE)
            if case=='body':o['lines'][1]['text']=o['lines'][1]['text'].replace('upgraded','downgraded')
            elif case=='city':s['cities']=[]
            elif case=='unit':r['units'].pop()
            elif case=='option':o['lines'].pop(3)
            elif case=='extra':o['lines'].insert(2,row('Pay 50 gold.',x=320,y=225,width=100))
            elif case=='button':o['lines'][-1]['text']='Cancel'
            elif case=='title':o['lines'][0]['confidence']=.7
            elif case=='source':source['options']=['Accept','Refuse']
            elif case=='labels':l=l.replace('Continue','Close')
            elif case=='conflict':o['ocr']={'conflicts':[{'text':'Cancel'}]}
            elif case=='radio':o['lines'][-2]['center'][0]-=60;o['lines'][-2]['bounds'][0]-=60
            with self.subTest(case=case):self.assertIsNone(self.classify(o,s,r,l,source))

    def test_only_geometrically_separate_background_conflicts_are_retained(self):
        o,s,r,l=fixture();o['ocr']={'conflicts':[dict(text='End of Turn',bounds=[476,445,62,11],reason='TEST ambiguous background status')]}
        d=self.classify(o,s,r,l);self.assertIsNotNone(d)
        self.assertEqual(d['evidence']['background_ocr_conflicts'],o['ocr']['conflicts'])
        for bounds in ([280,200,30,12],None,[476,445,62,False]):
            o['ocr']['conflicts'][0]['bounds']=bounds
            self.assertIsNone(self.classify(o,s,r,l))

    def test_original_antium_notice_preserves_background_footer_ambiguity(self):
        p=Path('runs/attempt-011/screens/ui-0002166.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        o=recognize(p)
        d=classify_dialog(o,state={'player':{'id':1},'cities':[{'owner':1,'name':'Antium'}]},
            rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['kind'],'production_upgrade_notice');self.assertIsNone(d['mechanical_action'])
        self.assertEqual([x['text']for x in d['options']],['Zoom to City','Continue'])
        self.assertEqual(d['evidence']['background_ocr_conflicts'],o['ocr']['conflicts'])

    def test_private_original_notice_offers_both_actual_choices(self):
        p=Path('runs/attempt-011/screens/ui-0002084.png')
        if not p.exists():self.skipTest('Private original frame unavailable')
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        from civ2.run import game_text,labels_text
        d=classify_dialog(recognize(p),state={'player':{'id':1},'cities':[{'owner':1,'name':'Veii'}]},
            rules=parse_rules(original_rules()),game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model'])
        self.assertEqual(d['resource_tag'],'UPGRADED');self.assertIsNone(d['mechanical_action'])
        self.assertEqual([x['text']for x in d['options']],['Zoom to City','Continue'])


if __name__=='__main__':unittest.main()
