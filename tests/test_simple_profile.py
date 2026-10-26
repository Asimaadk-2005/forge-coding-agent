import json
import re
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import acceptance_gate as gate
import game_blueprint
import main
import repair_engine
from repair_protocol import assertion_coverage, replace_symbols, symbols

REPEATED_FIXTURE = Path(__file__).parent / 'fixtures/empty_repeat_assertion'

# Offline contract fixtures only. None of these question answers are shipped as
# game content; the model continues to generate each project's question bank.
def basic_questions():
    expressions = [
        '1/2 + 1/4', '1/3 + 1/6', '1/4 + 1/4', '2/5 + 1/5', '1/8 + 3/8',
        '3/4 - 1/4', '2/3 - 1/3', '5/6 - 1/6', '3/8 - 1/8', '4/5 - 1/5',
        '1/2 * 1/2', '2/3 * 3/4', '1/4 * 1/2', '2/5 * 1/2', '3/4 * 2/3',
        '1/2 / 1/4', '3/4 / 1/2', '1/3 / 1/3', '2/5 / 1/5', '1/4 / 1/2',
    ]
    return [SimpleNamespace(id=str(i), prompt=e+' = ?', answer=gate.arithmetic_value(e)[0], explanation='Practice fractions')
            for i, e in enumerate(expressions)]


def assert_required(condition, message, *evidence):
    assert condition, message


def basic_domain():
    seen = []
    def parse(text):
        # A precision/negative/mixed probe accidentally used by the new checker
        # would fail this fixture instead of making a paid repair necessary.
        assert not any(c in text for c in '.eE- '), 'Unexpected advanced input probe: '+text
        seen.append(text)
        if not re.fullmatch(r'\d+(?:/\d+)?', text):
            raise ValueError('Invalid fraction')
        try:
            return Fraction(text)
        except ZeroDivisionError:
            raise ValueError('Zero denominator') from None
    def check(expected, text):
        try:
            return expected == parse(text)
        except ValueError:
            return False
    class Session:
        def __init__(self, questions):
            self.questions, self.correct, self.attempted, self.answered = questions, 0, 0, False
        def submit(self, text):
            if self.answered:
                return False, 'Already answered'
            correct = check(self.questions[0].answer, text)
            self.correct += int(correct)
            self.attempted += 1
            self.answered = True
            return correct, 'Checked'
    return SimpleNamespace(parse_answer=parse, check_answer=check, Question=lambda *a: SimpleNamespace(answer=a[2]), Session=Session), seen


def test_basic_checker_accepts_fraction_answers_without_precision_probes():
    domain, seen = basic_domain()
    gate.check_basic_math(domain, basic_questions(), assert_required, [])
    assert {'3/4','1/2','2/3','2/4','1'} <= set(seen)


def test_basic_profile_preserves_fraction_equality_and_all_four_operations():
    domain, _ = basic_domain()
    assert domain.check_answer(Fraction(1,2), '2/4')
    assert not domain.check_answer(Fraction(1,2), '1/3')
    questions = basic_questions()
    questions[0].prompt = '1 1/2 + 1/4 = ?'
    with pytest.raises(AssertionError, match='basic two-fraction'):
        gate.check_basic_math(domain, questions, assert_required, [])


def test_current_prompts_are_simple_and_legacy_runs_keep_their_contract():
    prompt = game_blueprint.SYSTEM_PROMPT + game_blueprint.CONTRACT + json.dumps(game_blueprint.FILES)
    assert '1e-9' not in prompt and '0.333333333' not in prompt
    assert '3/4' in prompt and 'EXACT' in prompt
    assert game_blueprint.VERSION == 3
    assert '1e-9' in game_blueprint.for_version(2).SYSTEM_PROMPT
    assert game_blueprint.for_version(3).VERSION == 3


def test_empty_exception_assertion_is_not_counted_as_a_valid_behavior_check():
    old = (REPEATED_FIXTURE/'recorded_tests.txt').read_text(encoding='utf-8')
    report = assertion_coverage(old)
    assert report['tests']['SessionTests.test_repeated_submit_prevented'] == 4
    assert any(e['test']=='SessionTests.test_repeated_submit_prevented' for e in report['empty_exception_contexts'])
    cleaned = old.replace('        with self.assertRaises(AssertionError):\n            pass\n', '')
    main.validate_test_repair(old, cleaned)


def corrected_repeat_method():
    return '''def test_repeated_submit_prevented(self):
    self.session.submit("3/4")
    with self.assertRaisesRegex(AssertionError, "already answered"):
        self.session.submit("1/2")
    self.assertEqual(self.session.attempted, 1)
    self.assertEqual(self.session.correct, 1)
    self.assertTrue(self.session.answered)
    self.assertEqual(self.session.index, 0)
'''


