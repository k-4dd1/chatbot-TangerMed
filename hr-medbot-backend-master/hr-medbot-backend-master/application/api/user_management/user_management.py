from fastapi import APIRouter, Depends, HTTPException, status
from typing import Annotated, Optional, List
import uuid

from database import session_scope
from database.models import User
from api.authentication import (
    get_authenticated_user
)
import re, bcrypt
from pydantic import BaseModel, validator, ConfigDict, constr




######## VALIDATORS #########

PHONE_REGEX = re.compile(r"^\+?[1-9]\d{9,14}$")  # E.164-like (+, 10-15 digits)
EMAIL_REGEX = re.compile(r"^[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}$")

def validate_phone_number(phone: str) -> bool:
    """Return True if `phone` matches expected pattern."""
    return bool(PHONE_REGEX.fullmatch(phone))

def validate_email(email: str) -> bool:
    """Return True if `email` matches expected pattern."""
    return bool(EMAIL_REGEX.fullmatch(email))

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )

####### /VALIDATORS ########

# ###### PASSWORD UTILS #####
def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(
        plain_password.encode('utf-8'),
        hashed_password.encode('utf-8')
    )

def get_password_hash(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')

###### /PASSWORD UTILS ######


# ---------------------------------------------------------------------------
# Router --------------------------------------------------------------------
# ---------------------------------------------------------------------------

UserManagementRouter = APIRouter()


# ---------------------------------------------------------------------------
# Schemas -------------------------------------------------------------------
# ---------------------------------------------------------------------------

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool
    is_active: bool

    model_config = ConfigDict(from_attributes=True)


class CreateUserRequest(BaseModel):
    username: constr(min_length=3, max_length=50)
    password: constr(min_length=8, max_length=128)
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_admin: bool = False

    @validator("phone_number")
    def _validate_phone(cls, v):  # noqa: N805
        if v is None:
            return v
        if not validate_phone_number(v):
            raise ValueError("Invalid phone number format")
        return v

    @validator("email")
    def _validate_email(cls, v):  # noqa: N805
        if v is None:
            return v
        if not validate_email(v):
            raise ValueError("Invalid email format")
        return v


class UpdateUserRequest(BaseModel):
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None

    @validator("phone_number")
    def _validate_phone(cls, v):  # noqa: N805
        if v is None:
            return v
        if not validate_phone_number(v):
            raise ValueError("Invalid phone number format")
        return v

    @validator("email")
    def _validate_email(cls, v):  # noqa: N805
        if v is None:
            return v
        if not validate_email(v):
            raise ValueError("Invalid email format")
        return v


class AdminChangePasswordRequest(BaseModel):
    new_password: constr(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Helpers -------------------------------------------------------------------
# ---------------------------------------------------------------------------

def _ensure_admin(user: User):
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")


def _get_user_or_404(db, user_id: uuid.UUID) -> User:
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


# ---------------------------------------------------------------------------
# Endpoints -----------------------------------------------------------------
# ---------------------------------------------------------------------------

@UserManagementRouter.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    req: CreateUserRequest,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Create a new user (admin only)."""
    _ensure_admin(current_user)

    with session_scope(write_enabled=True) as db:
        # Unique constraints --------------------------------------------------
        if db.query(User).filter(User.username == req.username).first():
            raise HTTPException(status_code=400, detail="Username already exists")
        if req.email and db.query(User).filter(User.email == req.email).first():
            raise HTTPException(status_code=400, detail="Email already used")
        if req.phone_number and db.query(User).filter(User.phone_number == req.phone_number).first():
            raise HTTPException(status_code=400, detail="Phone number already used")

        new_user = User(
            username=req.username,
            hashed_password=get_password_hash(req.password),
            first_name=req.first_name,
            last_name=req.last_name,
            phone_number=req.phone_number,
            email=req.email,
            is_admin=req.is_admin
        )
        db.add(new_user)
        db.flush()
        db.refresh(new_user)
        return new_user


@UserManagementRouter.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Update user data (admin only)."""
    _ensure_admin(current_user)

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with session_scope(write_enabled=True) as db:
        user_to_update = _get_user_or_404(db, user_uuid)

        # Uniqueness checks ---------------------------------------------------
        if req.phone_number and req.phone_number != user_to_update.phone_number:
            if db.query(User).filter(User.phone_number == req.phone_number).first():
                raise HTTPException(status_code=400, detail="Phone number already used")
            user_to_update.phone_number = req.phone_number

        if req.email and req.email != user_to_update.email:
            if db.query(User).filter(User.email == req.email).first():
                raise HTTPException(status_code=400, detail="Email already used")
            user_to_update.email = req.email

        # Simple assignments --------------------------------------------------
        for attr in [
            "first_name",
            "last_name",
            "is_admin",
            "is_active",
        ]:
            val = getattr(req, attr)
            if val is not None:
                setattr(user_to_update, attr, val)

        db.add(user_to_update)
        db.flush()
        db.refresh(user_to_update)
        return user_to_update


@UserManagementRouter.post("/{user_id}/password")
async def admin_change_password(
    user_id: str,
    req: AdminChangePasswordRequest,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Change a user's password (admin only)."""
    _ensure_admin(current_user)

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with session_scope(write_enabled=True) as db:
        target_user = _get_user_or_404(db, user_uuid)
        target_user.hashed_password = get_password_hash(req.new_password)
        db.add(target_user)
        return {"message": "Password updated successfully"}


@UserManagementRouter.get("/", response_model=List[UserResponse])
async def list_users(
    current_user: Annotated[User, Depends(get_authenticated_user)],
    active_only: bool | None = None,
):
    """Return list of users (admin only).

    Query params:
    - **active_only**: If True, only active users; if False, only disabled; if omitted, all users.
    """

    _ensure_admin(current_user)

    with session_scope() as db:
        q = db.query(User)
        if active_only is True:
            q = q.filter(User.is_active.is_(True))
        elif active_only is False:
            q = q.filter(User.is_active.is_(False))
        users = q.all()
    return users


@UserManagementRouter.post("/{user_id}/disable")
async def disable_user(
    user_id: str,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Disable a user account (admin only)."""
    _ensure_admin(current_user)

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with session_scope(write_enabled=True) as db:
        target_user = _get_user_or_404(db, user_uuid)
        target_user.is_active = False
        db.add(target_user)
        return {"message": "User disabled successfully"}


@UserManagementRouter.post("/{user_id}/enable")
async def enable_user(
    user_id: str,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Enable a previously disabled user account (admin only)."""

    _ensure_admin(current_user)

    try:
        user_uuid = uuid.UUID(str(user_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid user_id")

    with session_scope(write_enabled=True) as db:
        target_user = _get_user_or_404(db, user_uuid)
        target_user.is_active = True
        db.add(target_user)
    return {"message": "User enabled successfully"}
