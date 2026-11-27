"""Snapshot the configured SQLite DB before installing bundled skill revisions."""
import json,sqlite3
from datetime import datetime
from pathlib import Path
from sqlalchemy.engine import make_url
from app.config import settings

root=Path(__file__).resolve().parents[1]
url=make_url(settings.database_url)
if url.drivername.startswith('sqlite'):
    source=Path(url.database).resolve()
    if not source.is_relative_to(root):raise RuntimeError('Configured database is outside this workspace')
    destination=root/'data'/'backups'/('before-business-refinement-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.db')
    destination.parent.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as original,sqlite3.connect(destination) as backup:
        original.backup(backup)
        if backup.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise RuntimeError('Backup integrity check failed')
    print(json.dumps({'backup':str(destination),'integrity':'ok'}))
