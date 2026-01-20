import os
from fastapi import Depends
from pydantic import BaseModel, ConfigDict, validator
import re
from database.models import User
import bcrypt
from fastapi import Depends, HTTPException, status, APIRouter, WebSocket, WebSocketException, Request
from fastapi.security import OAuth2PasswordBearer
from datetime import datetime, timedelta, timezone
import jwt
from typing import Annotated, Optional
from database import session_scope
from sqlalchemy import or_
import uuid

# Secret key used for signing JWTs. In production, ensure the environment variable is set.
# Fallback to a deterministic dev key to avoid runtime errors in local/testing environments.
SECRET_KEY: str = os.getenv("SECRET_KEY", "__dev_secret_key_change_me__")

AUTH_ROUTER = APIRouter()


'''
create access token

/login


/me {get, post}
'''


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


########## MODELS ###########

class TokenResponse(BaseModel):
    access_token: str
    token_type: str

class JWTHeaderPayload(BaseModel):
    user_id: uuid.UUID


class MeResponse(BaseModel):
    id: uuid.UUID
    username: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class MePutPayload(BaseModel):
    """Request body for updating user details except username and metadata."""

    first_name: Optional[str] = None
    last_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None

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


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str

######### /MODELS ###########

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

###### JWT UTILS ##########

JWT_SECRET_KEY = SECRET_KEY
JWT_EXPIRES_MINUTES = 60 * 24 * 30 # 30 days
JWT_ALGORITHM = "HS256"
OAUTH2SCHEME = OAuth2PasswordBearer(tokenUrl="auth/token", auto_error=False) # Modified for JSON input

CredentialsException = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )


def create_access_token(data: dict):
    to_encode = data.copy()
    to_encode.update({"exp": datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRES_MINUTES)})
    encoded_jwt = jwt.encode(to_encode, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)
    return encoded_jwt


async def get_authenticated_user(token: Annotated[str, Depends(OAUTH2SCHEME)]):
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        # Validate and coerce the UUID string into a UUID instance
        try:
            jwt_payload = JWTHeaderPayload(user_id=uuid.UUID(str(payload.get("sub"))))
        except (ValueError, TypeError):
            raise CredentialsException
    except:
        raise CredentialsException
    with session_scope() as db:
        user = db.query(User).filter(User.id == jwt_payload.user_id).first()
    if not user:
      raise CredentialsException
    # Deny access for disabled accounts
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    return user  

async def _get_token_from_websocket(ws: WebSocket) -> Optional[str]:
    """Return JWT token sent by the client during the WebSocket handshake.

    The token is looked for in this order:

    1. `token` query-string parameter (e.g. `/ws/chat?token=<JWT>`)
    2. `access_token` cookie (set by HTTP login flow)
    3. Authorization header (native clients can set this)
    """
    token = ws.query_params.get("token")

    if not token:
        token = ws.cookies.get("access_token")

    if not token:
        auth_header = ws.headers.get("authorization")
        if auth_header and auth_header.lower().startswith("bearer "):
            token = auth_header[7:]

    return token

async def get_authenticated_user_websocket(ws: WebSocket):
    """Dependency to authenticate a WebSocket connection.

    If the client provides a valid JWT, returns the corresponding `User` ORM instance.
    Otherwise the socket is closed with code 1008 (policy violation) and a
    `WebSocketException` is raised so FastAPI will abort the endpoint execution.
    """
    token = await _get_token_from_websocket(ws)
    if token is None:
        # No credentials supplied – reject connection
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[JWT_ALGORITHM])
        user_id: str | None = payload.get("sub")
    except jwt.InvalidTokenError:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    if user_id is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    with session_scope() as db:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except (TypeError, ValueError):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
        user = db.query(User).filter(User.id == user_uuid).first()
    if user is None:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    if not user.is_active:
        await ws.close(code=status.WS_1008_POLICY_VIOLATION)
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION)
    return user


###### /JWT UTILS ########



###### LOGIN ###########

async def _extract_login_credentials(request: "Request") -> tuple[str, str]:
    """Return (identifier, password) extracted from JSON or form body, else 400.
    
    The 'username' field can contain either a username or an email address.
    """
    try:
        data = await request.json() if "json" in request.headers.get("content-type", "").lower() else await request.form()
        username = data.get("username")
        password = data.get("password")
        assert username and password, "Username and password required"
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request")
    return str(username), str(password)

@AUTH_ROUTER.post("/token", response_model=TokenResponse)
async def login_for_access_token(request: "Request"):
    """Obtain a JWT access token.

    Supports **both**:
    1. *application/x-www-form-urlencoded* (OAuth2 standard):
       ``grant_type=password&username=<user>&password=<pass>``
    2. *application/json* with body ``{"username": "<user>", "password": "<pass>"}``
    
    The ``username`` field accepts either a username or an email address.
    """

    identifier, password = await _extract_login_credentials(request)

    with session_scope() as db:
        user = (
            db.query(User)
            .filter(
                or_(
                    User.username == identifier,
                    User.email == identifier,
                    User.phone_number == identifier,
                )
            )
            .first()
        )

    if not user or not verify_password(password, user.hashed_password):
        raise CredentialsException
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account disabled")
    access_token = create_access_token(data={"sub": str(user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

########## /LOGIN ###########


########## ME ###############

@AUTH_ROUTER.get("/me", response_model=MeResponse)
async def read_users_me(current_user: Annotated[User, Depends(get_authenticated_user)]):
    return MeResponse.model_validate(current_user)

@AUTH_ROUTER.put("/me", response_model=MeResponse)
async def update_user_me(
    req: MePutPayload,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    # Validate already done by Pydantic. Need uniqueness checks for phone and email
    with session_scope(write_enabled=True) as db:
      

        if req.phone_number and req.phone_number != current_user.phone_number:
            if db.query(User).filter(User.phone_number == req.phone_number).first():
                raise HTTPException(status_code=400, detail="Phone number already used")
            current_user.phone_number = req.phone_number

        if req.email and req.email != current_user.email:
            if db.query(User).filter(User.email == req.email).first():
                raise HTTPException(status_code=400, detail="Email already used")
            current_user.email = req.email
        if req.first_name is not None:
            current_user.first_name = req.first_name
        if req.last_name is not None:
            current_user.last_name = req.last_name
        db.add(current_user)
        db.flush()
        db.refresh(current_user)
    return current_user

######## /ME ###############


####### password ##########

@AUTH_ROUTER.post("/password")
async def change_own_password(
    req: ChangePasswordRequest,
    current_user: Annotated[User, Depends(get_authenticated_user)],
):
    """Allow an authenticated user to change their own password.
    The user **must** provide the correct `old_password` for verification.
    """
    with session_scope(write_enabled=True) as db:
        if not verify_password(req.old_password, current_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Old password is incorrect")
        new_hash = get_password_hash(req.new_password)
        current_user.hashed_password = new_hash
        db.add(current_user)
        db.flush()
        db.refresh(current_user)
    return {"message": "Password updated successfully"}

####### /password ##########
