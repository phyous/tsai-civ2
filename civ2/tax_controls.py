"""Exact original tax-scrollbar pixels: observed controls, never chosen rates."""
import re

COLORS={'B':(0,0,0),'W':(255,255,255),'G':(195,195,195),'D':(130,130,130)}
LEFT=(
'BBBBBBBBBBBBBBBBB','BWWWWWWWWWWWWWWDB','BWGGGGGGGGGGGGDDB',
'BWGGGGGGGGGGGGDDB','BWGGGGGGGGGGGGDDB','BWGGGGGGBGGGGGDDB',
'BWGGGGGBBGGGGGDDB','BWGGGGBBBBBBGGDDB','BWGGGBBBBBBBGGDDB',
'BWGGGGBBBBBBGGDDB','BWGGGGGBBGGGGGDDB','BWGGGGGGBGGGGGDDB',
'BWGGGGGGGGGGGGDDB','BWGGGGGGGGGGGGDDB','BWDDDDDDDDDDDDDDB',
'BDDDDDDDDDDDDDDDB','BBBBBBBBBBBBBBBBB')
RIGHT=(
'BBBBBBBBBBBBBBBBB','BWWWWWWWWWWWWWWDB','BWGGGGGGGGGGGGDDB',
'BWGGGGGGGGGGGGDDB','BWGGGGGGGGGGGGDDB','BWGGGGGGBGGGGGDDB',
'BWGGGGGGBBGGGGDDB','BWGGGBBBBBBGGGDDB','BWGGGBBBBBBBGGDDB',
'BWGGGBBBBBBGGGDDB','BWGGGGGGBBGGGGDDB','BWGGGGGGBGGGGGDDB',
'BWGGGGGGGGGGGGDDB','BWGGGGGGGGGGGGDDB','BWDDDDDDDDDDDDDDB',
'BDDDDDDDDDDDDDDDB','BBBBBBBBBBBBBBBBB')
PATTERNS={'left':LEFT,'right':RIGHT}


def annotate_tax_controls(image,rows,source_hash):
    if image.size!=(640,480):return
    pixels=image.convert('RGB').load()
    for row in rows:
        if not re.fullmatch(r'(Taxes|Science|Luxuries):\s*\d{1,3}%',row['text']) or row['confidence']<.8:continue
        x,y,w,h=row['bounds']
        if not 220<=x<=300 or not 200<=y<=330 or not 40<=w<=120 or not 8<=h<=22:continue
        matches=[]
        for top in range(y+h-2,min(y+h+21,464)):
            for left in range(100,490):
                if pixels[left,top]!=(0,0,0) or pixels[left+1,top+1]!=(255,255,255):continue
                for direction,pattern in PATTERNS.items():
                    if all(pixels[left+xx,top+yy]==COLORS[color]
                           for yy,line in enumerate(pattern) for xx,color in enumerate(line)):
                        matches.append({'direction':direction,'bounds':[left,top,17,17],'pattern':list(pattern)})
        proof={'source_sha256':source_hash,'row_bounds':list(row['bounds']),'controls':matches}
        candidate={**row,'native_tax_arrows':proof}
        if proven_tax_arrows(candidate,source_hash):row['native_tax_arrows']=proof


def proven_tax_arrows(row,source_hash):
    p=row.get('native_tax_arrows')
    if (not isinstance(p,dict) or set(p)!={'source_sha256','row_bounds','controls'}
            or p['source_sha256']!=source_hash or p['row_bounds']!=list(row['bounds'])
            or not isinstance(p['controls'],list) or len(p['controls'])!=2):return None
    result=[];x,y,w,h=row['bounds']
    for c in p['controls']:
        if not isinstance(c,dict) or set(c)!={'direction','bounds','pattern'}:return None
        direction=c['direction'];box=c['bounds']
        if (direction not in PATTERNS or c['pattern']!=list(PATTERNS[direction])
                or not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box)
                or box[2:]!=[17,17] or not 100<=box[0]<=489
                or not y+h-2<=box[1]<=y+h+20):return None
        if not (box[0]+17<x if direction=='left' else box[0]>x+w):return None
        result.append({'direction':direction,'bounds':box,'center':[box[0]+8,box[1]+8]})
    if ({c['direction'] for c in result}!={'left','right'}
            or abs(result[0]['center'][1]-result[1]['center'][1])>1):return None
    return sorted(result,key=lambda c:c['center'][0])
