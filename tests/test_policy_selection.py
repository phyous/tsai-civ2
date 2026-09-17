"""TEST global decisions survive a vacated native selection; unit orders do not."""
from copy import deepcopy
import unittest
from civ2.policy import model_state,unit_candidates,PolicyError
from civ2.empire import empire_candidates,empire_request_for
from tests.test_empire import inputs

class MissingSelection(unittest.TestCase):
    def test_global_choices_have_no_inferred_actor_for_vacated_slot(self):
        state,screen,rules=inputs();state['selected_unit_id']=10
        state['units']=[{'id':5,'type_id':2,'type':'TEST Warriors','owner':1,'x':2,'y':2}]
        original=deepcopy(state)
        actions=empire_candidates(state,screen,rules=rules)
        request=empire_request_for(state,screen,actions,rules=rules)
        self.assertIsNone(request['state']['selected_unit'])
        self.assertIsNone(request['state']['selected_unit_city_context'])
        self.assertEqual(request['state']['neighboring_tiles'],[])
        self.assertIn('does not identify a unit',request['state']['selected_unit_note'])
        self.assertEqual(request['state']['owned_unit_roster'][0]['id'],5)
        self.assertEqual(request['questions']['empire_action']['criteria'],{k:a['label'] for k,a in actions.items()})
        self.assertEqual(state,original)
        with self.assertRaisesRegex(PolicyError,'unavailable or ambiguous'):unit_candidates(state,rules=rules)

    def test_absent_or_negative_selection_keeps_existing_context(self):
        for selected in (None,-1):
            state,_,rules=inputs();state['selected_unit_id']=selected
            projection=model_state(state,rules)
            self.assertIsNone(projection['selected_unit']);self.assertNotIn('selected_unit_note',projection)

    def test_duplicate_foreign_or_malformed_selected_actor_is_not_hidden(self):
        unit={'id':10,'type_id':2,'owner':1,'x':2,'y':2}
        for case in ('duplicate','foreign','malformed'):
            with self.subTest(case=case):
                state,_,rules=inputs();state['selected_unit_id']=10;state['units']=[deepcopy(unit)]
                if case=='duplicate':state['units'].append(deepcopy(unit))
                elif case=='foreign':state['units'][0]['owner']=2
                else:state['units'][0].pop('x')
                with self.assertRaises(PolicyError):model_state(state,rules)
                with self.assertRaises(PolicyError):unit_candidates(state,rules=rules)

if __name__=='__main__':unittest.main()
