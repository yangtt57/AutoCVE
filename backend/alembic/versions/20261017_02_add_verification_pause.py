"""给动态验证记录加暂停支持：``paused_at`` / ``paused_seconds``。

暂停的实现是把验证容器的进程冻结（Docker pause），记录本身需要知道
"现在是不是暂停中"以及"累计暂停了多久"，才能在继续后把暂停时间从
已用时里扣掉，并让暂停不再消耗验证预算。

Revision ID: 20261017_02
Revises: 20261017_01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261017_02"
down_revision = "20261017_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "vulnerability_verifications",
        sa.Column("paused_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "vulnerability_verifications",
        sa.Column("paused_seconds", sa.Float(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("vulnerability_verifications", "paused_seconds")
    op.drop_column("vulnerability_verifications", "paused_at")
