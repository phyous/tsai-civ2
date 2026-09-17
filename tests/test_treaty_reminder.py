"""Original TERMS is an observed reminder, never authority to move units."""
from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
from PIL import Image
from civ2.observe import _recover_treaty_reminder,recognize
from civ2.native_events import classify_information

BODY=['Remember, Sire, that by the terms of our',
      'recently-signed peace treaty with the TEST nation,',
      'we must immediately withdraw all of our',
      'military units from the vicinity (two square',
      'radius) of TEST Madrid and all other TEST nation cities.']
SOURCE=dict(tag='TERMS',title='Foreign Minister',width=320,options=[],buttons=[],listbox=False,
    body='Remember, Sire, that by the terms of our recently-signed peace treaty with the %STRING2, '
         'we must immediately withdraw all of our military units from the vicinity (two square radius) '
         'of %STRING1 and all other %STRING3 cities.')


def row(text,x,y,w):
    return dict(text=text,bounds=[x,y,w,16],center=[x+w//2,y+8],confidence=1,provenance=[{'preprocessing':'TEST original'}])


def fixture():
    return dict(width=640,height=480,sha256='a'*64,lines=[row('Foreign ifinister',270,166,102),
        *[row(text,196,190+i*20,306) for i,text in enumerate(BODY)],row('OK',308,300,24)])


class TreatyReminderTests(unittest.TestCase):
    def test_complete_terms_only_acknowledge_information(self):
        o=fixture();r=classify_information(o,[SOURCE])
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'TERMS')
        self.assertFalse(r['requires_model']);self.assertEqual(r['mechanical_action'],'acknowledge_information')
        self.assertEqual([x['text'] for x in r['options']],['OK'])
        for mode in ('missing','radius','choices','extra_control','other_title'):
            bad=deepcopy(o);source=deepcopy(SOURCE)
            if mode=='missing':bad['lines'].pop(3)
            elif mode=='radius':bad['lines'][4]['text']=bad['lines'][4]['text'].replace('two','three')
            elif mode=='choices':source['options']=['Withdraw','Break treaty']
            elif mode=='extra_control':bad['lines'].append(row('Cancel',370,300,40))
            else:bad['lines'][0]['text']='Unknown Minister'
            with self.subTest(mode=mode):self.assertFalse(classify_information(bad,[source])['supported'])

    def test_recovery_requires_agreement_unchanged_nation_and_complete_context(self):
        for mode in ('valid','nation','disagreement','weak','context'):
            o=fixture();rows=o['lines'];old=rows[2];old['text']=old['text'].replace('treaty','freaty')
            a=deepcopy(old);a['text']=a['text'].replace('freaty','treaty');b=deepcopy(a)
            if mode=='nation':a['text']=b['text']=a['text'].replace('TEST nation','OTHER nation')
            elif mode=='disagreement':b['text']=old['text']
            elif mode=='weak':b['confidence']=.5
            elif mode=='context':rows[4]['text']=rows[4]['text'].replace('two','three')
            before=deepcopy(rows)
            with self.subTest(mode=mode),patch('civ2.observe._crop_text',side_effect=[[a],[b]]):
                _recover_treaty_reminder(Image.new('RGB',(640,480)),rows,None,None,{})
                if mode=='valid':self.assertEqual(rows[2]['text'],BODY[1]);self.assertEqual(len(rows[2]['provenance']),3)
                else:self.assertEqual(rows,before)

    def test_actual_reminder_preserves_every_observed_withdrawal_term(self):
        from civ2.run import game_text,labels_text
        from civ2.dialogs import classify_dialog,dialog_resources
        from civ2.evidence import canonical
        import hashlib
        p=Path('runs/attempt-011/screens/ui-0001245.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original frame absent')
        data=p.read_bytes();o=recognize(p);d=classify_dialog(o,game_text=game_text(),labels_text=labels_text())
        self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],'TERMS')
        self.assertIn('two square',d['visible_text']);self.assertIn('Madrid',d['visible_text'])
        self.assertIn('Spanish',d['visible_text']);self.assertEqual([x['text'] for x in d['options']],['OK'])
        self.assertEqual(p.read_bytes(),data)
        source=next(r for r in dialog_resources(game_text()) if r['tag']=='TERMS')
        self.assertEqual(source,SOURCE)
        self.assertEqual(hashlib.sha256(canonical(source)).hexdigest(),'bad07103f15cd007440f30b75184642d501936e7e5b8f100e80d675a77365ea5')


if __name__=='__main__':unittest.main()