def test_real_failed_test_can_be_corrected_without_losing_meaningful_coverage():
    old = (REPEATED_FIXTURE/'recorded_tests.txt').read_text(encoding='utf-8')
    updated = replace_symbols(old, [{'symbol':'SessionTests.test_repeated_submit_prevented','code':corrected_repeat_method()}])
    main.validate_test_repair(old, updated)
    coverage = assertion_coverage(updated)
    assert coverage['tests']['SessionTests.test_repeated_submit_prevented'] == 5
    assert not coverage['empty_exception_contexts']


def test_recorded_exception_fix_preserves_operations_and_state_checks():
    old = (REPEATED_FIXTURE/'recorded_tests.txt').read_text(encoding='utf-8')
    recorded = json.loads((REPEATED_FIXTURE/'responses.json').read_text())[0]
    proposal = json.loads(recorded['response'])['repairs'][0]['replacements']
    updated = replace_symbols(old, proposal)
    main.validate_test_repair(old, updated)
    missing_state = proposal[0]['code'].replace('        self.assertEqual(self.session.correct, 1)', '')
    weaker = replace_symbols(old, [{'symbol':'SessionTests.test_repeated_submit_prevented','code':missing_state}])
    with pytest.raises(ValueError):
        main.validate_test_repair(old, weaker)


def test_per_test_guard_cannot_move_assertions_to_another_test():
    old = 'def test_a():\n    assert 1\n    assert 2\ndef test_b():\n    assert 3\n'
    changed = 'def test_a():\n    assert 1\ndef test_b():\n    assert 3\n    assert 2\n'
    with pytest.raises(ValueError, match='test_a'):
        main.validate_test_repair(old, changed)


def test_real_pytest_exception_assertions_are_preserved():
    real = 'def test_bad_input():\n    with pytest.raises(ValueError):\n        parse("bad")\n'
    assert assertion_coverage(real)['tests']['test_bad_input'] == 1
    with pytest.raises(ValueError, match='test_bad_input'):
        main.validate_test_repair(real, 'def test_bad_input():\n    pass\n')


def test_source_and_packaged_checker_receive_version_three(tmp_path):
    (tmp_path/'.agent').mkdir()
    (tmp_path/'.agent/run.json').write_text('{"desktop_contract":3}')
    workspace = tmp_path/'work';workspace.mkdir()
    import io
    def fake_command(args, *a, **kw):
        assert (workspace/'acceptance_gate.py').read_text().startswith('FORGE_DESKTOP_CONTRACT = 3\n')
        (tmp_path/'.agent/product-acceptance.json').write_text('{"status":"passed","math_profile":"basic-fractions"}')
    with patch.object(main, 'run_build_command', side_effect=fake_command):
        result=main.product_acceptance(tmp_path, Path(main.sys.executable), workspace, io.StringIO(), main.Event(), lambda *a:None)
    assert result['math_profile']=='basic-fractions'
    assert gate.project_contract(tmp_path)==3


def test_basic_focused_repair_does_not_restore_legacy_precision_rules():
    source='def parse_answer(text):\n    return None\n'
    failure={'diagnostics':{'path':'domain.py','symbol':'parse_answer','expected':'3/4','parsed':'None'}}
    prompt=repair_engine.focused_retry('',failure,{'domain.py':source},{'domain.py':symbols(source)},[],basic=True)
    assert '1e-9' not in prompt and '0.333333333' not in prompt
    assert '3/4' in prompt and '1/2' in prompt


def test_real_default_constructor_is_checked_before_profiled_gameplay(tmp_path):
    import sys
    report = tmp_path/'report.json'
    def create(root, data_dir=None):
        if data_dir is None:
            raise AttributeError("GameApp has no data_dir before base initialization")
        return SimpleNamespace()
    with patch.dict(sys.modules, {'main':SimpleNamespace(create_app=create)}), patch.object(gate,'check_app') as gameplay:
        with pytest.raises(RuntimeError, match='default desktop startup'):
            gate.run_source(tmp_path, report)
    gameplay.assert_not_called()
    evidence = json.loads(report.read_text())
    assert evidence['diagnostics']['category']=='default_constructor'
    assert evidence['diagnostics']['symbol']=='GameApp.__init__'


def test_default_constructor_diagnostic_never_becomes_a_math_repair():
    source = 'class GameApp:\n    def __init__(self, root): pass\n'
    failure = {'diagnostics': {'category':'default_constructor','path':'app.py','symbol':'GameApp.__init__'}}
    assert repair_engine.boundary_focus(failure, {'app.py':source}, {'app.py':symbols(source)}) is None
