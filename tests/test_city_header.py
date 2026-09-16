"""An OCR spelling can bind only a uniquely corroborated original city name."""
import copy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from tests.test_dialogs import observation,row

def screen(name='Vei'):
    return observation(row(f'City of {name}, 3000 B.C., Population 10,000 (Treasury: 2 Gold)',y=48,w=430),
        row('Food Storage',x=535,y=66,w=78),row('City Resources',x=320,y=112,w=86),
        row('Resource Map',x=104,y=255,w=84),row('Units Supported',x=100,y=284,w=94),
        row('Units Present',x=316,y=284,w=80),row('Buy',x=478,y=252,w=28),
        row('Change',x=594,y=252,w=48),row('Exit',x=607,y=459,w=26))

def saved_state():
    return {'player':{'id':1},'evidence':{'save_sha256':'b'*64},
            'cities':[{'id':1,'owner':1,'name':'Veii','x':19,'y':23}]}

class CityHeaderTests(unittest.TestCase):
    def test_unique_owned_native_save_recovers_name_without_rewriting_title(self):
        o=screen();state=saved_state();result=classify_dialog(o,state=state)
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'city_screen');self.assertEqual(result['observed_city_name'],'Veii')
        self.assertEqual(result['title'],o['lines'][0]['text'])
        self.assertEqual(result['city_name_recovery'],{
            'source':'Unique one-edit match to owned city in original save','ocr_text':'Vei',
            'canonical_name':'Veii','city_id':1,'save_sha256':'b'*64,'source_line':0})

    def test_unproven_provisional_foreign_ambiguous_or_distant_names_stay_raw(self):
        states=[None,{'cities':[{'name':'Veii'}]},saved_state(),saved_state(),saved_state(),saved_state()]
        states[2]['cities'][0]['owner']=2
        states[3]['cities'].append({'id':2,'owner':1,'name':'Wei','x':21,'y':23})
        states[4]['evidence']['save_sha256']='invalid'
        states[5]['cities'][0]['name']='Veyyy'
        for state in states:
            r=classify_dialog(screen(),state=state)
            self.assertEqual(r['observed_city_name'],'Vei');self.assertNotIn('city_name_recovery',r)
        o=screen();o['lines'][0]['confidence']=.5
        self.assertNotIn('city_name_recovery',classify_dialog(o,state=saved_state()))

    def test_exact_saved_match_needs_no_recovery_metadata(self):
        r=classify_dialog(screen('Veii'),state=saved_state())
        self.assertEqual(r['observed_city_name'],'Veii');self.assertNotIn('city_name_recovery',r)

    def test_optional_original_production_verb_and_provisional_alias(self):
        from civ2.observe import recognize
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        root=Path(__file__).resolve().parents[1];path=root/'runs/attempt-003/screens/ui-0000136.png'
        if not path.exists() or not (root/'.runtime/ocr').exists():self.skipTest('private original production image unavailable')
        o=recognize(path);rules=parse_rules(original_rules())
        for state in ({'cities':[{'name':'Veii'}]},saved_state()):
            state=copy.deepcopy(state)
            if 'evidence' in state:state['cities'].append({'name':'Vei'})
            r=classify_dialog(o,state=state,rules=rules)
            self.assertTrue(r['supported'],r);self.assertEqual(r['observed_city_name'],'Veii')
            self.assertEqual(r['title'],'What shall me budkd in Vei?')
            self.assertEqual([x['text'] for x in r['options']],['Settlers','Warriors','Phalanx','Barracks','Colossus'])
        for text in ('What shall he build in Veii?','What shall me destroy in Veii?',
                     'Why shall we build in Veii?','What shall me budxxxd in Veii?'):
            changed=copy.deepcopy(o)
            next(r for r in changed['lines'] if r['text'].startswith('What shall'))['text']=text
            self.assertFalse(classify_dialog(changed,state=saved_state(),rules=rules)['supported'])

if __name__=='__main__':unittest.main()
