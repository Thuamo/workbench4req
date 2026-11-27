from pathlib import Path
import subprocess, sys, os
import sqlite3


def test_explicit_migration_and_database_immutability(tmp_path):
    path=tmp_path/'migrations.db'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+path.as_posix(),'STORAGE_DIR':str(tmp_path/'files')}
    result=subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','upgrade','head'],capture_output=True,env=env)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    with sqlite3.connect(path) as conn:
        assert conn.execute('SELECT version_num FROM alembic_version').fetchone()[0]=='0009'
        assert len(conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'").fetchall())==5
        conn.execute("INSERT INTO users(id,created_at,username,display_name,password_hash,role,enabled) VALUES('u',CURRENT_TIMESTAMP,'migration-user','test','not-loginable','super_admin',1)")
        conn.execute("INSERT INTO users(id,created_at,username,display_name,password_hash,role,enabled) VALUES('dev',CURRENT_TIMESTAMP,'migration-dev','test','not-loginable','development_member',1)")
        conn.execute("INSERT INTO knowledge_bases(id,created_at,name,description,public,member_ids,enabled) VALUES('b',CURRENT_TIMESTAMP,'test','',1,'[]',1)")
        conn.execute("INSERT INTO knowledge_documents(id,created_at,title,owner_id,base_id,kind) VALUES('d',CURRENT_TIMESTAMP,'test','u','b','reference')")
        conn.execute("INSERT INTO document_versions(id,created_at,document_id,creator_id,label,filename,file_hash,content,blocks,warnings,status,parse_status,review_status,publish_status,index_status,revision,change_note,provenance) VALUES('v',CURRENT_TIMESTAMP,'d','u','V1','test.md','hash','locked','[]','[]','approved','ready','approved','queued','not_built',1,'','{}')")
        try:
            conn.execute("UPDATE document_versions SET content='changed' WHERE id='v'")
            raise AssertionError('immutable submitted version was modified')
        except sqlite3.IntegrityError:
            pass
        try:
            conn.execute("UPDATE knowledge_documents SET current_version_id='v',current_index_id='missing' WHERE id='d'")
            raise AssertionError('invalid pointers were accepted')
        except sqlite3.IntegrityError:
            pass
    blocked=subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','downgrade','0008'],capture_output=True,env=env)
    assert blocked.returncode!=0 and b'Reassign development member accounts' in blocked.stderr
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE users SET role='requirement_member' WHERE id='dev'")
    rollback=subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','downgrade','base'],capture_output=True,env=env)
    assert rollback.returncode==0,rollback.stderr.decode(errors='replace')


def test_requirement_context_backfill_preserves_rows_and_owner_boundary(tmp_path):
    import json
    path=tmp_path/'legacy.db'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+path.as_posix(),'STORAGE_DIR':str(tmp_path/'files')}
    def migrate(revision):
        result=subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','upgrade',revision],capture_output=True,env=env)
        assert result.returncode==0,result.stderr.decode(errors='replace')
    migrate('0002')
    run_id='run00000-origin'
    with sqlite3.connect(path) as conn:
        for user in ['u','other']:
            conn.execute("INSERT INTO users(id,created_at,username,display_name,password_hash,role,enabled) VALUES(?,CURRENT_TIMESTAMP,?,?,'not-loginable','requirement_member',1)",(user,user,user))
        for rid,owner,number in [('parent','u','TASK-run00000'),('child','u','AI-detail'),('private','other','AI-private')]:
            conn.execute("INSERT INTO requirements(id,created_at,owner_id,number,title,description,state,tags,acceptance,revision) VALUES(?,CURRENT_TIMESTAMP,?,?,?,'original','draft','{}','',1)",(rid,owner,number,rid))
        conn.execute("INSERT INTO skills(id,created_at,owner_id,name,command,description,public,enabled,publication_requested,current_version_id) VALUES('s',CURRENT_TIMESTAMP,'u','test','/test','',0,1,0,'sv')")
        conn.execute("INSERT INTO skill_versions(id,created_at,skill_id,creator_id,config) VALUES('sv',CURRENT_TIMESTAMP,'s','u','{}')")
        conn.execute("INSERT INTO agent_runs(id,created_at,owner_id,skill_version_id,status,inputs,result,citations,model_trace,error) VALUES(?,CURRENT_TIMESTAMP,'u','sv','completed',?,'{}','[]','{}','')",(run_id,json.dumps({'requirement_id':'parent'})))
        for rid in ['child','private']:
            conn.execute("INSERT INTO audit_logs(id,created_at,actor_id,action,resource_id,detail) VALUES(?,CURRENT_TIMESTAMP,'u','agent.confirm_requirement_candidate',?,?)",('audit-'+rid,rid,json.dumps({'run_id':run_id})))
    migrate('head')
    with sqlite3.connect(path) as conn:
        contexts={row[0]:row[1:] for row in conn.execute('SELECT requirement_id,kind,parent_id FROM requirement_contexts')}
        assert contexts=={'parent':('business',None),'child':('detail','parent')}
        assert conn.execute('SELECT COUNT(*) FROM requirements').fetchone()[0]==3
        assert conn.execute("SELECT description FROM requirements WHERE id='child'").fetchone()[0]=='original'


