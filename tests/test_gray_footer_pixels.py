"""Exact whole-crop evidence only; no reconstruction of absent glyph pixels."""
from copy import deepcopy
import hashlib
from pathlib import Path
from unittest import TestCase,mock
from PIL import Image
from civ2 import footer_pixels as footer
from civ2.observe import recognize


class FooterPixelsTests(TestCase):
    def test_higher_layout_uses_complete_wider_crop_and_exact484_glyphs(self):
        paths=[Path('runs/attempt-011/screens/ui-0002312.png'),Path('runs/attempt-011/screens/ui-0002356.png'),
               Path('runs/attempt-011/screens/ui-0000503.png')]
        if not all(p.exists() for p in paths):self.skipTest('Private original calibration unavailable')
        white,gray=[Image.open(p).convert('RGB').crop(footer.HIGH_CROP) for p in paths[:2]]
        self.assertEqual(hashlib.sha256(paths[0].read_bytes()).hexdigest(),footer.HIGH_WHITE_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(paths[1].read_bytes()).hexdigest(),footer.HIGH_GRAY_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(white.tobytes()).hexdigest(),footer.HIGH_WHITE_CROP_SHA256)
        self.assertEqual(hashlib.sha256(gray.tobytes()).hexdigest(),footer.HIGH_GRAY_CROP_SHA256)
        self.assertEqual([(a,b) for a,b in zip(white.getdata(),gray.getdata()) if a!=b],
                         [((255,255,255),(134,134,134))]*484)
        glyphs=lambda im:{(i%im.width,i//im.width) for i,p in enumerate(im.getdata()) if p==(255,255,255)}
        prior=Image.open(paths[2]).convert('RGB').crop(footer.HIGH_CROP)
        self.assertEqual(glyphs(white),{(x,y-6) for x,y in glyphs(prior)})
        o=recognize(paths[1]);lines=[r for r in o['lines'] if r['bounds'][0]>=466 and r['center'][1]>436]
        self.assertEqual([r['text'] for r in lines],['End of Turn','(Press ENTER)'])
        self.assertEqual([r['bounds'][1] for r in lines],[439,451])
        self.assertTrue(all(r['provenance'][0]['crop']==list(footer.HIGH_CROP) for r in lines))

    def test_higher_variant_rejects_changes_and_text_outside_its_entire_crop(self):
        image=Image.new('RGB',(640,480),(91,92,93));digest=hashlib.sha256(image.crop(footer.HIGH_CROP).tobytes()).hexdigest()
        with mock.patch.object(footer,'HIGH_GRAY_CROP_SHA256',digest):
            rows=[dict(text='TEST row',bounds=[478,438,62,13],confidence=.4)]
            self.assertTrue(footer.annotate_footer(image,rows,'a'*64))
            self.assertEqual([r['bounds'][1] for r in rows],[439,451])
            crossing=[dict(text='TEST crosses',bounds=[478,432,62,13],confidence=.4)]
            self.assertFalse(footer.annotate_footer(image,crossing,'a'*64))
            image.putpixel((480,438),(0,0,0))
            self.assertFalse(footer.annotate_footer(image,[],'a'*64))

    def test_bottom_pair_binds_crop_and_complete_unchanged_glyphs(self):
        base=Path('runs/attempt-012/screens')
        whites=list(base.glob('native-map-003126-*-1.png'))
        grays=list(base.glob('native-map-current-003126-*.png'))
        prior=Path('runs/attempt-011/screens/ui-0000503.png')
        if len(whites)!=1 or len(grays)!=1 or not prior.exists():self.skipTest('Private original calibration unavailable')
        white,gray=[Image.open(p).convert('RGB').crop(footer.CROP) for p in (whites[0],grays[0])]
        self.assertEqual(hashlib.sha256(whites[0].read_bytes()).hexdigest(),footer.BOTTOM_WHITE_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(grays[0].read_bytes()).hexdigest(),footer.BOTTOM_GRAY_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(white.tobytes()).hexdigest(),footer.BOTTOM_WHITE_CROP_SHA256)
        self.assertEqual(hashlib.sha256(gray.tobytes()).hexdigest(),footer.BOTTOM_GRAY_CROP_SHA256)
        self.assertEqual([(a,b) for a,b in zip(white.getdata(),gray.getdata()) if a!=b],
                         [((255,255,255),(134,134,134))]*484)
        glyphs=lambda im:{(i%im.width,i//im.width) for i,p in enumerate(im.getdata()) if p==(255,255,255)}
        original=Image.open(prior).convert('RGB').crop(footer.CROP)
        self.assertEqual(glyphs(white),{(x,y+4) for x,y in glyphs(original)})
        self.assertIn((footer.CROP,footer.BOTTOM_GRAY_CROP_SHA256,footer.BOTTOM_WHITE_CROP_SHA256),footer.FOOTER_BLINK_CALIBRATIONS)
        rows=[];self.assertTrue(footer.annotate_footer(Image.open(grays[0]).convert('RGB'),rows,footer.BOTTOM_GRAY_SOURCE_SHA256))
        self.assertEqual([r['bounds'][1] for r in rows],[449,461])
        image=Image.open(grays[0]).convert('RGB');image.putpixel((480,450),(0,0,0))
        self.assertFalse(footer.annotate_footer(image,[],'a'*64))

    def test_complete_match_keeps_prior_readings_and_other_screen_text(self):
        image=Image.new('RGB',(640,480),(91,92,93)) # Explicit synthetic TEST calibration.
        digest=hashlib.sha256(image.crop(footer.CROP).tobytes()).hexdigest()
        old=dict(text='TEST OCR disagreement',bounds=[478,445,60,12],confidence=.4,provenance=[{'text':'TEST'}])
        other=dict(text='TEST foreign modal',bounds=[100,100,120,20],confidence=1.)
        rows=[old,other]
        with mock.patch.object(footer,'GRAY_CROP_SHA256',digest):
            self.assertTrue(footer.annotate_footer(image,rows,'a'*64))
        self.assertIs(rows[0],other)
        self.assertEqual([r['text'] for r in rows[1:]],['End of Turn','(Press ENTER)'])
        for r in rows[1:]:
            p=r['provenance'][0]
            self.assertEqual(p['prior_readings'][0],old)
            self.assertEqual(p['image_sha256'],'a'*64)
            self.assertEqual(p['crop_rgb_sha256'],digest)

    def test_missing_or_altered_crop_wrong_size_and_crossing_text_refuse(self):
        base=Image.new('RGB',(640,480),(91,92,93));digest=hashlib.sha256(base.crop(footer.CROP).tobytes()).hexdigest()
        for mode in ('pixel','missing','size','crossing'):
            with self.subTest(mode=mode):
                image=base.copy();rows=[]
                if mode=='pixel':image.putpixel((480,450),(0,0,0))
                elif mode=='missing':image.paste((0,0,0),footer.CROP)
                elif mode=='size':image=image.resize((1280,960))
                else:rows=[dict(text='TEST crosses footer',bounds=[450,445,60,12],confidence=1.)]
                before=deepcopy(rows)
                with mock.patch.object(footer,'GRAY_CROP_SHA256',digest):
                    self.assertFalse(footer.annotate_footer(image,rows,'a'*64))
                self.assertEqual(rows,before)

    def test_actual_white_and_gray_original_frames_differ_only_in_glyph_color(self):
        a=Path('runs/attempt-011/screens/ui-0000503.png');b=Path('runs/attempt-011/screens/ui-0000576.png')
        if not a.exists() or not b.exists():self.skipTest('Private original calibration unavailable')
        self.assertEqual(hashlib.sha256(a.read_bytes()).hexdigest(),footer.WHITE_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(b.read_bytes()).hexdigest(),footer.GRAY_SOURCE_SHA256)
        white=Image.open(a).convert('RGB').crop(footer.CROP);gray=Image.open(b).convert('RGB').crop(footer.CROP)
        self.assertEqual(hashlib.sha256(white.tobytes()).hexdigest(),footer.WHITE_CROP_SHA256)
        self.assertEqual(hashlib.sha256(gray.tobytes()).hexdigest(),footer.GRAY_CROP_SHA256)
        changes=[(p,q) for p,q in zip(white.getdata(),gray.getdata()) if p!=q]
        self.assertEqual(changes,[((255,255,255),(134,134,134))]*484)
        o=recognize(b);lines=[r for r in o['lines'] if r['center'][1]>440]
        self.assertEqual([r['text'] for r in lines],['End of Turn','(Press ENTER)'])
        self.assertIn('exact_original_gray_footer_rgb_sha256',o['ocr']['passes'])

    def test_upper_layout_exact_source_pair_preserves_all484_glyphs(self):
        paths=[Path('runs/attempt-010/screens/ui-0001834.png'),Path('runs/attempt-010/screens/ui-0001855.png'),
               Path('runs/attempt-011/screens/ui-0000503.png')]
        if not all(p.exists() for p in paths):self.skipTest('Private original calibration unavailable')
        white,gray,prior=[Image.open(p).convert('RGB').crop(footer.CROP) for p in paths]
        self.assertEqual(hashlib.sha256(paths[0].read_bytes()).hexdigest(),footer.UPPER_WHITE_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(paths[1].read_bytes()).hexdigest(),footer.UPPER_GRAY_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(white.tobytes()).hexdigest(),footer.UPPER_WHITE_CROP_SHA256)
        self.assertEqual(hashlib.sha256(gray.tobytes()).hexdigest(),footer.UPPER_GRAY_CROP_SHA256)
        changed=[(a,b) for a,b in zip(white.getdata(),gray.getdata()) if a!=b]
        self.assertEqual(changed,[((255,255,255),(134,134,134))]*484)
        glyphs=lambda image:{(i%image.width,i//image.width) for i,p in enumerate(image.getdata()) if p==(255,255,255)}
        self.assertEqual(glyphs(white),{(x,y-4) for x,y in glyphs(prior)})
        o=recognize(paths[1]);lines=[r for r in o['lines'] if r['bounds'][0]>=466 and r['center'][1]>440]
        self.assertEqual([r['text'] for r in lines],['End of Turn','(Press ENTER)'])
        self.assertEqual([r['bounds'][1] for r in lines],[441,453])

    def test_upper_variant_refuses_any_altered_pixel(self):
        image=Image.new('RGB',(640,480),(91,92,93));digest=hashlib.sha256(image.crop(footer.CROP).tobytes()).hexdigest()
        rows=[]
        with mock.patch.object(footer,'UPPER_GRAY_CROP_SHA256',digest):
            self.assertTrue(footer.annotate_footer(image,rows,'a'*64))
            self.assertEqual([r['bounds'][1] for r in rows],[441,453])
            image.putpixel((480,450),(0,0,0))
            self.assertFalse(footer.annotate_footer(image,[],'a'*64))

    def test_lower_layout_exact_pair_preserves_all484_glyphs(self):
        paths=[Path('runs/attempt-011/screens/ui-0001896.png'),Path('runs/attempt-011/screens/ui-0001917.png'),
               Path('runs/attempt-011/screens/ui-0000503.png')]
        if not all(p.exists() for p in paths):self.skipTest('Private original calibration unavailable')
        white,gray,prior=[Image.open(p).convert('RGB').crop(footer.CROP) for p in paths]
        self.assertEqual(hashlib.sha256(paths[0].read_bytes()).hexdigest(),footer.LOWER_WHITE_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(paths[1].read_bytes()).hexdigest(),footer.LOWER_GRAY_SOURCE_SHA256)
        self.assertEqual(hashlib.sha256(white.tobytes()).hexdigest(),footer.LOWER_WHITE_CROP_SHA256)
        self.assertEqual(hashlib.sha256(gray.tobytes()).hexdigest(),footer.LOWER_GRAY_CROP_SHA256)
        self.assertEqual([(a,b)for a,b in zip(white.getdata(),gray.getdata())if a!=b],
                         [((255,255,255),(134,134,134))]*484)
        glyphs=lambda im:{(i%im.width,i//im.width)for i,p in enumerate(im.getdata())if p==(255,255,255)}
        self.assertEqual(glyphs(white),{(x,y+2)for x,y in glyphs(prior)})
        o=recognize(paths[1]);lines=[r for r in o['lines'] if r['bounds'][0]>=466 and r['center'][1]>440]
        self.assertEqual([r['text']for r in lines],['End of Turn','(Press ENTER)'])
        self.assertEqual([r['bounds'][1]for r in lines],[447,459])

    def test_lower_variant_rejects_changed_pixels_and_crossing_rows(self):
        image=Image.new('RGB',(640,480),(91,92,93));digest=hashlib.sha256(image.crop(footer.CROP).tobytes()).hexdigest()
        with mock.patch.object(footer,'LOWER_GRAY_CROP_SHA256',digest):
            rows=[];self.assertTrue(footer.annotate_footer(image,rows,'a'*64))
            self.assertEqual([r['bounds'][1]for r in rows],[447,459])
            crossing=[dict(text='TEST crosses crop',bounds=[450,445,60,12],confidence=1.)]
            self.assertFalse(footer.annotate_footer(image,crossing,'a'*64))
            image.putpixel((480,450),(0,0,0))
            self.assertFalse(footer.annotate_footer(image,[],'a'*64))
