"""Original single-contact Foreign Minister report; every button needs Jev.

The measured one-contact window and selected radio are required. Multiple
contacts, other layouts, and a partially read report fail closed. This reports
the observed leader/tribe; it does not infer the native civilization slot.
"""
from copy import deepcopy
from io import BytesIO
import hashlib
from pathlib import Path
import re
from PIL import Image


SOURCE = dict(tag='REPORTFOREIGN', title='Foreign Minister', width=580,
    body='Sire, our power is %STRING0 and our reputation is %STRING1.',
    options=[], buttons=['Check Intelligence', 'Send Emissary'], listbox=False)
SOURCE_SHA256 = '77ea7cf68eb56a39dc6bc96372b3b34bb5abe9ef42ae46bb4cb5ecb21d6d3129'
TITLES = {'Foreign Minister', 'Foreign Winister', 'Foreign Minisber'}
REPUTATIONS = ('Spotless', 'Excellent', 'Honorable', 'Questionable', 'Dishonorable', 'Poor', 'Despicable', 'Atrocious')
POWERS = ('Pathetic', 'Weak', 'Inadequate', 'Moderate', 'Strong', 'Mighty', 'Supreme')
RELATIONS = ('Allied', 'Peace', 'Cease Fire', 'War')
FRAME = (20, 182, 622, 299)
# Identical RGB hashes in isolated original3950/ui14 (Vikings) and
# attempt010/ui1942 (Germans). No original image assets are distributed.
PIXELS = (
    ((20,182,622,184), '930e7ae56be0addb6d373ff3ffd44668592d3efdfc73a634eaf84627e1ed38ae'),
    ((20,183,22,298), '47a9b01fd4f80c0ee4208fc6b5d2b23936e5d2c8707076ec97c3a96b45cb713c'),
    ((620,183,622,298), 'fd9ead0290581b3c041158bde7d12187948a28dd646f77bb0fd44a83f07ad7d3'),
    ((20,297,622,299), '783d2d7565842a119710c3e6bdd48fb101e74fc0c525ef6f641d3559efb2109c'),
    ((39,239,57,257), '38abafa3d3509f9f997bd599b87b17f15bb82270b57f2b83dd29fa5aa190f36e'),
    ((22,260,620,269), '37c0f071cb3c5c8f39634b4cd0a0a77781faaa68cce23e3e0f259ab033499782'),
)


def _pixels(observation):
    path = observation.get('path')
    if not isinstance(path, (str, Path)): return None
    try:
        data = Path(path).read_bytes()
        if hashlib.sha256(data).hexdigest() != observation['sha256']: return None
        with Image.open(BytesIO(data)) as source:
            if source.format != 'PNG' or source.size != (640,480): return None
            image = source.convert('RGB')
        if any(hashlib.sha256(image.crop(box).tobytes()).hexdigest() != digest for box,digest in PIXELS):
            return None
    except (OSError, ValueError): return None
    return [{'bounds':list(box), 'rgb_sha256':digest} for box,digest in PIXELS]


