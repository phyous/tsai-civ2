"""Legacy foreground exceptions require explicit, exact retained-image review."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageDraw
from civ2.evidence import canonical
from civ2.trade_recheck import recheck_foreground
from civ2.verify import Files, VerificationError, _trade_pending, verify_run
from test_verify_trade import TradeEvidenceTests


class TradeForegroundTests(unittest.TestCase):
    def test_portable_default_never_runs_ocr_and_opt_in_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            e=TradeEvidenceTests().make(directory)
            q=json.loads((e.directory/'decisions/request.json').read_text())
            original=q['state']['mandatory_dialog']['observed_text']
            q['state']['mandatory_dialog']['observed_text']='S2\n'+original
            e.change_artifact('decisions/request.json',q)
            proof={'image_sha256':e.screen['sha256'],'resource_tag':'EXCHANGE0'}
            with patch('civ2.trade_recheck.recheck_foreground',return_value=(original,proof)) as reader:
                with self.assertRaisesRegex(VerificationError,'explicit'):
                    verify_run(e.directory,ffprobe=None)
                reader.assert_not_called()
                report=verify_run(e.directory,ffprobe=None,recheck_trade_ocr=True)
                reader.assert_called_once()
                self.assertEqual(len(report['decisions']['retained_trade_ocr_rechecks']),1)
                self.assertTrue(any('opt-in' in line for line in report['limitations']))

    def test_rechecked_text_may_change_only_one_offered_name_glyph(self):
        for case in ('one_edit','two_edits','terms','option','missing_body'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                e=TradeEvidenceTests().make(directory)
                q=json.loads((e.directory/'decisions/request.json').read_text())
                original=q['state']['mandatory_dialog']['observed_text']
                changed=original.replace('discovered TEST Advance.','discovered TEST Adlvance.')
                if case=='two_edits':changed=changed.replace('TEST Adlvance.','TEST Adllvance.')
                if case=='terms':changed=changed.replace('secret of Alphabet','price of Alphabet')
                if case=='option':changed=changed.replace('No. We do not need','No. We need')
                if case=='missing_body':changed='\n'.join(changed.splitlines()[1:])
                q['state']['mandatory_dialog']['observed_text']='S2\n'+changed
                e.change_artifact('decisions/request.json',q)
                with patch('civ2.trade_recheck.recheck_foreground',return_value=(changed,{})):
                    if case=='one_edit':
                        report=verify_run(e.directory,ffprobe=None,recheck_trade_ocr=True)
                        self.assertTrue(report['decisions']['retained_trade_ocr_rechecks'][0]['offered_body_one_edit'])
                    else:
                        with self.assertRaises(VerificationError):verify_run(e.directory,ffprobe=None,recheck_trade_ocr=True)

    def test_exact_frame_rows_source_text_and_controls_are_required(self):
        from contextlib import ExitStack
        def row(text,x,y,w,h):
            return dict(text=text,confidence=1,bounds=[x,y,w,h],center=[x+w//2,y+h//2])
        for case in ('valid','crossing','beside','exterior_control','frame','text','center','source','unsupported','hash'):
            with self.subTest(case=case),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'source.png';image=Image.new('RGB',(640,480),(207,207,207))
                ImageDraw.Draw(image).rectangle((298,252,639,478),outline=(0,0,0))
                if case=='frame':image.putpixel((298,350),(1,1,1))
                image.save(path);source=hashlib.sha256(path.read_bytes()).hexdigest()
                lines=[row('S2',518,58,42,40),row('Neutral TEST Emissary',390,260,170,16),
                       row('TEST complete body',310,300,180,16),row('TEST decline',340,372,160,16),
                       row('TEST accept',340,397,160,16),row('OK',456,454,26,16)]
                if case=='crossing':lines[0]['bounds']=[518,245,42,40]
                if case=='beside':lines[0]['bounds']=[50,300,42,40]
                if case=='exterior_control':lines[0]['text']='Cancel'
                observation=dict(width=640,height=480,sha256=source,lines=lines)
                dialog=dict(title=lines[1]['text'],observed_text='\n'.join(r['text'] for r in lines),options=['TEST decline','TEST accept'])
                action={'parameters':{'center':[420,405]}}
                classified=dict(supported=True,requires_model=True,kind='diplomacy',resource_tag='EXCHANGE0',
                    title=dialog['title'],visible_text=dialog['observed_text'],options=[{'text':s,'center':[420,405]} for s in dialog['options']])
                if case=='text':classified['visible_text']='changed body'
                if case=='center':classified['options'][1]['center']=[421,405]
                if case=='unsupported':classified['supported']=False
                if case=='hash':observation['sha256']='0'*64
                resource={'tag':'EXCHANGE0'};game='TEST source';game_hash=hashlib.sha256(game.encode()).hexdigest()
                if case=='source':game_hash='0'*64
                with ExitStack() as stack:
                    stack.enter_context(patch('civ2.gdi_text._sources',return_value=(game,'')))
                    stack.enter_context(patch('civ2.dialogs.dialog_resources',return_value=[resource]))
                    stack.enter_context(patch('civ2.trade_recheck.SOURCE_PINS',{'EXCHANGE0':hashlib.sha256(canonical(resource)).hexdigest()}))
                    stack.enter_context(patch('civ2.observe.recognize',return_value=observation))
                    stack.enter_context(patch('civ2.dialogs.classify_dialog',return_value=classified))
                    if case=='valid':
                        text,proof=recheck_foreground(path,source,dialog,action,'EXCHANGE0',game_hash)
                        self.assertNotIn('S2',text);self.assertEqual(proof['excluded_above_window_rows'],1)
                    else:
                        with self.assertRaises(ValueError):recheck_foreground(path,source,dialog,action,'EXCHANGE0',game_hash)

    def test_actual_011_requests_reproduce_foreground_without_rewriting_evidence(self):
        from civ2.compact import expand_model_state
        root=Path('runs/attempt-011')
        if not (root/'decisions/000544-request.json').is_file():self.skipTest('Private retained exchange evidence unavailable')
        events=[json.loads(line) for line in (root/'events.jsonl').read_text().splitlines()]
        files=Files(root,recheck_trade_ocr=True)
        for ident in (535,544):
            event=next(e for e in events if e['kind']=='trade_followup_pending' and e['payload']['prior_trade']['decision']==ident)
            decision=deepcopy(next(e['payload'] for e in events if e['kind']=='model_decision' and e['payload']['decision']==ident))
            decision['question']=decision['selected_question']
            path=root/f'decisions/{ident:06}-request.json';original=path.read_bytes();request=json.loads(original)
            request['state']=expand_model_state(request['state'])
            source=decision['action']['preconditions']['image_sha256']
            checked=_trade_pending(event['payload'],decision,request,files,{source:{'classification':'diplomacy','supported':True}})
            self.assertEqual(checked,event['payload']['prior_trade']);self.assertEqual(path.read_bytes(),original)
            self.assertEqual(files.trade_ocr_rechecks[-1]['offered_body_one_edit'],ident==544)
            self.assertEqual(files.trade_ocr_rechecks[-1]['excluded_above_window_rows'],int(ident==535))


if __name__=='__main__':unittest.main()
