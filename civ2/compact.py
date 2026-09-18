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
EXTENDED_ENCODING={**ENCODING,
    'record_table_extensions':'Tables may include shared: an object of dotted columns whose values are present in every record. Those columns are omitted from columns/rows. Optional keys lists the original dictionary keys in row order; such a table decodes to a dictionary of records instead of a list. Optional nested_columns maps a column to the dotted columns of list-of-record cells, whose values are row arrays. Grouped tables instead have length and groups of indexes plus records; place each decoded group record at its original index, using optional keys for a dictionary. All values, absent cells and order are preserved.'}

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
        if isinstance(value,dict) and value and '$table' not in value:result.update(_flat(value,path))
        else:result['.'.join(path)]=deepcopy(value)
    return result


def _table(records,keys=None,*,allow_groups=True):
    original=records if keys is None else dict(zip(keys,records))
    if not isinstance(records,list) or len(records)<3 or not all(isinstance(v,dict) for v in records):
        return original
    try:flat=[_flat(v) for v in records]
    except ValueError:return original
    columns=sorted({key for row in flat for key in row})
    if not columns:return original
    variants=[(flat,{})]
    packed=deepcopy(flat);nested={}
    for key in columns:
        values=[row[key] for row in flat if key in row]
        if not values or not all(isinstance(v,list) and all(isinstance(r,dict) for r in v) for v in values):continue
        try:cells=[[_flat(r) for r in value] for value in values]
        except ValueError:continue
        shapes={tuple(sorted(r)) for cell in cells for r in cell}
        if len(shapes)!=1:continue
        shape=list(next(iter(shapes)))
        if not shape:continue
        nested[key]=shape
        for row in packed:
            if key in row:row[key]=[[r[k] for k in shape] for r in map(_flat,row[key])]
    if nested:variants.append((packed,nested))
    choices=[]
    for values,nested_columns in variants:
        shared={}
        for key in columns:
            if all(key in row for row in values):
                identical=[json.dumps(row[key],sort_keys=True,separators=(',',':'),ensure_ascii=False) for row in values]
                if all(v==identical[0] for v in identical):shared[key]=deepcopy(values[0][key])
        for common in ({},shared) if shared else ({},):
            varying=[key for key in columns if key not in common]
            rows=[];absent=[]
            for index,record in enumerate(values):
                rows.append([record.get(key) for key in varying])
                missing=[i for i,key in enumerate(varying) if key not in record]
                if missing:absent.append([index,missing])
            table={'$table':TABLE,'columns':varying,'rows':rows}
            if absent:table['absent']=absent
            if common:table['shared']=common
            if keys is not None:table['keys']=deepcopy(keys)
            if nested_columns:table['nested_columns']=nested_columns
            choices.append(table)
    if allow_groups:
        groups={}
        for index,row in enumerate(flat):groups.setdefault(tuple(sorted(row)),[]).append(index)
        if len(groups)>1:
            grouped={'$table':TABLE,'length':len(records),'groups':[
                {'indexes':indices,'records':_table([records[i] for i in indices],allow_groups=False)}
                for indices in groups.values()]}
            if keys is not None:grouped['keys']=deepcopy(keys)
            choices.append(grouped)
    table=min(choices,key=_size)
    return table if _size(table)<_size(original)*.9 else original


def _nested(value):
    if isinstance(value,list):
        return _table([_nested(item) for item in value])
    if not isinstance(value,dict):return deepcopy(value)
    result={key:_nested(item) for key,item in value.items()}
    if len(result)>=3 and all(isinstance(item,dict) and '$table' not in item for item in result.values()):
        return _table(list(result.values()),list(result))
    return result


def _reject_reserved_literals(value):
    if isinstance(value,list):
        for item in value:_reject_reserved_literals(item)
    elif isinstance(value,dict):
        if '$table' in value:raise ValueError('Literal table marker cannot be encoded as game data')
        for item in value.values():_reject_reserved_literals(item)


def compact_model_state(state):
    if not isinstance(state,dict):raise ValueError('Model state must be an object')
    encoding=state.get('model_state_encoding')
    if encoding is not None:
        if encoding==EXTENDED_ENCODING:
            expand_model_state(state)  # Validate even an idempotent encoded input.
            return deepcopy(state)
        if encoding!=ENCODING:raise ValueError('Unknown model state encoding')
        state=expand_model_state(state)
    _reject_reserved_literals(state)
    result=decision_facts(state)
    for key in (*LISTS,'planning','city_labor','empire_readiness','production_context'):
        if key in result:result[key]=_nested(result[key])
    result['model_state_encoding']=deepcopy(EXTENDED_ENCODING)
    return result


