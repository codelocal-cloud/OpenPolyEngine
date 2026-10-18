"""Generate independent local-only Docker passwords, never overwrite an existing .env."""
from pathlib import Path
import os
import secrets

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / ".env"
if TARGET.exists():
    print(".env already exists; leaving existing credentials untouched")
else:
    contents = f"""# Local development only. Do not commit or upload this file.
POLYBTC_DB_NAME=polybtc
POLYBTC_DB_USER=polybtc
POLYBTC_DB_PASSWORD={secrets.token_hex(24)}
POLYBTC_DB_HOST=127.0.0.1
POLYBTC_DB_PORT=55432
POLYBTC_REDIS_PASSWORD={secrets.token_hex(24)}
POLYBTC_REDIS_HOST=127.0.0.1
POLYBTC_REDIS_PORT=16379
"""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    fd = os.open(TARGET, flags, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write(contents)
    print(".env generated with unique random local DB/Redis passwords (mode 0600)")
