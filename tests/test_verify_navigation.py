"""Partial locator inputs remain counted evidence, never completed navigation."""
from copy import deepcopy
import tempfile
import unittest
from civ2.verify import verify_run,VerificationError
from test_verify import city_evidence


def move(sequence=3):
    return dict(type='relativeMouse',sequence=sequence,dx=1,dy=1,
                via='DOSBox Mouse_CursorMoved',dispatched=True,emulate=True)


def selection(e,label='TEST Rome',sequence=3):
    return dict(target=label,point=[320,190],before=e.screen['sha256'],selected_frame=e.screen['sha256'],
        inputs=[dict(type='mouse',event=event,sequence=sequence+i,x=320,y=190,button=0)
                for i,event in enumerate(('mousedown','mouseup'))],
        pointer_park=dict(issued=False,target=[2,1],inputs=[move(sequence+2)]))


def fixture(directory,phase='observe_selection'):
    e,action,_=city_evidence(directory)
    city={k:action['actor'][k] for k in ('id','owner','name','x','y')}
    p=dict(city=city,source_hash=e.screen['sha256'],phase=phase,receipt=selection(e),
           zoom_receipt=None,reason='TEST original locator could not be read.',error_type='ValueError')
    return e,p


def append(e,p,extra=None):
    def edit(rows):
        i=next(i for i,r in enumerate(rows) if r['kind']=='session_stopped');elapsed=rows[i]['elapsed_ms']
        events=[dict(kind='screen_observed',elapsed_ms=elapsed,payload=dict(path=e.screen['path'],
                    screen=e.screen['sha256'],classification='city_locator',supported=True)),
                dict(kind='city_navigation_incomplete',elapsed_ms=elapsed,payload=p)]
        if extra:events.append(dict(kind=extra[0],elapsed_ms=elapsed,payload=extra[1]))
        rows[i:i]=events
    e.rewrite(edit)


