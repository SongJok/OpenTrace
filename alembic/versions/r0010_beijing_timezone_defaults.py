"""统一面向用户的时间字段默认使用北京时间。"""

from alembic import op

revision = "r0010_beijing_timezone_defaults"
down_revision = "r0009_enterprise_skills"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE task_definitions ALTER COLUMN timezone SET DEFAULT 'Asia/Shanghai'")
    op.execute("ALTER TABLE alert_rules ALTER COLUMN timezone SET DEFAULT 'Asia/Shanghai'")


def downgrade() -> None:
    op.execute("ALTER TABLE task_definitions ALTER COLUMN timezone SET DEFAULT 'UTC'")
    op.execute("ALTER TABLE alert_rules ALTER COLUMN timezone SET DEFAULT 'UTC'")
