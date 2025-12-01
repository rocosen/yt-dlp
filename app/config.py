from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # App
    app_name: str = "Video Download Service"
    app_version: str = "1.0.0"
    debug: bool = False

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database
    database_url: str = "sqlite:///./data/tasks.db"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Download settings
    download_dir: str = "./downloads"
    max_concurrent_downloads: int = 100
    download_timeout: int = 3600  # 1 hour
    max_file_size: int = 5 * 1024 * 1024 * 1024  # 5GB

    # yt-dlp settings
    ytdlp_format: str = "bestvideo+bestaudio/best"
    ytdlp_proxy: Optional[str] = None

    # Storage settings (for future use)
    storage_type: str = "local"  # local, s3, oss
    s3_endpoint: Optional[str] = None
    s3_bucket: Optional[str] = None
    s3_access_key: Optional[str] = None
    s3_secret_key: Optional[str] = None
    s3_region: Optional[str] = None

    # Callback settings
    callback_timeout: int = 30
    callback_max_retries: int = 3

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

    @property
    def download_path(self) -> Path:
        path = Path(self.download_dir)
        path.mkdir(parents=True, exist_ok=True)
        return path


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
