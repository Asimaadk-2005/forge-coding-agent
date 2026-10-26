"""Offline protocol, resume, delivery and UI checks. No paid calls."""
import ast
import importlib.util
import io
import json
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
import requests

SPEC = importlib.util.spec_from_file_location("friend_agent", Path(__file__).resolve().parents[1] / "main.py")
agent = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(agent)


def response(events, done=True):
    result = Mock(ok=True, status_code=200, headers={"Content-Type": "text/event-stream"})
    result.__enter__ = Mock(return_value=result)
    result.__exit__ = Mock(return_value=False)
    lines = [": keepalive", ""]
    for event in events:
        lines += ["data: " + json.dumps(event), ""]
    if done:
        lines += ["data: [DONE]", ""]
    result.iter_lines.return_value = iter(lines)
    return result


def chunk(text="", finish=None, usage=None):
    result = {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}
    if usage is not None:
        result["usage"] = usage
    return result


def completed(text, finish="stop", cost=.002):
    return response([chunk(text, finish, {"prompt_tokens": 10, "completion_tokens": 20,
        "total_tokens": 30, "cost": cost})])


def catalog(price="0.000001"):
    return Mock(json=lambda: {"data": [{"id": "test/model", "pricing": {"prompt": price, "completion": price},
        "supported_parameters": ["reasoning", "response_format"], "reasoning": {"supported_efforts": ["none", "low", "high"]},
        "top_provider": {"max_completion_tokens": 100000}}]})


def manifest(extra=0):
    names = ["main.py", "requirements.txt", "README.md", "COMPONENT_APIS.md", "tests/test_game.py"]
    names += [f"game/module_{i}.py" for i in range(extra)]
    return {"files": [{"path": name, "purpose": name, "api": "", "depends_on": []} for name in names]}


def fake_model(payload):
    instruction = payload["messages"][1]["content"]
    if "AUDIT THE COMPLETE GENERATED PYTHON SOURCE" in instruction:
        return completed('{"issues": []}')
    if "Write ONLY" not in instruction:
        return completed(json.dumps(manifest(14)))
    path = instruction.split("Write ONLY the complete contents of ")[1].split(". No JSON")[0]
    if path.endswith(".py"):
        return completed("import tkinter\n" if path == "main.py" else "def test_domain():\n    assert 1 + 1 == 2\n")
    return completed("# " + path + "\n")


def job(tmp_path, **kwargs):
    kwargs.setdefault("contract_version", None)  # Legacy protocol fixtures; product gates tested separately.
    return agent.GenerationJob("secret-key", "test/model", "Task", "Docs", tmp_path, 8192,
        "Off", lambda *args: None, **kwargs)


def test_architecture_input_is_read_without_losing_uml(tmp_path):
    source = tmp_path / "Architecture_View.md"
    source.write_text("# View\n```plantuml\n@startuml\nA --> B\n@enduml\n```", encoding="utf-8")
    result = agent.read_selected_files([str(source)])
    assert "Architecture_View.md" in result
    assert "@startuml" in result and "A --> B" in result


def test_key_check_ignores_stale_tls_keylog_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SSLKEYLOGFILE", str(tmp_path / "missing" / "ssl.log"))
    def reply(*args, **kwargs):
        assert "SSLKEYLOGFILE" not in agent.os.environ
        assert kwargs["headers"]["Authorization"] == "Bearer secret-key"
        return Mock(ok=True)
    with patch.object(agent.requests, "get", side_effect=reply):
        agent.check_provider_key("OpenRouter", "secret-key")


def test_key_check_explains_missing_network_file_without_exposing_key():
    failure = requests.exceptions.ConnectionError(
        "Connection aborted.", FileNotFoundError(2, "No such file or directory"))
    with patch.object(agent.requests, "get", side_effect=failure):
        with pytest.raises(RuntimeError, match="Network setup refers to a missing file") as caught:
            agent.check_provider_key("DeepSeek", "secret-key")
    assert "secret-key" not in str(caught.value)


