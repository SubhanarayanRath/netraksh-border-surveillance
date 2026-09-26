"""
NETRAKSH — Authentication router.
POST /auth/token   — obtain JWT
POST /auth/users   — create user (ADMIN only)
"""
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from backend.database.session import get_db
from backend.models.orm import User
from backend.security.auth import (
    audit,
    create_access_token,
    hash_password,
    require_admin,
    verify_password,
)
from shared.schemas import TokenResponse, UserCreate

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/token", response_model=TokenResponse)
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db),
):
    user = db.query(User).filter(
        User.username == form_data.username, User.is_active == True
    ).first()
    
    if user:
        import hashlib
        req_p_bytes = form_data.password.encode("utf-8")
        logger.info(f"[DIAGNOSTIC] REQUEST - lookup succeeded. is_active={user.is_active}")
        logger.info(
            f"REQUEST_PASSWORD:\n"
            f"  char_length={len(form_data.password)}\n"
            f"  byte_length={len(req_p_bytes)}\n"
            f"  sha256={hashlib.sha256(req_p_bytes).hexdigest()}\n"
            f"  first_byte={hex(req_p_bytes[0]) if req_p_bytes else 'None'}\n"
            f"  last_byte={hex(req_p_bytes[-1]) if req_p_bytes else 'None'}"
        )
        verified = verify_password(form_data.password, user.hashed_password)
        logger.info(f"[DIAGNOSTIC] REQUEST - verify_password result: {verified}")
    else:
        logger.info(f"[DIAGNOSTIC] REQUEST - lookup failed or inactive. User query returned None.")
        verified = False

    if not user or not verified:
        audit(db, "LOGIN_FAILED", ip_address=request.client.host,
              detail=f"username={form_data.username}", success=False)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect credentials")

    user.last_login = datetime.utcnow()
    db.commit()
    token = create_access_token({"sub": user.username, "role": user.role})
    audit(db, "LOGIN_SUCCESS", user_id=user.id, ip_address=request.client.host)
    return TokenResponse(access_token=token, role=user.role, username=user.username)


@router.post("/users", status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(status_code=400, detail="Username already exists")
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    return {"username": user.username, "role": user.role, "id": user.id}
