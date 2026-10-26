"""Offline delivery-policy regressions; never contact a provider."""
import json
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import acceptance_gate
import main
from tests.test_agent import fixture_project


def test_natural_question_wording_is_valid_arithmetic():
    for prompt in ('What is 1/2 + 1/4?', '1/2 + 1/4 = ?', 'Calculate: 1/2 + 1/4'):
        assert acceptance_gate.arithmetic_value(prompt)[0] == Fraction(3, 4)


def test_timed_intro_does_not_require_a_skip_button(tmp_path):
    import tkinter as tk
    root = tk.Tk()
    app = SimpleNamespace(screen='intro', widgets={})
    try:
        root.after(10, lambda: setattr(app, 'screen', 'menu'))
        click = Mock(side_effect=AssertionError('No Skip button exists'))
        acceptance_gate.finish_intro(root, app, click)
        assert app.screen == 'menu'
        click.assert_not_called()
    finally:
        root.destroy()


def test_advisory_failure_preserves_verified_executable(tmp_path):
    fixture_project(tmp_path)
    events = []
    def command(arguments, project, log, cancel, *args, **kwargs):
        if 'PyInstaller' in arguments:
            output = Path(arguments[arguments.index('--distpath') + 1])
            output.mkdir()
            (output / 'SpaceFractions.exe').write_bytes(b'offline build fixture')
        else:
            assert (tmp_path / 'SpaceFractions.exe').is_file()
            assert any(kind == 'executable_ready' for kind, _ in events)
            raise RuntimeError('Recorded generated-test failure')
    with patch.object(main, 'protected_foundation', return_value={'forge_ui.py': 'hash'}), \
         patch.object(main, 'product_acceptance', return_value={'status':'passed'}), \
         patch.object(main, 'smoke_desktop'), patch.object(main, 'run_build_command', side_effect=command):
        executable = main.build_desktop(tmp_path, Path(main.sys.executable), lambda *e: events.append(e))
    report = json.loads((tmp_path / '.agent/desktop-build.json').read_text())
    assert executable.is_file() and report['status'] == 'complete'
    assert report['product_acceptance'] == 'passed_source_and_packaged'
    assert not report['tests_passed'] and report['generated_tests'] == 'warnings'
    assert report['warnings'] and report['validation_policy'] == 'essential'


def test_confirmed_gameplay_repair_is_limited_to_two_rounds(tmp_path):
    job = main.GenerationJob('unused', 'unused', 'Task', 'Docs', tmp_path, 4096, 'Off', lambda *a: None)
    job.repair_failed_build = Mock(return_value=True)
    with patch.object(main, 'build_desktop', side_effect=RuntimeError('ACCEPTANCE: broken score')) as build, \
         patch.object(main.repair_engine, 'settle', return_value=False):
        import pytest
        with pytest.raises(RuntimeError, match='broken score'):
            main.build_with_repairs(job, tmp_path, Path(main.sys.executable), lambda *a: None, main.Event())
    assert job.repair_failed_build.call_count == 2 and build.call_count == 3


def test_source_preview_can_open_while_generation_worker_is_busy(tmp_path):
    fixture_project(tmp_path)
    agent = main.CodeAgent.__new__(main.CodeAgent)
    agent.project, agent.executable = tmp_path, None
    agent.python = SimpleNamespace(get=lambda: main.sys.executable)
    agent.status, agent._append_activity = Mock(), Mock()
    with patch.object(main.subprocess, 'Popen') as launch:
        main.CodeAgent.play(agent)
    assert launch.call_args.args[0] == [main.sys.executable, '-B', '-u', str(tmp_path / 'main.py')]
    assert launch.call_args.kwargs['cwd'] == tmp_path
    assert (tmp_path / '.agent/preview.log').is_file()


def test_missing_session_total_is_normalized_without_model_or_ledger_changes(tmp_path):
    (tmp_path / '.agent').mkdir()
    (tmp_path / 'domain.py').write_text('class Session:\n    def __init__(self, questions):\n        self.questions = questions\n')
    source = ('from domain import Session\nclass GameApp(GameShell):\n'
              '    def summary(self):\n        return f"Résumé: {self.session.total}", "self.session.total"\n')
    (tmp_path / 'app.py').write_text(source, encoding='utf-8')
    before = main.hashlib.sha256((tmp_path / 'app.py').read_bytes()).hexdigest()
    state = {'desktop_contract':3, 'completed':{'app.py':before}, 'requests':[{'cost':.13}]}
    (tmp_path / '.agent/run.json').write_text(json.dumps(state))
    record = main.normalize_session_api(tmp_path)
    updated = (tmp_path / 'app.py').read_text(encoding='utf-8')
    assert 'f"Résumé: {len(self.session.questions)}"' in updated
    assert '"self.session.total"' in updated  # Strings/comments are untouched.
    assert record['api_requests'] == 0
    saved = json.loads((tmp_path / '.agent/run.json').read_text())
    assert saved['requests'] == state['requests'] and saved['completed']['app.py'] == record['after']
    assert main.normalize_session_api(tmp_path) is None
    assert len(list((tmp_path / '.agent/api-normalization').glob('*-app.py.txt'))) == 1


def test_real_session_total_property_is_preserved(tmp_path):
    (tmp_path / '.agent').mkdir()
    (tmp_path / '.agent/run.json').write_text('{"desktop_contract":3}')
    (tmp_path / 'domain.py').write_text('class Session:\n    @property\n    def total(self):\n        return 20\n')
    source = 'from domain import Session\nclass GameApp(GameShell):\n    def summary(self):\n        return self.session.total\n'
    (tmp_path / 'app.py').write_text(source)
    assert main.normalize_session_api(tmp_path) is None
    assert (tmp_path / 'app.py').read_text() == source


