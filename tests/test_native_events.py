"""Synthetic TEST events exercise complete-body and foreground boundaries."""
import copy
from pathlib import Path
import unittest
from zipfile import ZipFile

from civ2.native_events import classify_information


def row(text, y=150, x=320, width=220):
    return dict(text=text, bounds=[x-width//2, y-8, width, 16], center=[x, y], confidence=1.)


def observation(*lines):
    return dict(width=640, height=480, sha256='a'*64, lines=list(lines))


def resource(tag='DISORDER', title='Domestic Advisor', body='TEST disorder in %STRING0. Citizens protest!'):
    return dict(tag=tag, title=title, body=body, width=320, options=[], buttons=[], listbox=False)


def notice(*body, title='Domestic Advisor'):
    return observation(row(title, y=90), *(row(text, y=130+i*22) for i, text in enumerate(body)),
                       row('OK', y=240, width=25))


class NativeEventTests(unittest.TestCase):
    def test_complete_wrapped_original_template_yields_only_observed_ok(self):
        source = resource()
        screen = notice('TEST disorder in TEST Rome.', 'Citizens protest!')
        result = classify_information(screen, [source])
        self.assertTrue(result['supported'], result)
        self.assertEqual(result['kind'], 'information')
        self.assertEqual(result['mechanical_action'], 'acknowledge_information')
        self.assertEqual(result['resource_tag'], 'DISORDER')
        self.assertEqual(result['options'][0]['center'], [320, 240])
        self.assertEqual(result['evidence']['body_source_lines'], [1, 2])
        self.assertEqual(result['evidence']['source_tag'], 'DISORDER')
        self.assertFalse(result['requires_model'])

    def test_title_ok_and_partial_body_do_not_authorize_enter(self):
        for screen in (notice(), notice('TEST disorder in TEST Rome.'),
                       notice('Citizens protest!'), notice('TEST disorder in TEST Rome. Citizens protest!', 'Unexpected foreground warning')):
            with self.subTest(screen=screen):
                result = classify_information(screen, [resource()])
                self.assertFalse(result['supported'])
                self.assertIsNone(result['mechanical_action'])
                self.assertEqual(result['options'], [])

    def test_strategic_choice_or_ui_template_is_excluded_even_when_only_ok_is_read(self):
        screen = notice('TEST disorder in TEST Rome. Citizens protest!')
        for changes in (dict(options=['Continue', 'Change tax rate']), dict(buttons=['OK', 'Cancel']),
                        dict(listbox=True), dict(tag='CHEAT'), dict(tag='CITYMODAL1'), dict(title='Map Editor')):
            source = resource(); source.update(changes)
            with self.subTest(changes=changes):
                self.assertFalse(classify_information(screen, [source])['supported'])
        for control in ('Cancel', 'Yes', 'No', 'Help', 'OK'):
            extra = copy.deepcopy(screen); extra['lines'].append(row(control, y=270, width=40))
            self.assertFalse(classify_information(extra, [resource()])['supported'])

    def test_cannot_borrow_background_button_or_ignore_overlapping_foreground_text(self):
        screen = notice('TEST disorder in TEST Rome. Citizens protest!')
        displaced = copy.deepcopy(screen); displaced['lines'][-1] = row('OK', x=550, y=240, width=25)
        self.assertFalse(classify_information(displaced, [resource()])['supported'])
        overlay = copy.deepcopy(screen); overlay['lines'].append(row('TEST foreground confirmation', y=190))
        self.assertFalse(classify_information(overlay, [resource()])['supported'])
        layered = copy.deepcopy(screen); layered['lines'].append(row('Military Advisor', y=300))
        self.assertFalse(classify_information(layered, [resource()])['supported'])
        uncertain = copy.deepcopy(screen)
        uncertain['ocr'] = dict(conflicts=[dict(text='No', bounds=[300, 140, 30, 14])])
        self.assertFalse(classify_information(uncertain, [resource()])['supported'])

    def test_template_and_heading_ambiguity_refused(self):
        screen = notice('TEST disorder in TEST Rome. Citizens protest!')
        alternate = resource(tag='RESTORED')
        self.assertFalse(classify_information(screen, [resource(), alternate])['supported'])
        screen['lines'].append(row('Domestic Advisor', y=50))
        self.assertFalse(classify_information(screen, [resource()])['supported'])

    def test_repeated_placeholder_must_identify_same_visible_item(self):
        source = resource(tag='INHOCK', body='%STRING0 cannot maintain %STRING1. %STRING1 sold for %NUMBER0 TEST gold.')
        good = notice('TEST Rome cannot maintain TEST Granary.', 'TEST Granary sold for 40 TEST gold.')
        bad = notice('TEST Rome cannot maintain TEST Granary.', 'TEST Barracks sold for 40 TEST gold.')
        self.assertTrue(classify_information(good, [source])['supported'])
        self.assertFalse(classify_information(bad, [source])['supported'])

    def test_completion_template_needs_finite_original_verb_values(self):
        source = resource(tag='BUILT', body='%STRING0 %STRING3 %STRING1.')
        screen = notice('TEST Rome completes TEST Granary.')
        self.assertFalse(classify_information(screen, [source])['supported'])
        values = {'BUILT': {'STRING3': ['completes', 'builds']}}
        self.assertTrue(classify_information(screen, [source], placeholder_values=values)['supported'])
        self.assertFalse(classify_information(notice('TEST Rome chooses TEST Granary.'), [source], placeholder_values=values)['supported'])
        self.assertFalse(classify_information(notice('Shall TEST Rome complete TEST Granary?'), [source], placeholder_values=values)['supported'])

    def test_unmeasured_font_aliases_and_low_confidence_are_not_semantic_matches(self):
        screen = notice('TEST disorder in TEST Rome. Citizens protest!')
        screen['lines'][0]['text'] = 'Domestic Adwisor'
        self.assertFalse(classify_information(screen, [resource()])['supported'])
        screen['lines'][0]['text'] = 'Domestic Advisor'; screen['lines'][1]['confidence'] = .5
        self.assertFalse(classify_information(screen, [resource()])['supported'])

    def test_malformed_evidence_never_exposes_action(self):
        screen = notice('TEST disorder in TEST Rome. Citizens protest!')
        for changes in (dict(sha256='invalid'), dict(width=True), dict(lines='invalid')):
            bad = dict(screen, **changes)
            self.assertFalse(classify_information(bad, [resource()])['supported'])
        for value in (float('nan'), True, -1):
            bad = copy.deepcopy(screen); bad['lines'][1]['confidence'] = value
            self.assertFalse(classify_information(bad, [resource()])['supported'])

    def test_adjacent_city_rejection_preserves_exact_body_and_observed_heading(self):
        source=resource(tag='ADJACENTCITY',title='Civ Rules: Cities',
                        body='Cities cannot be built in adjacent squares.')
        for title in ('Civ Rules: Cities','Civ Rules: Cines'):
            with self.subTest(title=title):
                screen=notice('Cities cannot be built in adjacent squares.',title=title)
                result=classify_information(screen,[source])
                self.assertTrue(result['supported'],result)
                self.assertEqual(result['kind'],'rule_rejection')
                self.assertEqual(result['mechanical_action'],'acknowledge_information')
                self.assertFalse(result['requires_model'])
                self.assertEqual(result['title'],title)
                self.assertEqual(result['native_rejection']['body'],source['body'])
                self.assertEqual(result['native_rejection']['tag'],'ADJACENTCITY')
                self.assertEqual(result['native_rejection']['observation_sha256'],screen['sha256'])
                self.assertEqual(result['evidence']['observed_title'],title)
                self.assertEqual([o['text'] for o in result['options']],['OK'])

    def test_rule_alias_cannot_accept_other_rejection_or_arbitrary_body(self):
        source=resource(tag='ADJACENTCITY',title='Civ Rules: Cities',
                        body='Cities cannot be built in adjacent squares.')
        for body in ('Cities cannot be built at sea.', 'Cities cannot be built in adjacent',
                     'Cities cannot be built in adjacent squares. Really disband?',
                     'TEST arbitrary notice'):
            self.assertFalse(classify_information(notice(body,title='Civ Rules: Cines'),[source])['supported'])
        forged=copy.deepcopy(source); forged['body']='TEST arbitrary notice'
        self.assertFalse(classify_information(notice(forged['body'],title=source['title']),[forged])['supported'])
        for tag in ('CITYATSEA','NOADJACENTCITIES'):
            forged=copy.deepcopy(source); forged['tag']=tag
            self.assertFalse(classify_information(notice(source['body'],title=source['title']),[forged])['supported'])

    def test_rule_rejection_rejects_extra_control_or_unaligned_ok(self):
        source=resource(tag='ADJACENTCITY',title='Civ Rules: Cities',
                        body='Cities cannot be built in adjacent squares.')
        screen=notice(source['body'],title='Civ Rules: Cines')
        screen['lines'].append(row('Cancel',y=270,width=40))
        self.assertFalse(classify_information(screen,[source])['supported'])
        screen=notice(source['body'],title='Civ Rules: Cines')
        screen['lines'][-1]=row('OK',x=520,y=240,width=25)
        self.assertFalse(classify_information(screen,[source])['supported'])

    def test_advance_notice_requires_complete_original_discovery_body(self):
        source=resource(tag='CIVADVANCE',title='Civilization Advance',
                        body='%STRING0 %STRING1 discover the secret of %STRING2.')
        for title in ('Civilization Advance','Ciadization Advance'):
            screen=notice('Roman wise men discover the secret of','Alphabet.',title=title)
            result=classify_information(screen,[source])
            self.assertTrue(result['supported'],result)
            self.assertEqual(result['kind'],'information')
            self.assertNotIn('native_rejection',result)
            self.assertEqual(result['evidence']['observed_body'],'Roman wise men discover the secret of\nAlphabet.')
            self.assertEqual(result['title'],title)
            for body in ('Roman wise men discover the secret of', 'Alphabet.',
                         'Roman wise men select the secret of Alphabet.',
                         'Roman wise men discover the secret of Alphabet. Really continue?'):
                self.assertFalse(classify_information(notice(body,title=title),[source])['supported'])

    def test_original_notice_integration_keeps_rejection_distinct(self):
        from civ2.dialogs import classify_dialog
        text='@ADJACENTCITY\n@title=Civ Rules: Cities\nCities cannot be built in adjacent\nsquares.\n\n@CIVADVANCE\n@title=Civilization Advance\n@width=320\n%STRING0 %STRING1 discover the secret of %STRING2.\n'
        screen=notice('Cities cannot be built in adjacent squares.',title='Civ Rules: Cines')
        result=classify_dialog(screen,game_text=text)
        self.assertEqual(result['kind'],'rule_rejection')
        self.assertTrue(result['supported'])
        self.assertEqual(result['native_rejection']['body'],'Cities cannot be built in adjacent squares.')
        advance=notice('Roman wise men discover the secret of','Alphabet.',title='Ciadization Advance')
        result=classify_dialog(advance,game_text=text)
        self.assertTrue(result['supported'])
        self.assertEqual(result['resource_tag'],'CIVADVANCE')
        self.assertFalse(result['requires_model'])

    def test_optional_downloaded_original_disorder_support_and_government_templates(self):
        from civ2.dialogs import dialog_resources
        bundle = Path(__file__).resolve().parents[1]/'engine/game/civ2-win31.zip'
        if not bundle.exists():
            self.skipTest('Original private runtime bundle unavailable')
        with ZipFile(bundle) as archive:
            resources = dialog_resources(archive.read('civ2/GAME.TXT').decode('cp1252'))
        screens = [
            ('DISORDER', notice('Civil Disorder in TEST Rome.', 'Mayor flees in panic!')),
            ('SUPPORT', notice("TEST Rome can't support TEST Settlers.", 'Unit disbanded.', title='Military Advisor')),
            ('NEWGOVT', notice('TEST Caesar proclaimed TEST Consul', 'of new TEST Roman TEST Republic!', title='Newspaper')),
        ]
        for tag, screen in screens:
            with self.subTest(tag=tag):
                result = classify_information(screen, resources)
                self.assertTrue(result['supported'], result)
                self.assertEqual(result['resource_tag'], tag)


if __name__ == '__main__':
    unittest.main()
