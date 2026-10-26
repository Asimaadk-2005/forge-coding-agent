import hashlib
import json
import runpy
import tkinter as tk
from pathlib import Path

import pytest
import game_blueprint
import main
from unittest.mock import patch
from foundation.forge_ui import GameShell
from tests.test_agent import fixture_project


def test_canonical_plan_has_stable_contracts_and_complete_dependencies():
    plan = game_blueprint.normalize_plan({"files": [], "requirements": ["Play", "Admin"]})
    parsed = main.parse_manifest(json.dumps(plan))
    ordered = [item["path"] for item in parsed["files"]]
    assert ordered.index("domain.py") < ordered.index("content.py") < ordered.index("storage.py") < ordered.index("app.py")
    assert ordered.index("forge_ui.py") < ordered.index("app.py")
    assert parsed["requirements"] == ["Play", "Admin"]
    assert "GameApp(GameShell)" in next(f["api"] for f in parsed["files"] if f["path"] == "app.py")


def test_protected_foundation_changes_block_build(tmp_path):
    (tmp_path / ".agent").mkdir()
    target = tmp_path / "forge_ui.py"
    target.write_bytes(b"original")
    expected = {"forge_ui.py": hashlib.sha256(target.read_bytes()).hexdigest()}
    (tmp_path / ".agent/run.json").write_text(json.dumps({"desktop_contract": 1, "protected_files": expected}))
    assert main.protected_foundation(tmp_path) == expected
    target.write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="foundation was changed"):
        main.protected_foundation(tmp_path, expected)


@pytest.mark.parametrize("selection", ["forge_ui.py", "acceptance_gate.py", "tests/test_domain.py"])
def test_protected_acceptance_cannot_be_repaired_away(tmp_path, selection):
    run = main.GenerationJob("dummy", "dummy", "Task", "Docs", tmp_path, 4096, "Off", lambda *a: None)
    run.project = tmp_path
    (tmp_path / "domain.py").write_text("VALUE = 1\n")
    run.state = {"manifest": {"files": [{"path": "domain.py", "depends_on": []},
                  {"path": "forge_ui.py", "depends_on": []}, {"path": "tests/test_domain.py", "depends_on": []}]},
                  "protected_files": {"forge_ui.py": "hash"}, "completed": {"domain.py": "hash"}}
    with patch.object(run, "request", return_value=json.dumps({"path": selection, "test_contract_error": "fake", "contract_evidence": "fake"})):
        assert not run.repair_failed_build(RuntimeError("ACCEPTANCE: incorrect score"))


def test_scene_lifecycle_removes_overlays_and_obsolete_callbacks(tmp_path):
    root = tk.Tk()
    try:
        app = GameShell(root, tmp_path)
        app.page("admin", "Question bank")
        old = app.listing("questions")
        invoked = []
        app.later(0, lambda: invoked.append(True))
        app.page("menu", "Space Fractions")
        root.update()
        assert not old.winfo_exists()
        assert not invoked
        assert "questions" not in app.widgets
        assert len(app.canvas.find_all()) > 50
        app.page("play", "Flight")
        entry = app.entry("answer")
        calls = []
        button = app.button("check", "Check", lambda: calls.append(entry.get()))
        entry.insert(0, "3/4")
        button.invoke()
        assert calls == ["3/4"]
        app.page("menu", "Menu")
        assert not entry.winfo_exists()
        assert not button.winfo_exists()
    finally:
        app.close() if "app" in locals() else root.destroy()


def test_product_failure_stops_before_generated_tests_or_packaging(tmp_path):
    fixture_project(tmp_path)
    with patch.object(main, "protected_foundation", return_value={"forge_ui.py": "hash"}), \
         patch.object(main, "product_acceptance", side_effect=RuntimeError("ACCEPTANCE: invisible question")), \
         patch.object(main, "run_build_command") as command:
        with pytest.raises(RuntimeError, match="invisible question"):
            main.build_desktop(tmp_path, python=Path(main.sys.executable))
    command.assert_not_called()
    report = json.loads((tmp_path / ".agent/desktop-build.json").read_text())
    assert report["status"] == "failed"
    assert not report["tests_passed"]
    assert not (tmp_path / "Desktop/SpaceFractions.exe").exists()