def test_missing_empty_and_invalid_utf8_architecture_files_are_rejected(tmp_path):
    missing = tmp_path / "missing.md"
    with pytest.raises(FileNotFoundError, match="missing"):
        agent.read_selected_files([str(missing)])
    empty = tmp_path / "empty.md"
    empty.write_text(" \n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        agent.read_selected_files([str(empty)])
    malformed = tmp_path / "malformed.md"
    malformed.write_bytes(b"\xff\xfe")
    with pytest.raises(ValueError, match="UTF-8"):
        agent.read_selected_files([str(malformed)])


@pytest.mark.parametrize("count", [0, 1, 8, 20, 100])
def test_no_arbitrary_manifest_file_count(count):
    result = agent.parse_manifest(json.dumps(manifest(count)))
    assert len(result["files"]) == 5 + count


def test_omitted_deliverables_are_added_without_another_request():
    result = agent.parse_manifest(json.dumps({"files": ["logic.py"]}))
    assert {"main.py", "README.md", "requirements.txt", "COMPONENT_APIS.md", "tests/test_game.py", "logic.py"} == {p["path"] for p in result["files"]}


@pytest.mark.parametrize("path", ["../x.py", "C:/x.py", ".agent/run.json", "Desktop/file.py", ".github/workflows/x.yml", "MAIN.PY"])
def test_unsafe_and_duplicate_plan_paths_are_rejected(path):
    plan = manifest()
    plan["files"].append({"path": path})
    with pytest.raises(ValueError):
        agent.parse_manifest(json.dumps(plan))


def test_dependencies_are_sorted_and_cycles_rejected():
    plan = manifest()
    plan["files"][0]["depends_on"] = ["GAME/LOGIC.PY"]
    plan["files"].append({"path": "game/logic.py"})
    parsed = agent.parse_manifest(json.dumps(plan))
    paths = [p["path"] for p in parsed["files"]]
    assert paths.index("game/logic.py") < paths.index("main.py")
    plan["files"][-1]["depends_on"] = ["main.py"]
    with pytest.raises(ValueError, match="cycle"):
        agent.parse_manifest(json.dumps(plan))


def test_identical_duplicate_plan_entries_merge_case_insensitively():
    plan = manifest()
    plan["files"] += [{"path": "game/__init__.py", "purpose": "Empty package marker", "api": "(empty)", "depends_on": []},
                      {"path": "GAME/__init__.py", "purpose": "Package", "api": "(empty)", "depends_on": []}]
    parsed = agent.parse_manifest(json.dumps(plan))
    assert sum(p["path"].casefold() == "game/__init__.py" for p in parsed["files"]) == 1
    assert parsed["plan_adjustments"] == ["Merged repeated plan entry: game/__init__.py"]
    assert agent.parse_manifest(json.dumps(parsed)) == parsed


def test_invalid_plan_is_corrected_automatically_before_any_files(tmp_path):
    invalid = manifest()
    invalid["files"][0]["depends_on"] = ["missing.py"]
    calls = []
    def respond(url, **kwargs):
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return completed(json.dumps(invalid))
        if len(calls) == 2:
            return completed(json.dumps(manifest()))
        return fake_model(kwargs["json"])
    run = job(tmp_path)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=respond):
        run.run()
    assert "missing.py" in calls[1]["messages"][1]["content"]
    assert len(run.state["completed"]) == 5
    assert run.state["requests"][1]["stage"] == "Correcting project plan"


def test_adding_missing_entrypoint_does_not_make_test_dependency_cycle():
    plan = {"files": [{"path": "logic.py"}, {"path": "test_game.py", "depends_on": ["main.py"]}]}
    parsed = agent.parse_manifest(json.dumps(plan))
    paths = [p["path"] for p in parsed["files"]]
    assert paths.index("logic.py") < paths.index("main.py") < paths.index("test_game.py")


def test_live_usage_is_estimated_then_replaced_not_doubled():
    usage = agent.TokenUsage([{"content": "test"}])
    updates = []
    answer = agent.read_completion_stream(response([chunk("hello"), chunk(" world", "stop"),
        {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 30, "total_tokens": 40,
         "completion_tokens_details": {"reasoning_tokens": 20}, "cost": .01}}]), usage, "secret",
        lambda force=False: updates.append(usage.snapshot()), lambda phase: None)
    assert answer == "hello world"
    assert updates[0]["output"].startswith("≈")
    assert usage.record()["output"] == 30
    assert usage.record()["cost"] == .01


