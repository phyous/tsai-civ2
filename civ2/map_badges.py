"""Original 640×480 monochrome city-badge artwork, never decoded statistics."""
import re


def badge_pattern(pattern):
    if (not isinstance(pattern,list) or len(pattern)!=13
            or any(not isinstance(row,str) for row in pattern)
            or len(pattern[0]) not in (11,17)
            or any(len(row)!=len(pattern[0]) or set(row)-{'K','W'} for row in pattern)):
        return False
    if (set(pattern[0])!={'K'} or any(row[-1]!='K' for row in pattern[1:])
            or any(row[0]!='K' for row in pattern[1:11])):
        return False
    interior=''.join(row[1:-1] for row in pattern[1:])
    fraction=interior.count('W')/len(interior)
    return .45<=fraction<=.95


def annotate_badges(image,rows,source_hash):
    """Keep a unique original-pixel pattern near a tiny numeric OCR row."""
    if image.size!=(640,480):return
    pixels=image.convert('RGB').load()
    for row in rows:
        x,y,w,h=row['bounds']
        if (not re.fullmatch(r'[1-9][0-9]?',row['text']) or row['confidence']<.8
                or not 8<=x<x+w<=456 or not 70<=y<y+h<=440 or not 1<=w<=20 or not 8<=h<=24):continue
        candidates=[]
        for left in range(x-2,x+3):
            for top in range(y-3,y+2):
                for width in (11,17):
                    if (abs(left+width/2-row['center'][0])>5
                            or abs(top+6.5-row['center'][1])>6):continue
                    pattern=[''.join('K' if max(pixels[xx,yy])<80 else 'W' if min(pixels[xx,yy])>230 else '.'
                                     for xx in range(left,left+width))for yy in range(top,top+13)]
                    if badge_pattern(pattern):candidates.append(([left,top,width,13],pattern))
        if len(candidates)==1:
            box,pattern=candidates[0]
            row['map_badge_pixels']={'source_sha256':source_hash,'row_bounds':list(row['bounds']),
                                     'bounds':box,'pattern':pattern}


def proven_badge(row,source_hash):
    proof=row.get('map_badge_pixels')
    if (not isinstance(proof,dict) or set(proof)!={'source_sha256','row_bounds','bounds','pattern'}
            or proof['source_sha256']!=source_hash or proof['row_bounds']!=list(row['bounds'])
            or not badge_pattern(proof['pattern'])):return False
    box=proof['bounds']
    return (isinstance(box,list) and len(box)==4 and all(type(n) is int for n in box)
            and box[2]==len(proof['pattern'][0]) and box[3]==13
            and 6<=box[0] and box[0]+box[2]<=458 and 67<=box[1] and box[1]+13<=445
            and abs(box[0]+box[2]/2-row['center'][0])<=5
            and abs(box[1]+6.5-row['center'][1])<=6)
