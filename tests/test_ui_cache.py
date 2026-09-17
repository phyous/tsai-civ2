import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from civ2.ui import UI


def png(color):
    output=io.BytesIO();Image.new('RGB',(640,480),color).save(output,format='PNG');return output.getvalue()


class Capture:
    def __init__(self):self.data=png('white');self.calls=0
    def capture(self,path):self.calls+=1;Path(path).write_bytes(self.data)


class RecognitionCacheTests(unittest.TestCase):
    def setUp(self):
        self.directory=tempfile.TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        self.game=Capture();self.ui=UI(self.game,self.directory.name)
    def recognize(self,path):
        return dict(width=640,height=480,sha256=hashlib.sha256(Path(path).read_bytes()).hexdigest(),
                    lines=[dict(text='End of Turn')],text='End of Turn',ocr=dict(fallback_errors=[]))
    def test_capture_is_always_fresh_and_cached_result_is_isolated(self):
        with patch('civ2.ui.recognize',side_effect=self.recognize) as ocr:
            first=self.ui.observe();first['lines'][0]['text']='mutated';first['cursor_hotspot']=[1,1]
            second=self.ui.observe()
            self.assertEqual(self.game.calls,2);self.assertEqual(ocr.call_count,1)
            self.assertNotEqual(first['path'],second['path'])
            self.assertEqual(second['lines'][0]['text'],'End of Turn')
            self.assertNotIn('cursor_hotspot',second)
            self.assertIs(self.ui.latest,second)
            self.game.data=png('black');third=self.ui.observe()
            self.assertEqual(ocr.call_count,2);self.assertNotEqual(second['sha256'],third['sha256'])
    def test_fallback_failure_not_cached(self):
        def failing(path):
            result=self.recognize(path);result['ocr']['fallback_errors']=['transient'];return result
        with patch('civ2.ui.recognize',side_effect=failing) as ocr:
            self.ui.observe();self.ui.observe();self.assertEqual(ocr.call_count,2)
    def test_changed_recognizer_not_cached(self):
        with patch('civ2.ui.recognize',side_effect=self.recognize):self.ui.observe()
        with patch('civ2.ui.recognize',side_effect=self.recognize) as replacement:
            self.ui.observe();replacement.assert_called_once()
    def test_hash_mismatch_rejected(self):
        with patch('civ2.ui.recognize',return_value={'sha256':'0'*64}):
            with self.assertRaisesRegex(ValueError,'differs'):self.ui.observe()
        self.assertFalse(self.ui._recognition_cache)
    def test_cache_is_bounded(self):
        with patch('civ2.ui.recognize',side_effect=self.recognize) as ocr:
            for value in range(17):
                self.game.data=png((value,0,0));self.ui.observe()
            self.assertEqual(len(self.ui._recognition_cache),16)
            self.game.data=png((0,0,0));self.ui.observe();self.assertEqual(ocr.call_count,18)

if __name__=='__main__':unittest.main()