def test_account_limit_rejection_records_zero_model_usage():
    rejected = Mock(ok=False, status_code=403,
        headers={"Content-Type": "application/json"},
        json=lambda: {"error": {"message": "Workspace lifetime budget exceeded"}})
    usage = agent.TokenUsage([{"content": "large prompt"}])
    with pytest.raises(RuntimeError, match="budget exceeded"):
        agent.read_completion_stream(rejected, usage, "secret", lambda force=False: None,
                                     lambda phase: None)
    assert usage.record()["cost"] == 0
    assert usage.record()["total"] == 0


@pytest.mark.parametrize("finish,done", [("length", True), ("content_filter", True), ("stop", False)])
def test_failed_or_incomplete_stream_never_applies_file(finish, done):
    usage = agent.TokenUsage([{"content": "test"}])
    with pytest.raises(RuntimeError):
        agent.read_completion_stream(response([chunk("partial", finish)], done), usage, "secret",
            lambda force=False: None, lambda phase: None)


@pytest.mark.parametrize("init_path", ["tests/__init__.py", "__init__.py"])
def test_empty_package_initializer_is_saved_without_retry(tmp_path, init_path):
    plan = manifest()
    plan["files"].append({"path": init_path, "purpose": "Package marker", "depends_on": []})
    def answer(url, **kwargs):
        instruction = kwargs["json"]["messages"][1]["content"]
        if "Write ONLY the complete contents of " + init_path in instruction:
            return completed("")
        if "Write ONLY" not in instruction:
            return completed(json.dumps(plan))
        return fake_model(kwargs["json"])
    run = job(tmp_path)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=answer) as post:
        project, count, _, _ = run.run()
    assert count == 6
    assert (project / init_path).read_text(encoding="utf-8") == ""
    assert post.call_count == 8


def test_stream_cancellation():
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(agent.Cancelled):
        list(agent.iter_sse_data(completed("hello"), cancel))


def test_large_plan_generates_file_by_file_and_preserves_usage(tmp_path):
    run = job(tmp_path)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=lambda url, **kw: fake_model(kw["json"])) as post:
        project, count, plan, _ = run.run()
    assert count == 19
    assert post.call_count == 21
    assert run.state["status"] == "source_ready"
    assert len(run.state["requests"]) == 21
    assert "PROJECT CONTEXT:\nDocs" in post.call_args_list[0].kwargs["json"]["messages"][1]["content"]
    assert all("PROJECT CONTEXT:\nDocs" not in call.kwargs["json"]["messages"][1]["content"]
               for call in post.call_args_list[1:])
    assert "secret-key" not in (project / ".agent/run.json").read_text()
    assert all(c.kwargs["json"]["reasoning"] == {"effort": "none"} for c in post.call_args_list)
    assert all("response_format" not in c.kwargs["json"] for c in post.call_args_list[1:-1])
    assert post.call_args_list[-1].kwargs["json"]["response_format"] == {"type": "json_object"}


def test_resume_does_not_repeat_completed_files_or_reset_cost(tmp_path):
    run = job(tmp_path)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=[completed(json.dumps(manifest())), completed("import tkinter"), completed("partial", "length")]):
        with pytest.raises(RuntimeError, match="token limit"):
            run.run()
    resumed = job(tmp_path, resume=run.project)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=lambda url, **kw: fake_model(kw["json"])) as post:
        resumed.run()
    assert post.call_count == 5
    assert len(resumed.state["requests"]) == 8
    assert sum(r["budget_charge"] for r in resumed.state["requests"]) == pytest.approx(.016)


def test_official_many_files_release_unused_output_reservations(tmp_path):
    run = job(tmp_path, provider="DeepSeek", rates={"prompt": 1.32e-6, "completion": 3.96e-6})
    run.limit = 32768
    def official_reply(url, **kwargs):
        reply = fake_model(kwargs["json"])
        # Official usage includes token counts, without an OpenRouter dollar cost.
        original = reply.iter_lines.return_value
        reply.iter_lines.return_value = iter(line.replace(', "cost": 0.002', '') for line in original)
        return reply
    with patch.object(agent.requests, "get", return_value=Mock(ok=True, json=lambda: {"data": [{"id": "test/model"}]})), patch.object(agent.requests, "post", side_effect=official_reply):
        _, count, _, _ = run.run()
    assert count == 19
    assert sum(r["budget_reserved"] for r in run.state["requests"]) > .95
    assert sum(r["budget_charge"] for r in run.state["requests"]) < .01
    assert all(r["charge_basis"] == "reported_tokens_at_configured_rates" for r in run.state["requests"])