class NavigationAuditTests(unittest.TestCase):
    def test_completed_first_click_counted_without_dispatching_or_closing_transaction(self):
        with tempfile.TemporaryDirectory() as d:
            e,p=fixture(d);before=verify_run(e.directory,ffprobe=None);append(e,p)
            r=verify_run(e.directory,ffprobe=None)
            self.assertEqual(r['integrity'],'passed')
            self.assertEqual(r['decisions']['ordinary_input_events'],before['decisions']['ordinary_input_events']+3)
            self.assertEqual(r['decisions']['model_dispatches'],before['decisions']['model_dispatches'])
            self.assertTrue(r['completeness']['pending_city_navigation'])
            self.assertTrue(r['completeness']['pending_city_control'])
            self.assertFalse(r['completeness']['release_review_ready'])
            self.assertEqual(r['decisions']['input_coverage'],'incomplete')
            self.assertEqual(r['completeness']['uninterpreted_event_counts'],{})

    def test_partial_cursor_returned_down_or_up_is_not_fabricated_as_click_pair(self):
        for buttons in ([],['mousedown'],['mouseup'],['mousedown','mouseup']):
            with self.subTest(buttons=buttons),tempfile.TemporaryDirectory() as d:
                e,p=fixture(d,'select_city');r=p['receipt'];r.pop('selected_frame');r.pop('pointer_park');r['inputs']=[]
                r['failed_cursor']=dict(issued=None if buttons else False,status='failed',target=r['point'],
                    button_down_attempted=bool(buttons),error='TEST capture failure',inputs=[move()]+[
                        dict(type='mouse',event=b,sequence=4+i,x=0,y=0,button=0) for i,b in enumerate(buttons)])
                append(e,p);result=verify_run(e.directory,ffprobe=None)
                actual=result['decisions']['incomplete_city_navigation']
                self.assertEqual(actual['known_input_events'],1+len(buttons))
                self.assertEqual(result['decisions']['model_dispatches'],1)

    def test_null_preinput_and_partial_zoom_are_explicitly_unresolved(self):
        for mode in ('null','zoom'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e,p=fixture(d,'select_city' if mode=='null' else 'zoom_city')
                if mode=='null':p['receipt']=None
                else:
                    z=selection(e,'Zoom To City',6);z.pop('selected_frame');z.pop('pointer_park');z['inputs']=[]
                    z['failed_cursor']=dict(issued=False,status='failed',target=z['point'],button_down_attempted=False,
                                           error='TEST no cursor',inputs=[move(6)])
                    p['zoom_receipt']=z
                append(e,p);result=verify_run(e.directory,ffprobe=None)
                self.assertEqual(result['decisions']['incomplete_city_navigation']['known_input_events'],0 if mode=='null' else 4)
                self.assertTrue(result['completeness']['pending_city_navigation'])

    def test_bad_identity_phase_source_or_input_rejected(self):
        for mode in ('city','source','label','point','key','duplicate','phase','unknown_field','selected_missing',
                     'failed_target','failed_issued','extra_click','early_zoom'):
            with self.subTest(mode=mode),tempfile.TemporaryDirectory() as d:
                e,p=fixture(d);r=p['receipt']
                if mode=='city':p['city']['owner']=2
                elif mode=='source':p['source_hash']='a'*64
                elif mode=='label':r['target']='OTHER CITY'
                elif mode=='point':r['point']=[640,190]
                elif mode=='key':r['inputs']=[dict(type='key',code='Enter',down=v,repeat=False,sequence=3+i) for i,v in enumerate((True,False))]
                elif mode=='duplicate':r['pointer_park']['inputs'][0]['sequence']=4
                elif mode=='phase':p['phase']='completed'
                elif mode=='unknown_field':p['accepted']=True
                elif mode=='selected_missing':r.pop('selected_frame')
                elif mode=='early_zoom':p['zoom_receipt']=selection(e,'Zoom To City',6)
                else:
                    p['phase']='select_city';r['inputs']=[];r.pop('selected_frame');r.pop('pointer_park')
                    f=dict(issued=False,status='failed',target=r['point'],button_down_attempted=False,error='TEST error',inputs=[])
                    r['failed_cursor']=f
                    if mode=='failed_target':f['target']=[500,200]
                    elif mode=='failed_issued':f['issued']=True
                    else:
                        f.update(issued=None,button_down_attempted=True)
                        f['inputs']=[dict(type='mouse',event='mousedown',sequence=3+i,x=0,y=0,button=0) for i in range(2)]
                append(e,p)
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_no_replay_or_success_after_incomplete_without_new_review_protocol(self):
        for kind in ('navigate_selected_city','city_navigation_incomplete','inference_started','mechanical_input'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                e,p=fixture(d);append(e,p,(kind,deepcopy(p) if kind=='city_navigation_incomplete' else {}))
                with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None)

    def test_incomplete_locator_does_not_advance_labor_refresh(self):
        from test_verify import labor_evidence
        with tempfile.TemporaryDirectory() as d:
            e,_,_=labor_evidence(d)
            def edit(rows):
                i=next(i for i,r in enumerate(rows) if r['kind']=='navigate_selected_city')
                old=rows[i];p=old['payload'];receipt=deepcopy(p['receipt']);receipt['selected_frame']=e.screen['sha256']
                rows[i:]=[dict(kind='screen_observed',elapsed_ms=old['elapsed_ms'],payload=dict(
                    path=e.screen['path'],screen=e.screen['sha256'],classification='city_locator',supported=True)),
                    dict(kind='city_navigation_incomplete',elapsed_ms=old['elapsed_ms'],payload=dict(
                        city=p['city'],source_hash=e.screen['sha256'],phase='observe_selection',
                        receipt=receipt,zoom_receipt=None,reason='TEST next frame unknown',error_type=None))]
            e.rewrite(edit);r=verify_run(e.directory,ffprobe=None)
            self.assertTrue(r['completeness']['pending_labor_refresh'])
            self.assertTrue(r['completeness']['pending_city_navigation'])
            self.assertEqual(r['decisions']['incomplete_city_navigation']['known_input_events'],2)
            self.assertEqual(r['decisions']['city_labor_results'],[])


if __name__=='__main__':unittest.main()
