"""TEST evidence for an explicit Jev-selected labor preparation transaction."""
from copy import deepcopy
import json
import tempfile
import unittest

from civ2.verify import VerificationError, verify_run
from test_verify import city_evidence


def evidence(parent, complete=True):
    e, action, reviewed = city_evidence(parent, 'exit_city')
    action.update(id='review_labor', label='TEST review labor allocation')
    action['parameters'].update(only_open_menu=True, expected_screen='fresh_city_labor')
    criteria = {'review_labor':action['label'], 'exit_city':'TEST exit without labor review'}
    request = json.loads((e.directory/'decisions/request.json').read_text())
    request['questions']['city_action']['criteria'] = criteria
    request['state']['city_control_review'].update(controls=criteria, labor_checkpoint_ready=False)
    response = json.loads((e.directory/'decisions/response.json').read_text())
    response['answers']['city_action'].update(choice='review_labor', confidence=.7,
        probabilities={'review_labor':.7, 'exit_city':.3})
    e.change_artifact('decisions/request.json', request)
    e.change_artifact('decisions/response.json', response)
    city = {k:action['actor'][k] for k in ('id','owner','name','x','y')}
    digest = action['preconditions']['save_sha256']
    def edit(rows):
        for row in rows:
            if row['kind'] in ('model_decision', 'city_control_dispatched'):
                row['payload']['action'] = deepcopy(action)
        descriptor = next(row for row in rows if row['kind']=='checkpoint')['payload']['artifact']
        elapsed = rows[-1]['elapsed_ms']
        def event(kind, **payload):
            return dict(kind=kind,elapsed_ms=elapsed,payload=payload)
        common = dict(decision=1,purpose='prepare_labor_choices')
        transaction = [event('city_labor_refresh_started', **common, action=None,
            preparation_action=deepcopy(action), city=city, before_save_sha256=digest)]
        if complete:
            def click(target, point, sequence):
                return dict(before=e.screen['sha256'], target=target, point=point, inputs=[
                    dict(type='mouse',sequence=sequence+i,event=operation,x=point[0],y=point[1],button=0)
                    for i,operation in enumerate(('mousedown','mouseup'))])
            transaction += [
                event('checkpoint', artifact=descriptor, turn=1, year=-4000),
                event('city_labor_checkpoint', **common, checkpoint=2, save_sha256=digest, result=None),
                event('city_labor_refresh_input', **common, step='open_locator', before=e.screen['sha256'], inputs=[
                    dict(type='key',sequence=i,code=code,down=down,repeat=False)
                    for i,code,down in ((3,'ShiftLeft',True),(4,'KeyC',True),(5,'KeyC',False),(6,'ShiftLeft',False))]),
                event('navigate_selected_city', city=city,
                    receipt=click('TEST Rome',[100,100],7), zoom_receipt=click('Zoom To City',[150,400],9)),
                event('city_labor_ready', **common, city=city, save_sha256=digest, screen=e.screen['sha256'])]
        rows[-1:-1] = transaction
    e.rewrite(edit)
    return e


class LazyLaborVerifierTests(unittest.TestCase):
    def test_selected_exit_prepares_labor_without_extra_escape_or_claimed_reassignment(self):
        with tempfile.TemporaryDirectory() as directory:
            e = evidence(directory)
            result = verify_run(e.directory, ffprobe=None)
            self.assertEqual(result['integrity'], 'passed')
            self.assertEqual(result['decisions']['model_dispatches'], 1)
            self.assertEqual(result['decisions']['ordinary_input_events'], 10)
            self.assertFalse(result['completeness']['pending_city_control'])
            self.assertFalse(result['completeness']['pending_labor_refresh'])
            self.assertEqual(result['decisions']['city_labor_results'], [])

    def test_unfinished_preparation_remains_pending_without_claiming_labor_effect(self):
        with tempfile.TemporaryDirectory() as directory:
            result = verify_run(evidence(directory, complete=False).directory, ffprobe=None)
            self.assertTrue(result['completeness']['pending_city_control'])
            self.assertTrue(result['completeness']['pending_labor_refresh'])
            self.assertEqual(result['decisions']['city_labor_results'], [])

    def test_preparation_requires_exact_choice_actual_exit_and_later_observation(self):
        for mode in ('action','dispatch','decision','checkpoint','close','ready'):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                e = evidence(directory)
                def edit(rows):
                    start = next(row for row in rows if row['kind']=='city_labor_refresh_started')
                    if mode=='action':start['payload']['preparation_action']['parameters']['center']=[1,1]
                    elif mode=='dispatch':rows[:]=[row for row in rows if row['kind']!='city_control_dispatched']
                    elif mode=='decision':start['payload']['decision']=2
                    elif mode=='checkpoint':
                        index=rows.index(start)
                        rows[index:]=[row for row in rows[index:] if row['kind']!='checkpoint']
                    elif mode=='close':
                        rows.insert(rows.index(start)+1,dict(kind='city_labor_refresh_input',elapsed_ms=start['elapsed_ms'],payload=dict(
                            decision=1,purpose='prepare_labor_choices',step='close_city',before=e.screen['sha256'],inputs=[])))
                    else:next(row for row in rows if row['kind']=='city_labor_ready')['payload']['city']['name']='TEST Wrong'
                e.rewrite(edit)
                with self.assertRaises(VerificationError):verify_run(e.directory, ffprobe=None)


if __name__=='__main__':
    unittest.main()