def test_old_checkpoint_reservations_reconciled_on_resume(tmp_path):
    run = job(tmp_path)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=[completed(json.dumps(manifest())), completed("import tkinter"), completed("partial", "length")]):
        with pytest.raises(RuntimeError, match="token limit"):
            run.run()
    checkpoint = run.project / ".agent/run.json"
    state = json.loads(checkpoint.read_text())
    for record in state["requests"]:
        record["budget_charge"] = .30
        record["usage"]["cost_exact"] = False
        record.pop("charge_basis", None)
    checkpoint.write_text(json.dumps(state))
    resumed = job(tmp_path, resume=run.project)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=lambda url, **kw: fake_model(kw["json"])) as post:
        resumed.run()
    assert post.call_count == 5
    assert sum(r["budget_charge"] for r in resumed.state["requests"]) == pytest.approx(.016)


def test_unreported_interrupted_usage_keeps_reservation():
    record = {"budget_charge": .15, "usage": {"input_exact": True, "output_exact": False, "cost": .001}}
    assert agent.settle_request_charge(record) == .15
    record["usage"].update(output_exact=True, cost=float("nan"))
    assert agent.settle_request_charge(record) == .15


def test_source_inspection_finds_generated_ui_failures(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    (ui / "__init__.py").write_text("from .app import SpaceFractionsApp\n", encoding="utf-8")
    (ui / "intro_view.py").write_text(
        "import tkinter as tk\ndef draw(root):\n    return root.tk.call('after', 'info') % 1000\n",
        encoding="utf-8")
    (ui / "game_view.py").write_text(
        "import tkinter as tk\nfrom . import theme\ndef draw(root):\n"
        "    return tk.Frame(root, bg='red', **theme.panel_style())\n", encoding="utf-8")
    (ui / "theme.py").write_text("def panel_style():\n    return {'bg': 'blue'}\n", encoding="utf-8")
    plan = {"files": [{"path": p} for p in
        ("ui/__init__.py", "ui/intro_view.py", "ui/game_view.py", "ui/theme.py")]}
    findings = agent.inspect_generated_python(tmp_path, plan)
    assert len(findings) == 3
    assert {path for path, _ in findings} == {"ui/__init__.py", "ui/intro_view.py", "ui/game_view.py"}


def test_source_validation_repairs_empty_package_marker(tmp_path):
    ui = tmp_path / "ui"
    ui.mkdir()
    marker = ui / "__init__.py"
    marker.write_text("from .app import Missing\n", encoding="utf-8")
    run = job(tmp_path)
    run.project = tmp_path
    run.state = {"manifest": {"files": [{"path": "ui/__init__.py"}]},
                 "completed": {"ui/__init__.py": agent.hashlib.sha256(marker.read_bytes()).hexdigest()},
                 "requests": [], "inflight": None}
    run.info = {}
    run.rates = {"prompt": 0, "completion": 0}
    run.reasoning = None
    run.supported = []
    with patch.object(run, "request", side_effect=["", '{"issues": []}']) as request:
        run.validate_source(run.state["manifest"])
    assert marker.read_text(encoding="utf-8") == ""
    assert run.state["completed"]["ui/__init__.py"] == agent.hashlib.sha256(b"").hexdigest()
    assert request.call_count == 2


def test_runtime_review_repairs_named_file_and_updates_checkpoint(tmp_path):
    source = tmp_path / "main.py"
    source.write_text("def launch():\n    return None\n", encoding="utf-8")
    run = job(tmp_path)
    run.project = tmp_path
    run.state = {"manifest": {"files": [{"path": "main.py"}]},
                 "completed": {"main.py": agent.hashlib.sha256(source.read_bytes()).hexdigest()},
                 "requests": [], "inflight": None}
    with patch.object(run, "request", side_effect=[
            '{"issues": [{"path": "main.py", "failure": "launch never starts the Tk event loop"}]}',
            "def launch():\n    return 'started'\n"]) as request:
        run.validate_source(run.state["manifest"])
    assert source.read_text(encoding="utf-8") == "def launch():\n    return 'started'\n"
    assert run.state["source_reviewed"] is True
    assert run.state["completed"]["main.py"] == agent.hashlib.sha256(source.read_bytes()).hexdigest()
    assert request.call_count == 2


def test_budget_is_checked_before_paid_calls(tmp_path):
    run = job(tmp_path)
    with patch.object(agent.requests, "get", return_value=catalog("1")), patch.object(agent.requests, "post") as post:
        with pytest.raises(RuntimeError, match="budget|Budget"):
            run.run()
    post.assert_not_called()


def test_custom_run_budget_cannot_exceed_assignment_cap(tmp_path):
    with pytest.raises(ValueError, match="Run budget"):
        job(tmp_path, budget=1.0)
    run = job(tmp_path, budget=.0001)
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post") as post:
        with pytest.raises(RuntimeError, match="budget|Budget"):
            run.run()
    post.assert_not_called()


def test_truncated_python_is_repaired_once_under_same_budget(tmp_path):
    run = job(tmp_path)
    replies = [completed(json.dumps(manifest())), completed("def broken(:"), completed("import tkinter")]
    def answer(url, **kwargs):
        return replies.pop(0) if replies else fake_model(kwargs["json"])
    with patch.object(agent.requests, "get", return_value=catalog()), patch.object(agent.requests, "post", side_effect=answer):
        run.run()
    assert ast.parse((run.project / "main.py").read_text())
    assert any(r["stage"] == "Repair main.py" for r in run.state["requests"])


def test_validation_repair_changes_only_named_generated_file(tmp_path):
    run = job(tmp_path)
    run.project = tmp_path
    run.state = {"manifest": manifest(), "completed": {}, "requests": [], "inflight": None}
    source = tmp_path / "main.py"
    source.write_text("import tkinter\n", encoding="utf-8")
    run.state["completed"]["main.py"] = agent.hashlib.sha256(source.read_bytes()).hexdigest()
    with patch.object(run, "request", return_value="import tkinter\nVALUE = 1\n") as request:
        assert run.repair_failed_build(RuntimeError('File "C:\\project\\main.py", line 2'))
    assert source.read_text(encoding="utf-8") == "import tkinter\nVALUE = 1\n"
    assert request.call_count == 1
    assert not run.repair_failed_build(RuntimeError("PyInstaller executable missing"))


def test_build_repair_loop_stops_after_eight_attempts(tmp_path):
    run = Mock()
    run.repair_failed_build.return_value = True
    with patch.object(agent, "build_desktop", side_effect=RuntimeError("test failure")) as build:
        with pytest.raises(RuntimeError, match="test failure"):
            agent.build_with_repairs(run, tmp_path, None, lambda *args: None, threading.Event())
    assert build.call_count == 9
    assert run.repair_failed_build.call_count == 8


def test_test_corrections_preserve_cases_assertions_and_no_new_skips():
    before = "def test_value():\n    assert value == 1\n"
    agent.validate_test_repair(before, "def test_value():\n    assert value == 2\n")
    for after in ("def test_value():\n    pass\n", "def test_other():\n    assert value == 1\n",
                  "@pytest.mark.skip\ndef test_value():\n    assert value == 1\n"):
        with pytest.raises(ValueError, match="original preserved"):
            agent.validate_test_repair(before, after)


def test_unchanged_failures_feed_back_into_next_diagnosis(tmp_path):
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent/build.log").write_text("FAILED tests/test_math.py::test_decimal\n")
    run = SimpleNamespace(_last_repair_target="game/parser.py", repair_failed_build=Mock(return_value=True))
    with patch.object(agent, "build_desktop", side_effect=[RuntimeError("failed"), RuntimeError("failed"), tmp_path / "game.exe"]):
        assert agent.build_with_repairs(run, tmp_path, None, lambda *args: None, threading.Event()) == tmp_path / "game.exe"
    assert "did not resolve any failed tests" in run._repair_feedback
    assert "game/parser.py" in run._repair_feedback


def test_assertion_failure_diagnoses_implementation_and_preserves_tests(tmp_path):
    run = job(tmp_path)
    run.project = tmp_path
    (tmp_path / "game").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / ".agent").mkdir()
    source = tmp_path / "game/question_generator.py"
    source.write_text("def parse_fraction(text):\n    return None\n")
    test = tmp_path / "tests/test_question_generator.py"
    test.write_text("from game.question_generator import parse_fraction\ndef test_mixed():\n    assert parse_fraction('1 1/2') == 1.5\n")
    plan = {"files": [{"path": "game/question_generator.py", "api": "parse_fraction", "depends_on": []},
                      {"path": "tests/test_question_generator.py", "depends_on": ["game/question_generator.py"]}]}
    run.state = {"manifest": plan, "completed": {p: agent.hashlib.sha256((tmp_path / p).read_bytes()).hexdigest()
                 for p in ("game/question_generator.py", "tests/test_question_generator.py")}, "requests": []}
    full_log = "FIRST FAILURE: correct_answer must check true\n" + "detail\n" * 500 + "tests\\test_question_generator.py:4: AssertionError"
    (tmp_path / ".agent/build.log").write_text(full_log)
    original_test = test.read_bytes()
    with patch.object(run, "request", side_effect=['{"path":"game/question_generator.py","reason":"mixed parsing order"}',
                 "def parse_fraction(text):\n    from fractions import Fraction\n    whole, part = text.split()\n    return int(whole) + Fraction(part)\n"]) as request:
        assert run.repair_failed_build(RuntimeError("Tests or Windows build failed. See .agent/build.log.\ntests/test_question_generator.py:4: AssertionError"))
    assert request.call_count == 2
    assert "FIRST FAILURE" in request.call_args_list[0].args[1]
    assert "FIRST FAILURE" in request.call_args_list[1].args[1]
    assert "assert parse_fraction" in request.call_args_list[1].args[1]
    assert test.read_bytes() == original_test
    assert agent.hashlib.sha256(source.read_bytes()).hexdigest() == run.state["completed"]["game/question_generator.py"]
    assert len(list((tmp_path / ".agent/repairs").glob("*/before.py"))) == 1
    with patch.object(run, "request", return_value='{"path":"tests/test_question_generator.py"}'):
        assert not run.repair_failed_build(RuntimeError("tests/test_question_generator.py:4: AssertionError"))