def test_srs_workflow_repair_creates_version_without_rewriting_history(tmp_path):
    import json
    path=tmp_path/'srs-repair.db'
    env={**os.environ,'DATABASE_URL':'sqlite:///'+path.as_posix(),'STORAGE_DIR':str(tmp_path/'files')}
    def migrate(revision):
        result=subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','upgrade',revision],capture_output=True,env=env)
        assert result.returncode==0,result.stderr.decode(errors='replace')
    migrate('0004')
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO users(id,created_at,username,display_name,password_hash,role,enabled) VALUES('u',CURRENT_TIMESTAMP,'u','u','not-loginable','requirement_member',1)")
        conn.execute("INSERT INTO skills(id,created_at,owner_id,name,command,description,public,enabled,publication_requested,current_version_id) VALUES('s',CURRENT_TIMESTAMP,'u','软需生成V1','/srs','','0',1,0,'sv')")
        config=json.dumps({'workflow':'qa','system_prompt':'# 软需转化 Skill\n测试原指令','package_metadata':{}},ensure_ascii=False)
        conn.execute("INSERT INTO skill_versions(id,created_at,skill_id,creator_id,config) VALUES('sv',CURRENT_TIMESTAMP,'s','u',?)",(config,))
        conn.execute("INSERT INTO agent_runs(id,created_at,owner_id,skill_version_id,status,inputs,result,citations,model_trace,error) VALUES('run',CURRENT_TIMESTAMP,'u','sv','completed','{}',?, '[]','{}','')",(json.dumps({'analysis':{'answer':'历史摘要'}},ensure_ascii=False),))
    migrate('head')
    with sqlite3.connect(path) as conn:
        current=conn.execute("SELECT current_version_id FROM skills WHERE id='s'").fetchone()[0]
        assert current!='sv'
        assert json.loads(conn.execute('SELECT config FROM skill_versions WHERE id=?',(current,)).fetchone()[0])['workflow']=='specification'
        assert json.loads(conn.execute("SELECT config FROM skill_versions WHERE id='sv'").fetchone()[0])['workflow']=='qa'
        assert conn.execute("SELECT skill_version_id FROM agent_runs WHERE id='run'").fetchone()[0]=='sv'
        assert '历史摘要' in conn.execute("SELECT result FROM agent_runs WHERE id='run'").fetchone()[0]


