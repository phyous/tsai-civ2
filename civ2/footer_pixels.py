"""Exact native footer pixels, not a fuzzy font or an end-turn action.

The two retained original frames differ in this crop only at 484 pixels:
white (255,255,255) becomes gray (134,134,134). Both lines remain present.
Only the complete unmodified gray RGB crops below are recognized. A second
original layout has the same484 glyph pixels four pixels higher. No game asset
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


def annotate_footer(image,rows,source_hash):
    if image.size!=(640,480):return False
    digest=hashlib.sha256(image.convert('RGB').crop(CROP).tobytes()).hexdigest()
    variants={GRAY_CROP_SHA256:(GRAY_SOURCE_SHA256,WHITE_SOURCE_SHA256,WHITE_CROP_SHA256,0),
              UPPER_GRAY_CROP_SHA256:(UPPER_GRAY_SOURCE_SHA256,UPPER_WHITE_SOURCE_SHA256,UPPER_WHITE_CROP_SHA256,-4)}
    if digest not in variants:return False
    gray_source,white_source,white_crop,dy=variants[digest]
    inside=[]
    for row in rows:
        x,y,w,h=row['bounds']
        if x<CROP[2] and x+w>CROP[0] and y<CROP[3] and y+h>CROP[1]:
            # Do not discard text crossing outside the fully matched pixels.
            if not CROP[0]<=x<x+w<=CROP[2] or not CROP[1]<=y<y+h<=CROP[3]:return False
            inside.append(row)
    provenance=dict(preprocessing='exact_original_gray_footer_rgb_sha256',
        image_sha256=source_hash,crop=list(CROP),crop_rgb_sha256=digest,
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
