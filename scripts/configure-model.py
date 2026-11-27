"""Configure an encrypted local model from stdin; never print or persist plaintext keys."""
import argparse, json, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
sys.stdout.reconfigure(encoding='utf-8')
from sqlalchemy import select
from app.db import SessionLocal
from app.models import ModelConfig, Audit
from app.security import cipher
from app.schemas import ModelInput


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-url',required=True)
    parser.add_argument('--model',required=True)
    parser.add_argument('--name',default='本地聊天模型')
    args=parser.parse_args()
    key=sys.stdin.readline().strip()
    if not key:
        raise SystemExit('API key must be provided via stdin')
    data=ModelInput(name=args.name,base_url=args.base_url,model=args.model,api_key=key,kind='chat')
    encrypted=cipher().encrypt(data.api_key.encode()).decode()
    with SessionLocal() as db:
        config=db.scalar(select(ModelConfig).where(ModelConfig.base_url==data.base_url.rstrip('/'),ModelConfig.model==data.model,ModelConfig.kind=='chat').order_by(ModelConfig.created_at.desc()))
        if not config:
            config=ModelConfig(name=data.name,base_url=data.base_url.rstrip('/'),model=data.model,kind='chat',encrypted_key=encrypted,enabled=True)
            db.add(config)
        else:
            config.name=data.name
            config.encrypted_key=encrypted
            config.enabled=True
        db.flush()
        # Select this model as the sole active chat default; embedding is independent.
        for other in db.scalars(select(ModelConfig).where(ModelConfig.kind=='chat',ModelConfig.id!=config.id,ModelConfig.enabled.is_(True))).all():
            other.enabled=False
        db.add(Audit(actor_id=None,action='model.configure.local_cli',resource_id=config.id,detail={'model':config.model,'base_url':config.base_url,'kind':'chat'}))
        db.commit()
        print(json.dumps({'configured':True,'model':config.model,'base_url':config.base_url,'key_storage':'fernet-encrypted','config_id':config.id},ensure_ascii=False))


if __name__=='__main__':
    try:
        main()
    except Exception as error:
        print(json.dumps({'configured':False,'error_type':type(error).__name__}),file=sys.stderr)
        raise SystemExit(1)
