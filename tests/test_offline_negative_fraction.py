"""Replay the user's failed run. No key lookup, paid requests or new game."""
import hashlib
import importlib.util
import json
import sys
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import requests

import acceptance_gate
import main
import repair_engine
from repair_protocol import declaration_changes, symbols

FIXTURE = Path(__file__).parent / 'fixtures/negative_fraction_run'


@pytest.fixture(autouse=True)
def prohibit_network_and_keys(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Offline test attempted network or saved-key access')
    monkeypatch.setattr(requests.Session, 'request', forbidden)
    monkeypatch.setattr(main, 'load_key', forbidden)


def load_domain(source):
    module = type(sys)('offline_domain')
    with patch.dict(sys.modules, {'offline_domain': module}):
        exec(compile(source, 'offline_domain.py', 'exec'), module.__dict__)
    return module


def make_replay(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    for name in ('domain.py', 'content.py'):
        (tmp_path / name).write_bytes((FIXTURE / name).read_bytes())
    (tmp_path / 'main.py').write_text('from domain import check_answer\nfrom content import default_questions\nVALUE = 1\n')
    job = main.GenerationJob('offline-dummy', 'offline-dummy', 'Task', 'Docs', tmp_path, 32768, 'Off', lambda *a: None)
    job.project = tmp_path
    job.state = {'manifest': {'files': [{'path': p} for p in ('main.py', 'domain.py', 'content.py')]},
                 'completed': {p: hashlib.sha256((tmp_path / p).read_bytes()).hexdigest() for p in ('main.py', 'domain.py', 'content.py')},
                 'requests': []}
    (tmp_path / '.agent').mkdir()
    original = (tmp_path / 'domain.py').read_text(encoding='utf-8')
    domain = load_domain(original)
    evidence = acceptance_gate.answer_roundtrip_evidence(domain, Fraction(-5, 6), '-5/6')
    assert evidence['parsed'] == '5/6'
    failure = acceptance_gate.AcceptanceFailure('generated answer round-trip: q018', evidence)
    (tmp_path / '.agent/product-acceptance.json').write_text(json.dumps(acceptance_gate.failure_result(failure)))
    return job, RuntimeError('ACCEPTANCE: generated answer round-trip: q018'), original


def parser_reply(original):
    # This is an explicitly authored OFFLINE expected response, not a live LLM
    # result or code substituted into Forge's generated games.
    code = symbols(original)['parse_answer']['code']
    old = 'return Fraction(int(numerator), denom)'
    assert code.count(old) == 1
    fixed = code.replace(old, 'result = Fraction(int(numerator), denom)\n        return -result if value.startswith("-") else result')
    return json.dumps({'repairs': [{'path': 'domain.py', 'reason': 'Fraction branch discarded the input sign',
        'replacements': [{'symbol': 'parse_answer', 'code': fixed}]}]})


def recorded_responses():
    return json.loads((FIXTURE / 'recorded-noops.json').read_text(encoding='utf-8'))


def test_actual_run_rejects_negative_fraction_before_checker():
    domain = load_domain((FIXTURE / 'domain.py').read_text(encoding='utf-8'))
    evidence = acceptance_gate.answer_roundtrip_evidence(domain, Fraction(-5, 6), '-5/6')
    assert not domain.check_answer(Fraction(-5, 6), '-5/6')
    assert evidence['symbol'] == 'parse_answer'
    assert evidence['input'] == evidence['expected'] == '-5/6'
    assert evidence['parsed'] == '5/6'
    assert not evidence['parse_matches_expected']


def test_actual_noop_retries_the_parser_and_preserves_correct_checker(tmp_path):
    job, error, original = make_replay(tmp_path)
    first = recorded_responses()[0]['response']
    with patch.object(job, 'request', side_effect=[first, parser_reply(original)]) as request:
        assert job.repair_failed_build(error)
    assert request.call_count == 2
    retry = request.call_args_list[1].args[1]
    assert '"symbol": "parse_answer"' in retry
    assert '"expected": "-5/6"' in retry and '"parsed": "5/6"' in retry
    assert 'CURRENT DECLARATION:\ndef parse_answer' in retry
    assert 'previous response made no executable change' in retry
    assert '"symbol": "parse_answer"' in request.call_args_list[0].args[1]
    assert 'def check_answer(' not in request.call_args_list[0].args[1]
    updated = (tmp_path / 'domain.py').read_text(encoding='utf-8')
    assert symbols(original)['check_answer']['code'] == symbols(updated)['check_answer']['code']
    fixed_domain = load_domain(updated)
    content_namespace = {}
    with patch.dict(sys.modules, {'domain': fixed_domain}):
        exec(compile((FIXTURE / 'content.py').read_text(encoding='utf-8'), 'content.py', 'exec'), content_namespace)
    questions = content_namespace['default_questions']()
    assert len(questions) == 24
    for q in questions:
        assert q.answer == acceptance_gate.arithmetic_value(q.prompt)[0]
        assert fixed_domain.parse_answer(str(q.answer)) == q.answer
        assert fixed_domain.check_answer(q.answer, str(q.answer))
    assert job.state['requests'] == []  # mock adapter, no paid request ledger


def test_both_recorded_noops_preserve_source_and_report_actual_failure(tmp_path):
    job, error, original = make_replay(tmp_path)
    replies = [r['response'] for r in recorded_responses()]
    before = dict(job.state['completed'])
    with patch.object(job, 'request', side_effect=replies) as request:
        with pytest.raises(ValueError, match='domain.py:parse_answer') as stopped:
            job.repair_failed_build(error)
    assert request.call_count == 2
    assert 'observed 5/6' in str(stopped.value)
    assert 'q018' in str(stopped.value)
    assert (tmp_path / 'domain.py').read_text(encoding='utf-8') == original
    assert job.state['completed'] == before
    assert not job.state.get('pending_repair')
    rejections = [json.loads(p.read_text()) for p in (tmp_path / '.agent/rejected-repairs').glob('*.json')]
    assert len(rejections) == 2
    assert all(r['category'] == 'no_progress' for r in rejections)


def test_noop_file_cannot_discard_valid_repair_in_same_response(tmp_path):
    job, error, original = make_replay(tmp_path)
    record = json.loads(parser_reply(original))
    record['repairs'].insert(0, {'path': 'main.py', 'replacements': [{'symbol': 'VALUE', 'code': 'VALUE = 1 # explanation only'}]})
    with patch.object(job, 'request', return_value=json.dumps(record)) as request:
        assert job.repair_failed_build(error)
    assert request.call_count == 1
    assert (tmp_path / 'main.py').read_text().endswith('VALUE = 1\n')
    assert [c['path'] for c in job.state['pending_repair']['changes']] == ['domain.py']


def test_docstring_only_repair_is_not_a_behavior_fix():
    old = 'def check_answer(x):\n    """Old explanation."""\n    return x\n'
    new = 'def check_answer(x):\n    """A convincing but inaccurate new explanation."""\n    return x\n'
    updated, changes = declaration_changes(old, [{'symbol': 'check_answer', 'code': new}])
    assert updated == old and changes == []


def test_checker_focus_does_not_instruct_bool_function_to_return_fraction(tmp_path):
    job, error, original = make_replay(tmp_path)
    failure = repair_engine.failure_record(job, error)
    failure['diagnostics'].update(symbol='check_answer', parsed='-5/6', parse_matches_expected=True)
    retry = repair_engine.focused_retry('', failure, {'domain.py': original}, {'domain.py': symbols(original)}, [])
    assert 'Return bool from the answer checker' in retry


def test_diagnostics_survive_report_and_repair_error_boundaries(tmp_path):
    job, error, _ = make_replay(tmp_path)
    failure = repair_engine.failure_record(job, error)
    assert failure['diagnostics']['symbol'] == 'parse_answer'
    assert failure['diagnostics']['parsed'] == '5/6'
