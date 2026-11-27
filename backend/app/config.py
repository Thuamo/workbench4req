from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    database_url: str = 'sqlite:///./data/workbench.db'
    storage_dir: Path = Path('data')
    public_origin: str = 'http://localhost:3000'
    cookie_secure: bool = False
    session_hours: int = 12
    encryption_key: str = ''
    upload_limit_mb: int = 30
    embedding_dimensions: int = 1536
    qa_min_token_coverage: float = Field(default=0.25,gt=0,le=1)
    qa_semantic_threshold: float = Field(default=0.5,gt=0,le=1)
    qa_context_char_limit: int = Field(default=24000,ge=4000,le=120000)
    converter_executable: str = 'soffice'
    parse_timeout: int = 90
    plantuml_jar: Path | None = None
    plantuml_java: str = 'java'
    sqlite_busy_timeout_seconds: float = Field(default=3,gt=0,le=10)


settings = Settings()
settings.storage_dir.mkdir(parents=True, exist_ok=True)
