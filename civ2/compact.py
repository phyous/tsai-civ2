"""Readable record tables for model context, without pruning game facts/options.

Only audit identifiers/timestamps in historical records are omitted from model
context. Their original records remain in the evidence journal. Tables decode
exactly to the remaining projection, including absent versus explicit-null keys.
"""
from copy import deepcopy
import json
import re

REVISION='civ2-state-tables-v1'
TABLE='civ2-records-v1'
ENCODING={
    'revision':REVISION,
    'record_tables':'Objects marked $table=civ2-records-v1 are ordinary records: each row has the column values in order. A dotted column is a nested field. absent entries are [row_index,[column_indexes]] for missing keys; other nulls are explicit unknown/null values. Row order is unchanged.',
    'scope':'All supplied game facts, history text, outcomes and choices remain. Historical audit hashes and wall-clock timestamps are retained in the evidence journal instead of this model context. last_checkpoint turn/year may be stale; notice text is historical, not current hidden state.'}
LISTS=('owned_unit_roster','owned_cities','owned_city_locations','recent_actions',
       'recent_observed_events','contacted_diplomacy','currently_visible_foreign_units',
       'remembered_foreign_cities')


def _size(value):return len(json.dumps(value,separators=(',',':'),ensure_ascii=False))


def decision_facts(state):
    """Remove only explicitly named historical audit metadata, never game data."""
    result=deepcopy(state)
    for record in result.get('recent_actions',[]):
        if not isinstance(record,dict):continue
        key='observation_sha256_at_issue'
        if re.fullmatch('[0-9a-f]{64}',str(record.get(key,''))):record.pop(key)
    for record in result.get('recent_observed_events',[]):
        if not isinstance(record,dict):continue
        for key in ('id','image_sha256'):
            if re.fullmatch('[0-9a-f]{64}',str(record.get(key,''))):record.pop(key)
        for key in ('observed_at_utc','observation_elapsed_ms'):record.pop(key,None)
        for key in ('source','last_checkpoint'):
            source=record.get(key)
            if not isinstance(source,dict):continue
            for field in list(source):
                if field.endswith('_sha256') and re.fullmatch('[0-9a-f]{64}',str(source[field])):
                    source.pop(field)
            if not source:record.pop(key)
    return result


def _flat(record,prefix=()):
    result={}
    for key,value in record.items():
        if not isinstance(key,str) or not key or '.' in key:raise ValueError('Unsupported table key')
        path=prefix+(key,)
        if isinstance(value,dict) and value:result.update(_flat(value,path))
        else:result['.'.join(path)]=deepcopy(value)
    return result


def _table(records):
    if not isinstance(records,list) or len(records)<3 or not all(isinstance(v,dict) for v in records):
        return records
    try:flat=[_flat(v) for v in records]
    except ValueError:return records
    columns=sorted({key for row in flat for key in row})
    if not columns:return records
    rows=[];absent=[]
    for index,record in enumerate(flat):
        rows.append([record.get(key) for key in columns])
        missing=[i for i,key in enumerate(columns) if key not in record]
        if missing:absent.append([index,missing])
    table={'$table':TABLE,'columns':columns,'rows':rows}
    if absent:table['absent']=absent
    return table if _size(table)<_size(records)*.9 else records


def compact_model_state(state):
    if not isinstance(state,dict):raise ValueError('Model state must be an object')
    encoding=state.get('model_state_encoding')
    if encoding is not None:
        if encoding!=ENCODING:raise ValueError('Unknown model state encoding')
        return deepcopy(state)
    result=decision_facts(state)
    for key in LISTS:
        if key in result:result[key]=_table(result[key])
    labor=result.get('city_labor')
    if isinstance(labor,dict) and 'cities' in labor:labor['cities']=_table(labor['cities'])
    result['model_state_encoding']=deepcopy(ENCODING)
    return result


def _decode(value):
    if isinstance(value,list):return [_decode(v) for v in value]
    if not isinstance(value,dict):return value
    if '$table' not in value:return {k:_decode(v) for k,v in value.items()}
    if value['$table']!=TABLE:raise ValueError('Unknown record table encoding')
    if not {'$table','columns','rows'}<=set(value)<= {'$table','columns','rows','absent'}:
        raise ValueError('Invalid record table fields')
    columns=value['columns'];rows=value['rows'];missing={}
    if (not isinstance(columns,list) or not columns
            or any(not isinstance(c,str) or any(not p for p in c.split('.')) for c in columns)
            or len(set(columns))!=len(columns)
            or not isinstance(rows,list)):
        raise ValueError('Invalid record table schema')
    for item in value.get('absent',[]):
        if (not isinstance(item,list) or len(item)!=2 or type(item[0]) is not int
                or not 0<=item[0]<len(rows) or item[0] in missing or not isinstance(item[1],list)
                or any(type(i) is not int or not 0<=i<len(columns) for i in item[1])
                or len(set(item[1]))!=len(item[1])):raise ValueError('Invalid missing-cell schema')
        missing[item[0]]=set(item[1])
    records=[]
    for i,row in enumerate(rows):
        if not isinstance(row,list) or len(row)!=len(columns):raise ValueError('Invalid record row width')
        record={}
        for j,(column,cell) in enumerate(zip(columns,row)):
            if j in missing.get(i,set()):
                if cell is not None:raise ValueError('Missing cell contains a value')
                continue
            target=record;parts=column.split('.')
            for part in parts[:-1]:
                if part not in target:target[part]={}
                if not isinstance(target[part],dict):raise ValueError('Overlapping table columns')
                target=target[part]
            if parts[-1] in target:raise ValueError('Overlapping table columns')
            target[parts[-1]]=_decode(cell)
        records.append(record)
    return records


def expand_model_state(state):
    """Decode the exact submitted decision facts; audit omissions stay explicit."""
    result=deepcopy(state)
    encoding=result.pop('model_state_encoding',None)
    if encoding!=ENCODING:
        raise ValueError('Unknown model state encoding')
    return _decode(result)
