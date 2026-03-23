from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "do or not"
    app_env: str = Field(default="dev", alias="APP_ENV")
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    default_user_id: str = Field(default="local-user", alias="DEFAULT_USER_ID")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    dashscope_api_key: str | None = Field(default=None, alias="DASHSCOPE_API_KEY")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="DASHSCOPE_BASE_URL",
    )
    model_name: str = Field(default="qwen3-max", alias="MODEL_NAME")
    vision_model_name: str | None = Field(default=None, alias="VISION_MODEL_NAME")
    model_timeout_seconds: int = Field(default=18, alias="MODEL_TIMEOUT_SECONDS")
    run_timeout_seconds: int = Field(default=45, alias="RUN_TIMEOUT_SECONDS")
    upload_max_image_bytes: int = Field(default=5_000_000, alias="UPLOAD_MAX_IMAGE_BYTES")
    upload_max_image_count: int = Field(default=3, alias="UPLOAD_MAX_IMAGE_COUNT")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")
    langsmith_tracing: bool = Field(default=False, alias="LANGSMITH_TRACING")
    langsmith_otel_enabled: bool = Field(default=True, alias="LANGSMITH_OTEL_ENABLED")
    langsmith_api_key: str | None = Field(default=None, alias="LANGSMITH_API_KEY")
    langsmith_project: str = Field(default="do-or-not-dev", alias="LANGSMITH_PROJECT")
    langsmith_endpoint: str = Field(default="https://api.smith.langchain.com", alias="LANGSMITH_ENDPOINT")
    langsmith_workspace_id: str | None = Field(default=None, alias="LANGSMITH_WORKSPACE_ID")

    sqlite_db_path: Path = Field(default=Path("./data/do_or_not.db"), alias="SQLITE_DB_PATH")
    checkpoint_db_path: Path = Field(default=Path("./data/checkpoints.db"), alias="CHECKPOINT_DB_PATH")
    uploads_dir: Path = Field(default=Path("./data/uploads"), alias="UPLOADS_DIR")

    @property
    def data_dir(self) -> Path:
        return self.sqlite_db_path.parent


settings = Settings()
