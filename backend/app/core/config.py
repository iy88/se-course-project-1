"""应用配置：环境变量驱动，开发默认值面向 SQLite + 本地存储。"""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent
# 仓库根目录（backend/ 的上一级），运行期数据统一放在仓库下的 var/
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "CampusMarket API"
    environment: str = "dev"  # dev / prod

    # 数据库：开发阶段仅 SQLite；生产 MySQL 时替换为 mysql+aiomysql://...（本期不实现）
    database_url: str = f"sqlite+aiosqlite:///{PROJECT_ROOT / 'var' / 'db' / 'app.db'}"

    # 短时 KV（验证码等）：配置了 REDIS_URL 则用 Redis，否则进程内兜底
    redis_url: str = "redis://127.0.0.1:6379/0"

    # 对象存储：local=本地目录实现；oss=阿里云 OSS（本期仅留桩，不实现）
    storage_backend: str = "local"
    storage_local_root: Path = PROJECT_ROOT / "var" / "storage"
    oss_endpoint: str = ""
    oss_bucket: str = ""
    oss_access_key_id: str = ""
    oss_access_key_secret: str = ""

    # JWT
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    jwt_expire_days: int = 7

    # 文件签名 URL
    file_url_secret: str = "dev-file-secret-change-me"
    file_url_expire_seconds: int = 3600

    # 业务阈值（需求 8.4：设计阶段确定的保守取值）
    comment_max_length: int = 500
    comment_rate_limit_count: int = 3
    comment_rate_limit_seconds: int = 60
    trade_confirm_timeout_days: int = 7  # BR-05 单方确认 7 天未回应
    timeout_scan_interval_seconds: int = 60

    # 开发便利：验证码直接随接口返回（仅 environment=dev 且显式开启时）
    dev_expose_verification_code: bool = True

    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    # 确保运行期目录存在（var/db、var/storage 均在仓库下并被 Git 忽略）
    settings.storage_local_root.mkdir(parents=True, exist_ok=True)
    if settings.database_url.startswith("sqlite"):
        db_file = settings.database_url.split("///", 1)[-1]
        Path(db_file).parent.mkdir(parents=True, exist_ok=True)
    return settings
