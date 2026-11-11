"""Authentication helpers, password hashing, API key verification, and FastAPI RBAC guards."""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from sqlmodel import Session, select

from backend.config import settings
from backend.database import get_session
from backend.models import ApiKey, User, UserRole, utc_now

bearer_scheme = HTTPBearer(auto_error=False)
PBKDF2_ITERATIONS = 200_000


def hash_password(plain_password: str) -> str:
    """Hash a password using salted PBKDF2-HMAC-SHA256."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", plain_password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(plain_password: str, stored_hash: str) -> bool:
    """Verify a plaintext password against a stored PBKDF2 hash safely."""
    try:
        scheme, iters_str, salt, expected_hex = stored_hash.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        candidate = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iters_str),
        ).hex()
        return hmac.compare_digest(candidate, expected_hex)
    except ValueError:
        return False


def hash_api_key(raw_key: str) -> str:
    """Compute SHA-256 digest for storing API keys securely at rest."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key_pair() -> tuple[str, str, str]:
    """Generate (raw_secret, display_prefix, sha256_hash) for a new API key."""
    token = f"tdk_{secrets.token_urlsafe(24)}"
    return token, token[:12], hash_api_key(token)


def create_access_token(user: User) -> str:
    """Issue a signed JWT containing subject user id and role."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role.value,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.token_expire_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def _resolve_api_key_user(raw_key: str, session: Session) -> User | None:
    """Validate an X-API-Key token and update last_used_at timestamp."""
    digest = hash_api_key(raw_key.strip())
    record = session.exec(
        select(ApiKey).where(ApiKey.key_hash == digest, ApiKey.is_active.is_(True))
    ).first()
    if not record:
        return None
    record.last_used_at = utc_now()
    session.add(record)
    session.commit()
    return session.exec(select(User).where(User.id == record.user_id)).first()


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    session: Session = Depends(get_session),
) -> User:
    """Resolve authenticated active user via Bearer JWT or X-API-Key header."""
    user: User | None = None

    if credentials and credentials.credentials:
        try:
            payload = jwt.decode(
                credentials.credentials,
                settings.jwt_secret,
                algorithms=[settings.jwt_algorithm],
            )
            user_id = int(payload["sub"])
        except (jwt.PyJWTError, KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired authentication token.",
            ) from exc
        user = session.exec(select(User).where(User.id == user_id)).first()
    elif x_api_key:
        user = _resolve_api_key_user(x_api_key, session)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or revoked API key.",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication credentials were not provided.",
        )

    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is inactive or no longer exists.",
        )
    return user


def require_roles(*allowed_roles: UserRole):
    """Return a FastAPI dependency enforcing role-based authorization."""

    def checker(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return current_user

    return checker
