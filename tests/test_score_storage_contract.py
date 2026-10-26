import json
import runpy
from pathlib import Path

import main
import repair_engine
from repair_protocol import symbols


def test_score_envelope_round_trip_is_fixed_without_model_calls(tmp_path):
    source = '''import json
from pathlib import Path
class Store:
    def __init__(self, data_dir):
        self.scores_path = Path(data_dir)/'scores.json'
    def _read_json(self, path):
        return json.loads(path.read_text()) if path.exists() else None
    def load_scores(self):
        scores = self._read_json(self.scores_path)
        if not isinstance(scores, list):
            scores = []
        return scores
    def save_score(self, record):
        scores = self.load_scores()
        if not any(item['id']==record['id'] for item in scores):
            scores.append(record)
        self.scores_path.write_text(json.dumps({'version':1,'scores':scores}))
'''
    (tmp_path/'storage.py').write_text(source)
    record = main.normalize_score_storage_api(tmp_path)
    assert record['api_requests']==0
    Store = runpy.run_path(str(tmp_path/'storage.py'))['Store']
    first = {'id':'one','correct':2,'total':3}
    second = {'id':'two','correct':3,'total':3}
    Store(tmp_path).save_score(first)
    assert Store(tmp_path).load_scores()==[first]
    Store(tmp_path).save_score(second)
    Store(tmp_path).save_score(second)
    assert Store(tmp_path).load_scores()==[first,second]
    (tmp_path/'scores.json').write_text(json.dumps([first]))
    assert Store(tmp_path).load_scores()==[first]
    assert main.normalize_score_storage_api(tmp_path) is None
    assert json.loads((tmp_path/'.agent/api-normalization/receipts.jsonl').read_text())['path']=='storage.py'


def test_storage_evidence_focuses_on_loader_instead_of_controller():
    source='class Store:\n    def load_scores(self):\n        return []\n'
    failure={'diagnostics':{'category':'score_persistence','path':'storage.py','symbol':'Store.load_scores',
                            'json_type':'dict','records_on_disk':1}}
    table={'storage.py':symbols(source)}
    focus=repair_engine.boundary_focus(failure,{'storage.py':source},table)
    assert focus['symbol']=='Store.load_scores'
    instruction=repair_engine.focused_retry('',failure,{'storage.py':source},table,[],basic=True)
    assert 'unwrap the scores list' in instruction and 'Do not rewrite the controller' in instruction


def test_attempt_count_method_alias_uses_actual_domain_field(tmp_path):
    (tmp_path/'.agent').mkdir()
    (tmp_path/'.agent/run.json').write_text('{"desktop_contract":3}')
    (tmp_path/'domain.py').write_text('class Session:\n    def __init__(self):\n        self.attempted = 0\n')
    (tmp_path/'app.py').write_text('from domain import Session\nclass GameApp(GameShell):\n    def result(self):\n        return self.session.total_attempts()\n')
    main.normalize_session_api(tmp_path)
    assert 'return self.session.attempted' in (tmp_path/'app.py').read_text()
