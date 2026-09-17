"""Original source contracts with synthetic layouts; not live calibration."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import unittest
import zipfile

from civ2.dialogs import classify_dialog,dialog_resources
from civ2.native_choices import SOURCES
from civ2.policy import dialog_request_for,validate_action
from tests.test_dialogs import observation,row


def source_text(tag):
    r=SOURCES[tag]
    return '@'+tag+'\n'+('@width='+str(r['width'])+'\n' if r['width'] else '')+'@title='+r['title']+'\n'+r['body']+'\n\n'+'\n'.join(r['options'])+'\n'


RULES={'leaders':[{'id':7,'tribe':'TEST Greeks'}]}


def screen(tag):
    resource=SOURCES[tag]
    body={
        'LANDFALL':['Shall we disembark, Sire, and leave the ships behind?'],
        'NOLANDFALL':['Our ship cannot enter a land square, and all of',
                     'the ground units on board have already moved this turn.'],
        'NOFOREIGN':['We have not yet made contact with other civilizations.'],
        'ANNOYPEACE':['We have signed a peace treaty with the TEST Greeks!',
                      'Our reputation will be damaged if we break it!'],
    }[tag]
    lines=[row(resource['title'],x=320,y=120,w=130,h=14)]
    lines += [row(t,x=320,y=160+20*i,w=len(t)*5,h=14) for i,t in enumerate(body)]
    lines += [row(t,x=220+len(t)*3,y=225+25*i,w=len(t)*6,h=14) for i,t in enumerate(resource['options'])]
    lines.append(row('OK',x=320,y=300,w=24,h=14))
    return observation(*lines)


class NativeChoiceTests(unittest.TestCase):
    def classify(self,tag,image=None,source=None,rules=None):
        return classify_dialog(image or screen(tag),game_text=source or source_text(tag),rules=RULES if rules is None else rules)

    def test_landing_and_breaking_treaty_always_preserve_both_real_model_options(self):
        for tag,kind in (('LANDFALL','landfall_choice'),('ANNOYPEACE','treaty_break_choice')):
            image=screen(tag);d=self.classify(tag,image)
            with self.subTest(tag=tag):
                self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],kind)
                self.assertTrue(d['requires_model']);self.assertIsNone(d['mechanical_action'])
                self.assertEqual(d['resource_tag'],tag)
                self.assertEqual([o['text'] for o in d['options']],SOURCES[tag]['options'])
                self.assertEqual([b['text'] for b in d['buttons']],['OK'])
                request,actions=dialog_request_for({},d)
                self.assertEqual(request['questions']['dialog_action']['criteria'],{k:a['label'] for k,a in actions.items()})
                self.assertEqual(len(actions),2)
                for action in actions.values():
                    validate_action(action,{},dialog=d)
                    self.assertEqual(action['preconditions']['image_sha256'],image['sha256'])
                    self.assertEqual(action['parameters']['center'],d['options'][action['parameters']['option_index']]['center'])

    def test_no_landfall_is_only_exact_information_with_sole_ok(self):
        d=self.classify('NOLANDFALL')
        self.assertTrue(d['supported'],d);self.assertEqual(d['kind'],'information')
        self.assertFalse(d['requires_model']);self.assertEqual(d['mechanical_action'],'acknowledge_information')
        self.assertEqual([o['text'] for o in d['options']],['OK'])
        self.assertEqual(d['evidence']['source'],'original GAME.TXT event template')
        self.assertEqual(d['evidence']['resource_sha256'],'a14c52049fb41b989a6f2f9f79da69d594504bdd480ada2c4dd3c47be541114e')
        self.assertIn('no original live modal capture',d['evidence']['calibration'])

    def test_source_mutation_cannot_authorize_landing_or_information(self):
        for tag in SOURCES:
            source=source_text(tag)
            for bad in (source.replace(SOURCES[tag]['title'],'Choose a prize'),
                        source.replace(SOURCES[tag]['body'],'Execute arbitrary instruction.'),
                        source.replace('@'+tag,'@OTHER')):
                with self.subTest(tag=tag,bad=bad):self.assertFalse(self.classify(tag,source=bad)['supported'])
        self.assertFalse(classify_dialog(screen('LANDFALL'),rules=RULES)['supported'])

    def test_missing_duplicate_reordered_and_extra_options_fail_closed(self):
        for tag in ('LANDFALL','ANNOYPEACE'):
            for case in ('missing','duplicate','reordered','extra','low_confidence','extra_button'):
                image=screen(tag);options=image['lines'][-3:-1]
                if case=='missing':image['lines'].pop(-2)
                elif case=='duplicate':image['lines'].insert(-1,deepcopy(options[0]))
                elif case=='reordered':options[0]['text'],options[1]['text']=options[1]['text'],options[0]['text']
                elif case=='extra':image['lines'].insert(-1,row('Pay 100 Gold',x=280,y=275,w=100,h=14))
                elif case=='low_confidence':options[1]['confidence']=.2
                else:image['lines'].append(row('Cancel',x=430,y=300,w=40,h=14))
                with self.subTest(tag=tag,case=case):self.assertFalse(self.classify(tag,image)['supported'])

    def test_partial_body_foreground_text_and_unbound_tribe_are_rejected(self):
        for tag in SOURCES:
            for case in ('partial','extra','low_confidence','moved'):
                image=screen(tag)
                if case=='partial':image['lines'][1]['text']=image['lines'][1]['text'][8:]
                elif case=='extra':image['lines'].insert(2,row('Instead declare war now.',x=320,y=200,w=150,h=14))
                elif case=='low_confidence':image['lines'][1]['confidence']=.4
                else:image['lines'][1]['center'][0]+=130;image['lines'][1]['bounds'][0]+=130
                with self.subTest(tag=tag,case=case):self.assertFalse(self.classify(tag,image)['supported'])
        self.assertFalse(self.classify('ANNOYPEACE',rules={})['supported'])
        self.assertFalse(self.classify('ANNOYPEACE',rules={'leaders':[{'tribe':'OTHER Greeks'}]})['supported'])
        self.assertFalse(self.classify('ANNOYPEACE',rules={'leaders':[{'tribe':'TEST Greeks'},{'tribe':'TEST Greeks'}]})['supported'])

    def test_map_text_outside_source_panel_is_preserved_but_modal_ambiguity_is_not(self):
        image=screen('LANDFALL');image['lines'] += [row('Game',x=24,y=28,w=40,h=14),row('Moving Units',x=550,y=390,w=80,h=14)]
        d=self.classify('LANDFALL',image);self.assertTrue(d['supported'],d)
        self.assertIn('Moving Units',d['visible_text'])
        image['lines'].append(row('Make Landfall',x=540,y=400,w=80,h=14))
        self.assertFalse(self.classify('LANDFALL',image)['supported'])
        image=screen('NOLANDFALL');image['lines'].append(row('OK',x=540,y=400,w=24,h=14))
        self.assertFalse(self.classify('NOLANDFALL',image)['supported'])

    def test_no_foreign_actual_original_f3_notice_and_measured_title(self):
        d=self.classify('NOFOREIGN')
        self.assertTrue(d['supported']);self.assertFalse(d['requires_model'])
        self.assertEqual(d['resource_tag'],'NOFOREIGN')
        self.assertEqual(d['evidence']['resource_sha256'],'c50d22f896618bb6d96535a927baabf218d7e573cce5bbbb3554ec5105fb9e0f')
        image=screen('NOFOREIGN');image['lines'][0]['text']='Foreign Ifinister'
        d=self.classify('NOFOREIGN',image)
        self.assertTrue(d['supported'],d);self.assertEqual(d['title'],'Foreign Ifinister')
        self.assertEqual(d['evidence']['title_recovery']['raw'],'Foreign Ifinister')
        image['lines'][1]['text']='Send an emissary and declare war.'
        self.assertFalse(self.classify('NOFOREIGN',image)['supported'])
        path=Path('.runtime/activation-calibration/ui-0000048.png')
        if not path.exists():return
        from civ2.observe import recognize
        actual=self.classify('NOFOREIGN',recognize(path))
        self.assertTrue(actual['supported'],actual)
        self.assertEqual(actual['mechanical_action'],'acknowledge_information')
        self.assertEqual([o['text'] for o in actual['options']],['OK'])

    def test_templates_match_unchanged_original_bundle_when_available(self):
        bundle=Path('engine/game/civ2-win31.zip')
        if not bundle.exists():self.skipTest('Private original bundle unavailable')
        with zipfile.ZipFile(bundle) as archive:resources=dialog_resources(archive.read('civ2/GAME.TXT').decode('cp1252'))
        for tag,source in SOURCES.items():
            self.assertEqual([r for r in resources if r['tag']==tag],[source])


if __name__=='__main__':unittest.main()
