"""Assemble the optional browser backup separately from the desktop release."""
import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.assemble_release import ignore_runtime

CORE = ('main.py','keyvault.py','game_blueprint.py','legacy_blueprint.py',
        'acceptance_gate.py','validation_runner.py','repair_engine.py','repair_protocol.py')


def assemble(runtime, output):
    runtime, output = Path(runtime).resolve(), Path(output).resolve()
    archive = output.with_name(output.name+'-Windows-x64.zip')
    if output.exists() or archive.exists():
        raise ValueError('Choose a new output name; existing packages are preserved.')
    if output.is_relative_to(runtime) or runtime.is_relative_to(output):
        raise ValueError('Runtime and destination must not overlap.')
    for name in ('python.exe','python312.dll','Lib/site-packages/PyInstaller','Lib/site-packages/pytest','tcl'):
        if not (runtime/name).exists():
            raise ValueError('Runtime is incomplete: '+name)
    output.mkdir(parents=True)
    for name in CORE:
        shutil.copy2(ROOT/name,output/name)
    shutil.copytree(runtime,output/'runtime',ignore=ignore_runtime)
    shutil.copytree(ROOT/'foundation',output/'foundation',ignore=ignore_runtime)
    (output/'fallback').mkdir()
    for name in ('web_agent.py','index.html','README.md'):
        shutil.copy2(ROOT/'fallback'/name,output/'fallback'/name)
    shutil.copy2(ROOT/'fallback/Forge-Web.cmd',output/'Forge-Web.cmd')
    shutil.copy2(ROOT/'fallback/README.md',output/'README.txt')
    shutil.copytree(ROOT/'input',output/'inputs')
    (output/'licenses').mkdir()
    shutil.copy2(runtime/'LICENSE.txt',output/'licenses/Python.txt')
    (output/'licenses/README.txt').write_text(
        'Python license: Python.txt and runtime/LICENSE.txt.\n'
        'Package notices remain in runtime/Lib/site-packages and runtime/tcl.\n',encoding='utf-8')
    records = [{'path':p.relative_to(output).as_posix(),'bytes':p.stat().st_size,
                'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
               for p in sorted(output.rglob('*')) if p.is_file()]
    manifest = {'kind':'optional-cli-browser-backup','platform':'windows-x64',
                'primary_submission':'Forge desktop EXE package', 'files':records}
    (output/'backup-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for record in records:
            data = (output/record['path']).read_bytes()
            assert hashlib.sha256(data).hexdigest()==record['sha256']
            z.writestr('Forge-Web/'+record['path'],data)
        z.write(output/'backup-manifest.json','Forge-Web/backup-manifest.json')
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
    result = {'folder':str(output),'archive':str(archive),'files':len(records)+1,
              'archive_bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),
              'crc':'passed','primary_desktop_modified':False}
    evidence = ROOT/'prototype-tests/fallback'
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'release.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime',required=True)
    parser.add_argument('--output',required=True)
    args = parser.parse_args()
    assemble(args.runtime,args.output)