def test_cloud_keeps_independent_checks_without_private_checkpoint(tmp_path):
    fixture_project(tmp_path)
    (tmp_path / ".agent").mkdir()
    (tmp_path / "forge_ui.py").write_bytes(b"reviewed")
    hashes = {"forge_ui.py": hashlib.sha256(b"reviewed").hexdigest()}
    checkpoint = tmp_path / ".agent/run.json"
    checkpoint.write_text(json.dumps({"desktop_contract": 1, "protected_files": hashes,
                                      "task": "private prompt", "requests": ["private usage"]}))
    main.export_cloud_build(tmp_path)
    checkpoint.unlink()
    assert main.protected_foundation(tmp_path) == hashes
    exported = (tmp_path / ".agent/product-contract.json").read_text()
    assert "private" not in exported
    assert (tmp_path / ".agent/acceptance_gate.py").read_text(encoding="utf-8") == main.asset_text("acceptance_gate.py")
    assert "!.agent/product-contract.json" in (tmp_path / ".gitignore").read_text()


def test_invalid_repair_formats_retry_without_applying_bad_source(tmp_path):
    run = main.GenerationJob("dummy", "dummy", "Task", "Docs", tmp_path, 4096, "Off", lambda *a: None)
    run.contract_version = None
    run.project = tmp_path
    source = tmp_path / "domain.py"
    source.write_text("VALUE = 1\n")
    run.state = {"manifest": {"files": [{"path": "domain.py", "depends_on": []}]},
                 "completed": {"domain.py": "original"}, "requests": []}
    replies = ['{"path":"domain.py", "reason":', '{"path":"domain.py","reason":"observable defect"}',
               "Here’s the corrected file", "VALUE = 2\n"]
    with patch.object(run, "request", side_effect=replies) as request:
        assert run.repair_failed_build(RuntimeError("ACCEPTANCE: wrong arithmetic"))
    assert request.call_count == 4
    assert source.read_text() == "VALUE = 2\n"
    assert len(list((tmp_path / ".agent/rejected-repairs").glob("*.txt"))) == 1


def test_python_formatting_is_normalized_without_an_extra_paid_request():
    assert main.python_response("Here is the file.\n\n```python\nVALUE = 2\n```\n") == "VALUE = 2\n"
    valid = 'DOC = """\n```python\nexample\n```\n"""\n'
    assert main.python_response(valid) == valid
    ambiguous = "```python\nA = 1\n```\n```python\nB = 2\n```"
    with pytest.raises(SyntaxError):
        main.ast.parse(main.python_response(ambiguous))


def test_exact_edits_preserve_unrelated_source_and_reject_ambiguous_matches():
    original = "VALUE = 1\nOTHER = 99\n"
    assert main.apply_source_edits(original, {"edits": [{"old": "VALUE = 1", "new": "VALUE = 2"}]}) == "VALUE = 2\nOTHER = 99\n"
    for record in ({"edits": []}, {"edits": [{"old": "missing", "new": "bad"}]},
                   {"edits": [{"old": "VALUE = 1", "new": "def broken(:"}]}):
        with pytest.raises((ValueError, SyntaxError)):
            main.apply_source_edits(original, record)


def test_frozen_runtime_hook_does_not_enter_source_cli():
    with patch.object(main.sys, "frozen", True, create=True), \
         patch.dict(main.os.environ, {}, clear=True):
        # PyInstaller executes runtime hooks with __name__ == '__main__'.
        namespace = runpy.run_path(str(Path(main.__file__).parent / "acceptance_gate.py"), run_name="__main__")
    assert callable(namespace["frozen_hook"])
