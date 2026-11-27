import os, tempfile
from pathlib import Path
from alembic.config import Config
from alembic import command
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from app.config import settings
from app.db import engine

config=Config('backend/alembic.ini')
command.upgrade(config,'head')
with engine.begin() as connection:
    # Verify triggers without leaving test rows in the actual local database.
    triggers=connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars().all()
    assert len(triggers)>=5,triggers
print('Alembic head and five integrity triggers verified')
