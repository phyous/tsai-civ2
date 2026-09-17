from copy import deepcopy
from pathlib import Path
import unittest
from civ2.dialogs import classify_dialog
from civ2.observe import recognize
from civ2.run import game_text

class HistoryNoticeTests(unittest.TestCase):
    def actual(self,run,number):
        p=Path(f'runs/attempt-{run}/screens/ui-{number:07d}.png')
        if not p.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original game capture unavailable')
        o=recognize(p);o['path']=str(p)
        return o

    def test_actual_reports_only_acknowledge_visible_rows(self):
        for run,n in [('004',988),('006',1040),('008',165),('009',207)]:
            o=self.actual(run,n);d=classify_dialog(o,game_text=game_text())
            self.assertTrue(d['supported'],d)
            self.assertEqual(d['resource_tag'],'HISTORY')
            self.assertEqual(d['mechanical_action'],'acknowledge_information')
            self.assertFalse(d['requires_model'])
            self.assertEqual(len(d['options']),1)

    def test_extra_choice_bad_rank_or_missing_category_refuses(self):
        o=self.actual('006',1040)
        for mode in ('extra','rank','category'):
            z=deepcopy(o)
            if mode=='extra':
                row=deepcopy(next(r for r in z['lines'] if r['text']=='OK'));row['text']='Cancel';z['lines'].append(row)
            elif mode=='rank':
                next(r for r in z['lines'] if r['text'].startswith('2. The'))['text']='2. The Glorious Civilization of the Vikings'
            else:z['lines']=[r for r in z['lines'] if 'MOST POWERFUL' not in r['text']]
            self.assertFalse(classify_dialog(z,game_text=game_text())['supported'])


class HistoryBindingTests(unittest.TestCase):
    """Portable TEST fixtures exercise source, rank and retained-context binding."""
    SOURCE = ("@HISTORY\n@width=480\n@title=Civilization II\n"
              "^^%STRING1 completes his epic history:\n^^'The %STRING2 Civilizations in the World'\n"
              "@HISTORIANS\n1\nTEST Historian\n@HISTORIES\nTEST WEALTHIEST\n"
              "@HISTORYRANK\nGlorious\nGreat\nFine\nMediocre\nPuny\nPathetic\nHopeless\n")

    def fixture(self):
        from tests.test_dialogs import row, observation
        return observation(row('Civilization II',y=182,w=90),
            row('TEST Historian completes his epic history:',y=207,w=310),
            row("'The TEST WEAL THIEST Civilizations in the World'",y=230,w=390),
            row('3. The Fine Civilization of the TEST Romans',x=275,y=267,w=380),
            row('OK',y=296,w=24))

    def test_no_legacy_bypass_for_rank_number_or_arbitrary_title(self):
        for index,text in ((3,'3. The Great Civilization of the TEST Romans'),
                           (0,'TEST warning')):
            o=self.fixture();o['lines'][index]['text']=text
            self.assertFalse(classify_dialog(o,game_text=self.SOURCE)['supported'])

    def test_measured_tiny_heading_still_requires_source_body_and_unique_control(self):
        from tests.test_dialogs import row
        o=self.fixture();o['lines'][0]['text']='Cimlivation !'
        d=classify_dialog(o,game_text=self.SOURCE)
        self.assertTrue(d['supported']);self.assertEqual(d['title'],'Cimlivation !')
        for mode in ('body','rank','category','control'):
            z=deepcopy(o)
            if mode=='body':z['lines'][1]['text']='TEST Historian demands tribute:'
            elif mode=='rank':z['lines'][3]['text']='3. The Great Civilization of the TEST Romans'
            elif mode=='category':z['lines'][2]['text']='The TEST unknown civilizations'
            else:z['lines'].append(row('Cancel',y=296,w=50))
            self.assertFalse(classify_dialog(z,game_text=self.SOURCE)['supported'],mode)

    def test_actual_history_template_is_required_not_only_catalogs(self):
        for source in (self.SOURCE[self.SOURCE.index('@HISTORIANS'):],
                       self.SOURCE.replace('completes his epic history:', 'demands payment:'),
                       self.SOURCE.replace('@width=480','@width=320'),
                       self.SOURCE.replace('@HISTORIANS','\nPay 100 gold.\n@HISTORIANS',1)):
            self.assertFalse(classify_dialog(self.fixture(),game_text=source)['supported'])

    def test_conflicting_ocr_and_extra_foreground_prose_are_not_acknowledged(self):
        from tests.test_dialogs import row
        o=self.fixture();o['ocr']={'conflicts':[{'text':'TEST conflicting choice'}]}
        self.assertFalse(classify_dialog(o,game_text=self.SOURCE)['supported'])
        o=self.fixture();o['lines'].append(row('Pay TEST gold',y=248,w=100))
        self.assertFalse(classify_dialog(o,game_text=self.SOURCE)['supported'])

    def test_partial_public_ranking_remains_partial_and_reaches_session_memory(self):
        import hashlib
        import tempfile
        from PIL import Image,ImageDraw
        from civ2.evidence import Journal
        from tests.test_session import session
        with tempfile.TemporaryDirectory() as directory:
            s=session();s.journal=Journal(Path(directory)/'TEST-history');s.checkpoints=1
            self.addCleanup(s.journal.close)
            path=s.journal.directory/'screens'/'TEST-history.png';path.parent.mkdir(exist_ok=True)
            image=Image.new('RGB',(640,480),'white');ImageDraw.Draw(image).text((5,5),'TEST fixture',fill='black');image.save(path)
            o=self.fixture();o.update(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            d=classify_dialog(o,game_text=self.SOURCE)
            self.assertEqual(d['evidence']['history_report']['source'],
                'Original HISTORY, HISTORIANS, HISTORIES and HISTORYRANK resources')
            notice=s.remember_public_notice(o,d,self.SOURCE)
            self.assertIsNotNone(notice)
            self.assertIn('3. The Fine',notice['observed_text'])
            self.assertNotIn('1. The',notice['observed_text'])
            self.assertNotIn('2. The',notice['observed_text'])
            s.game.rpc.assert_not_called();s.game.click.assert_not_called()
            s.journal.close()

    def test_same_pixel_crop_cannot_replace_printed_rank_number(self):
        from unittest.mock import patch
        from PIL import Image
        from civ2 import observe
        def prepared(text,y):
            return dict(text=text,confidence=1.,center=[220,y],bounds=[80,y-7,280,14],
                        provenance=[{'preprocessing':'TEST'}])
        header=prepared('TEST Historian completes his epic history:',207)
        original=prepared('3. The Fine Civilization of the TEST Romans',267)
        changed=prepared('2. The Great Civilization of the TEST Romans',267)
        rows=[header,original];before=deepcopy(rows)
        with patch.object(observe,'_crop_text',side_effect=[[deepcopy(header)],[deepcopy(header)],
                                                         [deepcopy(changed)],[deepcopy(changed)]]):
            observe._recover_history_rows(Image.new('RGB',(640,480)),rows,None,None,{'passes':[]})
        self.assertEqual(rows[1],before[1])
