import logging, secrets
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from .db_errors import sqlite_busy
from .config import settings
from .services.ai import ModelServiceError
from .routes import auth, documents, knowledge, reviews, business, workflows, chat, admin, deletion, document_workspaces,processing_tasks,ledger_fill

app=FastAPI(title='需求智能工作台',version='1.0.0',description='真实数据库、版本化知识、多人会签与 Agent 工作流')
for module in [auth,documents,knowledge,reviews,business,workflows,chat,admin,deletion,document_workspaces,processing_tasks,ledger_fill]:
    app.include_router(module.router)


@app.middleware('http')
async def security_headers(request: Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        cookie=request.cookies.get('csrf','')
        token=request.headers.get('x-csrf-token','')
        if (origin and origin!=settings.public_origin) or not cookie or not secrets.compare_digest(cookie,token):
            return JSONResponse({'detail':'CSRF 或来源校验失败'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    return response


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request,error: IntegrityError):
    logging.warning('Database constraint failure on %s',request.url.path)
    return JSONResponse({'detail':'记录冲突或关联数据无效，请刷新后重试'},status_code=409)


@app.get('/health')
def health():
    from sqlalchemy import text
    from .db import SessionLocal
    with SessionLocal() as db:
        db.execute(text('SELECT 1'))
    return {'status':'ok'}


@app.exception_handler(OperationalError)
async def database_error(request: Request,error: OperationalError):
    if sqlite_busy(error):
        logging.warning('Database busy on %s',request.url.path)
        return JSONResponse({'detail':'数据库繁忙或被其他程序占用，请稍后重试；如正在编辑数据库，请先保存并关闭数据库连接。'},status_code=503,headers={'Retry-After':'2','Cache-Control':'no-store'})
    return await unexpected_error(request,error)


@app.exception_handler(Exception)
async def unexpected_error(request: Request,error: Exception):
    incident=secrets.token_hex(6)
    logging.error('Request failure %s on %s',incident,request.url.path,exc_info=error)
    return JSONResponse({'detail':f'服务处理失败，请稍后重试。错误标识：{incident}'},status_code=500)


@app.exception_handler(ModelServiceError)
async def model_error(request: Request,error: ModelServiceError):
    logging.warning('Model service unavailable: HTTP %s code=%s',error.provider_status,error.code)
    return JSONResponse({'detail':str(error),'code':'model_service_unavailable','provider_code':error.code},status_code=503 if error.code.lower() in ('arrearage','isv.out_of_service') else 502)
