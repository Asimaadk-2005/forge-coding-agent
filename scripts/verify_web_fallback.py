"""Local HTTP/worker transport integration with API connections forbidden."""
import http.client
import io
import json
import socket
import sys
import tempfile
import threading
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fallback.web_agent import create_server, forge


def run():
    calls = []
    network_attempts = []
    original_connect = socket.socket.connect
    def loopback_only(sock,address):
        if not isinstance(address,tuple) or address[0] != '127.0.0.1':
            network_attempts.append(str(address))
            raise AssertionError('Only local fallback HTTP traffic is permitted')
        return original_connect(sock,address)
    def offline_worker(agent,*args):
        calls.append('mocked desktop worker')
        project = Path(args[3])/'SpaceFractions_offline_transport_fixture'
        project.mkdir()
        (project/'.agent').mkdir()
        (project/'main.py').write_text('# Offline HTTP fixture, not a model-generated game\n')
        (project/'.agent/private.txt').write_text('Must not be in source download')
        exe = project/'SpaceFractions.exe'
        exe.write_bytes(b'Offline download fixture, not a runnable executable')
        (project/'.agent/desktop-build.json').write_text('{"warnings":["Fixture warning"]}')
        agent.events.put(('project',str(project)))
        agent.events.put(('phase','Offline transport fixture'))
        agent.events.put(('preview_ready',str(project)))
        agent.events.put(('executable_ready',str(exe)))
        agent.events.put(('done',(project,exe,1)))
    with tempfile.TemporaryDirectory(prefix='forge-web-test-') as directory, \
         patch.object(socket.socket,'connect',loopback_only), \
         patch.object(forge.CodeAgent,'worker',offline_worker):
        server = create_server(0,directory)
        thread = threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        def request(method,path,payload=None,token=True,origin=None,host=None):
            conn = http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
            headers = {'Content-Type':'application/json'}
            if token: headers['X-Forge-Token'] = server.app.token
            if origin: headers['Origin'] = origin
            if host: headers['Host'] = host
            conn.request(method,path,json.dumps(payload) if payload is not None else None,headers)
            response = conn.getresponse()
            result = response.status,response.read()
            conn.close()
            return result
        try:
            status,page = request('GET','/',token=False)
            assert status==200 and b'__FORGE_TOKEN__' not in page and server.app.token.encode() in page
            assert request('GET','/api/state',token=False)[0]==403
            assert request('GET','/api/state',origin='https://other.example')[0]==403
            assert request('GET','/api/state',host='other.example')[0]==403
            assert request('GET','/api/game.exe')[0]==404
            (Path(directory)/'Chosen folder').mkdir()
            status,folders = request('POST','/api/folders',{'path':directory})
            assert status==200 and any(f['name']=='Chosen folder' for f in json.loads(folders)['folders'])
            data = {'key':'offline-fixture-key','provider':'DeepSeek','model':'deepseek-v4-pro',
                    'task':'Transport fixture only','output':directory,
                    'documents':[{'name':'Architecture.md','text':'Fixture document'}]}
            assert request('POST','/api/generate',data)[0]==200
            server.app.thread.join(5)
            status,body = request('GET','/api/state')
            state = json.loads(body)
            assert state['exe_ready'] and not state['busy'] and b'offline-fixture-key' not in body
            status,exe = request('GET','/api/game.exe')
            assert status==200 and exe.startswith(b'Offline download fixture')
            status,source = request('GET','/api/source.zip')
            with zipfile.ZipFile(io.BytesIO(source)) as archive:
                assert archive.namelist()==['main.py']
            assert request('POST','/api/stop',{})[0]==200
            assert len(calls)==1 and not network_attempts
            result = {'http_status':'passed','worker_adapter':'passed using an explicit mock',
                      'download_filtering':'passed','loopback_origin_and_token_checks':'passed',
                      'provider_requests':0,'saved_key_reads':0,'new_generation':False,
                      'note':'Transport/download fixtures are not real model-generated code or game EXEs.'}
            evidence = ROOT/'prototype-tests/fallback'
            evidence.mkdir(parents=True,exist_ok=True)
            (evidence/'http-verification.json').write_text(json.dumps(result,indent=2))
            print(json.dumps(result))
        finally:
            server.shutdown();server.server_close();thread.join(3)


if __name__=='__main__':
    run()
