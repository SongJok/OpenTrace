#!/usr/bin/env python3
"""
Seed script — creates initial admin user.
Usage: python scripts/seed_user.py
"""
from __future__ import annotations

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


async def main() -> None:
    # Load .env
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

    from infra.storage.database import engine, Base
    from infra.storage.models import User
    from passlib.context import CryptContext
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy import select
    import uuid

    pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    print("✓ Tables ready")

    SESSION = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with SESSION() as session:
        result = await session.execute(
            select(User).where(User.email == "songts@tuwan.com")
        )
        existing = result.scalar_one_or_none()
        if existing:
            print(f"✓ User already exists: {existing.email} (id={existing.id})")
            return

        uid = str(uuid.uuid4())
        user = User(
            id=uid,
            email="songts@tuwan.com",
            hashed_password=pwd_ctx.hash("123456"),
            display_name="Song TS",
            is_active=True,
            is_superuser=True,
        )
        session.add(user)
        await session.commit()

    print(f"✓ Created user: songts@tuwan.com (id={uid})")
    print("  Email:    songts@tuwan.com")
    print("  Password: 123456")


if __name__ == "__main__":
    asyncio.run(main())
