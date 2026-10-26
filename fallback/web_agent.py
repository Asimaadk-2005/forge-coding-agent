"""Optional CLI-launched browser UI; reuses Forge's desktop generation worker."""
import argparse
import io
import json
import os
import queue
import secrets
import sys
import tempfile
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import main as forge


class WebAgent:
    def __init__(self, output=None):
        self.token = secrets.token_urlsafe(32)
        self.output = str(Path(output or Path.home() / 'ForgeGames').resolve())
        self.lock = threading.RLock()
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.busy = False
        self.project = None
        self.executable = None
        self.source_ready = False
        self.phase = 'Ready'
        self.logs = []
        self.usage = {}
        self.thread = None
        self.port = None

    def settings(self, payload):
        key = str(payload.get('key', '')).strip()
        provider = payload.get('provider', 'DeepSeek')
        if not key or len(key) > 4096:
            raise ValueError('Enter your API key.')
        if provider not in ('DeepSeek', 'OpenRouter'):
            raise ValueError('Choose official DeepSeek or OpenRouter.')
        model = str(payload.get('model', '')).strip()
        if not model:
            raise ValueError('Enter the provider model ID.')
        return key, provider, model

    def check_key(self, payload):
        key, provider, model = self.settings(payload)
        job = forge.GenerationJob(key, model, '', '', Path(self.output), 32768, 'Off', lambda *a: None,
            provider=provider, rates={'prompt':1.32e-6, 'completion':3.96e-6})
        try:
            forge.configure_provider(job)
        except Exception as error:
            raise ValueError(str(error).replace(key, '[REDACTED]')) from None
        return {'message':'Key and selected model are available.'}

    def folders(self, payload):
        path = Path(str(payload.get('path') or self.output)).expanduser()
        if not path.is_absolute():
            raise ValueError('Enter an absolute folder path.')
        while not path.exists() and path.parent != path:
            path = path.parent
        if not path.is_dir():
            raise ValueError('That folder is not available.')
        path = path.resolve()
        try:
            children = []
            for child in path.iterdir():
                try:
                    if not child.name.startswith('.') and child.is_dir():
                        children.append({'name':child.name,'path':str(child)})
                except OSError:
                    continue
        except OSError:
            raise ValueError('This folder cannot be opened by the current Windows user.') from None
        anchors = [{'name':'Home','path':str(Path.home())}]
        if os.name == 'nt':
            mask = forge.ctypes.windll.kernel32.GetLogicalDrives()
            anchors.extend({'name':chr(65+i)+':','path':chr(65+i)+':\\'} for i in range(26) if mask & (1 << i))
        else:
            anchors.append({'name':'Root','path':'/'})
        return {'path':str(path),'parent':str(path.parent), 'anchors':anchors,
                'folders':sorted(children,key=lambda item:item['name'].casefold())}

    def build_existing(self, payload):
        project = Path(str(payload.get('project',''))).expanduser()
        if not project.is_absolute() or not (project/'main.py').is_file():
            raise ValueError('Choose an existing generated project folder containing main.py.')
        project = project.resolve()
        with self.lock:
            if self.busy:
                raise ValueError('A generation or build is already running.')
            self.events = queue.Queue()
            self.cancel = threading.Event()
            self.busy, self.source_ready = True, True
            self.project, self.executable = project, None
            self.usage, self.logs = {}, ['Building saved source locally — no model requests or API key needed.']
            self.phase = 'Building saved project'
            self.thread = threading.Thread(target=self._build_worker,args=(project,),daemon=True)
            self.thread.start()
        return {'message':'Local rebuild started. No API requests.'}

    def _build_worker(self, project):
        try:
            self.events.put(('project',str(project)))
            executable = forge.build_desktop(project,Path(sys.executable),
                lambda kind,value:self.events.put((kind,value)),self.cancel)
            receipt = project/'.agent/run.json'
            if receipt.is_file():
                state = json.loads(receipt.read_text(encoding='utf-8'))
                state['status'] = 'complete'
                receipt.write_text(json.dumps(state,indent=2),encoding='utf-8')
            self.events.put(('done',(project,executable,0)))
        except Exception as error:
            self.events.put(('error',str(error)))

    def start(self, payload):
        key, provider, model = self.settings(payload)
        task = str(payload.get('task', '')).strip()
        if not task:
            raise ValueError('Enter the generation task.')
        documents = payload.get('documents', [])
        if not isinstance(documents, list) or not documents:
            raise ValueError('Select the architecture Markdown files.')
        selected = []
        names = set()
        for item in documents:
            if not isinstance(item, dict):
                raise ValueError('Each document needs a filename and text.')
            name = str(item.get('name', ''))
            if Path(name).name != name or '/' in name or '\\' in name or not name.lower().endswith('.md'):
                raise ValueError('Use Markdown filenames without directories.')
            if name.casefold() in names:
                raise ValueError('Each selected filename must be unique.')
            names.add(name.casefold())
            text = item.get('text')
            if not isinstance(text, str) or not text.strip():
                raise ValueError('An input document is empty.')
            selected.append((name, text))
        output_text = str(payload.get('output', self.output)).strip()
        output = Path(output_text).expanduser()
        if not output_text or not output.is_absolute():
            raise ValueError('Enter an absolute output folder, for example D:\\ForgeGames.')
        with self.lock:
            if self.busy:
                raise ValueError('A generation is already running.')
            self.events = queue.Queue()
            self.cancel = threading.Event()
            self.busy = True
            self.project = self.executable = None
            self.source_ready = False
            self.logs, self.usage = [], {}
            self.phase = 'Reading selected architecture files'
            self.thread = threading.Thread(target=self._worker,
                args=(key, provider, model, task, output.resolve(), selected), daemon=True)
            self.thread.start()
        return {'message':'Generation started.'}

    def _worker(self, key, provider, model, task, output, documents):
        try:
            with tempfile.TemporaryDirectory(prefix='forge-web-input-') as temporary:
                paths = []
                for name, text in documents:
                    path = Path(temporary) / name
                    path.write_text(text, encoding='utf-8', newline='')
                    paths.append(str(path))
                # Same code path, costs, repair limit and EXE builder as Forge.exe.
                agent = forge.CodeAgent.__new__(forge.CodeAgent)
                agent.events, agent.cancel = self.events, self.cancel
                forge.CodeAgent.worker(agent, key, model, task, output, tuple(paths), 32768,
                    'Off', None, provider, {'prompt':1.32e-6, 'completion':3.96e-6},
                    'Local', sys.executable, forge.RUN_BUDGET)
        except Exception as error:
            self.events.put(('error', str(error).replace(key, '[REDACTED]')))

    def snapshot(self):
        with self.lock:
            while True:
                try:
                    kind, value = self.events.get_nowait()
                except queue.Empty:
                    break
                if kind == 'project':
                    self.project = Path(value).resolve()
                    self.logs.append('Project: ' + str(self.project))
                elif kind == 'phase':
                    self.phase = str(value)
                    self.logs.append(self.phase)
                elif kind == 'usage':
                    self.usage = value
                elif kind == 'preview_ready':
                    self.source_ready = True
                elif kind == 'executable_ready':
                    self.executable = Path(value).resolve()
                    self.logs.append('Windows executable: ' + str(self.executable))
                elif kind == 'done':
                    self.project, executable, count = value
                    self.project = Path(self.project).resolve()
                    self.executable = Path(executable).resolve() if executable else None
                    self.source_ready, self.busy = True, False
                    report = self.project / '.agent/desktop-build.json'
                    warnings = json.loads(report.read_text(encoding='utf-8')).get('warnings', []) if report.is_file() else []
                    self.phase = 'Game EXE ready' + (' · optional warnings recorded' if warnings else '')
                    self.logs.append(self.phase)
                elif kind == 'error':
                    self.busy = False
                    self.phase = 'Stopped' if self.cancel.is_set() else 'Needs attention'
                    self.logs.append(str(value))
            return {'busy':self.busy, 'phase':self.phase, 'logs':self.logs[-1000:], 'usage':self.usage,
                'project':str(self.project) if self.project else '', 'output':self.output,
                'executable':str(self.executable) if self.executable else '',
                'exe_ready':bool(self.executable and self.executable.is_file()),
                'source_ready':self.source_ready}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Request bodies, API keys and session tokens are never logged.

    def valid_request(self, token=True):
        allowed = {f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'}
        if self.headers.get('Host') not in allowed:
            self.send_error(403, 'Local browser access only')
            return False
        origin = self.headers.get('Origin')
        if origin and origin not in {'http://' + host for host in allowed}:
            self.send_error(403, 'Different browser origin rejected')
            return False
        if token and not secrets.compare_digest(self.headers.get('X-Forge-Token', ''), self.server.app.token):
            self.send_error(403, 'Browser session token required')
            return False
        return True

    def send_bytes(self, data, content_type='application/json; charset=utf-8', status=200, filename=None):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if filename:
            self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        self.end_headers()
        self.wfile.write(data)

    def send_json(self, data, status=200):
        self.send_bytes(json.dumps(data).encode('utf-8'), status=status)

    def do_GET(self):
        if self.path == '/':
            if self.valid_request(token=False):
                page = Path(__file__).with_name('index.html').read_text(encoding='utf-8')
                self.send_bytes(page.replace('__FORGE_TOKEN__', self.server.app.token).encode('utf-8'), 'text/html; charset=utf-8')
            return
        if not self.valid_request():
            return
        app = self.server.app
        state = app.snapshot()
        if self.path == '/api/state':
            self.send_json(state)
        elif self.path == '/api/game.exe':
            if not state['exe_ready'] or not app.executable.is_relative_to(app.project):
                self.send_json({'error':'No completed executable yet.'}, 404)
            else:
                self.send_bytes(app.executable.read_bytes(), 'application/octet-stream', filename='SpaceFractions.exe')
        elif self.path == '/api/source.zip':
            if not state['source_ready'] or not app.project:
                self.send_json({'error':'Source generation is not complete.'}, 404)
                return
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
                for path in app.project.rglob('*'):
                    relative = path.relative_to(app.project)
                    if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(app.project) and not any(part.startswith('.') or part in {'__pycache__','Desktop'} for part in relative.parts) and path.suffix.lower() not in {'.exe','.pyc','.log'}:
                        archive.write(path, relative.as_posix())
            self.send_bytes(buffer.getvalue(), 'application/zip', filename='SpaceFractions-source.zip')
        else:
            self.send_json({'error':'Not found.'}, 404)

    def do_POST(self):
        if not self.valid_request():
            return
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8 * 1024 * 1024:
                raise ValueError('Request size is invalid (maximum 8 MiB).')
            payload = json.loads(self.rfile.read(size))
            if not isinstance(payload, dict):
                raise ValueError('Expected a JSON object.')
            if self.path == '/api/check-key':
                response = self.server.app.check_key(payload)
            elif self.path == '/api/folders':
                response = self.server.app.folders(payload)
            elif self.path == '/api/build':
                response = self.server.app.build_existing(payload)
            elif self.path == '/api/generate':
                response = self.server.app.start(payload)
            elif self.path == '/api/stop':
                self.server.app.cancel.set()
                response = {'message':'Stop requested; completed files are preserved.'}
            else:
                self.send_json({'error':'Not found.'}, 404)
                return
            self.send_json(response)
        except (ValueError, TypeError, KeyError) as error:
            self.send_json({'error':str(error)}, 400)
        except Exception:
            self.send_json({'error':'The local operation failed. Check the output path and runtime.'}, 500)


def create_server(port=8765, output=None):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.app = WebAgent(output)
    return server


def run():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--output', help='Default absolute output folder shown in the browser')
    args = parser.parse_args()
    server = create_server(args.port, args.output)
    print('Forge WEB BACKUP — desktop EXE remains the primary submission.', flush=True)
    print(f'Open http://127.0.0.1:{server.server_port}/ in your browser. Keep this terminal open.', flush=True)
    print('Press Ctrl+C to stop. Keys are held in memory only; no API requests occur until you submit.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.app.cancel.set()
    finally:
        server.server_close()


if __name__ == '__main__':
    run()