def _decode(value,*,extended=False):
    if isinstance(value,list):return [_decode(v,extended=extended) for v in value]
    if not isinstance(value,dict):return value
    if '$table' not in value:return {k:_decode(v,extended=extended) for k,v in value.items()}
    if value['$table']!=TABLE:raise ValueError('Unknown record table encoding')
    if 'groups' in value:
        if not extended or set(value) not in ({'$table','length','groups'},{'$table','length','groups','keys'}):
            raise ValueError('Invalid grouped table fields')
        length=value['length'];groups=value['groups'];keys=value.get('keys')
        if type(length) is not int or length<1 or length>100000 or not isinstance(groups,list) or not groups:
            raise ValueError('Invalid grouped table dimensions')
        if 'keys' in value and (not isinstance(keys,list) or len(keys)!=length
                or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys)):
            raise ValueError('Invalid grouped table keys')
        records={}
        for group in groups:
            if not isinstance(group,dict) or set(group)!={'indexes','records'} or not isinstance(group['indexes'],list):
                raise ValueError('Invalid record group')
            indexes=group['indexes'];items=_decode(group['records'],extended=extended)
            if not isinstance(items,list) or len(indexes)!=len(items) or not indexes or not all(isinstance(r,dict) for r in items):
                raise ValueError('Invalid group records')
            for i,record in zip(indexes,items):
                if type(i) is not int or not 0<=i<length or i in records:raise ValueError('Overlapping group indexes')
                records[i]=record
        if len(records)!=length:raise ValueError('Missing group records')
        ordered=[records[i] for i in range(length)]
        return dict(zip(keys,ordered)) if keys is not None else ordered
    allowed={'$table','columns','rows','absent'}|({'shared','keys','nested_columns'} if extended else set())
    if not {'$table','columns','rows'}<=set(value)<=allowed:
        raise ValueError('Invalid record table fields')
    columns=value['columns'];rows=value['rows'];missing={}
    shared=value.get('shared',{});keys=value.get('keys')
    if (not isinstance(shared,dict) or any(not isinstance(k,str) or any(not p for p in k.split('.')) for k in shared)):
        raise ValueError('Invalid shared columns')
    if (not isinstance(columns,list) or not columns and not shared
            or any(not isinstance(c,str) or any(not p for p in c.split('.')) for c in columns)
            or len(set(columns))!=len(columns)
            or not isinstance(rows,list)):
        raise ValueError('Invalid record table schema')
    if set(columns)&set(shared):raise ValueError('Overlapping shared columns')
    nested=value.get('nested_columns',{})
    if (not isinstance(nested,dict) or set(nested)-set(columns)-set(shared)
            or any(not isinstance(v,list) or not v or any(not isinstance(k,str) or any(not p for p in k.split('.')) for k in v)
                   or len(set(v))!=len(v) for v in nested.values())):
        raise ValueError('Invalid nested columns')
    if 'keys' in value and (not isinstance(keys,list) or len(keys)!=len(rows)
            or any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys)):
        raise ValueError('Invalid keyed record table')
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
        combined=[*zip(columns,row),*shared.items()]
        present=[column for j,(column,_) in enumerate(combined) if j not in missing.get(i,set())]
        for column in present:
            if any(column.startswith(other+'.') for other in present if other!=column):
                raise ValueError('Overlapping present table paths')
        for j,(column,cell) in enumerate(combined):
            if j in missing.get(i,set()):
                if cell is not None:raise ValueError('Missing cell contains a value')
                continue
            target=record;parts=column.split('.')
            for part in parts[:-1]:
                if part not in target:target[part]={}
                if not isinstance(target[part],dict):raise ValueError('Overlapping table columns')
                target=target[part]
            if parts[-1] in target:raise ValueError('Overlapping table columns')
            if column in nested:
                cell={'$table':TABLE,'columns':nested[column],'rows':cell}
            target[parts[-1]]=_decode(cell,extended=extended)
        records.append(record)
    return dict(zip(keys,records)) if keys is not None else records


def expand_model_state(state):
    """Decode the exact submitted decision facts; audit omissions stay explicit."""
    result=deepcopy(state)
    encoding=result.pop('model_state_encoding',None)
    if encoding not in (ENCODING,EXTENDED_ENCODING):
        raise ValueError('Unknown model state encoding')
    return _decode(result,extended=encoding==EXTENDED_ENCODING)
