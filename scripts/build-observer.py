#!/usr/bin/env python3
"""Build the pinned read-only Win16 helper and an ignored private runtime overlay."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
COMPILER_URL = 'https://github.com/open-watcom/open-watcom-v2/releases/download/Current-build/open-watcom-2_0-c-linux-x64'
COMPILER_SHA256 = 'b51ad127b52c44ddcc9451e4960674b9b31b1457b84c798521dcf3f84c494273'
COMPILER_BYTES = 129066721
IMAGE = 'debian@sha256:88200866dfff7ea7f5cbcb6ec7c8a701889efe6fe859fe64d6990e4b07ea4171'
SOURCE_SHA256 = 'ce82cdd26379bdd2817fb1fd87b34474a21753b3a043046dcdee84da74760dc5'
HELPER_SHA256 = 'b2ca27df1f3c15d6cdbcc8411be761e4d96fd018425bc23c65df329490432236'
ORIGINAL_EXE_SHA256 = 'b5a64ecbd8ebdd37e3ca2391c57319fec7ac227fcd2c3b9c96498969ea51ef96'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def compiler_archive(path):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        request=urllib.request.Request(COMPILER_URL,headers={'User-Agent':'tsai-civ2-observer-build/1.0'})
        temporary=path.with_name(path.name+'.download')
        try:
            with urllib.request.urlopen(request,timeout=60) as response,temporary.open('wb') as target:
                remaining=COMPILER_BYTES+1
                while remaining:
                    block=response.read(min(1024*1024,remaining))
                    if not block:break
                    target.write(block);remaining-=len(block)
            verify_compiler(temporary)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
    verify_compiler(path)
    return path


def verify_compiler(path):
    if path.stat().st_size!=COMPILER_BYTES or sha(path.read_bytes())!=COMPILER_SHA256:
        raise RuntimeError('Official compiler bytes differ from the pinned build. Current-build is mutable; use an existing verified --compiler-archive. Do not bypass this check.')


def extract_toolchain(archive,directory):
    directory.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            relative=PurePosixPath(item.filename)
            if not relative.parts or relative.parts[0] not in ('binl64','h','lib286'):continue
            if relative.is_absolute() or '..' in relative.parts or '\\' in item.filename:
                raise RuntimeError('Unsafe compiler archive path')
            target=directory.joinpath(*relative.parts)
            if target.resolve().is_relative_to(directory.resolve()) is False:
                raise RuntimeError('Compiler extraction escapes its directory')
            if item.is_dir():target.mkdir(parents=True,exist_ok=True);continue
            data=source.read(item)
            target.parent.mkdir(parents=True,exist_ok=True)
            # Revalidate cached files against the already hash-pinned archive.
            if not target.exists() or target.read_bytes()!=data:target.write_bytes(data)
            target.chmod(0o755 if relative.parts[0]=='binl64' else 0o644)


def build_helper(archive,cache,source):
    if sha(source.read_bytes())!=SOURCE_SHA256:
        raise RuntimeError('Observer source changed; review source and update the pinned helper build together')
    toolchain=cache/'watcom';work=cache/'work'
    extract_toolchain(archive,toolchain);work.mkdir(parents=True,exist_ok=True)
    (work/'civ2obs.exe').unlink(missing_ok=True)
    # Container has no network and only these explicit host mounts. No user
    # profile, environment secret, or game archive is mounted into the compiler.
    command=['docker','run','--rm','--platform','linux/amd64','--network','none',
             '--mount',f'type=bind,src={toolchain.resolve()},dst=/watcom,readonly',
             '--mount',f'type=bind,src={source.resolve()},dst=/src/civ2_observer.c,readonly',
             '--mount',f'type=bind,src={work.resolve()},dst=/work','-w','/work',
             '-e','WATCOM=/watcom','-e','INCLUDE=/watcom/h:/watcom/h/win',
             '-e','PATH=/watcom/binl64:/usr/bin:/bin',IMAGE,
             'wcl','-bt=windows','-ms','-zW','-fe=civ2obs.exe','/src/civ2_observer.c','toolhelp.lib']
    subprocess.run(command,check=True)
    helper=work/'civ2obs.exe'
    if sha(helper.read_bytes())!=HELPER_SHA256:
        raise RuntimeError('Compiled helper does not match its independently calibrated pinned hash')
    return helper,command


def make_overlay(original,helper,destination,*,original_sha256):
    if original.resolve()==destination.resolve():
        raise RuntimeError('The private overlay must not replace the original archive')
    if sha(original.read_bytes())!=original_sha256:
        raise RuntimeError('Original runtime archive checksum differs')
    helper_data=helper.read_bytes()
    if sha(helper_data)!=HELPER_SHA256:raise RuntimeError('Observer helper checksum differs')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=destination.parent,prefix='.observer-',suffix='.zip',delete=False) as stream:
        temporary=Path(stream.name)
    try:
        with zipfile.ZipFile(original) as source,zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as target:
            names=source.namelist()
            if len(names)!=len(set(name.casefold() for name in names)) or any(name.casefold()=='civ2obs.exe' for name in names):
                raise RuntimeError('Original archive contains an ambiguous/helper filename')
            if sha(source.read('civ2/CIV2.EXE'))!=ORIGINAL_EXE_SHA256:
                raise RuntimeError('Original CIV2.EXE checksum differs')
            for item in source.infolist():
                data=source.read(item)
                if item.filename=='WINDOWS/WIN.INI':
                    old=b'load=\r\n'
                    if data.count(old)!=1:raise RuntimeError('Original Windows startup entry differs')
                    data=data.replace(old,b'load=c:\\CIV2OBS.EXE\r\n')
                target.writestr(item,data)
            info=zipfile.ZipInfo('CIV2OBS.EXE',(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
            info.external_attr=0o100644<<16
            target.writestr(info,helper_data)
        # Validate every decompressed original byte. Game/Windows binaries and
        # all game rules/assets stay unchanged; only the requested load line differs.
        with zipfile.ZipFile(original) as source,zipfile.ZipFile(temporary) as target:
            if set(target.namelist())!=set(source.namelist())|{'CIV2OBS.EXE'}:
                raise RuntimeError('Private overlay changes unexpected archive members')
            changed=[name for name in source.namelist() if source.read(name)!=target.read(name)]
            if changed!=['WINDOWS/WIN.INI'] or sha(target.read('civ2/CIV2.EXE'))!=ORIGINAL_EXE_SHA256:
                raise RuntimeError('Private overlay changed original game bytes')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return {'path':str(destination.relative_to(ROOT)), 'bytes':destination.stat().st_size,
            'sha256':sha(destination.read_bytes()),'changed_original_members':['WINDOWS/WIN.INI'],
            'added_members':['CIV2OBS.EXE'],'original_exe_sha256':ORIGINAL_EXE_SHA256}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--compiler-archive',type=Path,
        help='Existing official installer with the exact pinned SHA; never a replacement toolchain')
    args=parser.parse_args()
    if shutil.which('docker') is None:raise RuntimeError('Docker with Linux amd64 containers is required')
    cache=ROOT/'.runtime/observer-build'
    archive=compiler_archive(args.compiler_archive or cache/'open-watcom-linux-x64')
    helper,command=build_helper(archive,cache,ROOT/'scripts/civ2_observer.c')
    manifest=json.loads((ROOT/'engine/runtime-manifest.json').read_text())
    entry=next(item for item in manifest['files'] if item['path']=='game/civ2-win31.zip')
    result=make_overlay(ROOT/'engine'/entry['path'],helper,ROOT/'engine/game/civ2-win31-observer.zip',original_sha256=entry['sha256'])
    report={'format':'tsai-civ2-observer-build-v1','compiler':{'url':COMPILER_URL,'sha256':COMPILER_SHA256,'bytes':COMPILER_BYTES},
            'container':{'image':IMAGE,'platform':'linux/amd64'},'source_sha256':SOURCE_SHA256,'helper_sha256':HELPER_SHA256,
            'compile_arguments':command[command.index('wcl'):], 'original_archive_sha256':entry['sha256'],'overlay':result}
    (ROOT/'engine/game/observer-build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('Verified pinned observer helper and private game overlay; original CIV2.EXE unchanged.')
    print('Ready: engine/game/civ2-win31-observer.zip (ignored; do not publish the archive).')


if __name__=='__main__':main()
