"""Locator progress survives observation failures without automatic replay."""
from copy import deepcopy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from civ2.run import controller_context,navigate_city,run_steps


def fixture():
    city={'id':0,'owner':1,'name':'TEST Rome','x':8,'y':8}
    initial={'sha256':'a'*64,'path':'/TEST/screens/before.png'}
    selected={'sha256':'b'*64,'path':'/TEST/screens/selected.png'}
    dialog={'kind':'city_locator','supported':True,
        'options':[{'text':'TEST Rome','center':[200,180],'source_line':2}],
        'buttons':[{'text':'Zoom To City','center':[320,380],'source_line':3}]}
    def click(label,point,before,after,sequence):
        return {'target':label,'point':point,'before':before,'selected_frame':after,
            'inputs':[{'type':'mouse','event':event,'button':0,'x':point[0],'y':point[1],'sequence':sequence+i}
                      for i,event in enumerate(('mousedown','mouseup'))],
            'pointer_park':{'issued':False,'target':[2,1],'inputs':[]}}
    first=click('TEST Rome',[200,180],'a'*64,'b'*64,1)
    zoom=click('Zoom To City',[320,380],'b'*64,'c'*64,3)
    s=SimpleNamespace(state={'turn':1,'cities':[city]},rules={},decisions=4,recorder=None,
                      ui=Mock(),game=Mock(),journal=Mock())
    ctx=controller_context(s);ctx['pending_city']=city
    ctx['pending_labor_refresh']={'phase':'await_locator','city':city}
    s.ui.select_text.side_effect=[first,zoom];s.ui.observe.return_value=selected
    return s,ctx,initial,dialog,first,zoom


class CityNavigationTests(unittest.TestCase):
    def invoke(self,s,ctx,initial,dialog):
        with patch('civ2.run.classify_dialog',return_value=dialog),patch('civ2.run.labels_text',return_value='TEST'):
            return navigate_city(s,ctx,initial,dialog,'TEST')

    def test_success_records_one_aggregate_and_waits_for_actual_reopening(self):
        s,ctx,o,d,first,zoom=fixture()
        self.assertIsNone(self.invoke(s,ctx,o,d))
        s.journal.append.assert_called_once_with('navigate_selected_city',city=ctx['pending_city'],receipt=first,zoom_receipt=zoom)
        self.assertIsNone(ctx['pending_city_navigation'])
        self.assertEqual(ctx['pending_labor_refresh']['phase'],'await_reopened')
        self.assertIsNone(ctx['city_labor_ready'])
        s.ui.observe.assert_called_once_with()

    def test_failed_post_selection_read_keeps_first_click_and_blocks_reentry(self):
        s,ctx,o,d,first,zoom=fixture();s.ui.observe.side_effect=ValueError('Invalid normalized OCR geometry')
        self.assertIsNotNone(self.invoke(s,ctx,o,d))
        event=s.journal.append.call_args
        self.assertEqual(event.args,('city_navigation_incomplete',))
        self.assertEqual(event.kwargs['receipt'],first);self.assertIsNone(event.kwargs['zoom_receipt'])
        self.assertEqual(event.kwargs['phase'],'observe_selection')
        self.assertEqual(ctx['pending_labor_refresh']['phase'],'await_locator')
        self.assertTrue(ctx['pending_city_navigation']['blocked'])
        s.ui.reset_mock();s.journal.reset_mock()
        with patch('civ2.run.game_text',return_value='TEST'):
            self.assertIn('deliberate reviewed recovery',run_steps(s)['reason'])
            self.assertIn('deliberate reviewed recovery',run_steps(s)['reason'])
        s.ui.observe.assert_not_called();s.ui.select_text.assert_not_called();s.journal.append.assert_not_called()

    def test_unsupported_intermediate_or_missing_zoom_cannot_drop_completed_click(self):
        for mode in ('unsupported','missing_zoom','classifier_error'):
            s,ctx,o,d,first,zoom=fixture();next_dialog=deepcopy(d)
            if mode=='unsupported':next_dialog['supported']=False
            elif mode=='missing_zoom':next_dialog['buttons']=[]
            with self.subTest(mode=mode),patch('civ2.run.labels_text',return_value='TEST'),patch('civ2.run.classify_dialog',
                    return_value=next_dialog,side_effect=ValueError('TEST classifier failure') if mode=='classifier_error' else None):
                self.assertIsNotNone(navigate_city(s,ctx,o,d,'TEST'))
            self.assertEqual(s.ui.select_text.call_count,1)
            self.assertEqual(s.journal.append.call_args.kwargs['receipt'],first)
            self.assertEqual(ctx['pending_labor_refresh']['phase'],'await_locator')

    def test_partial_first_or_zoom_receipts_remain_unfinished(self):
        for phase in ('select_city','zoom_city'):
            s,ctx,o,d,first,zoom=fixture();partial=deepcopy(first if phase=='select_city' else zoom)
            partial.pop('selected_frame');error=RuntimeError('TEST capture failure');error.selection_receipt=partial
            s.ui.select_text.side_effect=[error] if phase=='select_city' else [first,error]
            with self.subTest(phase=phase):self.assertIsNotNone(self.invoke(s,ctx,o,d))
            payload=s.journal.append.call_args.kwargs
            self.assertEqual(payload['phase'],phase)
            self.assertEqual(payload['receipt' if phase=='select_city' else 'zoom_receipt'],partial)
            self.assertEqual(ctx['pending_labor_refresh']['phase'],'await_locator')
            self.assertIsNone(ctx['city_labor_ready'])


if __name__=='__main__':unittest.main()
