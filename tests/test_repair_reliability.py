import hashlib
import json
import subprocess
import sys
from fractions import Fraction
from unittest.mock import patch

import pytest
import main
import game_blueprint
import repair_engine
from acceptance_gate import arithmetic_value
from repair_protocol import replace_symbols, parse_repair_response


@pytest.mark.parametrize('prompt,answer', [
    ('1/3 + 1/6 + 1/2 = ?', Fraction(1)),
    ('(1/2 + 1/3) * 3/5 = ?', Fraction(1, 2)),
    ('-1 1/2 + 2/3 = ?', Fraction(-5, 6)),
    ('-0 1/2 + 1/4 = ?', Fraction(-1, 4)),
    ('Calculate: 2/3 ÷ (4/5) = ?', Fraction(5, 6)),
    ('1/2 ÷ 1/3 = ?', Fraction(3, 2)),
    ('1/2 / 1/3 = ?', Fraction(3, 2)),
    ('1/2 -1 1/2 = ?', Fraction(-1)),
    ('1/2+1 1/2 = ?', Fraction(2)),
])
def test_complete_expression_verification(prompt, answer):
    assert arithmetic_value(prompt)[0] == answer


@pytest.mark.parametrize('prompt', ['1/2 + 1/3 trailing text', '__import__("os")', '2**8', 'True + 1'])
def test_expression_checker_never_uses_a_prefix_or_executes_code(prompt):
    with pytest.raises((SyntaxError, ValueError)):
        arithmetic_value(prompt)


def test_package_aliases_merge_before_generation_and_dependencies_follow():
    items = [{'path': p, 'depends_on': ['game/domain.py']} for p in (
        'game/domain.py', 'domain.py', 'game/content.py', 'game/forge_ui.py',
        'game/__init__.py', 'game/tests/__init__.py', 'game/tests/test_domain.py')]
    plan = game_blueprint.normalize_plan({'files': items})
    paths = [f['path'] for f in plan['files']]
    assert not any(p.startswith('game/') for p in paths)
    assert paths.count('domain.py') == 1
    assert paths.count('tests/test_domain.py') == 1
    assert 'tests/__init__.py' in paths
    assert plan['desktop_contract'] == game_blueprint.VERSION
    assert main.parse_manifest(json.dumps(plan))


@pytest.mark.parametrize('path', ['main.pya', '../domain.py', 'D:/domain.py'])
def test_plan_rejects_bad_extension_and_paths(path):
    with pytest.raises(ValueError):
        game_blueprint.normalize_plan({'files': [{'path': path}]})


def test_declaration_repair_preserves_other_source_and_decorators():
    source = 'OTHER = 9\nclass A:\n    @property\n    def value(self):\n        return 1\n'
    changed = replace_symbols(source, [{'symbol': 'A.value', 'code': '@property\ndef value(self):\n    return 2'}])
    assert 'OTHER = 9' in changed
    namespace = {}
    exec(changed, namespace)
    assert namespace['A']().value == 2
    with pytest.raises(ValueError):
        replace_symbols('VALUE=1\n', [{'symbol': 'VALUE', 'code': 'OTHER = VALUE'}])
    with pytest.raises(ValueError):
        replace_symbols(source, [{'symbol': 'A', 'code': 'class A:\n    pass'}, {'symbol': 'A.value', 'code': 'def value(self): return 2'}])


def test_callback_id_enumeration_is_valid_cleanup_but_not_a_clock(tmp_path):
    manifest = {'files': [{'path': 'main.py'}]}
    target = tmp_path / 'main.py'
    target.write_text('for job in list(root.tk.call("after", "info") or []):\n    root.after_cancel(job)\n')
    assert main.inspect_generated_python(tmp_path, manifest) == []
    target.write_text('elapsed = float(root.tk.call("after", "info"))\n')
    assert 'not elapsed time' in main.inspect_generated_python(tmp_path, manifest)[0][1]


def test_final_provider_boundary_is_parsed_without_guessing_arbitrary_json():
    assert parse_repair_response('malformed explanation <｜end▁of▁thinking｜>{"repairs":[]}') == {'repairs': []}
    assert parse_repair_response('<think>explanation</think>{"repairs":[]}') == {'repairs': []}
    with pytest.raises(ValueError):
        parse_repair_response('narrative {"repairs":[]} trailing')
    with pytest.raises(ValueError):
        parse_repair_response('explanation</think>{"repairs":[')


def test_provider_keeps_output_limit_type_for_bounded_repair_retry():
    from types import SimpleNamespace
    job = SimpleNamespace(provider='DeepSeek', key='dummy', thinking='Off', current=None,
                          show_usage=lambda: None, cancel=None, emit=lambda *a: None)
    with patch.object(main, 'prepare_network_environment'), patch.object(main.requests, 'post'), \
         patch.object(main, 'read_completion_stream', side_effect=main.OutputLimitError('length')):
        with pytest.raises(main.OutputLimitError):
            main.provider_completion(job, {}, 'Repair')


