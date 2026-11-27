import sqlite3


def sqlite_busy(error: BaseException) -> bool:
    original=getattr(error,'orig',error)
    if not isinstance(original,sqlite3.OperationalError):
        return False
    code=getattr(original,'sqlite_errorcode',None)
    if isinstance(code,int) and code&255 in (sqlite3.SQLITE_BUSY,sqlite3.SQLITE_LOCKED):
        return True
    return str(original).lower() in ('database is locked','database table is locked','database schema is locked')