def fixture_project(tmp_path):
    (tmp_path / "main.py").write_text("import tkinter as tk\nif __name__ == '__main__':\n    tk.Tk().mainloop()\n")
    (tmp_path / "requirements.txt").write_text("# standard library only\n")
    (tmp_path / "README.md").write_text("# Game")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_game.py").write_text("def test_score():\n    assert 2 + 3 == 5\n")
    return tmp_path


def test_cloud_export_is_deterministic_excludes_secrets_and_does_not_upload(tmp_path):
    project = fixture_project(tmp_path)
    (project / ".agent").mkdir()
    (project / ".gitignore").write_text(".agent/\n")
    (project / ".agent/run.json").write_text('{"private": "task details"}')
    with patch.object(agent.requests, "post") as network:
        agent.export_cloud_build(project)
        agent.export_cloud_build(project)
    network.assert_not_called()
    script = (project / ".agent/build_windows.py").read_text()
    ast.parse(script)
    assert "private" not in script
    ignores = (project / ".gitignore").read_text().splitlines()
    assert ".agent/" not in ignores
    assert "!.agent/build_windows.py" in ignores
    workflow = (project / ".github/workflows/build-windows.yml").read_text()
    assert "windows-latest" in workflow and "SpaceFractions.exe" in workflow
    assert "workflow_dispatch" in workflow


