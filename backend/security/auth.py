"""
NETRAKSH Backend — Security layer.
JWT authentication, RBAC (ADMIN/OPERATOR/AUDITOR), password hashing.
No private keys exposed to frontend. No credentials hardcoded.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database.session import get_db
from backend.models.orm import AuditLog, User
from shared.constants import UserRole

logger = logging.getLogger(__name__)

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Password utilities
# ---------------------------------------------------------------------------

def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


# ---------------------------------------------------------------------------
# Current user dependency
# ---------------------------------------------------------------------------

def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_scheme),
    db: Session = Depends(get_db),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(credentials.credentials)
    username: str = payload.get("sub", "")
    if not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload")
    user = db.query(User).filter(User.username == username, User.is_active == True).first()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    return user


def require_roles(*roles: UserRole):
    """Dependency factory that enforces RBAC."""
    def _check(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in [r.value for r in roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not permitted for this action. Required: {[r.value for r in roles]}",
            )
        return current_user
    return _check


# Convenience role dependencies
require_admin = require_roles(UserRole.ADMIN)
require_operator_or_admin = require_roles(UserRole.ADMIN, UserRole.OPERATOR)
require_any_role = require_roles(UserRole.ADMIN, UserRole.OPERATOR, UserRole.AUDITOR)


# ---------------------------------------------------------------------------
# Audit logging
# ---------------------------------------------------------------------------

def audit(
    db: Session,
    action: str,
    user_id: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    detail: Optional[str] = None,
    success: bool = True,
) -> None:
    if not settings.AUDIT_LOG_ENABLED:
        return
    log = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        ip_address=ip_address,
        detail=detail,
        success=success,
    )
    db.add(log)
    db.commit()


# ---------------------------------------------------------------------------
# Bootstrap: create initial users if they don't exist
# ---------------------------------------------------------------------------

def bootstrap_users(db: Session) -> None:
    """Called on startup to ensure at least one user of each role exists."""
    defaults = [
        (settings.ADMIN_USERNAME, settings.ADMIN_PASSWORD, UserRole.ADMIN.value),
        (settings.INITIAL_OPERATOR_USERNAME, settings.INITIAL_OPERATOR_PASSWORD, UserRole.OPERATOR.value),
        (settings.INITIAL_AUDITOR_USERNAME, settings.INITIAL_AUDITOR_PASSWORD, UserRole.AUDITOR.value),
    ]
    for username, password, role in defaults:
        existing = db.query(User).filter(User.username == username).first()
        if existing is None:
            user = User(username=username, hashed_password=hash_password(password), role=role)
            db.add(user)
            logger.info(f"Bootstrap: created user '{username}' with role '{role}'")
    db.commit()
