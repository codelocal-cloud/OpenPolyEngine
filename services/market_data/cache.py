"""Bounded Redis snapshot cache: short TTL, no credentials or orders."""
from __future__ import annotations

import json
import redis
from .config import RedisConfig
from .models import MarketSnapshot


class RedisCache:
    def __init__(self, config: RedisConfig | None = None):
        self.config = config or RedisConfig.from_env()
        self.client = redis.Redis(
            host=self.config.host,
            port=self.config.port,
            password=self.config.password,
            socket_connect_timeout=3,
            socket_timeout=3,
            decode_responses=True,
        )

    def publish(self, snapshots: list[MarketSnapshot]) -> int:
        with self.client.pipeline(transaction=True) as pipe:
            count = 0
            for snap in snapshots:
                # Never pass synthetic fixture prices off as real feed values.
                if snap.data_source != "gamma_public":
                    continue
                payload = json.dumps(snap.to_dict(), sort_keys=True)
                pipe.set(f"polybtc:market:latest:{snap.slug}", payload, ex=30)
                pipe.publish("polybtc:market:updates", payload)
                count += 1
            if count:
                pipe.execute()
            return count
