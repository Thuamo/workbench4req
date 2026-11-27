"""Add the QA member role."""
from alembic import op
import sqlalchemy as sa

revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

OLD_ROLES = "role IN ('requirement_member','qa_member','reviewer','super_admin','development_member')"
NEW_ROLES = OLD_ROLES


def replace_role_constraint(condition):
    db = op.get_bind()
    constraints = sa.inspect(db).get_check_constraints('users')
    role = next(c for c in constraints if 'role' in c['sqltext'].lower())
    old_name = role['name'] or 'ck_users_role'
    with op.batch_alter_table('users', naming_convention={'ck': 'ck_%(table_name)s_role'}) as batch:
        batch.drop_constraint(old_name, type_='check')
        batch.create_check_constraint('ck_users_role', condition)


def upgrade():
    replace_role_constraint("role IN ('requirement_member','qa_member','reviewer','super_admin','development_member')")


def downgrade():
    db = op.get_bind()
    if db.execute(sa.text("SELECT 1 FROM users WHERE role='qa_member' LIMIT 1")).first():
        raise RuntimeError('Reassign QA accounts before removing the role')
    replace_role_constraint("role IN ('requirement_member','reviewer','super_admin','development_member')")
