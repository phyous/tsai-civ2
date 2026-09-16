"""Clearly synthetic TEST OCR fixtures, plus optional private-image calibration."""
import copy
from pathlib import Path
import unittest

from civ2.dialogs import DialogObservationError,classify_dialog,dialog_resources


def row(text,x=320,y=150,w=240,h=16,confidence=1.):
    return dict(text=text,center=[x,y],bounds=[x-w//2,y-h//2,w,h],confidence=confidence)


def observation(*rows):
    return dict(width=640,height=480,sha256='a'*64,lines=list(rows),text='\n'.join(r['text'] for r in rows))


RULES=dict(advances=[dict(name='TEST Alphabet'),dict(name='TEST Bronze Working')],
           units=[dict(name='TEST Warriors'),dict(name='TEST Phalanx')],
           improvements=[dict(name='TEST Granary'),dict(name='TEST Pyramids')])
DIPLOMACY='''@TESTOFFER
@title=%STRING0 Emissary
@width=320
"We offer %STRING0 for %NUMBER0 gold."

Never mind.
Pay %NUMBER0 gold.
'''


def list_dialog(kind='research'):
    if kind=='research':
        title='What discovery shall our TEST scientists pursue?'
        items=['TEST Alphabet','TEST Bronze Working']
        extra='Goal'
    else:
        title='What shall we build in TEST Rome?'
        items=['TEST Warriors (3 Turns)','TEST Granary (8 Turns)']
        extra='Auto'
    return observation(row(title,y=90,w=400),row(items[0],x=230,y=150,w=170),
                       row(items[1],x=400,y=175,w=190),row('OK',x=230,y=250,w=25),
                       row('Cancel',x=310,y=250,w=50),row('Help',x=390,y=250,w=30),row(extra,x=440,y=250,w=32))


def native_map():
    """Synthetic TEST geometry matching the observed original 640x480 map panes."""
    return observation(row("Sid Meier's Civilization II",x=320,y=10,w=170,h=12),
        row('Game Kingdom View Orders Advisors World Cheat Civilopedia',x=253,y=27,w=490,h=12),
        row('Roman Map',x=231,y=53,w=78),row('World',x=552,y=53,w=44),
        row('10,000 People',x=513,y=210,w=74,h=12),row('4000 B.C.',x=501,y=222,w=50,h=12),
        row('0 Gold 4.0.6',x=508,y=234,w=68,h=12),row('Moving Units',x=550,y=259,w=72,h=14),
        row('(Plains)',x=497,y=276,w=46,h=12),row('No Orders',x=554,y=304,w=56,h=12),
        row('Settlers',x=548,y=316,w=44,h=12))


ROMAN_STATE=dict(player=dict(id=1,tribe_id=0,tribe='Romans'),cities=[],known_cities=[])


class DialogTests(unittest.TestCase):
    def test_tax_and_luxury_options_are_exact_observed_percentages(self):
        for title,kind in [('Select New Tax Rate','tax_rate'),('Select New Luxury Rate','luxury_rate')]:
            o=observation(row(title,y=80),row('Government Type: Despotism',y=120),row('Maximum Rate: 60%',y=145),
                          row('0%',y=180,w=24),row('20%',y=205,w=30),row('60%',y=230,w=30),row('OK',y=280,w=25))
            r=classify_dialog(o)
            self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],kind)
            self.assertEqual([c['text'] for c in r['options']],['0%','20%','60%'])
            self.assertTrue(r['requires_model']);self.assertEqual(r['maximum_rate'],60)
            o['lines'].insert(-1,row('80%',y=250,w=30))
            self.assertFalse(classify_dialog(o)['supported'])

    def test_rate_slider_tick_or_unparsed_combined_label_not_guessed_as_option(self):
        o=observation(row('Select New Tax Rate',y=80),row('Government Type: Despotism',y=120),row('Maximum Rate: 60%',y=145),
                      row('0% 20% 40% 60%',y=200),row('OK',y=280,w=25))
        self.assertFalse(classify_dialog(o)['supported'])

    def test_revolution_confirmation_requires_jev_and_both_choices(self):
        o=observation(row('Revolution',y=80),row('Do we want a revolution to overthrow',y=130,w=230),row('the TEST Roman Despotism?',y=150),
                      row('Yes',y=190,w=30),row('No',y=215,w=20),row('OK',y=260,w=25))
        r=classify_dialog(o)
        self.assertTrue(r['supported'],r);self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertEqual([c['text'] for c in r['options']],['Yes','No'])
        o['lines']=[r for r in o['lines'] if r['text']!='No']
        self.assertFalse(classify_dialog(o)['supported'])

    def test_post_revolution_information_does_not_reissue_revolution(self):
        o=observation(row('Revolution!',y=80),row('The TEST Romans are revolting!',y=140),row('Citizens demand new government.',y=165),row('OK',y=240,w=25))
        r=classify_dialog(o)
        self.assertEqual(r['kind'],'information');self.assertEqual(r['mechanical_action'],'acknowledge_information')

    def test_city_locator_requires_known_owned_labels_and_bound_external_target(self):
        o=observation(row('Where in the heck is . . .',y=80),row('TEST Rome',y=140),row('TEST Veii',y=165),
                      row('OK',x=240,y=230,w=25),row('Zoom To City',x=370,y=230,w=90))
        self.assertFalse(classify_dialog(o)['supported'])
        s=dict(cities=[dict(name='TEST Rome'),dict(name='TEST Veii')])
        r=classify_dialog(o,state=s)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'city_locator')
        self.assertFalse(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertEqual([c['text'] for c in r['options']],['TEST Rome','TEST Veii'])
        o['lines'].insert(2,row('UNKNOWN foreign city',y=190))
        self.assertFalse(classify_dialog(o,state=s)['supported'])

    def test_research_actual_options_and_auxiliary_buttons_separate(self):
        o=list_dialog();r=classify_dialog(o,rules=RULES)
        self.assertTrue(r['supported'],r)
        self.assertEqual(r['kind'],'research_choice')
        self.assertEqual([x['text'] for x in r['options']],['TEST Alphabet','TEST Bronze Working'])
        self.assertEqual([x['center'] for x in r['options']],[[230,150],[400,175]])
        self.assertEqual({x['text'] for x in r['buttons']},{'OK','Cancel','Help','Goal'})
        self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertTrue(all(x['enabled'] is None for x in r['options']))

    def test_production_preserves_displayed_suffix_and_multiple_columns(self):
        o=list_dialog('production');r=classify_dialog(o,rules=RULES)
        self.assertTrue(r['supported'],r)
        self.assertEqual(r['options'][0]['text'],'TEST Warriors (3 Turns)')
        self.assertEqual(r['options'][1]['center'],[400,175])
        self.assertNotIn('Auto',[x['text'] for x in r['options']])

    def test_no_rules_no_invented_research_list(self):
        r=classify_dialog(list_dialog())
        self.assertFalse(r['supported']);self.assertEqual(r['options'],[])

    def test_unknown_list_row_blocks_partial_options(self):
        o=list_dialog();o['lines'].insert(2,row('TEST misread Brome Wrking',y=200))
        r=classify_dialog(o,rules=RULES)
        self.assertFalse(r['supported']);self.assertEqual(r['options'],[])

    def test_duplicate_options_and_centers_rejected(self):
        o=list_dialog();o['lines'].insert(2,row('TEST Alphabet',y=200))
        self.assertFalse(classify_dialog(o,rules=RULES)['supported'])
        o=list_dialog();o['lines'][2]=row('TEST Bronze Working',x=230,y=150,w=170)
        self.assertFalse(classify_dialog(o,rules=RULES)['supported'])

    def test_missing_confirmation_and_low_confidence_fail_closed(self):
        o=list_dialog();o['lines']=[r for r in o['lines'] if r['text']!='OK']
        self.assertFalse(classify_dialog(o,rules=RULES)['supported'])
        o=list_dialog();o['lines'][1]['confidence']=.3
        self.assertFalse(classify_dialog(o,rules=RULES)['supported'])

    def test_multiple_recognized_dialog_titles_rejected(self):
        o=list_dialog();o['lines'].append(row('What shall we build in TEST Rome?',y=70))
        self.assertFalse(classify_dialog(o,rules=RULES)['supported'])

    def test_new_city_default_accept_requires_observed_nonempty_name(self):
        o=observation(row('What Shall We Name This City?',y=90),row('City Name:',x=240,y=145,w=90),
                      row('TEST Rome',x=380,y=145,w=100),row('OK',x=280,y=210,w=25),row('Cancel',x=370,y=210,w=50))
        r=classify_dialog(o)
        self.assertTrue(r['supported'],r);self.assertEqual(r['default_name'],'TEST Rome')
        self.assertEqual(r['mechanical_action'],'accept_observed_default_name')
        self.assertEqual([x['text'] for x in r['options']],['OK'])
        o['lines']=[r for r in o['lines'] if r['text']!='TEST Rome']
        self.assertFalse(classify_dialog(o)['supported'])

    def test_found_new_city_notice_is_not_name_entry(self):
        o=observation(row('Found New City',y=90),row('TEST Rome Founded: 4000 B.C.',y=140),row('OK',y=210,w=25))
        r=classify_dialog(o)
        self.assertEqual(r['kind'],'information');self.assertEqual(r['mechanical_action'],'acknowledge_information')

    def test_single_information_ok_and_confirmation_not_autoaccepted(self):
        o=observation(row('Game saved!',y=100),row('TEST Caesar of the TEST Romans',y=150),row('OK',y=220,w=25))
        self.assertEqual(classify_dialog(o)['mechanical_action'],'acknowledge_information')
        o['lines'] += [row('Yes',x=260,y=220,w=30),row('No',x=390,y=220,w=20)]
        self.assertFalse(classify_dialog(o)['supported'])

    def test_rules_notice_needs_information_only_resource(self):
        text='@TESTNOTICE\n@title=Civ Rules: TEST movement\nTEST action is unavailable.\n'
        o=observation(row('Civ Rules: TEST movement',y=90),row('TEST action is unavailable.',y=140),row('OK',y=210,w=25))
        self.assertFalse(classify_dialog(o)['supported'])
        self.assertTrue(classify_dialog(o,game_text=text)['supported'])
        text+='\nContinue anyway.\nCancel.\n'
        self.assertFalse(classify_dialog(o,game_text=text)['supported'])

    def test_diplomacy_requires_actual_matching_body_and_all_choices(self):
        o=observation(row('TEST Roman Emissary',y=90),row('"We offer TEST Writing for 100 gold."',y=135,w=350),
                      row('Never mind.',y=180),row('Pay 100 gold.',y=205),row('OK',y=250,w=25))
        r=classify_dialog(o,game_text=DIPLOMACY)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'TESTOFFER')
        self.assertEqual([x['text'] for x in r['options']],['Never mind.','Pay 100 gold.'])
        self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertFalse(classify_dialog(o)['supported'])
        o['lines']=[r for r in o['lines'] if r['text']!='Never mind.']
        self.assertFalse(classify_dialog(o,game_text=DIPLOMACY)['supported'])

    def test_quoted_choices_in_body_not_executable(self):
        o=observation(row('TEST Roman Emissary',y=90),row('We once said Pay 100 gold. during a TEST meeting.',y=140,w=400),row('OK',y=250,w=25))
        r=classify_dialog(o,game_text=DIPLOMACY)
        self.assertFalse(r['supported']);self.assertEqual(r['options'],[])

    def test_generic_game_over_is_not_victory(self):
        o=observation(row('Game Over!',y=90),row('Your final score has been computed.',y=135),
                      row("No, I'm done.",y=190),row('Yes, keep playing.',y=215))
        r=classify_dialog(o)
        self.assertEqual(r['kind'],'game_over');self.assertEqual(r['outcome'],'terminal_unspecified')
        self.assertIsNone(r['mechanical_action'])

    def test_explicit_conquest_is_only_victory_candidate_for_review(self):
        r=classify_dialog(observation(row('Your civilization has conquered the entire planet!',y=180,w=440)))
        self.assertEqual(r['kind'],'victory');self.assertEqual(r['outcome'],'victory_candidate_conquest')
        self.assertEqual(r['options'],[]);self.assertIn('review',r['reason'])

    def test_rival_centauri_arrival_and_ambiguous_spacestory_not_win(self):
        r=classify_dialog(observation(row('Science Advisor',y=90),row('TEST Greeks spaceship arrives on Alpha Centauri!',y=180,w=440),row('OK',y=250,w=25)))
        self.assertFalse(r['supported']);self.assertEqual(r['kind'],'space_arrival')
        r=classify_dialog(observation(row('Alpha Centauri',y=190),row('TEST Your name may one day be written in the annals.',y=220,w=450)))
        self.assertFalse(r['supported']);self.assertIsNone(r['outcome'])

    def test_government_choices_are_observed_not_all_possible_concepts(self):
        o=observation(row('Select Type of Government',y=90),row('Despotism',y=140),row('Monarchy',y=170),row('OK',y=220,w=25))
        r=classify_dialog(o)
        self.assertTrue(r['supported']);self.assertEqual([x['text'] for x in r['options']],['Despotism','Monarchy'])

    def test_normal_map_end_turn_and_foreground_unknown(self):
        o=native_map()
        self.assertEqual(classify_dialog(o,state=ROMAN_STATE)['kind'],'normal_map')
        o['lines'].append(row('End of Turn',x=545,y=390,w=100))
        r=classify_dialog(o,state=ROMAN_STATE);self.assertEqual(r['kind'],'end_turn');self.assertEqual(r['options'],[]);self.assertIsNone(r['mechanical_action'])
        o['lines'].append(row('OK',y=270,w=25))
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_native_map_needs_independent_panes_and_known_player_not_government_word(self):
        o=native_map();self.assertNotIn('Despotism',o['text'])
        self.assertTrue(classify_dialog(o,state=ROMAN_STATE)['supported'])
        self.assertFalse(classify_dialog(o)['supported'])
        self.assertFalse(classify_dialog(o,state=dict(player=dict(tribe_id=1,tribe='Egyptians')))['supported'])
        for marker in ('Roman Map','World','10,000 People','4000 B.C.','0 Gold 4.0.6','Moving Units'):
            cut=copy.deepcopy(o);cut['lines']=[r for r in cut['lines'] if r['text']!=marker]
            with self.subTest(marker=marker):self.assertFalse(classify_dialog(cut,state=ROMAN_STATE)['supported'])

    def test_native_map_only_uses_measured_ocr_aliases_at_original_positions(self):
        o=native_map()
        for r in o['lines']:
            r['text']={'Roman Map':'Roman Hap','World':'Workd','Moving Units':'Moving Uhits'}.get(r['text'],r['text'])
        self.assertEqual(classify_dialog(o,state=ROMAN_STATE)['kind'],'normal_map')
        world=next(r for r in o['lines'] if r['text']=='Workd');world.update(center=[320,150],bounds=[298,142,44,16])
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_native_map_low_confidence_pane_or_unit_status_refused(self):
        for marker in ('Roman Map','World','4000 B.C.','Moving Units'):
            o=native_map();next(r for r in o['lines'] if r['text']==marker)['confidence']=.5
            with self.subTest(marker=marker):self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_ocr_corrupted_saved_modal_does_not_become_background_map(self):
        o=native_map();o['lines'] += [row('Game samed!',y=203,w=82),
            row('Dictator Caesar of the Romans',y=227,w=210),row('OК',y=276,w=24)]
        r=classify_dialog(o,state=ROMAN_STATE)
        self.assertFalse(r['supported']);self.assertIn('playfield',r['reason'])

    def test_unknown_playfield_text_refused_but_observed_city_labels_allowed(self):
        o=native_map();o['lines'].append(row('TEST Rome',x=260,y=320,w=90))
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])
        s=copy.deepcopy(ROMAN_STATE);s['cities']=[dict(id=0,name='TEST Rome',x=8,y=8)]
        self.assertEqual(classify_dialog(o,state=s)['kind'],'normal_map')
        o['lines'].append(row('Please select an option',x=320,y=180,w=190))
        self.assertFalse(classify_dialog(o,state=s)['supported'])

    def test_menu_and_government_text_alone_do_not_identify_native_map(self):
        o=observation(row("Sid Meier's Civilization II",y=12),row('Game Kingdom View Orders Advisors World Civilopedia',y=30,w=530),row('4000 B.C. Despotism',x=530,y=90,w=200))
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_optional_actual_private_clean_map_and_saved_modal(self):
        from civ2.observe import recognize
        root=Path(__file__).resolve().parents[1]
        clean=root/'.runtime/campaign-01-start/ui-0000011.png'
        saved=root/'.runtime/campaign-01-start/ui-0000014.png'
        if not clean.exists() or not saved.exists() or not (root/'.runtime/ocr').exists():
            self.skipTest('private original map/modal calibration images unavailable')
        r=classify_dialog(recognize(clean),state=ROMAN_STATE)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'normal_map')
        self.assertFalse(classify_dialog(recognize(saved),state=ROMAN_STATE)['supported'])

    def test_resource_parser_separates_body_choices_and_explicit_buttons(self):
        t=dialog_resources(DIPLOMACY)[0]
        self.assertEqual(t['body'],'"We offer %STRING0 for %NUMBER0 gold."')
        self.assertEqual(t['options'],['Never mind.','Pay %NUMBER0 gold.'])

    def test_malformed_geometry_and_missing_hash_rejected(self):
        o=list_dialog();o['sha256']='bad'
        with self.assertRaises(DialogObservationError):classify_dialog(o)
        o=list_dialog();o['lines'][1]['center']=[-1,20]
        with self.assertRaises(DialogObservationError):classify_dialog(o)
        o=list_dialog();o['lines'][1]['confidence']=float('nan')
        with self.assertRaises(DialogObservationError):classify_dialog(o)

    def test_optional_actual_private_city_image(self):
        from civ2.observe import recognize
        root=Path(__file__).resolve().parents[1]
        image=root/'.runtime/rome-city-screen.png'
        if not image.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private original calibration image/OCR unavailable')
        o=recognize(image);r=classify_dialog(o)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'city_screen')
        buttons={x['text']:x for x in r['buttons']}
        self.assertEqual(buttons['Change']['center'],[595,252])
        self.assertEqual(buttons['Buy']['center'],[478,252])
        self.assertEqual(buttons['Exit']['center'],[607,459])
        self.assertTrue(all(x['text'] in o['text'] for x in r['options']))


if __name__=='__main__':unittest.main()
