#!/usr/bin/env python3
"""Generate private exact-GDI masks from locally installed original Windows fonts."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile,ZIP_DEFLATED
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from civ2.gdi_text import (Atlas,ATLAS_ID,ATLAS_SHA256,METRICS_SHA256,
                            REGULAR_ATLAS_ID,REGULAR_ATLAS_SHA256,REGULAR_METRICS_SHA256)


def sha(data):return hashlib.sha256(data).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler-archive',type=Path,help='Exact pinned official OpenWatcom installer, as in build-observer.py')
    args=parser.parse_args()
    if not shutil.which('docker') or not shutil.which('node'):raise RuntimeError('Docker amd64 and Node.js are required')
    spec=importlib.util.spec_from_file_location('observer_builder',ROOT/'scripts/build-observer.py')
    builder=importlib.util.module_from_spec(spec);spec.loader.exec_module(builder)
    cache=ROOT/'.runtime/gdi-font-build';work=cache/'work';work.mkdir(parents=True,exist_ok=True)
    installer=builder.compiler_archive(args.compiler_archive or cache/'open-watcom-linux-x64')
    toolchain=cache/'watcom';builder.extract_toolchain(installer,toolchain)
    source=ROOT/'scripts/gdi_atlas.c'
    command=['docker','run','--rm','--platform','linux/amd64','--network','none',
        '--mount',f'type=bind,src={toolchain.resolve()},dst=/watcom,readonly',
        '--mount',f'type=bind,src={source.resolve()},dst=/src/gdi_atlas.c,readonly',
        '--mount',f'type=bind,src={work.resolve()},dst=/work','-w','/work',
        '-e','WATCOM=/watcom','-e','INCLUDE=/watcom/h:/watcom/h/win','-e','PATH=/watcom/binl64:/usr/bin:/bin',
        builder.IMAGE,'wcl','-bt=windows','-ms','-zW','-fe=fontprb.exe','/src/gdi_atlas.c']
    subprocess.run(command,check=True,timeout=60)
    modern=json.loads((ROOT/'engine/modern-manifest.json').read_text())
    for item in modern['files']:
        data=(ROOT/'engine'/item['path']).read_bytes();expected=item.get('derived',item)
        if len(data)!=expected['bytes'] or sha(data)!=expected['sha256']:raise RuntimeError('Pinned modern assets required; run fetch_modern_runtime.py')
    manifest=json.loads((ROOT/'engine/runtime-manifest.json').read_text())
    entry=next(x for x in manifest['files'] if x['path']=='game/civ2-win31.zip')
    original=ROOT/'engine'/entry['path'];data=original.read_bytes()
    if sha(data)!=entry['sha256']:raise RuntimeError('Original runtime archive differs')
    overlay=cache/'font-runtime.zip'
    with ZipFile(original) as z,ZipFile(overlay,'w',ZIP_DEFLATED) as out:
        if len(z.namelist())!=len(set(n.casefold() for n in z.namelist())) or 'fontprb.exe' in {n.casefold() for n in z.namelist()}:
            raise RuntimeError('Ambiguous original archive')
        original_exe=z.read('civ2/CIV2.EXE')
        if sha(original_exe)!=builder.ORIGINAL_EXE_SHA256:raise RuntimeError('Original CIV2 executable differs')
        for name in z.namelist():
            payload=z.read(name)
            if name=='WINDOWS/WIN.INI':
                if payload.count(b'load=\r\n')!=1 or payload.count(b'run=c:\\civ2\\CIV2.EXE\r\n')!=1:raise RuntimeError('Original startup differs')
                payload=payload.replace(b'load=\r\n',b'load=C:\\FONTPRB.EXE\r\n').replace(b'run=c:\\civ2\\CIV2.EXE\r\n',b'run=\r\n')
            out.writestr(name,payload)
        out.writestr('FONTPRB.EXE',(work/'fontprb.exe').read_bytes())
    extracted=cache/'extracted'
    subprocess.run(['node',str(ROOT/'scripts/extract-gdi-atlas.cjs'),str(overlay),
                    str(ROOT/'engine/vendor/modern/emulators.js'),str(extracted)],check=True,timeout=75)
    bitmap=(extracted/'atlas.bmp').read_bytes();metrics=(extracted/'glyphs.tsv').read_bytes();Atlas(bitmap,metrics)
    regular=(extracted/'atreg.bmp').read_bytes();regular_metrics=(extracted/'regular.tsv').read_bytes();Atlas(regular,regular_metrics,'regular')
    destination=ROOT/'engine/game/gdi-fonts';destination.mkdir(parents=True,exist_ok=True)
    for name,value in [('times-bold-16.bmp',bitmap),('times-bold-16.tsv',metrics),('times-regular-16.bmp',regular),('times-regular-16.tsv',regular_metrics)]:
        temporary=destination/(name+'.tmp');temporary.write_bytes(value);temporary.replace(destination/name)
    report={'atlas_id':ATLAS_ID,'atlas_sha256':ATLAS_SHA256,'metrics_sha256':METRICS_SHA256,
        'regular_atlas':{'id':REGULAR_ATLAS_ID,'sha256':REGULAR_ATLAS_SHA256,'metrics_sha256':REGULAR_METRICS_SHA256},
        'original_archive_sha256':entry['sha256'],'original_exe_sha256':sha(original_exe),
        'source_sha256':sha(source.read_bytes()),'probe_sha256':sha((work/'fontprb.exe').read_bytes()),
        'compiler_sha256':builder.COMPILER_SHA256,'container':builder.IMAGE,
        'modified_private_members':['WINDOWS/WIN.INI'],'added_private_members':['FONTPRB.EXE'],
        'scope':'Separate private original GDI instance; Civ2 and observer not started; no campaign controls'}
    (destination/'generation.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Verified exact original-GDI atlas: engine/game/gdi-fonts (private and ignored; do not publish).')


if __name__=='__main__':main()
