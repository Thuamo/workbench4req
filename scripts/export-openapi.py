import json
from pathlib import Path
from app.main import app
output = Path('docs/openapi.json')
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps(app.openapi(),ensure_ascii=False,indent=2),encoding='utf-8')
print('OpenAPI schema exported without user data')
