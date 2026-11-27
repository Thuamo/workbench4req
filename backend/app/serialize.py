from sqlalchemy import inspect


def record(obj,exclude: tuple=()) -> dict:
    if obj is None:
        return {}
    return {c.key:getattr(obj,c.key) for c in inspect(obj).mapper.column_attrs if c.key not in ('password_hash','token_hash','encrypted_key',*exclude)}
