"""A forced exchange continuation needs both native singleton and prior choice proof."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from PIL import Image,ImageDraw
from civ2.dialogs import _rows,dialog_resources
from civ2.exchange_picker import ACCEPT, accepted_trade_context, classify_exchange_picker

SOURCE='@TAKECIV\n@width=320\n@title=Select Civilization Advance\n@listbox\n@button=Goal\n'


def fixture(directory):
    path=Path(directory)/'frame.png';image=Image.new('RGB',(640,480),(150,150,150));draw=ImageDraw.Draw(image)
    draw.rectangle((309,170,628,439),fill=(65,65,65))
    draw.rectangle((310,186,627,439),fill=(207,207,207))
    draw.rectangle((580,170,626,182),fill=(105,105,105));image.save(path)
    def row(text,x,y,w,h):return {'text':text,'bounds':[x,y,w,h],'center':[x+w//2,y+h//2],'confidence':1.}
    observation={'width':640,'height':480,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'path':str(path),
      'lines':[row('Select Ciadization Advance',384,146,168,16),row('TEST Advance',310,170,94,15),
               row('Goal',372,454,30,14),row('OK',538,454,25,12)]}
    return observation,{'advances':[{'id':12,'name':'TEST Advance'}]},dialog_resources(SOURCE)


class ExchangePickerTests(TestCase):
    def test_case_only_rule_binding_preserves_raw_label_and_rejects_ambiguity(self):
        for case in ('case','spacing','glyph','unicode','ambiguous'):
            with self.subTest(case=case),TemporaryDirectory() as directory:
                o,rules,resources=fixture(directory);o['lines'][1]['text']='TEST advance'
                if case=='spacing':o['lines'][1]['text']='TEST  advance'
                if case=='glyph':o['lines'][1]['text']='TEST advanee'
                if case=='unicode':o['lines'][1]['text']='TEſT advance'
                if case=='ambiguous':rules['advances'].append({'id':99,'name':'TEST ADVANCE'})
                result=classify_exchange_picker(o,_rows(o),resources,rules)
                if case=='case':
                    self.assertEqual(result['options'][0]['text'],'TEST advance')
                    self.assertEqual(result['advance'],{'id':12,'name':'TEST Advance'})
                    self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
                else:self.assertIsNone(result)

    def test_singleton_is_observation_proof_never_a_mechanical_permission(self):
        with TemporaryDirectory() as directory:
            o,rules,resources=fixture(directory)
            result=classify_exchange_picker(o,_rows(o),resources,rules)
            self.assertEqual(result['advance'],{'id':12,'name':'TEST Advance'})
            self.assertEqual(result['options'][0]['text'],'TEST Advance')
            self.assertTrue(result['evidence']['prior_accepted_trade_required'])
            self.assertIsNone(result['mechanical_action'])
            self.assertTrue(result['requires_model'])
            self.assertEqual(result['title'],'Select Ciadization Advance')

    def test_unread_text_or_scrollbar_or_unselected_row_prevents_singleton_proof(self):
        for point in ((390,205),(628,230),(600,175)):
            with self.subTest(point=point),TemporaryDirectory() as directory:
                o,rules,resources=fixture(directory);path=Path(o['path'])
                image=Image.open(path).convert('RGB');image.putpixel(point,(0,0,0));image.save(path)
                o['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertIsNone(classify_exchange_picker(o,_rows(o),resources,rules))

    def test_unknown_advance_additional_row_source_tamper_and_wrong_hash_fail(self):
        for case in ('unknown','extra','source','hash','caption'):
            with self.subTest(case=case),TemporaryDirectory() as directory:
                o,rules,resources=fixture(directory)
                if case=='unknown':rules['advances'][0]['name']='Other advance'
                elif case=='extra':o['lines'].append(deepcopy(o['lines'][1]))
                elif case=='source':resources[0]['listbox']=False
                elif case=='hash':o['sha256']='0'*64
                else:o['lines'][0]['text']='Select Technology Advance'
                self.assertIsNone(classify_exchange_picker(o,_rows(o),resources,rules))

    def test_optional_original_trade_picker_proves_masonry_only(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        path=Path('runs/attempt-006/screens/ui-0000975.png')
        if not path.exists() or not Path('.runtime/ocr').exists():self.skipTest('Private original capture unavailable')
        original=path.read_bytes();o=recognize(path);o['path']=str(path)
        result=classify_exchange_picker(o,_rows(o),dialog_resources(game_text()),parse_rules(original_rules()))
        self.assertIsNotNone(result)
        self.assertEqual(result['advance']['name'],'Masonry')
        self.assertEqual(path.read_bytes(),original)


class AcceptedTradeTests(TestCase):
    def fixture(self):
        rules={'advances':[{'id':12,'name':'TEST Advance'}]}
        dialog={'id':'diplomacy','kind':'diplomacy','title':'TEST Emissary','supported':True,
                'requires_model':True,'resource_tag':'EXCHANGE0','sha256':'a'*64,
                'options':[{'text':'"No. We do not need TEST Advance."','center':[450,379]},
                           {'text':ACCEPT,'center':[464,403]}]}
        action={'id':'option_1','kind':'dialog_choice','label':ACCEPT,
                'actor':{'kind':'dialog','id':'diplomacy','title':'TEST Emissary'},
                'parameters':{'option_index':1,'observed_text':ACCEPT,'center':[464,403]},
                'preconditions':{'image_sha256':'a'*64,'save_sha256':'b'*64,'turn':49}}
        return rules,dialog,action

    def test_only_prior_accepted_source_exchange_enables_matching_forced_advance(self):
        rules,dialog,action=self.fixture();pending=accepted_trade_context(dialog,action,89,rules)
        self.assertEqual(pending['offered_advance'],{'id':12,'name':'TEST Advance'})
        with TemporaryDirectory() as directory:
            o,rules,resources=fixture(directory)
            classified=classify_exchange_picker(o,_rows(o),resources,rules,{'pending_trade':pending})
            self.assertEqual(classified['mechanical_action'],'accept_single_trade_advance')
            self.assertFalse(classified['requires_model'])
            self.assertEqual(classified['prior_trade']['decision'],89)
            for changes in ({'offered_advance':{'id':5,'name':'Other'}},{'decision':90},
                            {'action_sha256':'0'*64},{'accepted_option_index':0}):
                invalid={**pending,**changes}
                self.assertIsNone(classify_exchange_picker(o,_rows(o),resources,rules,{'pending_trade':invalid})['mechanical_action'])

    def test_decline_counteroffer_wrong_source_stale_image_and_unknown_advance_fail(self):
        for case in ('decline','counteroffer','tag','source_hash','label','unknown'):
            rules,dialog,action=self.fixture()
            if case=='decline':action['parameters']['option_index']=0
            elif case=='counteroffer':action['parameters']['option_index']=2
            elif case=='tag':dialog['resource_tag']='SELLTECH'
            elif case=='source_hash':action['preconditions']['image_sha256']='f'*64
            elif case=='label':action['parameters']['observed_text']='TEST accept something else'
            else:rules['advances'][0]['name']='Other'
            self.assertIsNone(accepted_trade_context(dialog,action,89,rules),case)


class MultipleExchangeTests(TestCase):
    def test_actual_four_advances_preserve_ocr_capitalization(self):
        from civ2.observe import recognize
        from civ2.dialogs import classify_dialog
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        p=Path('runs/attempt-010/screens/ui-0003299.png')
        if not p.exists():self.skipTest('Private original capture absent')
        o=recognize(p);o['path']=str(p)
        result=classify_dialog(o,game_text=game_text(),rules=parse_rules(original_rules()))
        self.assertTrue(result['supported'],result)
        self.assertEqual(result['kind'],'exchange_picker')
        self.assertEqual([r['text'] for r in result['options']],['Construction','Iron working','Polytheism','The Wheel'])
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
        self.assertIn('Iron working',[r['text']for r in o['lines']])

    def fixture(self,directory):
        o,rules,resources=fixture(directory)
        for i,name in ((1,'TEST Second'),(2,'TEST Third')):
            item=deepcopy(o['lines'][1]);item['text']=name;item['bounds'][1]+=17*i;item['center'][1]+=17*i
            o['lines'].insert(1+i,item);rules['advances'].append({'id':12+i,'name':name})
        return o,rules,resources
    def test_every_visible_advance_is_a_real_model_choice(self):
        with TemporaryDirectory() as directory:
            o,rules,resources=self.fixture(directory)
            result=classify_exchange_picker(o,_rows(o),resources,rules,{'pending_trade':{'offered_advance':rules['advances'][0]}})
            self.assertEqual([r['text'] for r in result['options']],['TEST Advance','TEST Second','TEST Third'])
            self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
            self.assertIsNone(result['advance']);self.assertIsNone(result['prior_trade'])
            self.assertFalse(result['evidence']['complete_visible_singleton'])
    def test_missing_row_or_hidden_content_cannot_be_called_complete(self):
        for case in ('missing','duplicate','extra_pixels','scroll'):
            with TemporaryDirectory() as directory:
                o,rules,resources=self.fixture(directory)
                if case=='missing':o['lines'].pop(2)
                elif case=='duplicate':o['lines'][2]['text']=o['lines'][1]['text']
                else:
                    path=Path(o['path']);im=Image.open(path).convert('RGB')
                    im.putpixel((400,245) if case=='extra_pixels' else (628,245),(0,0,0));im.save(path)
                    o['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
                self.assertIsNone(classify_exchange_picker(o,_rows(o),resources,rules))
    def test_actual_original_three_options_remain_independent(self):
        from civ2.observe import recognize
        from civ2.run import game_text
        from civ2.boot import original_rules
        from civ2.save import parse_rules
        p=Path('runs/attempt-010/screens/ui-0000508.png')
        if not p.exists():self.skipTest('Private original capture absent')
        o=recognize(p);o['path']=str(p)
        result=classify_exchange_picker(o,_rows(o),dialog_resources(game_text()),parse_rules(original_rules()))
        self.assertEqual([r['text'] for r in result['options']],['Masonry','Pottery','Warrior Code'])
        self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
