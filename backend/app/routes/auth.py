import secrets
from datetime import timedelta
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from ..db import get_db
from ..models import User, AuthSession, LoginAttempt, now
from ..schemas import Register, Login, PasswordChange
from ..security import current_user, hasher, dummy_hash, verify, digest, rate_limit, audit, write_lock
from ..config import settings

router=APIRouter(prefix='/auth',tags=['认证'])


def user_info(user: User) -> dict:
    return {'id':user.id,'username':user.username,'display_name':user.display_name,'role':user.role,'enabled':user.enabled}


@router.get('/csrf')
def csrf(response: Response):
    token=secrets.token_urlsafe(32)
    response.set_cookie('csrf',token,httponly=False,secure=settings.cookie_secure,samesite='strict')
    return {'csrf_token':token}


@router.post('/register')
def register(data: Register,request: Request,db: Session=Depends(get_db)):
    key=digest('register:'+request.client.host)
    write_lock(db)
    rate_limit(db,key)
    db.add(LoginAttempt(key=key))
    db.commit()
    if db.scalar(select(User.id).where(User.username==data.username)):
        raise HTTPException(409,'用户名已存在')
    user=User(username=data.username,display_name=data.display_name,password_hash=hasher.hash(data.password))
    db.add(user)
    db.flush()
    audit(db,user,'user.register',user.id)
    db.commit()
    return user_info(user)


@router.post('/login')
def login(data: Login,request: Request,response: Response,db: Session=Depends(get_db)):
    key=digest('login:'+request.client.host+':'+data.username)
    write_lock(db)
    rate_limit(db,key)
    user=db.scalar(select(User).where(User.username==data.username))
    valid=verify(data.password,user.password_hash if user else dummy_hash)
    if not valid or not user or not user.enabled:
        db.add(LoginAttempt(key=key))
        db.commit()
        raise HTTPException(401,'用户名或密码错误')
    db.execute(delete(LoginAttempt).where(LoginAttempt.key==key))
    old=request.cookies.get('session')
    if old:
        db.execute(delete(AuthSession).where(AuthSession.token_hash==digest(old)))
    token=secrets.token_urlsafe(48)
    db.add(AuthSession(user_id=user.id,token_hash=digest(token),expires_at=now()+timedelta(hours=settings.session_hours)))
    audit(db,user,'user.login',user.id)
    db.commit()
    response.set_cookie('session',token,httponly=True,secure=settings.cookie_secure,samesite='lax',max_age=settings.session_hours*3600)
    return user_info(user)


@router.get('/me')
def me(user: User=Depends(current_user)):
    return user_info(user)


@router.post('/logout')
def logout(request: Request,response: Response,user: User=Depends(current_user),db: Session=Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.token_hash==digest(request.cookies.get('session',''))))
    db.commit()
    response.delete_cookie('session')
    return {'ok':True}


@router.post('/password')
def password(data: PasswordChange,user: User=Depends(current_user),db: Session=Depends(get_db)):
    if not verify(data.current_password,user.password_hash):
        raise HTTPException(403,'原密码错误')
    user.password_hash=hasher.hash(data.password)
    db.execute(delete(AuthSession).where(AuthSession.user_id==user.id))
    audit(db,user,'user.password',user.id)
    db.commit()
    return {'ok':True,'message':'密码已修改，请重新登录'}