def test_frozen_cloud_export_does_not_require_original_python_source(tmp_path):
    project = tmp_path / "game"
    project.mkdir()
    fixture_project(project)
    resource = tmp_path / "cloud_builder.txt"
    resource.write_text(agent.cloud_builder_source(), encoding="utf-8")
    with patch.object(agent.sys, "frozen", True, create=True), patch.object(agent.sys, "_MEIPASS", str(tmp_path), create=True), patch.object(agent.inspect, "getsource", side_effect=AssertionError("Source unavailable")):
        agent.export_cloud_build(project)
    assert (project / ".agent/build_windows.py").exists()


def test_cloud_export_preserves_existing_user_workflow(tmp_path):
    project = fixture_project(tmp_path)
    path = project / ".github/workflows/build-windows.yml"
    path.parent.mkdir(parents=True)
    path.write_text("user workflow")
    with pytest.raises(ValueError, match="preserved"):
        agent.export_cloud_build(project)
    assert path.read_text() == "user workflow"
    assert not (project / ".agent/build_windows.py").exists()


def test_deepseek_official_endpoint_and_thinking_off(tmp_path):
    run = job(tmp_path, provider="DeepSeek", rates={"prompt": 1e-6, "completion": 2e-6})
    run.current = agent.TokenUsage([{"content": "prompt"}])
    run.show_usage = lambda force=False: None
    with patch.object(agent.requests, "post", return_value=completed("file")) as post:
        agent.provider_completion(run, {"provider": {}, "reasoning": {}, "model": "deepseek-v4-pro"}, "File")
    assert post.call_args.args[0] == "https://api.deepseek.com/chat/completions"
    payload = post.call_args.kwargs["json"]
    assert "provider" not in payload and "reasoning" not in payload
    assert payload["thinking"] == {"type": "disabled"}


