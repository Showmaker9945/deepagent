from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

VisionBackend = Literal["dashscope", "local_hf"]


def get_dashscope_api_key_status(value: str | None) -> str:
    if not value:
        return "missing"

    normalized = value.strip().strip('"').strip("'").lower()
    if normalized == "your-dashscope-api-key":
        return "placeholder"
    return "configured"


def describe_dashscope_config_issue(value: str | None) -> str | None:
    status = get_dashscope_api_key_status(value)
    if status == "missing":
        return "未配置 `DASHSCOPE_API_KEY`，当前无法调用 DeepAgent 主模型。"
    if status == "placeholder":
        return "`DASHSCOPE_API_KEY` 仍是占位值 `your-dashscope-api-key`，请替换为真实 DashScope API Key。"
    return None


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

    vision_backend: VisionBackend = Field(default="local_hf", alias="VISION_BACKEND")
    vision_model_name: str | None = Field(default=None, alias="VISION_MODEL_NAME")
    local_vision_model_id: str = Field(
        default="Qwen/Qwen2.5-VL-7B-Instruct",
        alias="LOCAL_VISION_MODEL_ID",
    )
    local_vision_model_dir: Path = Field(
        default=Path("./models/Qwen2.5-VL-7B-Instruct"),
        alias="LOCAL_VISION_MODEL_DIR",
    )
    local_vision_device: str = Field(default="auto", alias="LOCAL_VISION_DEVICE")
    local_vision_dtype: str = Field(default="float16", alias="LOCAL_VISION_DTYPE")
    local_vision_load_in_4bit: bool = Field(default=True, alias="LOCAL_VISION_LOAD_IN_4BIT")
    local_vision_max_new_tokens: int = Field(default=240, alias="LOCAL_VISION_MAX_NEW_TOKENS")
    local_vision_max_image_pixels: int = Field(default=786_432, alias="LOCAL_VISION_MAX_IMAGE_PIXELS")

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

    @property
    def dashscope_api_key_status(self) -> str:
        return get_dashscope_api_key_status(self.dashscope_api_key)

    @property
    def has_usable_dashscope_api_key(self) -> bool:
        return self.dashscope_api_key_status == "configured"

    @property
    def dashscope_config_issue(self) -> str | None:
        return describe_dashscope_config_issue(self.dashscope_api_key)

    @property
    def local_vision_model_downloaded(self) -> bool:
        return (self.local_vision_model_dir / "config.json").exists()

    @property
    def visual_config_issue(self) -> str | None:
        if self.vision_backend == "dashscope":
            return self.dashscope_config_issue
        if self.vision_backend == "local_hf" and not self.local_vision_model_downloaded:
            return (
                "本地视觉模型尚未下载完成。"
                f" 期望目录：`{self.local_vision_model_dir.as_posix()}`"
            )
        return None

    @property
    def visual_backend_ready(self) -> bool:
        return self.visual_config_issue is None


settings = Settings()
