"""Foreground control identity must survive identical labels behind its dialog."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest
from unittest import mock
from civ2.ui import UI


def row(text,x,y):
    return dict(text=text,center=[x,y],bounds=[x-20,y-6,40,12],confidence=1)


class ObservedTargetTests(unittest.TestCase):
    def fixture(self):
        directory=tempfile.TemporaryDirectory();self.addCleanup(directory.cleanup)
        ui=UI(mock.Mock(),directory.name)
        observation=dict(width=640,height=480,sha256='a'*64,
            lines=[row('Rome',480,250),row('Rome',480,280),row('Rome',480,310),row('Rome',220,180)])
        ui.latest=observation;ui.observe=mock.Mock(return_value={'sha256':'b'*64})
        ui.park_pointer=mock.Mock(return_value={'issued':False})
        ui.key=mock.Mock()
        ui.game.click.return_value=[{'issued':True,'target':[220,180]}]
        return ui,observation

    def test_classified_row_wins_over_identical_background_labels(self):
        ui,observation=self.fixture()
        with self.assertRaises(ValueError):ui.select_text(observation,'Rome',exact=True)
        ui.game.click.assert_not_called()
        with mock.patch('civ2.ui.time.sleep'):
            receipt=ui.select_text(observation,'Rome',exact=True,source_line=3,center=[220,180])
        ui.game.click.assert_called_once_with(220,180,timeout=20)
        self.assertEqual(set(receipt),{'target','point','before','selected_frame','inputs','pointer_park'})
        self.assertEqual(receipt['before'],'a'*64);self.assertEqual(receipt['point'],[220,180])
        ui.key.assert_not_called()

    def test_stale_or_changed_source_never_dispatches(self):
        for alteration in ('stale','index','bool_index','center','text','partial','off_image'):
            ui,observation=self.fixture();args=dict(exact=True,source_line=3,center=[220,180]);text='Rome'
            if alteration=='stale':observation=deepcopy(observation)
            elif alteration=='index':args['source_line']=40
            elif alteration=='bool_index':args['source_line']=True
            elif alteration=='center':args['center']=[221,180]
            elif alteration=='text':text='Veii'
            elif alteration=='partial':args['exact']=False
            elif alteration=='off_image':observation['width']=200
            with self.subTest(alteration=alteration),self.assertRaises(ValueError):ui.select_text(observation,text,**args)
            ui.game.click.assert_not_called()

    def test_post_click_geometry_failure_retains_receipts_but_cannot_confirm(self):
        for confirm in (False,True):
            ui,observation=self.fixture()
            ui.observe.return_value={'sha256':'b'*64,'lines':[],'text':'',
                                     'ocr':{'unreadable_after_input':True}}
            with self.subTest(confirm=confirm),mock.patch('civ2.ui.time.sleep'):
                if confirm:
                    with self.assertRaisesRegex(ValueError,'cannot authorize') as caught:
                        ui.select_text(observation,'Rome',exact=True,source_line=3,center=[220,180],confirm=True)
                    receipt=caught.exception.selection_receipt
                else:
                    receipt=ui.select_text(observation,'Rome',exact=True,source_line=3,center=[220,180])
            self.assertEqual(receipt['inputs'],ui.game.click.return_value)
            self.assertEqual(receipt['pointer_park'],ui.park_pointer.return_value)
            self.assertEqual(receipt['selected_frame'],'b'*64)
            ui.observe.assert_called_once_with(retain_unreadable=True);ui.key.assert_not_called()

    def test_later_errors_attach_only_receipts_that_actually_returned(self):
        for phase in ('click','park_pointer','observe'):
            ui,observation=self.fixture();error=RuntimeError('TEST failure')
            failed={'target':[220,180],'inputs':[],'issued':False,'status':'failed','button_down_attempted':False}
            if phase=='click':
                error.cursor_receipt=failed;ui.game.click.side_effect=error
            elif phase=='park_pointer':ui.park_pointer.side_effect=error
            else:ui.observe.side_effect=error
            with self.subTest(phase=phase),mock.patch('civ2.ui.time.sleep'),self.assertRaises(RuntimeError) as caught:
                ui.select_text(observation,'Rome',exact=True,source_line=3,center=[220,180])
            receipt=caught.exception.selection_receipt
            self.assertEqual(caught.exception.selection_phase,phase)
            self.assertEqual(receipt['before'],observation['sha256']);self.assertNotIn('selected_frame',receipt)
            self.assertEqual(receipt['inputs'],[] if phase=='click' else ui.game.click.return_value)
            self.assertEqual('pointer_park' in receipt,phase=='observe')
            if phase=='click':self.assertEqual(receipt['failed_cursor'],failed)
            ui.key.assert_not_called()

    def test_actual_locator_binds_one_foreground_rome_among_background_copies(self):
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        path=Path(__file__).resolve().parents[1]/'runs/attempt-008/screens/ui-0000266.png'
        if not path.exists():self.skipTest('Private original calibration image unavailable')
        observation=recognize(path)
        dialog=classify_dialog(observation,state={'cities':[{'name':'Rome'}]})
        self.assertEqual(dialog['kind'],'city_locator');self.assertTrue(dialog['supported'])
        choices=[r for r in dialog['options'] if r['text']=='Rome'];self.assertEqual(len(choices),1)
        self.assertGreater(sum(r['text']=='Rome' for r in observation['lines']),1)
        ui,_=self.fixture();ui.latest=observation;choice=choices[0]
        with mock.patch('civ2.ui.time.sleep'):
            receipt=ui.select_text(observation,choice['text'],exact=True,
                source_line=choice['source_line'],center=choice['center'])
        self.assertEqual(receipt['point'],choice['center']);self.assertEqual(receipt['before'],observation['sha256'])

if __name__=='__main__':unittest.main()
