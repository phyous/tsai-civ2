"""Pixel proof for the original small gold-framed event illustration."""
import re

BLACK=(0,0,0)
GOLD={(190,150,44),(207,166,52)}


def _frame(pixels,x,y):
    for yy in range(40):
        for xx in range(72):
            if xx<2 or yy<2 or xx>=70 or yy>=38:
                if pixels[x+xx,y+yy]!=BLACK:return False
            elif xx<4 or yy<4 or xx>=68 or yy>=36:
                if pixels[x+xx,y+yy] not in GOLD:return False
    return True


def annotate_notice_icons(image,rows,source_hash):
    if image.size!=(640,480):return
    pixels=image.convert('RGB').load()
    for row in rows:
        x,y,w,h=row['bounds'];glyphs=''.join(row['text'].split())
        if (not 1<=len(glyphs)<=8 or not 1<=w<=40 or not 1<=h<=32
                or not 70<=x<=250 or not 100<=y<=350
                or row['text'].casefold() in {'ok','no','yes','help','cancel','done','exit'}):continue
        found=[]
        for left in range(max(0,x-67),x-3):
            for top in range(max(0,y-35),y-3):
                if (x+w>left+68 or y+h>top+36 or pixels[left,top]!=BLACK
                        or pixels[left+2,top+2] not in GOLD):continue
                if _frame(pixels,left,top):found.append([left,top,72,40])
        if len(found)==1:
            row['native_notice_icon']={'source_sha256':source_hash,'row_bounds':list(row['bounds']),
                                      'frame':found[0],'black_border_pixels':432,'gold_border_pixels':400}


def proven_notice_icon(row,source_hash):
    p=row.get('native_notice_icon')
    if (not isinstance(p,dict) or set(p)!={'source_sha256','row_bounds','frame','black_border_pixels','gold_border_pixels'}
            or p['source_sha256']!=source_hash or p['row_bounds']!=list(row['bounds'])
            or p['black_border_pixels']!=432 or p['gold_border_pixels']!=400):return None
    box=p['frame'];x,y,w,h=row['bounds']
    if (not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box)
            or box[2:]!=[72,40] or not 0<=box[0]<=568 or not 0<=box[1]<=440
            or not box[0]+4<=x<x+w<=box[0]+68 or not box[1]+4<=y<y+h<=box[1]+36
            or len(''.join(row['text'].split()))>8):return None
    return box
