"""Enforce submitted content, review decisions, snapshots and version-pointer consistency."""
from alembic import op
revision='0002'
down_revision='0001'
branch_labels=None
depends_on=None


def upgrade():
    dialect=op.get_bind().dialect.name
    if dialect=='sqlite':
        op.execute("""CREATE TRIGGER locked_version_content BEFORE UPDATE ON document_versions
        WHEN OLD.status != 'draft' AND (NEW.content IS NOT OLD.content OR NEW.file_hash IS NOT OLD.file_hash OR NEW.blocks IS NOT OLD.blocks OR NEW.content_hash IS NOT OLD.content_hash OR NEW.label IS NOT OLD.label)
        BEGIN SELECT RAISE(ABORT, 'submitted version is immutable'); END""")
        op.execute("""CREATE TRIGGER locked_review_decision BEFORE UPDATE ON review_tasks
        WHEN NEW.reviewer_id IS NOT OLD.reviewer_id OR NEW.request_id IS NOT OLD.request_id OR
        (OLD.decision != 'pending' AND (NEW.decision IS NOT OLD.decision OR NEW.comment IS NOT OLD.comment OR NEW.decided_at IS NOT OLD.decided_at))
        BEGIN SELECT RAISE(ABORT, 'review decision is immutable'); END""")
        op.execute("""CREATE TRIGGER locked_snapshot BEFORE UPDATE ON knowledge_base_snapshots
        WHEN NEW.manifest IS NOT OLD.manifest OR NEW.base_id IS NOT OLD.base_id
        BEGIN SELECT RAISE(ABORT, 'snapshot is immutable'); END""")
        op.execute("""CREATE TRIGGER locked_knowledge_revision BEFORE UPDATE ON knowledge_item_versions
        BEGIN SELECT RAISE(ABORT, 'knowledge revision is immutable'); END""")
        op.execute("""CREATE TRIGGER valid_document_pointers BEFORE UPDATE OF current_version_id,current_index_id ON knowledge_documents
        WHEN (NEW.current_version_id IS NULL AND NEW.current_index_id IS NOT NULL) OR
        (NEW.current_version_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM document_versions v WHERE v.id=NEW.current_version_id AND v.document_id=NEW.id AND v.review_status='approved') OR NOT EXISTS(SELECT 1 FROM index_builds b WHERE b.id=NEW.current_index_id AND b.version_id=NEW.current_version_id AND b.status='ready')))
        BEGIN SELECT RAISE(ABORT, 'version/index pointers inconsistent'); END""")
    elif dialect=='postgresql':
        op.execute("""CREATE FUNCTION protect_workbench_records() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_TABLE_NAME='document_versions' THEN
            IF OLD.status != 'draft' AND (NEW.content,NEW.file_hash,NEW.blocks::text,NEW.content_hash,NEW.label) IS DISTINCT FROM (OLD.content,OLD.file_hash,OLD.blocks::text,OLD.content_hash,OLD.label) THEN RAISE EXCEPTION 'submitted version is immutable'; END IF;
          ELSIF TG_TABLE_NAME='review_tasks' THEN
            IF (NEW.reviewer_id,NEW.request_id) IS DISTINCT FROM (OLD.reviewer_id,OLD.request_id) OR (OLD.decision!='pending' AND (NEW.decision,NEW.comment,NEW.decided_at) IS DISTINCT FROM (OLD.decision,OLD.comment,OLD.decided_at)) THEN RAISE EXCEPTION 'review decision is immutable'; END IF;
          ELSIF TG_TABLE_NAME='knowledge_base_snapshots' THEN
            IF (NEW.manifest::text,NEW.base_id) IS DISTINCT FROM (OLD.manifest::text,OLD.base_id) THEN RAISE EXCEPTION 'snapshot is immutable'; END IF;
          ELSIF TG_TABLE_NAME='knowledge_item_versions' THEN
            RAISE EXCEPTION 'knowledge revision is immutable';
          ELSIF TG_TABLE_NAME='knowledge_documents' THEN
            IF (NEW.current_version_id IS NULL AND NEW.current_index_id IS NOT NULL) OR (NEW.current_version_id IS NOT NULL AND (NOT EXISTS(SELECT 1 FROM document_versions v WHERE v.id=NEW.current_version_id AND v.document_id=NEW.id AND v.review_status='approved') OR NOT EXISTS(SELECT 1 FROM index_builds b WHERE b.id=NEW.current_index_id AND b.version_id=NEW.current_version_id AND b.status='ready'))) THEN RAISE EXCEPTION 'version/index pointers inconsistent'; END IF;
          END IF;
          RETURN NEW;
        END $$""")
        for table in ['document_versions','review_tasks','knowledge_base_snapshots','knowledge_item_versions','knowledge_documents']:
            op.execute(f'CREATE TRIGGER protect_{table} BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION protect_workbench_records()')


def downgrade():
    if op.get_bind().dialect.name=='sqlite':
        for name in ['locked_version_content','locked_review_decision','locked_snapshot','locked_knowledge_revision','valid_document_pointers']:
            op.execute(f'DROP TRIGGER IF EXISTS {name}')
    elif op.get_bind().dialect.name=='postgresql':
        for table in ['document_versions','review_tasks','knowledge_base_snapshots','knowledge_item_versions','knowledge_documents']:
            op.execute(f'DROP TRIGGER IF EXISTS protect_{table} ON {table}')
        op.execute('DROP FUNCTION protect_workbench_records()')
