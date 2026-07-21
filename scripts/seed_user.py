#!/usr/bin/env python3
"""兼容入口：本地开发账号统一由 seed_dev_user.py 管理。"""

from __future__ import annotations

import asyncio

from scripts.seed_dev_user import main

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
