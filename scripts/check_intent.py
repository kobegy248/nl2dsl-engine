import os, json, yaml
os.environ['PYTHONIOENCODING'] = 'utf-8'

from tests.e2e.mock_data import create_mock_database
from nl2dsl.api_factory import create_app
from fastapi.testclient import TestClient

engine, *_ = create_mock_database('sqlite:///:memory:')
fixtures_dir = os.path.join('tests', 'e2e', 'fixtures')
with open(os.path.join(fixtures_dir, 'metrics_test.yaml'), 'r', encoding='utf-8') as f:
    metrics_data = yaml.safe_load(f)
registry_dict = {
    'metrics': metrics_data.get('metrics', {}),
    'dimensions': metrics_data.get('dimensions', {}),
    'data_sources': metrics_data.get('data_sources', {}),
}
with open(os.path.join(fixtures_dir, 'permissions_test.yaml'), 'r', encoding='utf-8') as f:
    perm_data = yaml.safe_load(f)

app = create_app(
    engine=engine,
    registry_dict=registry_dict,
    permissions=perm_data.get('users', {}),
    sensitive_columns=perm_data.get('sensitive_columns', {}),
    masking_rules=perm_data.get('masking_rules', {}),
)
client = TestClient(app)

for q in ['各品类销售额占比', '销售额趋势', '销售额排名前5', '先查华东再查华南']:
    resp = client.post('/api/v1/query', json={
        'question': q, 'user_id': 'u001', 'tenant_id': 't001',
    })
    data = resp.json()
    expl = data.get('explanation', '')
    intent = 'unknown'
    if '意图' in expl:
        parts = expl.split('意图')
        if len(parts) > 1:
            intent_part = parts[1].split('】')[0] if '】' in parts[1] else parts[1][:20]
            intent = intent_part.strip().strip("'\"")
    print(f'{q}')
    print(f'  status: {data.get("status")}')
    print(f'  data rows: {len(data.get("data", []))}')
    print(f'  intent: {intent}')
    print(f'  expl: {expl[:60]}...')
    print()
