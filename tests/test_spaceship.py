"""Source/synthetic spaceship choice proof, with no live calibration claim."""
from copy import deepcopy
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile
from PIL import Image,ImageDraw
from civ2.dialogs import _rows,classify_dialog,dialog_resources
from civ2.evidence import canonical
from civ2.gdi_text import WHITE_RING,BLACK_RING
from civ2.spaceship import SOURCES,SOURCE_HASHES,OPTION_LINES,classify_spaceship


GAME='\n'.join('@'+tag+'\n@width=320\n@title='+s['title']+'\n'+
    ('@options\n'+'\n'.join(OPTION_LINES[tag]) if tag in OPTION_LINES else
     'Confirm spaceship launch.\n(%NUMBER0%% chance of success)\n\n'+'\n'.join(s['options']))+'\n'
    for tag,s in SOURCES.items())


def fixture(directory,tag='COMPONENT',probability=100):
    def row(text,x,y,w=190,h=16):
        return dict(text=text,bounds=[x,y,w,h],center=[x+w//2,y+h//2],confidence=1.)
    title=SOURCES[tag]['title'];rows=[row(title,220,140,200)]
    if tag=='COMPONENT':names=['Propulsion (7 so far)','Fuel (6 so far)'];ys=[184,209]
    elif tag=='MODULE':names=['Habitation (1 so far)','Life Support (0 so far)','Solar Panel (2 so far)'];ys=[184,209,234]
    else:
        rows.extend([row('Confirm spaceship launch.',160,173,260),row(f'({probability}% chance of success)',160,196,260)])
        names=SOURCES[tag]['options'];ys=[237,262]
    rows.extend(row(name,193,y-8) for name,y in zip(names,ys))
    by=ys[-1]+37;rows.append(row('OK',308,by,24));bottom=by+27
    image=Image.new('RGB',(640,480),(130,130,130));draw=ImageDraw.Draw(image)
    draw.rectangle((149,132,490,bottom),fill=(160,160,160),outline=(0,0,0))
    draw.line((150,133,488,133),fill=(223,223,223));draw.line((489,134,489,bottom-1),fill=(65,65,65))
    for y in ys:
        for dx,dy in WHITE_RING:image.putpixel((173+dx,y+dy),(255,255,255))
        for dx,dy in BLACK_RING:image.putpixel((173+dx,y+dy),(0,0,0))
    path=Path(directory)/'ship.png';image.save(path)
    return dict(width=640,height=480,path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest(),lines=rows)


class SpaceshipChoices(unittest.TestCase):
    def classify(self,o,text=GAME):
        return classify_spaceship(o,_rows(o),dialog_resources(text),text)

    def test_every_component_module_and_launch_choice_remains_a_real_model_option(self):
        self.assertEqual(dialog_resources(GAME),list(SOURCES.values()))
        for tag in SOURCES:
            with self.subTest(tag=tag),TemporaryDirectory() as directory:
                o=fixture(directory,tag);before=deepcopy(o);result=self.classify(o)
                self.assertIsNotNone(result);self.assertTrue(result['requires_model']);self.assertIsNone(result['mechanical_action'])
                count=3 if tag=='MODULE' else 2
                self.assertEqual(len(result['options']),count);self.assertTrue(all(r['control']=='option' for r in result['options']))
                self.assertNotIn('OK',[r['text'] for r in result['options']]);self.assertEqual(o,before)
                evidence=result['evidence']['spaceship_choice']
                self.assertEqual(evidence['pixels']['complete_observed_radio_count'],count)
                self.assertIn('not live calibrated',evidence['pixels']['calibration'])
                if tag=='LAUNCH':
                    self.assertEqual(evidence['details']['observed_success_percent'],100)
                    self.assertFalse(evidence['details']['launch_executed'])
                else:
                    self.assertTrue(evidence['options_directive_verified']);self.assertFalse(evidence['details']['allocation_executed'])
                    self.assertEqual(len(evidence['details']['observed_counts']),count)

    def test_source_records_options_directives_and_source_order_are_required(self):
        for tag in SOURCES:
            with self.subTest(tag=tag),TemporaryDirectory() as directory:
                o=fixture(directory,tag)
                self.assertIsNone(self.classify(o,GAME.replace(SOURCES[tag]['title'],SOURCES[tag]['title']+' altered')))
                self.assertIsNone(self.classify(o,GAME.replace('@width=320','@width=321')))
                if tag in OPTION_LINES:
                    # Generic resources are unchanged by removing @options;
                    # the additional raw source proof must still reject it.
                    stripped=GAME.replace('@options\n','')
                    self.assertEqual(dialog_resources(stripped),dialog_resources(GAME))
                    self.assertIsNone(self.classify(o,stripped))
                    self.assertIsNone(self.classify(o,GAME+'\n@'+tag+'\n'))

    def test_counts_and_probability_must_be_complete_observed_numbers(self):
        for tag,text in [('COMPONENT','Propulsion (7 so tar)'),('MODULE','Habitation (? so far)'),
                         ('LAUNCH','(101% chance of success)'),('LAUNCH','(100 chance of success)')]:
            with self.subTest(tag=tag,text=text),TemporaryDirectory() as directory:
                o=fixture(directory,tag);index=2 if tag=='LAUNCH' else 1;o['lines'][index]['text']=text
                self.assertIsNone(self.classify(o))
        for number in (0,37,100):
            with TemporaryDirectory() as directory:
                result=self.classify(fixture(directory,'LAUNCH',number))
                self.assertEqual(result['evidence']['spaceship_choice']['details']['observed_success_percent'],number)

    def test_missing_choice_extra_control_low_confidence_and_extra_prose_fail_closed(self):
        for tag in SOURCES:
            for mode in ('missing','extra','control','weak','swapped','duplicate','conflict'):
                with self.subTest(tag=tag,mode=mode),TemporaryDirectory() as directory:
                    o=fixture(directory,tag);index=3 if tag=='LAUNCH' else 1
                    if mode=='missing':o['lines'].pop(index)
                    elif mode=='extra':o['lines'].insert(index,dict(o['lines'][index],text='Spend 100 gold.'))
                    elif mode=='control':o['lines'].append(dict(o['lines'][-1],text='Cancel'))
                    elif mode=='weak':o['lines'][index]['confidence']=.79
                    elif mode=='swapped':o['lines'][index]['text'],o['lines'][index+1]['text']=o['lines'][index+1]['text'],o['lines'][index]['text']
                    elif mode=='duplicate':o['lines'].append(deepcopy(o['lines'][0]))
                    else:o['ocr']={'conflicts':[{'reason':'unresolved OCR'}]}
                    self.assertIsNone(self.classify(o))

    def test_png_hash_complete_frame_and_independent_radio_count_are_mandatory(self):
        for mode in ('hash','frame','radio','extra_radio','partial_bounds'):
            with self.subTest(mode=mode),TemporaryDirectory() as directory:
                o=fixture(directory);p=Path(o['path'])
                if mode=='hash':o['sha256']='a'*64
                elif mode=='partial_bounds':o['lines'][1]['bounds'][0]=140
                else:
                    image=Image.open(p).convert('RGB')
                    if mode=='frame':image.putpixel((149,132),(160,160,160))
                    elif mode=='radio':image.putpixel((173,176),(160,160,160))
                    else:
                        for dx,dy in WHITE_RING:image.putpixel((230+dx,185+dy),(255,255,255))
                        for dx,dy in BLACK_RING:image.putpixel((230+dx,185+dy),(0,0,0))
                    image.save(p);o['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
                self.assertIsNone(self.classify(o))

    def test_hook_and_canonical_actions_preserve_both_launch_decisions(self):
        from civ2.policy import dialog_request_for,validate_action
        for tag in SOURCES:
            with self.subTest(tag=tag),TemporaryDirectory() as directory:
                o=fixture(directory,tag);d=classify_dialog(o,game_text=GAME)
                self.assertTrue(d['supported'],d);self.assertTrue(d['requires_model']);self.assertIsNone(d['outcome'])
                request,actions=dialog_request_for({},d)
                self.assertEqual(list(request['questions']['dialog_action']['criteria'].values()),[r['text'] for r in d['options']])
                for index,action in enumerate(actions.values()):
                    self.assertEqual(action['parameters']['option_index'],index)
                    self.assertEqual(action['preconditions']['image_sha256'],o['sha256'])
                    validate_action(action,{},dialog=d)

    def test_original_private_source_agrees_with_every_public_pin(self):
        for tag,source in SOURCES.items():self.assertEqual(hashlib.sha256(canonical(source)).hexdigest(),SOURCE_HASHES[tag])
        path=Path('engine/game/civ2-win31.zip')
        if not path.exists():self.skipTest('Private original source unavailable')
        with ZipFile(path) as z:text=z.read('civ2/GAME.TXT').decode('cp1252')
        for tag,source in SOURCES.items():
            self.assertEqual([r for r in dialog_resources(text) if r['tag']==tag],[source])
            with TemporaryDirectory() as directory:self.assertIsNotNone(self.classify(fixture(directory,tag),text))


if __name__=='__main__':unittest.main()
