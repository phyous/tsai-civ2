"""Parse observed native calendar labels without altering their source text.

Original captions use both ``4000 B.C.`` and ``A.D. 1``. Bindings compare
their explicit number and era; no turn number or hidden state supplies a date.
"""
import re

ERA_PATTERN = r'(?:B\.?\s*C\.?|A\.?\s*D\.?)'
DATE_PATTERN = rf'(?:[0-9]{{1,5}}\s*{ERA_PATTERN}|{ERA_PATTERN}\s*[0-9]{{1,5}})(?![A-Za-z0-9.])'
CITY_PATTERN = rf'^City of (.+?),\s*({DATE_PATTERN})'
DAMAGED_CITY_PATTERN = rf'^Ci(?:ty|sy|cy) of (.+?),\s*({DATE_PATTERN})'


def date_parts(text):
    """Return the actual digit string and ASCII era, or None if incomplete."""
    if not isinstance(text, str):return None
    text=text.strip()
    if re.fullmatch(DATE_PATTERN,text,re.I) is None:return None
    digits=re.search(r'[0-9]+',text).group()
    if int(digits)==0:return None  # The native calendar has no year zero.
    era=re.sub(r'[^A-Za-z]','',text).upper()
    return digits,era


def date_year(text):
    parts=date_parts(text)
    return None if parts is None else int(parts[0])*(-1 if parts[1]=='BC' else 1)


def date_key(text):
    """Existing review-token spelling, equivalent for either era position."""
    parts=date_parts(text)
    return None if parts is None else str(int(parts[0]))+parts[1]


def city_date_match(text, *, damaged_prefix=False):
    """Match a caption prefix; groups remain actual city and raw date strings."""
    if not isinstance(text,str):return None
    match=re.match(DAMAGED_CITY_PATTERN if damaged_prefix else CITY_PATTERN,text,re.I)
    if match and re.match(rf'\s*(?:{ERA_PATTERN})(?![A-Za-z])',text[match.end():],re.I):return None
    return match if match and date_parts(match[2]) is not None else None
