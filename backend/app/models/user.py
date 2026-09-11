"""사용자와 인증 세션 (04_DB_SPEC.md)."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, bigint_pk, created_at_column, enum_column
from app.models.enums import StartingLevel


class User(Base):
    """Public signup은 없다. 계정은 seed/admin CLI로 만든다."""

    __tablename__ = "users"

    id: Mapped[int] = bigint_pk()
    # 05_API_SPEC.md의 `POST /api/auth/login {login_id, password}`.
    # 정규화(공백 제거 + ASCII lowercase)는 쓰기 시점에 애플리케이션이 하고
    # DB에는 정규화된 값만 들어간다. 조회 시 lower()나 citext를 쓰지 않는다.
    # UNIQUE가 정규화 전 값에 걸리면 대소문자만 다른 중복 계정이 생긴다.
    login_id: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # Argon2id hash. 원본 password는 저장하지 않는다.
    password_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    # 정책 기본값(Asia/Seoul, beginner)은 14_CONFIGURATION.md가 canonical이다.
    # server_default로 박으면 config와 두 곳이 되므로 애플리케이션이 주입한다.
    timezone: Mapped[str] = mapped_column(sa.Text, nullable=False)
    starting_level: Mapped[StartingLevel] = mapped_column(
        enum_column(StartingLevel, "starting_level"), nullable=False
    )
    created_at: Mapped[datetime] = created_at_column()
    is_active: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.text("true")
    )

    __table_args__ = (
        sa.UniqueConstraint("login_id"),
        # 이메일 형식은 강제하지 않는다(public signup 없음, 메일 발송 없음).
        sa.CheckConstraint(
            r"login_id ~ '^[a-z0-9._+@-]{3,64}$'",
            name="login_id_format",
        ),
    )


class AuthSession(Base):
    """인증 세션. 학습 세션(`study_sessions`)과 이름을 분리한다."""

    __tablename__ = "auth_sessions"

    id: Mapped[int] = bigint_pk()
    user_id: Mapped[int] = mapped_column(sa.BigInteger, sa.ForeignKey("users.id"), nullable=False)
    # opaque random token의 hash만 저장한다. 조회 키이므로 unique다.
    token_hash: Mapped[str] = mapped_column(sa.Text, nullable=False)
    created_at: Mapped[datetime] = created_at_column()
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    last_used_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))

    __table_args__ = (
        sa.UniqueConstraint("token_hash"),
        sa.Index("ix_auth_sessions_user_id", "user_id"),
    )
