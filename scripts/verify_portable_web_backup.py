"""Smoke the portable CLI/browser backup using its runtime, with no model calls."""
import hashlib
import argparse
import http.client
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import main

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--folder',type=Path,default=ROOT/'release/Forge-Web-Backup')
parser.add_argument('--port',type=int,default=8767)
args = parser.parse_args()
folder = args.folder.resolve()
env = main.process_environment()
env['PATH'] = str(Path(os.environ['SystemRoot'])/'System32')
help_result = subprocess.run([os.environ['COMSPEC'],'/d','/c',str(folder/'Forge-Web.cmd'),'--help'],
    cwd=folder,env=env,capture_output=True,timeout=30)
assert help_result.returncode == 0, 'Portable launcher failed'
process = subprocess.Popen([str(folder/'runtime/python.exe'),'-B',str(folder/'fallback/web_agent.py'),'--port',str(args.port)],
    cwd=folder,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
try:
    page = None
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError('Portable backend exited early')
        try:
            connection = http.client.HTTPConnection('127.0.0.1',args.port,timeout=1)
            connection.request('GET','/')
            response = connection.getresponse()
            page = response.read().decode('utf-8')
            assert response.status==200
            connection.close()
            break
        except OSError:
            time.sleep(.1)
    assert page and 'Download game EXE' in page
    token = re.search(r"const TOKEN='([^']+)'",page).group(1)
    connection = http.client.HTTPConnection('127.0.0.1',args.port,timeout=3)
    connection.request('GET','/api/state',headers={'X-Forge-Token':token})
    response = connection.getresponse()
    state = json.loads(response.read())
    connection.close()
    assert response.status==200 and state['phase']=='Ready' and not state['busy']
    assert not state['exe_ready']
    result = {'portable_batch_help':'passed','packaged_backend_http':'passed','browser_state_api':'passed',
              'windows_only_path':True,'external_python_install_used':False,'model_requests':0,
              'new_generation':False,'note':'Startup/API smoke only; no new live model generation.'}
    evidence=ROOT/('prototype-tests/fallback-v2' if folder.name.endswith('v2') else 'prototype-tests/fallback')
    evidence.mkdir(parents=True,exist_ok=True)
    (evidence/'portable-smoke.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))
finally:
    process.terminate()
    process.wait(timeout=10)
