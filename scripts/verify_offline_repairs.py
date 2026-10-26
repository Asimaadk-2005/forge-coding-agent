"""Run Forge regressions with network connections and saved-key reads forbidden."""
import json
import socket
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
import pytest
import main
import keyvault


def run():
    attempts = {'network': 0, 'saved_key': 0}
    def network_forbidden(*args, **kwargs):
        attempts['network'] += 1
        raise AssertionError('Offline verification forbids network access')
    def keys_forbidden(*args, **kwargs):
        attempts['saved_key'] += 1
        raise AssertionError('Offline verification forbids saved-key access')
    class Evidence:
        passed = 0
        def pytest_runtest_logreport(self, report):
            if report.when == 'call' and report.passed:
                self.passed += 1
    evidence = Evidence()
    with patch.object(requests.Session, 'request', network_forbidden), \
         patch.object(socket.socket, 'connect', network_forbidden), \
         patch.object(socket, 'create_connection', network_forbidden), \
         patch.object(main, 'load_key', keys_forbidden), \
         patch.object(keyvault, 'load_key', keys_forbidden):
        code = pytest.main([str(ROOT / 'tests'), '-q', '--capture=sys'], plugins=[evidence])
    result = {'exit_code': int(code), 'passed': evidence.passed, 'forbidden_attempts': attempts,
              'paid_api_calls': 0, 'new_generation': False,
              'scope': 'Offline recorded-response and mocked-adapter regression tests; not a live model generation'}
    destination = ROOT / 'prototype-tests/offline-repair-v3/agent-tests.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))
    return int(code) or int(any(attempts.values()))


if __name__ == '__main__':
    raise SystemExit(run())
