"""Allow the development member role."""
from alembic import op
import sqlalchemy as sa

revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

OLD_ROLES = "role IN ('requirement_member','reviewer','super_admin')"
NEW_ROLES = "role IN ('requirement_member','reviewer','super_admin','development_member')"


def replace_role_constraint(condition):
    db = op.get_bind()
    constraints = sa.inspect(db).get_check_constraints('users')
    role = next(c for c in constraints if 'role' in c['sqltext'].lower())
    old_name = role['name'] or 'ck_users_role'
    with op.batch_alter_table('users', naming_convention={'ck': 'ck_%(table_name)s_role'}) as batch:
        batch.drop_constraint(old_name, type_='check')
        batch.create_check_constraint('ck_users_role', condition)


def upgrade():
    replace_role_constraint(NEW_ROLES)


def downgrade():
    db = op.get_bind()
    if db.execute(sa.text("SELECT 1 FROM users WHERE role='development_member' LIMIT 1")).first():
        raise RuntimeError('Reassign development member accounts before removing the role')
    replace_role_constraint(OLD_ROLES)