def test_desktop_validation_rejects_web_source_and_install_commands(tmp_path):
    project = fixture_project(tmp_path)
    (project / "requirements.txt").write_text("--index-url https://bad.example\n")
    with pytest.raises(ValueError, match="dependency"):
        agent.validate_desktop(project)
    (project / "requirements.txt").write_text("")
    (project / "main.py").write_text("import http.server\n")
    with pytest.raises(ValueError, match="native"):
        agent.validate_desktop(project)


def test_build_reports_missing_development_python(tmp_path):
    project = fixture_project(tmp_path)
    with pytest.raises(RuntimeError, match="portable builder is missing"):
        agent.build_desktop(project, python=tmp_path / "missing-python.exe")


def test_portable_builder_is_resolved_beside_relocated_forge(tmp_path):
    runtime = tmp_path / "moved folder" / "runtime"
    runtime.mkdir(parents=True)
    (runtime / "python.exe").write_bytes(b"fixture")
    with patch.object(agent.sys, "frozen", True, create=True), patch.object(agent.sys, "executable", str(runtime.parent / "Forge.exe")):
        assert Path(agent.default_builder_python()) == runtime / "python.exe"
    (runtime / "python.exe").unlink()
    with patch.object(agent.sys, "frozen", True, create=True), patch.object(agent.sys, "executable", str(runtime.parent / "Forge.exe")):
        assert agent.default_builder_python() == ""


def test_build_process_timeout_is_bounded(tmp_path):
    with pytest.raises(RuntimeError, match="timed out"):
        agent.run_build_command([agent.sys.executable, "-c", "import time;time.sleep(5)"],
                                tmp_path, io.StringIO(), threading.Event(), timeout=.1)


def test_minimal_ui_fits_and_exposes_provider_controls():
    import tkinter as tk
    root = tk.Tk()
    try:
        with patch.object(agent, "load_key", return_value=""):
            app = agent.CodeAgent(root)
        root.update()
        assert app.play_button.winfo_rooty() + app.play_button.winfo_height() < root.winfo_rooty() + root.winfo_height()
        assert app.output_box.winfo_rooty() + app.output_box.winfo_height() < app.generate_button.winfo_rooty()
        assert app.output_box.master.master is app.task_box.master is app.file_list.master
        assert not app.play_button.enabled
        assert app.provider_box.cget("values") == ("DeepSeek", "OpenRouter")
        assert app.provider.get() == "DeepSeek"
        assert app.build_mode.get() == "Local"
        assert not app.cloud_button.winfo_ismapped()
        assert app.input_price.get() == "1.32"
        assert app.output_price.get() == "3.96"
        app.api_key.set("secret")
        with patch.object(agent, "load_key", return_value=""):
            app.provider.set("DeepSeek")
        assert not app.api_key.get()
        assert app.model.get() == "deepseek-v4-pro"
    finally:
        app.close() if "app" in locals() else root.destroy()


def test_provider_switch_loads_each_saved_key_without_printing_it():
    import tkinter as tk
    root = tk.Tk()
    try:
        with patch.object(agent, "load_key", side_effect=lambda name: {"OpenRouter": "router-test", "DeepSeek": "official-test"}[name]):
            app = agent.CodeAgent(root)
            assert app.api_key.get() == "official-test"
            assert app.remember_key.get()
            app.provider.set("OpenRouter")
            assert app.api_key.get() == "router-test"
            assert app.remember_key.get()
    finally:
        app.close() if "app" in locals() else root.destroy()
