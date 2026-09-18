"""Complete original informational spaceship notices; not victory evidence."""
from copy import deepcopy
import hashlib
from pathlib import Path
import unittest
from zipfile import ZipFile
from civ2.dialogs import classify_dialog,dialog_resources
from civ2.evidence import canonical
from civ2.native_events import classify_information,SPACE_NOTICE_RESOURCES
from tests.test_native_events import notice,row


DATA={
    'BADSPACE':('Excess Spaceship Parts','%STRING0 is building %STRING1, but no more are required.',
                ['TEST Rome is building SS Component, but','no more are required.']),
    'SPACERACE':('Science Advisor','%STRING0 build space ship!',['TEST Romans build space ship!']),
    'LAUNCHED':('Science Advisor','%STRING0 LAUNCH space ship! Estimate arrival in %NUMBER0.',
                ['TEST Romans LAUNCH space ship!','Estimate arrival in 2020.']),
    'NOFURTHER':('Science Advisor','No further %STRING0 required.',['No further Propulsion required.']),
    'SPACERETURNS':('Science Advisor','%STRING0 spaceship returns to earth.',['TEST Romans spaceship returns to earth.']),
    'SPACEDESTROYED':('Science Advisor','%STRING0 spaceship destroyed.',['TEST Romans spaceship destroyed.']),
    'NOSPACESHIPS':('Space ships','The space race has not yet begun!',['The space race has not yet begun!']),
}
SOURCES={tag:dict(tag=tag,title=title,body=body,width=320,options=[],buttons=[],listbox=False)
         for tag,(title,body,_) in DATA.items()}
GAME=''.join(f"@{s['tag']}\n@width=320\n@title={s['title']}\n{s['body']}\n\n" for s in SOURCES.values())


class SpaceNotices(unittest.TestCase):
    def test_all_seven_exact_notices_acknowledge_only_the_actual_sole_ok(self):
        for tag,(title,_,body) in DATA.items():
            with self.subTest(tag=tag):
                o=notice(*body,title=title);before=deepcopy(o);d=classify_dialog(o,game_text=GAME)
                self.assertTrue(d['supported'],d);self.assertEqual(d['resource_tag'],tag)
                self.assertEqual(d['kind'],'information');self.assertFalse(d['requires_model'])
                self.assertEqual(d['mechanical_action'],'acknowledge_information')
                self.assertEqual([r['text'] for r in d['options']],['OK']);self.assertIsNone(d['outcome'])
                self.assertEqual(d['evidence']['observed_body'],'\n'.join(body));self.assertEqual(o,before)

    def test_partial_body_extra_choice_source_tamper_and_unreadable_control_refuse(self):
        for tag,(title,_,body) in DATA.items():
            for mode in ('body','punctuation','choice','second_ok','weak','geometry','source','source_options'):
                o=notice(*body,title=title);s=deepcopy(SOURCES[tag])
                if mode=='body':o['lines'].pop(1)
                elif mode=='punctuation':o['lines'][-2]['text']=o['lines'][-2]['text'][:-1]
                elif mode=='choice':o['lines'].insert(-1,row('Launch CONFIRMED!',y=195))
                elif mode=='second_ok':o['lines'].append(row('OK',y=275,width=25))
                elif mode=='weak':o['lines'][-1]['confidence']=.7
                elif mode=='geometry':o['lines'][-1]=row('OK',x=530,y=240,width=25)
                elif mode=='source':s['body']=s['body'].replace('space','altered space').replace('required','approved')
                else:s['options']=['Launch CONFIRMED!']
                with self.subTest(tag=tag,mode=mode):self.assertFalse(classify_information(o,[s])['supported'])

    def test_arrival_remains_unverified_and_never_an_information_acknowledgement(self):
        o=notice('TEST Romans spaceship arrives on Alpha Centauri!',title='Science Advisor')
        source=GAME+'\n@EAGLEHASLANDED\n@width=320\n@title=Science Advisor\n%STRING0 spaceship arrives on Alpha Centauri!\n'
        d=classify_dialog(o,game_text=source)
        self.assertFalse(d['supported']);self.assertEqual(d['kind'],'space_arrival');self.assertIsNone(d['mechanical_action'])

    def test_original_source_and_verifier_share_all_exact_pins(self):
        from civ2.verify import PUBLIC_NOTICE_RESOURCES
        self.assertEqual(dialog_resources(GAME),list(SOURCES.values()))
        for tag,s in SOURCES.items():
            digest=hashlib.sha256(canonical(s)).hexdigest()
            self.assertEqual(SPACE_NOTICE_RESOURCES[tag],digest);self.assertEqual(PUBLIC_NOTICE_RESOURCES[tag],digest)
        path=Path('engine/game/civ2-win31.zip')
        if not path.exists():self.skipTest('Private original source unavailable')
        with ZipFile(path) as z:original=dialog_resources(z.read('civ2/GAME.TXT').decode('cp1252'))
        for tag,s in SOURCES.items():self.assertEqual([r for r in original if r['tag']==tag],[s])


if __name__=='__main__':unittest.main()
