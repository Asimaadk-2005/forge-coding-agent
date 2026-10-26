"""Browser backup unit tests; no networking or provider credentials."""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from fallback.web_agent import WebAgent, forge


def payload(tmp_path):
    return {'key':'offline-fixture-key','provider':'DeepSeek','model':'deepseek-v4-pro',
            'task':'Fixture task','output':str(tmp_path),
            'documents':[{'name':'Architecture.md','text':'# Fixture architecture'}]}


def test_web_uses_the_same_desktop_worker_and_portable_runtime(tmp_path):
    app = WebAgent(tmp_path)
    with patch.object(forge.CodeAgent,'worker') as worker:
        app.start(payload(tmp_path))
        app.thread.join(3)
    args = worker.call_args.args
    assert args[1:5] == ('offline-fixture-key','deepseek-v4-pro','Fixture task',tmp_path)
    assert args[6:11] == (32768,'Off',None,'DeepSeek',{'prompt':1.32e-6,'completion':3.96e-6})
    assert args[11:] == ('Local',forge.sys.executable,forge.RUN_BUDGET)
    assert 'offline-fixture-key' not in json.dumps(app.snapshot())


@pytest.mark.parametrize('name',['../private.md',r'..\private.md','C:\\private.md','instructions.exe'])
def test_web_rejects_document_path_escape_before_starting_worker(tmp_path,name):
    app = WebAgent(tmp_path)
    data = payload(tmp_path)
    data['documents'][0]['name'] = name
    with patch.object(forge.CodeAgent,'worker') as worker, pytest.raises(ValueError):
        app.start(data)
    worker.assert_not_called()
    assert not app.busy


def test_optional_warnings_keep_download_available(tmp_path):
    app = WebAgent(tmp_path)
    project = tmp_path / 'fixture'
    (project / '.agent').mkdir(parents=True)
    executable = project / 'SpaceFractions.exe'
    executable.write_bytes(b'Transport fixture only; not a runnable game')
    (project / '.agent/desktop-build.json').write_text('{"warnings":["Fixture advisory warning"]}')
    app.busy = True
    app.events.put(('project',str(project)))
    app.events.put(('done',(project,executable,11)))
    state = app.snapshot()
    assert not state['busy'] and state['exe_ready'] and state['source_ready']
    assert 'warnings' in state['phase']


def test_key_check_redacts_failed_provider_messages(tmp_path):
    app = WebAgent(tmp_path)
    with patch.object(forge,'configure_provider',side_effect=RuntimeError('Rejected offline-fixture-key')):
        with pytest.raises(ValueError) as error:
            app.check_key(payload(tmp_path))
    assert 'offline-fixture-key' not in str(error.value)
    assert '[REDACTED]' in str(error.value)


def test_browser_secret_is_never_written_into_static_source():
    page = (Path(__file__).resolve().parents[1]/'fallback/index.html').read_text(encoding='utf-8')
    assert '__FORGE_TOKEN__' in page
    assert 'localStorage' not in page and 'sessionStorage' not in page
