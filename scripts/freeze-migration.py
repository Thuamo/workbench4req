from pathlib import Path
from sqlalchemy import create_engine
from alembic.migration import MigrationContext
from alembic.autogenerate import produce_migrations, render_python_code
from app.db import Base
from app import models

with create_engine('sqlite:///:memory:').connect() as connection:
    context=MigrationContext.configure(connection)
    migration=produce_migrations(context,Base.metadata)
    upgrade=render_python_code(migration.upgrade_ops)
    downgrade=render_python_code(migration.downgrade_ops)
content='''"""Initial schema frozen from the validated baseline."""
from alembic import op
import sqlalchemy as sa
import pgvector.sqlalchemy
revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('CREATE EXTENSION IF NOT EXISTS vector')
'''+upgrade+'''\n
def downgrade():
'''+downgrade+'\n'
Path('backend/migrations/versions/0001_initial.py').write_text(content,encoding='utf-8')
print('Frozen explicit migration created:',len(content),'characters')
