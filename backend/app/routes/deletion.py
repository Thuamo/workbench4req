from fastapi import APIRouter, Depends, Body, HTTPException
from sqlalchemy.orm import Session
from ..db import get_db
from ..security import current_user
from ..models import User
from ..services.deletion import delete_record

router=APIRouter(tags=['删除与历史保留'])

@router.delete('/records/{resource_type}/{resource_id}')
def remove_record(resource_type: str,resource_id: str,data: dict | None=Body(None),user: User=Depends(current_user),db: Session=Depends(get_db)):
    if not data or data.get('confirm') is not True: raise HTTPException(422,'请先确认删除')
    reason=data.get('reason','用户删除')
    if not isinstance(reason,str) or not 1<=len(reason.strip())<=1000: raise HTTPException(422,'删除原因应为1至1000字')
    return delete_record(db,user,resource_type,resource_id,reason.strip())
