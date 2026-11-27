from sqlalchemy import create_engine, event
from sqlalchemy.engine import make_url
from pathlib import Path
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from .config import settings


class Base(DeclarativeBase):
    pass


database_path = make_url(settings.database_url).database
if settings.database_url.startswith('sqlite') and database_path and database_path != ':memory:':
    Path(database_path).parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(settings.database_url, pool_pre_ping=True,
                       connect_args={'check_same_thread': False, 'timeout': settings.sqlite_busy_timeout_seconds} if settings.database_url.startswith('sqlite') else {})
SessionLocal = sessionmaker(engine, expire_on_commit=False)
if engine.dialect.name == 'sqlite':
    @event.listens_for(engine, 'connect')
    def sqlite_options(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
        connection.execute('PRAGMA journal_mode=WAL')


def get_db():
    with SessionLocal() as db:
        yield db
