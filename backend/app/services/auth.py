"""인증 서비스 (spec/04_SECURITY_AND_DATA.md의 Authentication / Session Cookie).

HTTP를 모른다. cookie 설정과 401 판정은 `app.api.auth` / `app.api.deps`가 한다.
"""

from __future__ import annotations

import hashlib
import secrets
import string
from datetime import datetime, timedelta

import sqlalchemy as sa
from argon2 import PasswordHasher
from argon2.exceptions import Argon2Error, InvalidHashError
from sqlalchemy.orm import Session

from app.models.user import AuthSession, User

# ADR-004. `__Host-` prefix는 Secure / Path=/ / Domain 미지정을 브라우저가 강제하게
# 만들고 형제 subdomain이 같은 이름의 cookie를 덮어쓰는 것을 막는다.
SESSION_COOKIE_NAME = "__Host-nc_session"

# 32 bytes = 256 bit. token_urlsafe는 base64라 문자열 길이가 43자가 된다.
SESSION_TOKEN_BYTES = 32

# 파라미터를 발명하지 않는다. 명세는 "Argon2id 등 안전한 password hash"만 요구하고
# PHC 문자열이 자기 기술적이라 나중에 파라미터를 올려도 기존 해시를 검증할 수 있다.
_hasher = PasswordHasher()

# login_id가 존재하지 않을 때도 같은 비용을 치르게 해서 user enumeration을 막는다.
# 값은 매 프로세스마다 다른 난수라 미리 계산해 둘 수 없다.
DUMMY_PASSWORD_HASH = _hasher.hash(secrets.token_urlsafe(SESSION_TOKEN_BYTES))

# str.lower()는 유니코드 규칙을 따른다. DB CHECK가 ASCII만 허용하므로 ASCII만 내린다.
_ASCII_LOWER = str.maketrans(string.ascii_uppercase, string.ascii_lowercase)


def normalize_login_id(raw: str) -> str:
    """앞뒤 공백 제거 + ASCII lowercase.

    쓰기와 조회가 **같은 함수**를 쓴다. 조회 시점에 lower()를 걸면 UNIQUE가 정규화
    전 값에 걸려 대소문자만 다른 중복 계정이 생긴다.
    """
    return raw.strip().translate(_ASCII_LOWER)


def hash_password(password: str) -> str:
    """Argon2id PHC 문자열을 만든다. 복잡도 규칙은 명세에 없으므로 두지 않는다."""
    if not password:
        raise ValueError("password must not be empty")
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """검증 실패를 예외로 흘리지 않는다. 호출부는 참/거짓만 알면 된다."""
    try:
        return _hasher.verify(password_hash, password)
    except (Argon2Error, InvalidHashError):
        return False


def generate_session_token() -> str:
    """opaque random session token. random/uuid4를 쓰지 않는다."""
    return secrets.token_urlsafe(SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    """DB에 남길 token hash.

    session token은 256bit 난수라 추측할 구조가 없다. 느린 password hash가 필요한
    이유(저엔트로피 오프라인 추측)가 성립하지 않고, salt가 없어야
    `WHERE token_hash = :h`가 unique 인덱스를 탄다.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(db: Session, *, user_id: int, ttl_days: int, now: datetime) -> str:
    """세션 row를 만들고 **원본 token**을 돌려준다. commit은 호출부가 한다.

    원본 token은 cookie로만 나가고 DB에도 로그에도 남지 않는다.

    `now`는 호출부(요청)가 읽은 값이다. 여기서 시계를 다시 읽지 않는다(ADR-007).
    """
    token = generate_session_token()
    db.add(
        AuthSession(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=now + timedelta(days=ttl_days),
            last_used_at=now,
            created_at=now,
        )
    )
    return token


def resolve_session(db: Session, token: str, *, now: datetime) -> User | None:
    """유효한 session이면 User, 아니면 None.

    실패 사유(없음 / 폐기됨 / 만료됨 / 비활성 사용자)를 구분해서 돌려주지 않는다.
    호출부가 같은 401을 내야 oracle이 생기지 않는다.

    만료 판정의 canonical source는 `expires_at`과 `revoked_at`이다. cookie Max-Age는
    브라우저 힌트일 뿐이다.
    """
    row = db.execute(
        sa.select(AuthSession, User)
        .join(User, User.id == AuthSession.user_id)
        .where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now,
            User.is_active.is_(True),
        )
    ).first()
    if row is None:
        return None
    # Row 언패킹은 타입을 잃는다. _tuple()이 typed 접근자다(.tuple()은 deprecated).
    auth_session, user = row._tuple()
    # MVP는 absolute expiry만 쓴다. last_used_at은 기록하되 만료를 연장하지 않는다.
    auth_session.last_used_at = now
    return user


def revoke_session(db: Session, token: str, *, now: datetime) -> None:
    """logout. 이미 폐기된 세션이면 아무것도 하지 않는다. commit은 호출부가 한다."""
    db.execute(
        sa.update(AuthSession)
        .where(
            AuthSession.token_hash == hash_token(token),
            AuthSession.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
