"""Chạy PostgreSQL 16 cục bộ (gói pgserver) cho dev/test trên máy không có Docker.
In ra DATABASE_URL. Server tiếp tục chạy sau khi script kết thúc."""
from __future__ import annotations

import sys
from pathlib import Path

import pgserver

ROOT = Path(__file__).resolve().parent.parent


def main() -> None:
    d = ROOT / ".localpg"
    srv = pgserver.get_server(str(d), cleanup_mode=None)
    if "--create" in sys.argv:
        srv.psql("CREATE DATABASE semsearch;")
    print(srv.get_uri().rsplit("/", 1)[0] + "/semsearch")


if __name__ == "__main__":
    main()
