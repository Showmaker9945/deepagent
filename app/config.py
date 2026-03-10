from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "do or not"
    secret_key: str = Field(default="change-me", alias="SECRET_KEY")
    default_user_id: str = Field(default="local-user", alias="DEFAULT_USER_ID")

    dashscope_api_key: str | None = Field(default=None, alias="DASHSCOPE_API_KEY")
    dashscope_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="DASHSCOPE_BASE_URL",
    )
    model_name: str = Field(default="qwen3-max", alias="MODEL_NAME")
    tavily_api_key: str | None = Field(default=None, alias="TAVILY_API_KEY")

    sqlite_db_path: Path = Field(default=Path("./data/do_or_not.db"), alias="SQLITE_DB_PATH")
    checkpoint_db_path: Path = Field(default=Path("./data/checkpoints.db"), alias="CHECKPOINT_DB_PATH")

    @property
    def data_dir(self) -> Path:
        return self.sqlite_db_path.parent


settings = Settings()
