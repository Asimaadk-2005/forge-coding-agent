"""Trusted pytest reporting used outside the generated source manifest."""
import json
import sys
from pathlib import Path


def run(project, destination):
    import pytest
    project = Path(project).resolve()
    sys.path.insert(0, str(project))
    failures = []
    passed = []
    class Reporter:
        def pytest_runtest_logreport(self, report):
            if report.failed:
                crash = getattr(report.longrepr, "reprcrash", None)
                failures.append({"nodeid": report.nodeid, "when": report.when,
                    "message": getattr(crash, "message", str(report.longrepr)[-800:]),
                    "traceback": str(report.longrepr),
                    "path": str(getattr(crash, "path", "")), "line": getattr(crash, "lineno", None)})
            elif report.when == "call" and report.passed:
                passed.append(report.nodeid)
    code = pytest.main(["-q", "--tb=short", "--capture=sys", "-p", "no:cacheprovider", str(project / "tests")], plugins=[Reporter()])
    Path(destination).write_text(json.dumps({"exit_code": int(code), "passed": len(passed), "failures": failures}, indent=2), encoding="utf-8")
    return code


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1], sys.argv[2]))
