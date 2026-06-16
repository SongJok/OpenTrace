#!/usr/bin/env python3
"""
Create or refresh local dev login user (development only).

Run inside API container or host with PYTHONPATH=. and DATABASE_URL set:
  python scripts/seed_dev_user.py
"""
from __future__ import annotations

import asyncio
import sys
import uuid

from passlib.context import CryptContext
from sqlalchemy import select

from infra.config.settings import settings
from infra.storage.database import AsyncSessionLocal
from infra.storage.models import User

pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


async def main() -> int:
    if settings.app_env != "development":
        print("skip: app_env is not development")
        return 0
    if not settings.dev_seed_user_enabled:
        print("skip: dev_seed_user_enabled=false")
        return 0

    email = (settings.dev_seed_user_email or "dev@example.com").strip().lower()
    password = settings.dev_seed_user_password or "opentrace123"
    if len(password) < 6:
        print("✗ dev_seed_user_password must be at least 6 characters")
        return 1

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        hashed = pwd_ctx.hash(password)
        if user:
            user.hashed_password = hashed
            user.status = "active"
            user.is_active = True
            if not user.display_name:
                user.display_name = "Dev User"
            await db.commit()
            print(f"✓ 已更新开发账号: {email}")
        else:
            user = User(
                id=str(uuid.uuid4()),
                email=email,
                hashed_password=hashed,
                display_name="Dev User",
                status="active",
                role="admin",
                is_superuser=True,
                is_active=True,
            )
            db.add(user)
            await db.commit()
            print(f"✓ 已创建开发账号: {email}")

    print(f"  密码: {password}")
    print("  登录页使用上述邮箱和密码即可。")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))