def test_play_prefers_executable_even_after_a_warning(tmp_path):
    executable = tmp_path / 'SpaceFractions.exe'
    executable.write_bytes(b'local executable fixture')
    agent = main.CodeAgent.__new__(main.CodeAgent)
    agent.project, agent.executable = tmp_path, None
    with patch.object(main.subprocess, 'Popen') as launch:
        main.CodeAgent.play(agent)
    assert launch.call_args.args[0] == [str(executable)]


def test_real_play_button_stays_enabled_after_test_warnings(tmp_path):
    import tkinter as tk
    fixture_project(tmp_path)
    executable = tmp_path / 'SpaceFractions.exe'
    executable.write_bytes(b'local executable fixture')
    (tmp_path / '.agent').mkdir()
    (tmp_path / '.agent/desktop-build.json').write_text(json.dumps({
        'product_acceptance':'passed_source_and_packaged', 'warnings':['Recorded advisory failure']}))
    root = tk.Tk()
    app = None
    try:
        with patch.object(main, 'load_key', return_value=None):
            app = main.CodeAgent(root)
        app.events.put(('preview_ready', str(tmp_path)))
        root.after_cancel(app._poll_timer)
        app.poll_events()
        assert not app.play_button.enabled
        app.events.put(('done', (tmp_path, executable, 0)))
        root.after_cancel(app._poll_timer)
        app.poll_events()
        assert app.play_button.caption == 'Play game' and app.play_button.enabled
        assert 'warnings' in app.status.get()
        with patch.object(main.subprocess, 'Popen') as launch:
            app.play_button.command()
        assert launch.call_args.args[0] == [str(executable)]
    finally:
        app.close() if app else root.destroy()


def test_fresh_generation_corrects_the_missing_alias_before_play_is_enabled(tmp_path):
    # Minimal mocked provider outputs test the actual generation path, not a
    # manually patched saved project. This is not a live/generated-game claim.
    generated = {
        'domain.py':'class Session:\n    def __init__(self, questions):\n        self.questions = questions\n',
        'app.py':'from domain import Session\nfrom forge_ui import GameShell\nclass GameApp(GameShell):\n    def summary(self):\n        return self.session.total\n',
        'main.py':'import tkinter as tk\nfrom app import GameApp\n',
        'content.py':'TITLE = "Fixture"\n', 'storage.py':'class Store:\n    pass\n',
        'tests/test_domain.py':'def test_fixture():\n    assert True\n',
        'tests/test_app.py':'def test_fixture():\n    assert True\n',
    }
    events = []
    def emit(kind, value):
        if kind == 'preview_ready':
            assert 'len(self.session.questions)' in (Path(value) / 'app.py').read_text()
        events.append((kind, value))
    def respond(stage, instruction, *args):
        if stage == 'Planning component APIs':
            return '{"files":[]}'
        path = instruction.split('Write ONLY the complete contents of ')[1].split('. No JSON')[0]
        return generated.get(path, '# Fixture documentation\n')
    job = main.GenerationJob('unused', 'unused', 'Fixture', 'Fixture', tmp_path, 4096, 'Off', emit)
    with patch.object(main, 'configure_provider', side_effect=lambda j: setattr(j, 'info', {})), \
         patch.object(job, 'request', side_effect=respond):
        project, *_ = job.run()
    assert project.parent == tmp_path and any(k == 'preview_ready' for k,_ in events)
    assert job.state['completed']['app.py'] == main.hashlib.sha256((project / 'app.py').read_bytes()).hexdigest()
    assert job.state['requests'] == []


def test_declared_fraction_type_is_enforced_on_the_first_default_load(tmp_path):
    import runpy
    (tmp_path / '.agent').mkdir()
    (tmp_path / '.agent/run.json').write_text('{"desktop_contract":3,"completed":{},"requests":[]}')
    (tmp_path / 'domain.py').write_text(
        'from dataclasses import dataclass\nfrom fractions import Fraction\n'
        '@dataclass(frozen=True)\nclass Question:\n    id: str\n    prompt: str\n    answer: Fraction\n')
    changes = main.normalize_generation_api(tmp_path)
    assert 'domain.py' in changes
    domain = runpy.run_path(str(tmp_path / 'domain.py'))
    first = domain['Question']('q1', '1/2 + 1/4', '3/4')
    assert first.answer == Fraction(3,4) and isinstance(first.answer, Fraction)
    assert main.normalize_generation_api(tmp_path) == {}


def test_draw_only_and_label_only_both_display_the_question(tmp_path):
    import tkinter as tk
    from foundation.forge_ui import GameShell
    root = tk.Tk()
    app = GameShell(root, tmp_path)
    try:
        app.page('play', 'Fractions')
        app.entry('answer')
        app.button('check','Check',lambda:None)
        app.draw_question('1/2 + 1/4')
        root.update()
        assert app.widgets['question'].winfo_ismapped()
        assert app.widgets['question'].cget('text') == app._prompt == '1/2 + 1/4'
        app.page('play', 'Fractions')
        app.label('question','1/3 + 1/6')
        root.update()
        assert app._prompt == '1/3 + 1/6'
        app.widgets['question'].configure(text='1/4 + 1/4')
        app._paint()
        assert app._prompt == '1/4 + 1/4'
        assert any(app.canvas.itemcget(item, 'text') == '1/4 + 1/4'
                   for item in app.canvas.find_all() if app.canvas.type(item) == 'text')
    finally:
        app.close()
