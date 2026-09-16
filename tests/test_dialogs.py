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
SCIENCE='''@REPORTSCIENCE
@width=540
@title=Science Advisor Report
@listbox=12
@columns=3
@button=Info
@button=Goal
^Researching: %STRING0 (%NUMBER0 of %NUMBER1)
^Discoveries every %NUMBER2 turns.
^
^^Civilization Advances Achieved:
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
    def test_measured_research_heading_variants_require_native_controls_and_exact_peers(self):
        rrules={'advances':[{'id':0,'name':'Alphabet'},{'id':1,'name':'Currency'},{'id':2,'name':'Pottery'}]}
        o=observation(row('Whait discovery shall our wise men porsue?',y=80,w=320),
            row('Aphabet',x=250,y=120,w=70),row('Currency',x=250,y=145,w=70),row('Pottery',x=250,y=170,w=70),
            row('Help',x=220,y=260,w=30),row('Goal',x=320,y=260,w=30),row('OK',x=420,y=260,w=24))
        r=classify_dialog(o,rules=rrules)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'research_choice')
        self.assertEqual(r['title'],o['lines'][0]['text'])
        self.assertEqual(r['title_recovery']['ocr_text'],o['lines'][0]['text'])
        self.assertEqual([x['text'] for x in r['options']],['Alphabet','Currency','Pottery'])
        self.assertEqual(r['options'][0]['center'],[250,120])
        self.assertEqual(r['options'][0]['ocr_text'],'Aphabet')
        for mutate in (lambda x:x['lines'].pop(5),lambda x:x['lines'].pop(3),
                       lambda x:x['lines'][0].update(confidence=.5),
                       lambda x:x['lines'][0].update(text='Whait discovery shall our wise men purchase?'),
                       lambda x:x['lines'].insert(4,row('Unrecognized advance',x=250,y=195,w=140)),
                       lambda x:x['lines'].append(row('Cancel',x=480,y=260,w=40))):
            changed=copy.deepcopy(o);mutate(changed)
            with self.subTest(changed=changed):self.assertFalse(classify_dialog(changed,rules=rrules)['supported'])

    def test_optional_actual_research_title_and_selected_font_recovery(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-002/screens/ui-0000082.png'
        if not path.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private original research image unavailable')
        o=recognize(path);r=classify_dialog(o,rules=parse_rules(original_rules()))
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'research_choice')
        self.assertEqual([x['text'] for x in r['options']],['Alphabet','Ceremonial Burial','Currency','Horseback Riding','Masonry','Pottery','Warrior Code'])
        self.assertEqual(r['options'][0]['center'],[279,109])
        self.assertEqual(r['title_recovery']['ocr_text'],'Whait discovery shall our wise men porsue?')
        self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])

    def test_research_name_recovery_is_unique_bounded_and_keeps_observed_center(self):
        rrules={'advances':[{'id':0,'name':'Alphabet'},{'id':1,'name':'Currency'},{'id':2,'name':'Pottery'}]}
        o=observation(row('What discovery shall our wise men pursue?',y=80,w=320),
            row('Aphabet',x=200,y=120,w=70),row('Currency',x=200,y=145,w=70),row('Pottery',x=200,y=170,w=70),
            row('Help',x=220,y=260,w=30),row('Goal',x=320,y=260,w=30),row('OK',x=420,y=260,w=24))
        r=classify_dialog(o,rules=rrules)
        self.assertTrue(r['supported'],r);a=r['options'][0]
        self.assertEqual(a['text'],'Alphabet');self.assertEqual(a['ocr_text'],'Aphabet')
        self.assertEqual(a['center'],[200,120]);self.assertEqual(a['source_line'],1)
        self.assertEqual(a['name_recovery']['original_advance_id'],0)
        ambiguous=copy.deepcopy(rrules);ambiguous['advances'].append({'id':3,'name':'Aphabets'})
        self.assertFalse(classify_dialog(o,rules=ambiguous)['supported'])
        for mutate in (lambda x:x['lines'][1].update(text='Aphbet'),lambda x:x['lines'].pop(3),
                       lambda x:x['lines'].pop(5),lambda x:x['lines'][1].update(confidence=.5)):
            changed=copy.deepcopy(o);mutate(changed)
            self.assertFalse(classify_dialog(changed,rules=rrules)['supported'])

    def test_optional_actual_selected_font_alphabet_recovery(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-001/screens/ui-0000096.png'
        if not path.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private original research image unavailable')
        r=classify_dialog(recognize(path),rules=parse_rules(original_rules()))
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'research_choice')
        self.assertEqual([x['text'] for x in r['options']],['Alphabet','Ceremonial Burial','Currency','Horseback Riding','Masonry','Pottery','Warrior Code'])
        self.assertEqual(r['options'][0]['center'],[123,112])

    def test_reviewed_native_event_integration_requires_complete_body(self):
        resources='@DISORDER\n@title=Domestic Advisor\nCivil disorder in %STRING0!\n'
        o=observation(row('Domestic Advisor',y=90),row('Civil disorder in TEST Rome!',y=140,w=260),row('OK',y=220,w=24))
        r=classify_dialog(o,game_text=resources)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'DISORDER')
        self.assertEqual(r['mechanical_action'],'acknowledge_information');self.assertEqual(r['sha256'],o['sha256'])
        self.assertIn('template_sha256',r['evidence'])
        o['lines'][1]['text']='Civil disorder in TEST Rome! Change all taxes?'
        self.assertFalse(classify_dialog(o,game_text=resources)['supported'])

    def test_built_event_uses_finite_original_completion_verbs(self):
        resources='@BUILT\n@title=Domestic Advisor\n%STRING0 %STRING3 %STRING1.\n'
        o=observation(row('Domestic Advisor',y=90),row('TEST Rome completes TEST Settlers.',y=140,w=300),row('OK',y=220,w=24))
        r=classify_dialog(o,game_text=resources)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'BUILT')
        o['lines'][1]['text']='TEST Rome destroys TEST Settlers.'
        self.assertFalse(classify_dialog(o,game_text=resources)['supported'])

    def test_science_report_preserves_observed_information_and_only_acknowledges_ok(self):
        o=observation(row('Science Advisor Report',y=80),
            row('Researching: TEST Alphabet (3 of 20)',y=125,w=320),
            row('Discoveries every 10 turns.',y=150,w=250),
            row('Civilization Advances Achieved:',y=190,w=280),
            row('TEST Bronze Working',x=200,y=230,w=180),
            row('Info',x=170,y=350,w=30),row('Goal',x=320,y=350,w=30),row('OK',x=470,y=350,w=24))
        r=classify_dialog(o,rules=RULES,game_text=SCIENCE)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'science_advisor')
        self.assertEqual(r['mechanical_action'],'acknowledge_information');self.assertFalse(r['requires_model'])
        self.assertEqual([c['text'] for c in r['options']],['OK'])
        self.assertEqual({c['text'] for c in r['buttons']},{'OK','Info','Goal'})
        self.assertEqual(r['report']['researching'],'TEST Alphabet')
        self.assertEqual(r['report']['research_progress'],3)
        self.assertEqual(r['report']['research_required'],20)
        self.assertEqual(r['report']['visible_achieved_advances'],['TEST Bronze Working'])
        self.assertIn('may be incomplete',r['report']['knowledge'])
        for kwargs in ({'rules':RULES},{'game_text':SCIENCE},{}):
            self.assertFalse(classify_dialog(o,**kwargs)['supported'])
        for mutate in (lambda x:x['lines'].pop(1),lambda x:x['lines'].pop(),
                       lambda x:x['lines'].append(row('Cancel',x=570,y=350,w=45)),
                       lambda x:x['lines'].insert(4,row('Change your research now.',y=215,w=250)),
                       lambda x:x['lines'][4].update(text='Unknown advance')):
            changed=copy.deepcopy(o);mutate(changed)
            self.assertFalse(classify_dialog(changed,rules=RULES,game_text=SCIENCE)['supported'])

    def test_science_report_rejects_ambiguous_control_and_list_geometry(self):
        o=observation(row('Science Advisor Report',y=80),
            row('Researching: TEST Alphabet (0 of 20)',y=125,w=320),
            row('Discoveries every 20 turns.',y=150,w=250),
            row('Civilization Advances Achieved:',y=190,w=280),
            row('TEST Bronze Working',x=200,y=230,w=180),
            row('Info',x=170,y=350,w=30),row('Goal',x=320,y=350,w=30),row('OK',x=470,y=350,w=24))
        for mutate in (lambda x:x['lines'].append(row('OK',x=570,y=350,w=24)),
                       lambda x:x['lines'][4].update(center=[200,175],bounds=[110,167,180,16]),
                       lambda x:x['lines'][1].update(confidence=.5)):
            changed=copy.deepcopy(o);mutate(changed)
            self.assertFalse(classify_dialog(changed,rules=RULES,game_text=SCIENCE)['supported'])

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

    def test_measured_foond_title_requires_founded_body_and_observed_ok(self):
        o=observation(row('Foond New City',y=90),row('TEST Rome Founded: 4000 B.C.',y=140),row('OK',y=210,w=25))
        r=classify_dialog(o)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'FOUNDED')
        self.assertEqual(r['observed_city_name'],'TEST Rome');self.assertFalse(r['requires_model'])
        self.assertEqual(r['options'][0]['text'],'OK')
        for index in (1,2):
            changed=copy.deepcopy(o);changed['lines'].pop(index)
            self.assertFalse(classify_dialog(changed)['supported'])
        o['lines'][1]['text']='Do you want to abandon TEST Rome?'
        self.assertFalse(classify_dialog(o)['supported'])

    def test_measured_cicy_heading_still_requires_single_founded_body(self):
        o=observation(row('Foond New Cicy',y=90),row('TEST Veii Founded: 3900 B.C.',y=140),row('OK',y=210,w=25))
        r=classify_dialog(o)
        self.assertTrue(r['supported'],r)
        self.assertEqual(r['observed_city_name'],'TEST Veii')
        o['lines'].append(row('Abandon this city?',y=165))
        self.assertFalse(classify_dialog(o)['supported'])

    def test_city_window_warning_only_acknowledges_complete_original_notice(self):
        o=observation(row('City Window',x=320,y=203,w=86),
            row('You must close the City Window before the game can',x=299,y=228,w=358),
            row('proceed.',x=150,y=248,w=60),row('Close City Window',x=219,y=278,w=122),
            row('OK',x=422,y=278,w=24))
        r=classify_dialog(o)
        self.assertTrue(r['supported'],r);self.assertEqual(r['resource_tag'],'CITYMODAL1')
        self.assertEqual(r['mechanical_action'],'acknowledge_information')
        self.assertEqual([x['text'] for x in r['options']],['OK'])
        self.assertEqual({x['text'] for x in r['buttons']},{'Close City Window','OK'})
        self.assertFalse(r['requires_model'])
        for mutate in (lambda x:x['lines'].pop(),lambda x:x['lines'].pop(2),
                       lambda x:x['lines'][1].update(text='Do you want to close every city?')):
            changed=copy.deepcopy(o);mutate(changed)
            self.assertFalse(classify_dialog(changed)['supported'])

    def test_production_template_recovery_requires_known_city_names_stats_and_controls(self):
        o=observation(row('What shall me bodd in Rooe?',y=280,w=220),
            row('TEST Warriors',x=215,y=310,w=120),row('(10 Turns, ADM: 1/1/1 HP: 1/1)',x=435,y=310,w=220),
            row('TEST Granary',x=215,y=335,w=120),row('(40 Turns)',x=495,y=335,w=95),
            row('Auto',x=170,y=420,w=30),row('Help',x=320,y=420,w=30),row('OK',x=470,y=420,w=24))
        s={'cities':[{'name':'Rome'}]}
        r=classify_dialog(o,rules=RULES,state=s)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'production_choice')
        self.assertEqual(r['observed_city_name'],'Rome')
        self.assertEqual([c['text'] for c in r['options']],['TEST Warriors','TEST Granary'])
        self.assertEqual(r['title'],'What shall me bodd in Rooe?')
        self.assertEqual(r['title_match']['template'],'What shall we build in Rome?')
        self.assertFalse(classify_dialog(o,rules=RULES)['supported'])
        self.assertFalse(classify_dialog(o,rules=RULES,state={'cities':[{'name':'Rome'},{'name':'Rope'}]})['supported'])
        for index in (1,2,5,6,7):
            changed=copy.deepcopy(o);changed['lines'].pop(index)
            self.assertFalse(classify_dialog(changed,rules=RULES,state=s)['supported'])
        changed=copy.deepcopy(o);changed['lines'][0]['text']='What shall we destroy in Rome?'
        self.assertFalse(classify_dialog(changed,rules=RULES,state=s)['supported'])

    def test_optional_actual_city_warning_founding_and_production_screens(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        root=Path(__file__).resolve().parents[1];base=root/'runs/attempt-001/screens'
        paths={n:base/f'ui-{n:07d}.png' for n in (13,27,52,55,69)}
        if not all(p.exists() for p in paths.values()) or not (root/'.runtime/ocr').exists():
            self.skipTest('private original city calibration images unavailable')
        rules=parse_rules(original_rules());state={'cities':[{'name':'Rome'}]}
        for n,expected in ((13,'information'),(27,'city_screen'),(52,'information'),(55,'city_screen'),(69,'production_choice')):
            r=classify_dialog(recognize(paths[n]),rules=rules,state=state)
            self.assertTrue(r['supported'],(n,r));self.assertEqual(r['kind'],expected)
            if n==69:self.assertEqual([x['text'] for x in r['options']],['Settlers','Warriors','Phalanx','Barracks','Colossus'])
            if n==52:self.assertEqual([x['text'] for x in r['options']],['OK'])

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

    def test_status_gold_numeric_glyph_alias_is_layout_only_and_narrow(self):
        for amount in ('1','I','l','1I','1,Il1'):
            o=native_map();next(r for r in o['lines'] if ' Gold ' in r['text'])['text']=amount+' Gold 4.0.6'
            r=classify_dialog(o,state=ROMAN_STATE)
            self.assertTrue(r['supported'],(amount,r));self.assertEqual(r['kind'],'normal_map')
            self.assertNotIn('treasury',r);self.assertNotIn('gold',r)
        for text in ('Oil Gold 4.0.6','Gold 4.0.6','I GoId 4.0.6','I gold please'):
            o=native_map();next(r for r in o['lines'] if ' Gold ' in r['text'])['text']=text
            self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])
        o=native_map();gold=next(r for r in o['lines'] if ' Gold ' in r['text'])
        gold.update(text='I Gold 4.0.6',center=[320,234],bounds=[286,228,68,12])
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_observed_cold_status_alias_never_supplies_treasury(self):
        o=native_map();gold=next(r for r in o['lines'] if ' Gold ' in r['text'])
        gold['text']='14 Cold 4.0.6'
        result=classify_dialog(o,state=ROMAN_STATE)
        self.assertTrue(result['supported']);self.assertNotIn('treasury',result)
        gold.update(center=[320,234],bounds=[286,228,68,12])
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_optional_actual_turn_two_gold_glyph_map(self):
        from civ2.observe import recognize
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-001/screens/ui-0000100.png'
        if not path.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private turn-two original map unavailable')
        s=copy.deepcopy(ROMAN_STATE);s['cities']=[{'name':'Rome'}]
        r=classify_dialog(recognize(path),state=s)
        self.assertTrue(r['supported'],r);self.assertEqual(r['kind'],'normal_map')

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

    def test_map_name_can_use_exact_known_same_pixel_reading_but_never_guess(self):
        o=native_map();label=row('Veu',x=233,y=229,w=35,h=16);o['lines'].append(label)
        state=copy.deepcopy(ROMAN_STATE);state['cities']=[{'name':'Veii'}]
        reading={'text':'Veii','confidence':1.,'preprocessing':'native',
                 'normalized_bounds':[label['bounds'][0]/640,label['bounds'][1]/480,35/640,16/480]}
        label['provenance']=[reading,{**reading,'text':'Veu','preprocessing':'map_label_11_3x'}]
        self.assertEqual(classify_dialog(o,state=state)['kind'],'normal_map')
        label['provenance'][0]={**reading,'normalized_bounds':[.1,.1,.05,.03]}
        self.assertFalse(classify_dialog(o,state=state)['supported'])
        label['provenance'][0]=reading;state['cities'].append({'name':'Veu'})
        self.assertFalse(classify_dialog(o,state=state)['supported'])

    def test_known_city_sprite_low_confidence_glyphs_do_not_become_dialog_text(self):
        o=native_map();s=copy.deepcopy(ROMAN_STATE);s['cities']=[{'name':'Rome'}]
        o['lines'] += [row('Rome',x=234,y=293,w=49,h=15),
                       row('ОБ П',x=242,y=272,w=40,h=20,confidence=.3)]
        self.assertEqual(classify_dialog(o,state=s)['kind'],'normal_map')
        for change in ({'confidence':.8},{'center':[320,150],'bounds':[300,140,40,20]},
                       {'text':'Please select'},{'text':'ОК'},{'text':'NO'},
                       {'text':'ОБ П','bounds':[190,260,104,24]}, {'text':'unknown','confidence':.9},
                       {'text':'N O'}, {'text':'menu'}):
            bad=copy.deepcopy(o);bad['lines'][-1].update(change)
            self.assertFalse(classify_dialog(bad,state=s)['supported'],change)
        self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])
        modal=copy.deepcopy(o);modal['lines'].append(row('Game samed!',y=203,w=82))
        self.assertFalse(classify_dialog(modal,state=s)['supported'])

    def test_city_sprite_fragments_generalize_to_known_foreign_names_and_size_labels(self):
        s=copy.deepcopy(ROMAN_STATE);s['known_cities']=[{'name':'TEST Other'}]
        for text in ('AB2','Wu Fom 1','ШБ','123'):
            o=native_map();o['lines'] += [row('TEST Other (12)',x=202,y=277,w=110,h=16),
                row(text,x=196,y=255,w=85,h=35,confidence=.3)]
            self.assertEqual(classify_dialog(o,state=s)['kind'],'normal_map',text)
            self.assertFalse(classify_dialog(o,state=ROMAN_STATE)['supported'])

    def test_optional_actual006_city_sprite_map(self):
        from civ2.observe import recognize
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-006/screens/ui-0000034.png'
        if not p.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private original006sprite frame unavailable')
        state=copy.deepcopy(ROMAN_STATE);state['cities']=[{'name':'Rome'}]
        result=classify_dialog(recognize(p),state=state)
        self.assertEqual(result['kind'],'end_turn',result)
        self.assertNotIn('population',result)

    def test_optional_actual005_city_and_terrain_sprite_map(self):
        from civ2.observe import recognize
        root=Path(__file__).resolve().parents[1];p=root/'runs/attempt-005/screens/ui-0000295.png'
        if not p.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private original005sprite frame unavailable')
        state=copy.deepcopy(ROMAN_STATE);state['cities']=[{'name':'Rome'}]
        self.assertEqual(classify_dialog(recognize(p),state=state)['kind'],'normal_map')

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
        self.assertEqual(r['evidence']['city_resource_map']['resource_map']['center'],[104,255])
        self.assertEqual(r['evidence']['city_resource_map']['citizens']['center'],[104,112])

    def test_city_resource_anchors_require_unique_exact_observed_rows(self):
        labels=['Food Storage','City Resources','Units Supported','Units Present','Resource Map','Citizens']
        o=observation(*[row(t,x=104,y=100+i*30,w=90) for i,t in enumerate(labels)],
                      *[row(t,x=x,y=400,w=35) for t,x in [('Buy',478),('Change',595),('Exit',607)]])
        r=classify_dialog(o)
        self.assertTrue(r['supported']);self.assertEqual(r['kind'],'city_screen')
        self.assertEqual(set(r['evidence']['city_resource_map']),{'resource_map','citizens'})
        o['lines'].append(row('Citizens',x=103,y=115,w=60))
        self.assertNotIn('city_resource_map',classify_dialog(o)['evidence'])

    def test_city_locator_joined_heading_still_requires_actual_owned_options(self):
        o=observation(row('Where in the heckis.',y=85,w=150),row('TEST Rome',x=190,y=110,w=90),
                      row('Zoom To City',x=196,y=394,w=90),row('OK',x=320,y=394,w=24),row('Cancel',x=445,y=394,w=50))
        result=classify_dialog(o,state={'cities':[{'name':'TEST Rome'}]})
        self.assertTrue(result['supported']);self.assertEqual(result['kind'],'city_locator')
        self.assertEqual(result['options'][0]['text'],'TEST Rome')
        self.assertFalse(classify_dialog(o,state={'cities':[{'name':'TEST Veii'}]})['supported'])

    def test_built_notice_radio_choices_are_model_decisions_not_information(self):
        source='@BUILT\n@title=Domestic Advisor\n%STRING0 %STRING3 %STRING1.\n'
        o=observation(row('Domestic Advisor',y=174,w=140),row('TEST Rome builds TEST Settlers.',x=280,y=200,w=260),
                      row('Zoom to City',x=249,y=226,w=90),row('Continue',x=236,y=249,w=60),row('OK',y=304,w=24))
        state={'cities':[{'name':'TEST Rome'}]};rules={'units':[{'name':'TEST Settlers'}]}
        result=classify_dialog(o,state=state,rules=rules,game_text=source)
        self.assertTrue(result['supported']);self.assertEqual(result['kind'],'production_notice')
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        self.assertEqual([r['text'] for r in result['options']],['Zoom to City','Continue'])
        for altered in (source.replace('%STRING0 %STRING3 %STRING1.','Do something dangerous.'),None):
            self.assertFalse(classify_dialog(o,state=state,rules=rules,game_text=altered)['supported'])
        self.assertFalse(classify_dialog(o,state={'cities':[{'name':'TEST Veii'}]},rules=rules,game_text=source)['supported'])
        self.assertFalse(classify_dialog(o,state=state,rules={'units':[]},game_text=source)['supported'])
        bad=copy.deepcopy(o);bad['lines'].append(row('Something else',x=240,y=276,w=100))
        self.assertFalse(classify_dialog(bad,state=state,rules=rules,game_text=source)['supported'])

    def test_government_offer_measured_glyphs_require_full_source_and_both_options(self):
        source='@AUTOMONARCHY\n@title=Civ Rules: Governments\nTo switch governments TEST Rome must endure a brief period of Anarchy.\n\nNot just yet.\nBegin revolution.\n'
        o=observation(row('Cir Roles: Gopernments',y=116,w=150),
                      row('Lo switch governments TEST Rome must endure a briel period of Anarchy.',y=180,w=440),
                      row('• Not just yet.',x=186,y=230,w=90),row('• Begin revolution.',x=203,y=255,w=110),row('OK',y=305,w=25))
        r=classify_dialog(o,game_text=source)
        self.assertTrue(r['supported']);self.assertEqual(r['resource_tag'],'AUTOMONARCHY')
        self.assertTrue(r['requires_model']);self.assertIsNone(r['mechanical_action'])
        self.assertEqual(r['options'][0]['text'],'• Not just yet.')
        for text in ('TEST Rome avoids all Anarchy.','To switch governments TEST Rome must endure.'):
            changed=copy.deepcopy(o);changed['lines'][1]['text']=text
            self.assertFalse(classify_dialog(changed,game_text=source)['supported'])
        missing=copy.deepcopy(o);missing['lines'].pop(2)
        self.assertFalse(classify_dialog(missing,game_text=source)['supported'])

    def test_optional_actual_monarchy_offer_is_a_fresh_model_choice(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-005/screens/ui-0000328.png'
        if not path.exists() or not (root/'.runtime/ocr').exists():self.skipTest('Private original government offer unavailable')
        r=classify_dialog(recognize(path),game_text=game_text())
        self.assertTrue(r['supported']);self.assertEqual(r['kind'],'revolution_offer')
        self.assertEqual([c['text'] for c in r['options']],['• Not just yet.','• Begin revolution.'])


if __name__=='__main__':unittest.main()