def classify_foreign_report(observation, rows, resources, rules, labels_text):
    """Accept validated classifier rows and retain all actual button choices."""
    if (not isinstance(observation,dict) or (observation.get('width'),observation.get('height')) != (640,480)
            or not re.fullmatch('[0-9a-f]{64}',str(observation.get('sha256','')))
            or observation.get('ocr',{}).get('conflicts')
            or not isinstance(rows,list) or not isinstance(resources,list)
            or not isinstance(rules,dict) or not isinstance(labels_text,str)):
        return None
    if [r for r in resources if isinstance(r,dict) and r.get('tag')=='REPORTFOREIGN'] != [SOURCE]:
        return None
    labels=labels_text.splitlines()
    if (labels[7:11] != ['@POPUPS','OK','Help','Cancel']
            or labels[157:162] != [*RELATIONS,'No Embassy']
            or labels[236:251] != [*REPUTATIONS,*POWERS]): return None
    inside=[];outside=[]
    for row in rows:
        x,y,w,h=row['bounds'];left,top,right,bottom=FRAME
        if x+w<=left or x>=right or y+h<=top or y>=bottom: outside.append(row)
        elif left<=x and top<=y and x+w<=right and y+h<=bottom: inside.append(row)
        else: return None
    if len(inside)!=6 or any(r['confidence']<.8 for r in inside): return None
    ordered=sorted(inside,key=lambda r:(r['center'][1],r['center'][0]))
    title,body,contact=ordered[:3]
    buttons=sorted(ordered[3:],key=lambda r:r['center'][0])
    if title['text'] not in TITLES or not (315<=title['center'][0]<=327 and 194<=title['center'][1]<=203): return None
    if not (28<=body['bounds'][0]<=34 and 211<=body['bounds'][1]<=218 and 217<=body['center'][1]<=226): return None
    body_match=re.fullmatch(r'Sire, our power is ([A-Za-z]+) and our reputation is ([A-Za-z]+)\.',body['text'])
    if not body_match or body_match[1] not in POWERS or body_match[2] not in REPUTATIONS: return None
    if not (58<=contact['bounds'][0]<=72 and 237<=contact['bounds'][1]<=243
            and 244<=contact['center'][1]<=253 and contact['bounds'][3]<=24): return None
    # Keep the title/rank and attitude exactly as observed. Only the leader and
    # tribe identity is corroborated against the original public RULES roster.
    match=re.fullmatch(r"([A-Za-z][A-Za-z .'-]{1,80}) of the ([A-Za-z][A-Za-z '-]{0,45}) \(([A-Za-z][A-Za-z -]{0,30}), (Allied|Peace|Cease Fire|War), No Embassy\)",contact['text'])
    if not match: return None
    named=[]
    for leader in rules.get('leaders',[]):
        if not isinstance(leader,dict) or leader.get('tribe') != match[2]: continue
        for sex in ('male','female'):
            name=leader.get(sex)
            if (isinstance(name,str) and match[1].endswith(' '+name)
                    and re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,35}",match[1][:-len(name)-1])):
                named.append({'leader':name,'tribe':leader['tribe']})
    if len(named)!=1: return None
    if [r['text'] for r in buttons] != ['Check Intelligence','Send Emissary','Cancel']: return None
    for button,cx in zip(buttons,(126,321,519)):
        if abs(button['center'][0]-cx)>6 or not 277<=button['center'][1]<=287 or not 270<=button['bounds'][1]<=279:
            return None
    proof=_pixels(observation)
    if proof is None: return None
    def control(row):
        return {k:deepcopy(row[k]) for k in ('text','center','source_line','confidence')}|{'control':'button','enabled':None}
    controls=[control(r) for r in buttons]
    evidence={'source':'Original GAME.TXT REPORTFOREIGN, LABELS.TXT and observed single-contact native window',
        'resource_sha256':SOURCE_SHA256,'labels_sha256':hashlib.sha256(labels_text.encode()).hexdigest(),
        'image_sha256':observation['sha256'],'original_title':SOURCE['title'],'observed_title':title['text'],
        'observed_body':body['text'],'observed_contact':contact['text'],'observed_power':body_match[1],
        'observed_reputation':body_match[2], 'selected_contact':named[0],
        'selected_contact_scope':'One observed selected radio; no native civilization-slot mapping inferred',
        'complete_contact_count':1,'frame_bounds':list(FRAME),'pixel_regions':proof,
        'source_lines':[r['source_line'] for r in [title,body,contact,*buttons]],
        'outside_report_rows':[{'text':r['text'],'bounds':r['bounds'],'source_line':r['source_line']} for r in outside]}
    return dict(kind='foreign_minister',title=title['text'],resource_tag='REPORTFOREIGN',options=controls,
        buttons=deepcopy(controls),requires_model=True,mechanical_action=None,evidence={'foreign_report':evidence})
