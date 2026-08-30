from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"


class Settings(BaseSettings):
    app_name: str = "GradeWise API"
    environment: Literal["development", "test", "production"] = "development"
    api_prefix: str = "/api"
    database_url: str = "postgresql+asyncpg://gradewise:change-me@localhost:5432/gradewise"
    readonly_database_url: str = (
        "postgresql+asyncpg://gradewise_ro:readonly-change-me@localhost:5432/gradewise"
    )
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "development-only-change-this-secret"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    cors_origins: str = "http://localhost:5173,http://localhost:8080"

    llm_provider: Literal["deepseek", "qwen"] = "qwen"
    llm_model: str = "deepseek-chat"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com"
    qwen_api_key: str = ""
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    query_timeout_ms: int = 5_000
    query_max_rows: int = 500
    conversation_ttl_seconds: int = 86_400
    chart_mcp_url: str = "http://chart-mcp:3030"
    mcp_service_token: str = "development-mcp-token"
    agent_protocol_url: str = "http://agent-worker:2024"
    seed_fake_data: bool = True
    demo_password: str = Field(default="GradeWise123!", min_length=8)

    model_config = SettingsConfigDict(
        env_file=(PROJECT_ENV_FILE, Path.cwd() / ".env"),
        extra="ignore",
        case_sensitive=False,
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def active_llm(self) -> tuple[str, str, str]:
        if self.llm_provider == "qwen":
            return self.qwen_model, self.qwen_api_key, self.qwen_base_url
        return self.llm_model, self.llm_api_key, self.llm_base_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
