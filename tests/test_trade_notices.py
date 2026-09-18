"""Source/synthetic coverage only; no live caravan calibration is claimed."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from zipfile import ZipFile
from civ2.dialogs import classify_dialog,dialog_resources
from civ2.evidence import canonical
from civ2.native_events import classify_information,TRADE_NOTICE_RESOURCES
from tests.test_native_events import notice,row


def source(tag,title,body):
    return dict(tag=tag,title=title,body=body,width=420,options=[],buttons=[],listbox=False)


SOURCES={
    'CARAVAN':source('CARAVAN','Trade Route','%STRING0 caravan from %STRING1 arrives in %STRING2. Trade route established.  Revenue: %NUMBER0 gold.'),
    'FOODCARAVAN':source('FOODCARAVAN','Trade Route','Food caravan from %STRING1 arrives in %STRING2. Citizens plan feast in celebration.'),
    'CARAVANHOME':source('CARAVANHOME','Civ Rules: Trade units','You cannot change the home city of a trade unit.'),
    'CARAVANOTHER':source('CARAVANOTHER','Trade Route','%STRING0 %STRING1 caravan from %STRING2 arrives in %STRING3.  %STRING1-%STRING4 trade route established.'),
}
BODIES={
    'CARAVAN':['Silk caravan from TEST Rome arrives in TEST Athens.','Trade route established. Revenue: 25 gold.'],
    'FOODCARAVAN':['Food caravan from TEST Rome arrives in TEST Antium.','Citizens plan feast in celebration.'],
    'CARAVANHOME':['You cannot change the home city of a trade unit.'],
    'CARAVANOTHER':['TEST Roman Silk caravan from TEST Rome arrives in TEST Athens.','Silk-Wine trade route established.'],
}
GAME=''.join(f"@{s['tag']}\n@width=420\n@title={s['title']}\n{s['body']}\n\n"for s in SOURCES.values())


class TradeNotices(unittest.TestCase):
    def test_complete_original_information_has_only_actual_ok_and_no_inferred_effect(self):
        self.assertEqual(dialog_resources(GAME),list(SOURCES.values()))
        for tag,body in BODIES.items():
            o=notice(*body,title=SOURCES[tag]['title']);before=deepcopy(o)
            d=classify_dialog(o,game_text=GAME)
            self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],tag)
            self.assertEqual(d['kind'],'information');self.assertFalse(d['requires_model'])
            self.assertEqual(d['mechanical_action'],'acknowledge_information')
            self.assertEqual([x['text']for x in d['options']],['OK'])
            self.assertEqual(d['evidence']['observed_body'],'\n'.join(body))
            self.assertIsNone(d['outcome']);self.assertEqual(o,before)

    def test_source_terms_controls_geometry_and_complete_punctuation_are_required(self):
        for tag,body in BODIES.items():
            for mode in ('missing','dot','extra','choice','second_ok','low','displaced','altered_source'):
                o=notice(*body,title=SOURCES[tag]['title']);s=deepcopy(SOURCES[tag])
                if mode=='missing':o['lines'].pop(1)
                elif mode=='dot':o['lines'][-2]['text']=o['lines'][-2]['text'][:-1]
                elif mode=='extra':o['lines'].insert(-1,row('Pay 25 gold to continue.',y=195))
                elif mode=='choice':o['lines'].insert(-1,row('Establish route.',y=195))
                elif mode=='second_ok':o['lines'].append(row('OK',y=275,width=25))
                elif mode=='low':o['lines'][1]['confidence']=.7
                elif mode=='displaced':o['lines'][-1]=row('OK',x=530,y=240,width=25)
                else:s['width']=440
                with self.subTest(tag=tag,mode=mode):self.assertFalse(classify_information(o,[s])['supported'])

    def test_repeated_commodity_and_arrival_revenue_cannot_be_changed_or_omitted(self):
        variants=[('CARAVANOTHER',['TEST Roman Silk caravan from TEST Rome arrives in TEST Athens.','Wine-Wine trade route established.']),
                  ('CARAVAN',['Silk caravan from TEST Rome arrives in TEST Athens.','Trade route established.']),
                  ('FOODCARAVAN',['Food caravan from TEST Rome arrives in TEST Antium.','Revenue: 25 gold.']),
                  ('CARAVANHOME',['You can change the home city of a trade unit.'])]
        for tag,body in variants:self.assertFalse(classify_information(notice(*body,title=SOURCES[tag]['title']),[SOURCES[tag]])['supported'])

    def test_original_templates_and_verifier_share_exact_pins(self):
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        for tag,s in SOURCES.items():
            digest=hashlib.sha256(canonical(s)).hexdigest()
            self.assertEqual(TRADE_NOTICE_RESOURCES[tag],digest)
            self.assertEqual(PUBLIC_NOTICE_RESOURCES[tag],digest)
        p=Path('engine/game/civ2-win31.zip')
        if not p.exists():self.skipTest('Private original source unavailable')
        with ZipFile(p)as z:original=dialog_resources(z.read('civ2/GAME.TXT').decode('cp1252'))
        for tag,s in SOURCES.items():self.assertEqual([r for r in original if r['tag']==tag],[s])


if __name__=='__main__':unittest.main()