def test_processing_task_migration_hides_only_proven_placeholders(tmp_path):
    import json
    path=tmp_path/'tasks.db';env={**os.environ,'DATABASE_URL':'sqlite:///'+path.as_posix(),'STORAGE_DIR':str(tmp_path/'files')}
    def migrate(ref):
        p=subprocess.run([sys.executable,'-m','alembic','-c','backend/alembic.ini','upgrade',ref],capture_output=True,env=env)
        assert p.returncode==0,p.stderr.decode(errors='replace')
    migrate('0005')
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO users(id,created_at,username,display_name,password_hash,role,enabled) VALUES('u',CURRENT_TIMESTAMP,'u','u','not-loginable','requirement_member',1)")
        c.execute("INSERT INTO knowledge_bases(id,created_at,name,description,public,member_ids,enabled) VALUES('b',CURRENT_TIMESTAMP,'b','',1,'[]',1)")
        c.execute("INSERT INTO skills(id,created_at,owner_id,name,command,description,public,enabled,publication_requested,current_version_id) VALUES('s',CURRENT_TIMESTAMP,'u','skill','/s','',0,1,0,'sv')")
        c.execute("INSERT INTO skill_versions(id,created_at,skill_id,creator_id,config) VALUES('sv',CURRENT_TIMESTAMP,'s','u',?)",(json.dumps({'workflow':'specification'}),))
        for index,kind in enumerate(['automatic','manual','reviewed','clarified','related']):
            run='run0000'+str(index);rid='req'+str(index);doc='doc'+str(index);vid='v'+str(index)
            c.execute("INSERT INTO requirements(id,created_at,owner_id,number,title,description,state,tags,acceptance,revision) VALUES(?,CURRENT_TIMESTAMP,'u',?,?,'','specified','{}','',1)",(rid,'TASK-'+run[:8],kind))
            c.execute("INSERT INTO requirement_contexts(id,created_at,requirement_id,kind,origin_run_id) VALUES(?,CURRENT_TIMESTAMP,?,'business',?)",('ctx'+str(index),rid,run))
            c.execute("INSERT INTO agent_runs(id,created_at,owner_id,skill_version_id,status,inputs,result,citations,model_trace,error) VALUES(?,CURRENT_TIMESTAMP,'u','sv','completed',?,?, '[]','{}','')",(run,json.dumps({'requirement_id':rid}),json.dumps({'saved_version_id':vid})))
            c.execute("INSERT INTO knowledge_documents(id,created_at,title,owner_id,base_id,requirement_id,kind) VALUES(?,CURRENT_TIMESTAMP,?,'u','b',?,'specification')",(doc,kind,rid))
            c.execute("INSERT INTO document_versions(id,created_at,document_id,creator_id,label,filename,file_hash,content,blocks,warnings,status,parse_status,review_status,publish_status,index_status,revision,change_note,provenance) VALUES(?,CURRENT_TIMESTAMP,?,'u','V1','t.md','hash','original','[]','[]',?,'ready',?,'not_published','not_built',1,'',?)",(vid,doc,'pending_review' if kind=='reviewed' else 'draft','pending' if kind=='reviewed' else 'not_submitted',json.dumps({'agent_run_id':run})))
            if kind=='manual':c.execute("INSERT INTO audit_logs(id,created_at,actor_id,action,resource_id,detail) VALUES('manual',CURRENT_TIMESTAMP,'u','requirement.edit',?,'{}')",(rid,))
            if kind=='reviewed':c.execute("INSERT INTO review_requests(id,created_at,version_id,submitter_id,status,locked_hash,note) VALUES('review',CURRENT_TIMESTAMP,?,'u','pending','hash','')",(vid,))
        c.execute("INSERT INTO clarification_questions(id,created_at,owner_id,requirement_id,category,description,reason,evidence,target,feedback,conclusion,status) VALUES('question',CURRENT_TIMESTAMP,'u','req3','规则','确认问题','','{}','','','保留结论','confirmed')")
        c.execute("INSERT INTO requirement_relations(id,created_at,source_id,target_id,owner_id,kind,status,evidence) VALUES('relation',CURRENT_TIMESTAMP,'req4','req1','u','依赖','confirmed','{}')")
    migrate('head')
    with sqlite3.connect(path) as c:
        records={r[0]:r[1:] for r in c.execute('SELECT run_id,requirement_id,legacy_hidden,needs_review FROM processing_task_contexts')}
        assert records['run00000']==(None,1,0)
        assert records['run00001']==('req1',0,1) and records['run00002']==('req2',0,1)
        assert c.execute('SELECT count(*) FROM requirements').fetchone()[0]==5
        assert records['run00003']==('req3',0,1) and records['run00004']==('req4',0,1)
        assert c.execute("SELECT requirement_id FROM knowledge_documents WHERE id='doc0'").fetchone()[0] is None
        assert c.execute("SELECT requirement_id FROM knowledge_documents WHERE id='doc2'").fetchone()[0]=='req2'
        assert {r[0] for r in c.execute('SELECT content FROM document_versions')}=={'original'}
        assert c.execute('SELECT count(*) FROM processing_task_documents').fetchone()[0]==5
        assert c.execute("SELECT inputs FROM agent_runs WHERE id='run00000'").fetchone()[0]==json.dumps({'requirement_id':'req0'})
