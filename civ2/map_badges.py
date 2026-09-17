"""Original 640×480 monochrome city-badge artwork, never decoded statistics."""
import re
import hashlib

# Original011/1917: the city's colored sprite occludes this badge's lower
# right corner. Exact complete RGB pixels, never a relaxed border heuristic.
OCCLUDED_CROP_SHA256='4cda04b1b2a298453ec58028bf52b268ab38ad93c34e9ee5282164fa78cca350'
OCCLUDED_SOURCE_SHA256='1ba9f24c49066273a989bb046ed15a4cf583d94538487d967da6db92c6e91a1b'


def occluded_badge_bounds(image,row):
    if image.size!=(640,480):return None
    x,y,w,h=row['bounds']
    if (not re.fullmatch(r'[1-9][0-9]?',row['text']) or row['confidence']<.8
            or not 8<=x<x+w<=456 or not 70<=y<y+h<=440 or not 1<=w<=20 or not 8<=h<=24):return None
    image=image.convert('RGB');matches=[]
    for left in range(x-2,x+3):
        for top in range(y-4,y+2):
            if abs(left+5.5-row['center'][0])>5 or abs(top+7.5-row['center'][1])>6:continue
            if hashlib.sha256(image.crop((left,top,left+11,top+15)).tobytes()).hexdigest()==OCCLUDED_CROP_SHA256:
                matches.append([left,top,11,15])
    return matches[0] if len(matches)==1 else None


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
        elif not candidates and (box:=occluded_badge_bounds(image,row)):
            row['map_badge_pixels']={'kind':'exact_original_occluded_badge_rgb_v1','source_sha256':source_hash,
                'row_bounds':list(row['bounds']),'bounds':box,'crop_rgb_sha256':OCCLUDED_CROP_SHA256,
                'reference_image_sha256':OCCLUDED_SOURCE_SHA256}


def proven_badge(row,source_hash):
    proof=row.get('map_badge_pixels')
    if isinstance(proof,dict) and proof.get('kind')=='exact_original_occluded_badge_rgb_v1':
        box=proof.get('bounds')
        return (set(proof)=={'kind','source_sha256','row_bounds','bounds','crop_rgb_sha256','reference_image_sha256'}
            and proof['source_sha256']==source_hash and proof['row_bounds']==list(row['bounds'])
            and proof['crop_rgb_sha256']==OCCLUDED_CROP_SHA256 and proof['reference_image_sha256']==OCCLUDED_SOURCE_SHA256
            and isinstance(box,list) and len(box)==4 and all(type(n)is int for n in box)
            and box[2:]==[11,15] and 6<=box[0]<=447 and 66<=box[1]<=430
            and abs(box[0]+5.5-row['center'][0])<=5 and abs(box[1]+7.5-row['center'][1])<=6)
    if (not isinstance(proof,dict) or set(proof)!={'source_sha256','row_bounds','bounds','pattern'}
            or proof['source_sha256']!=source_hash or proof['row_bounds']!=list(row['bounds'])
            or not badge_pattern(proof['pattern'])):return False
    box=proof['bounds']
    return (isinstance(box,list) and len(box)==4 and all(type(n) is int for n in box)
            and box[2]==len(proof['pattern'][0]) and box[3]==13
            and 6<=box[0] and box[0]+box[2]<=458 and 67<=box[1] and box[1]+13<=445
            and abs(box[0]+box[2]/2-row['center'][0])<=5
            and abs(box[1]+6.5-row['center'][1])<=6)
