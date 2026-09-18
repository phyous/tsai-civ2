"""Exact native footer pixels, not a fuzzy font or an end-turn action.

The two retained original frames differ in this crop only at 484 pixels:
white (255,255,255) becomes gray (134,134,134). Both lines remain present.
Only the complete unmodified gray RGB crops below are recognized. A second
original layout has the same484 glyph pixels four pixels higher, and another
has them two pixels lower. No game asset
or bitmap is shipped; these are hashes and observed text/bounds.
"""
from copy import deepcopy
import hashlib

CROP=(466,440,640,480)
GRAY_CROP_SHA256='0af9c6d6e79e1d4eaac1451ee5b7e7d00a7b8ddb9bc03b824e128c432223cc6f'
WHITE_CROP_SHA256='ec10470467bfab1f6b2ebed7477e903560635e1459e709f1def9950ebaf1e876'
GRAY_SOURCE_SHA256='ebe3a67179aaac588d86bde0bc6a1f84c0616a3fc29b2fce497521a03198f57c'
WHITE_SOURCE_SHA256='e02fb177e873f6ea4acf243f7da4fa878e0a6897c1925abffe8c85f96bda3377'
LINES=(('End of Turn',(476,445,62,11)),('(Press ENTER)',(479,457,76,12)))
UPPER_GRAY_CROP_SHA256='b3915ba35950564261b5ec4470c3939361eaf79cdef35a11ef63343948802f00'
UPPER_WHITE_CROP_SHA256='076b13aa2d44628216a65516163be69f3a7df17ae4bc6999ec43a16b1549782a'
UPPER_GRAY_SOURCE_SHA256='a4bad2f24613550ca0f87aa6bb09c6d4c3f1c42aa59d4ea7523adcbc2147781c'
UPPER_WHITE_SOURCE_SHA256='e562ac74c7c31bf73e72775c42084b3071ec845cab335110e2277d327930d24f'
LOWER_GRAY_CROP_SHA256='f4471ef79e70f122083dddb33caf4826be2b1fc6d504f278b4fa92f650ca6f67'
LOWER_WHITE_CROP_SHA256='b0f0223f7d73eac968e8cf1b41f1997aa884097051a756dcc77de4710e466110'
LOWER_GRAY_SOURCE_SHA256='1ba9f24c49066273a989bb046ed15a4cf583d94538487d967da6db92c6e91a1b'
LOWER_WHITE_SOURCE_SHA256='f6ec6d1a96ff50312f810bcba3ea682d81201bbc1aba10d53942dfa40d01cba7'
HIGH_CROP=(466,436,640,480)
HIGH_GRAY_CROP_SHA256='15251847501ee8c15891dfa5811bd21d69c24491097c18a1638982652d207624'
HIGH_WHITE_CROP_SHA256='0ebb7c0036fa59b8ec6e425e6b73dc2ea2f1f912584334a303f67b228daff580'
HIGH_GRAY_SOURCE_SHA256='c6463b3bb8765c82cf199e6c8ab0913eea99b5b66e7939bebb55f7771e974915'
HIGH_WHITE_SOURCE_SHA256='8f35ecc8d37179208c2ef7d5041cf8408ec6aaf3f20ebac3038245a3180ad556'

BOTTOM_GRAY_CROP_SHA256='3750d8c95e42ea808f3132ee886260a911bc8bd51f24ddb7036b098cdd04af25'
BOTTOM_WHITE_CROP_SHA256='2b21364b6c20f876f8ebc89537ccf052f47ed3b9c41eaf9c00a28ecfd09079db'
BOTTOM_GRAY_SOURCE_SHA256='62f821a7f962ef2592901726a7060deae6682930e6266e508e8d53914d6c9671'
BOTTOM_WHITE_SOURCE_SHA256='62622ac234b745e8c90428421ea482b3f88556fce99f1bc9201caba35f5b7c93'

# A blink comparison must bind both hashes to the same original crop.
FOOTER_BLINK_CALIBRATIONS=(
    (CROP,GRAY_CROP_SHA256,WHITE_CROP_SHA256),
    (CROP,UPPER_GRAY_CROP_SHA256,UPPER_WHITE_CROP_SHA256),
    (CROP,LOWER_GRAY_CROP_SHA256,LOWER_WHITE_CROP_SHA256),
    (HIGH_CROP,HIGH_GRAY_CROP_SHA256,HIGH_WHITE_CROP_SHA256),
    (CROP,BOTTOM_GRAY_CROP_SHA256,BOTTOM_WHITE_CROP_SHA256),
)


def annotate_footer(image,rows,source_hash):
    if image.size!=(640,480):return False
    crop=CROP;digest=hashlib.sha256(image.convert('RGB').crop(crop).tobytes()).hexdigest()
    variants={GRAY_CROP_SHA256:(GRAY_SOURCE_SHA256,WHITE_SOURCE_SHA256,WHITE_CROP_SHA256,0),
              UPPER_GRAY_CROP_SHA256:(UPPER_GRAY_SOURCE_SHA256,UPPER_WHITE_SOURCE_SHA256,UPPER_WHITE_CROP_SHA256,-4),
              LOWER_GRAY_CROP_SHA256:(LOWER_GRAY_SOURCE_SHA256,LOWER_WHITE_SOURCE_SHA256,LOWER_WHITE_CROP_SHA256,2),
              BOTTOM_GRAY_CROP_SHA256:(BOTTOM_GRAY_SOURCE_SHA256,BOTTOM_WHITE_SOURCE_SHA256,BOTTOM_WHITE_CROP_SHA256,4)}
    if digest not in variants:
        # The original three-unit viewing panel places the same complete484
        # glyph mask six pixels higher. Include its observed OCR bounds too;
        # do not discard a row crossing the narrower historical crop.
        crop=HIGH_CROP;digest=hashlib.sha256(image.convert('RGB').crop(crop).tobytes()).hexdigest()
        if digest!=HIGH_GRAY_CROP_SHA256:return False
        variants[digest]=(HIGH_GRAY_SOURCE_SHA256,HIGH_WHITE_SOURCE_SHA256,HIGH_WHITE_CROP_SHA256,-6)
    gray_source,white_source,white_crop,dy=variants[digest]
    inside=[]
    for row in rows:
        x,y,w,h=row['bounds']
        if x<crop[2] and x+w>crop[0] and y<crop[3] and y+h>crop[1]:
            # Do not discard text crossing outside the fully matched pixels.
            if not crop[0]<=x<x+w<=crop[2] or not crop[1]<=y<y+h<=crop[3]:return False
            inside.append(row)
    provenance=dict(preprocessing='exact_original_gray_footer_rgb_sha256',
        image_sha256=source_hash,crop=list(crop),crop_rgb_sha256=digest,
        gray_reference_image_sha256=gray_source,
        white_reference_image_sha256=white_source,
        white_reference_crop_rgb_sha256=white_crop,
        calibration='Both original lines visually verified; exactly484 white pixels change to gray134',
        prior_readings=[{k:deepcopy(r[k]) for k in ('text','bounds','confidence','provenance') if k in r} for r in inside])
    rows[:]=[r for r in rows if not any(r is old for old in inside)]
    for text,bounds in LINES:
        x,y,w,h=bounds;y+=dy
        rows.append(dict(text=text,confidence=1.,bounds=[x,y,w,h],center=[x+w//2,y+h//2],
            x=x/640,y=y/480,width=w/640,height=h/480,provenance=[deepcopy(provenance)]))
    return True
