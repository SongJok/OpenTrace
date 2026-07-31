"""动态大模型配置 ORM。"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from infra.storage.database import Base


def _uuid() -> str:
    return str(uuid.uuid4())


class UserModelSettings(Base):
    """用户在租户/工作区范围内选择的大模型端点；密钥仅保存密文。"""

    __tablename__ = "user_model_settings"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            name="uq_user_model_settings_scope",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    active_profile: Mapped[str] = mapped_column(String(20), nullable=False, default="environment")
    active_source: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    active_free_model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    active_custom_model_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("user_custom_models.id", ondelete="SET NULL"), nullable=True
    )

    official_provider: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    official_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    official_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    official_model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    official_models: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    official_api_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="auto")

    relay_provider: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    relay_base_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    relay_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    relay_model: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    relay_models: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    relay_api_mode: Mapped[str] = mapped_column(
        String(32), nullable=False, default="chat_completions"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UserCustomModel(Base):
    """用户在租户/工作区范围内保存的单个 OpenAI-compatible 模型。"""

    __tablename__ = "user_custom_models"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "tenant_id",
            "workspace_id",
            "name",
            name="uq_user_custom_models_scope_name",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tenant_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    workspace_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default="default", index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    provider: Mapped[str] = mapped_column(String(128), nullable=False, default="自定义 / Custom")
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key_encrypted: Mapped[str] = mapped_column(Text, nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    api_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="chat_completions")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
