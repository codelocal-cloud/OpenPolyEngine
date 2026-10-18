"""Local Postgres and Redis connection settings without secret-in-URL exposure."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class PostgresConfig:
    host: str
    port: int
    name: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "PostgresConfig":
        load_dotenv(REPO_ROOT / ".env", override=False)
        password = os.getenv("POLYBTC_DB_PASSWORD", "")
        if not password or password == "REPLACE_WITH_RANDOM_PASSWORD":
            raise ValueError("POLYBTC_DB_PASSWORD missing; configure .env")
        port = int(os.getenv("POLYBTC_DB_PORT", "55432"))
        if not (1 <= port <= 65535):
            raise ValueError("Invalid database port")
        return cls(
            host=os.getenv("POLYBTC_DB_HOST", "127.0.0.1"),
            port=port,
            name=os.getenv("POLYBTC_DB_NAME", "polybtc"),
            user=os.getenv("POLYBTC_DB_USER", "polybtc"),
            password=password,
        )

    def connect_kwargs(self) -> dict:
        return dict(
            host=self.host,
            port=self.port,
            dbname=self.name,
            user=self.user,
            password=self.password,
            connect_timeout=5,
            application_name="polybtc_readonly_scanner",
        )


@dataclass(frozen=True)
class RedisConfig:
    host: str
    port: int
    password: str

    @classmethod
    def from_env(cls) -> "RedisConfig":
        load_dotenv(REPO_ROOT / ".env", override=False)
        password = os.getenv("POLYBTC_REDIS_PASSWORD", "")
        if not password or password == "REPLACE_WITH_DIFFERENT_RANDOM_PASSWORD":
            raise ValueError("POLYBTC_REDIS_PASSWORD missing; configure .env")
        return cls(
            host=os.getenv("POLYBTC_REDIS_HOST", "127.0.0.1"),
            port=int(os.getenv("POLYBTC_REDIS_PORT", "16379")),
            password=password,
        )