def test_windowed_executable_console_failure_cannot_abort_a_build():
    with patch('builtins.print', side_effect=OSError(22, 'Invalid argument')):
        main.console_message('Testing game logic and component APIs')


def make_job(tmp_path):
    run = main.GenerationJob('dummy', 'dummy', 'Task', 'Docs', tmp_path, 32768, 'Off', lambda *a: None)
    run.project = tmp_path
    (tmp_path / '.agent').mkdir(exist_ok=True)
    (tmp_path / 'main.py').write_text('from domain import VALUE\n')
    (tmp_path / 'domain.py').write_text('VALUE = 1\n')
    run.state = {'manifest': {'files': [{'path': p} for p in ('main.py', 'domain.py', 'tests/test_app.py')]},
                 'completed': {'main.py': 'hash', 'domain.py': 'hash', 'tests/test_app.py': 'hash'}, 'requests': []}
    return run


def validation(tmp_path):
    report = {'failures': [{'nodeid': 'tests/test_app.py::TestApp::test_play', 'when': 'teardown',
                          'message': 'TclError: application has been destroyed', 'traceback': 'app.close(); root.destroy()'}]}
    (tmp_path / '.agent/validation.json').write_text(json.dumps(report))
    return RuntimeError('Tests or Windows build failed. See .agent/build.log.')


def test_actual_teardown_repair_targets_fixture_and_no_progress_rolls_back(tmp_path):
    run = make_job(tmp_path)
    target = tmp_path / 'tests/test_app.py'
    target.parent.mkdir()
    original = 'class TestApp:\n    def tearDown(self):\n        self.app.close()\n        self.root.destroy()\n    def test_play(self):\n        assert True\n'
    target.write_text(original)
    error = validation(tmp_path)
    reply = {'repairs': [{'path': 'tests/test_app.py', 'reason': 'double root destruction',
                         'test_contract_error': 'close destroys root', 'contract_evidence': 'GameShell.close lifecycle',
                         'replacements': [{'symbol': 'TestApp.tearDown', 'code': 'def tearDown(self):\n    self.app.close()'}]}]}
    with patch.object(run, 'request', return_value=json.dumps(reply)) as request:
        assert run.repair_failed_build(error)
        assert request.call_count == 1
        assert request.call_args.args[2] == 16384
    assert 'self.root.destroy()' not in target.read_text()
    assert (tmp_path / 'domain.py').read_text() == 'VALUE = 1\n'
    assert repair_engine.settle(run, error)
    assert target.read_text() == original
    assert run.state['rejected_repairs']
    assert run.state['repair_outcomes'][-1]['outcome'] == 'rolled_back_no_progress'


def test_clipped_declaration_response_retries_larger_without_partial_writes(tmp_path):
    run = make_job(tmp_path)
    reply = {'repairs': [{'path': 'domain.py', 'reason': 'bad constant',
                         'replacements': [{'symbol': 'VALUE', 'code': 'VALUE = 2'}]}]}
    with patch.object(run, 'request', side_effect=[main.OutputLimitError('length'), json.dumps(reply)]) as request:
        assert run.repair_failed_build(RuntimeError('/domain.py: source failure'))
    assert [call.args[2] for call in request.call_args_list] == [16384, 32768]
    assert (tmp_path / 'domain.py').read_text() == 'VALUE = 2\n'
    assert not repair_engine.settle(run)
    assert run.state['repair_outcomes'][-1]['outcome'] == 'validated'


def test_external_edits_prevent_rollback_and_preserve_pending_receipt(tmp_path):
    run = make_job(tmp_path)
    reply = {'repairs': [{'path': 'domain.py', 'replacements': [{'symbol': 'VALUE', 'code': 'VALUE = 2'}]}]}
    error = RuntimeError('/domain.py: source failure')
    with patch.object(run, 'request', return_value=json.dumps(reply)):
        run.repair_failed_build(error)
    (tmp_path / 'domain.py').write_text('VALUE = 3\n')
    with pytest.raises(RuntimeError, match='edited externally'):
        repair_engine.settle(run, error)
    assert 'pending_repair' in run.state
    assert (tmp_path / 'domain.py').read_text() == 'VALUE = 3\n'


def test_validation_runner_records_call_and_cleanup_separately(tmp_path):
    tests = tmp_path / 'tests'
    tests.mkdir()
    (tests / 'test_bad.py').write_text('import unittest\nclass TestBad(unittest.TestCase):\n    def tearDown(self): raise RuntimeError("cleanup")\n    def test_math(self): self.assertEqual(1,2)\n')
    report = tmp_path / 'validation.json'
    result = subprocess.run([sys.executable, '-I', str(main.Path(main.__file__).parent / 'validation_runner.py'), str(tmp_path), str(report)], capture_output=True)
    assert result.returncode != 0
    data = json.loads(report.read_text())
    assert any('cleanup' in failure['traceback'] for failure in data['failures'])
    assert any('AssertionError: 1 != 2' in failure['traceback'] for failure in data['failures'])
