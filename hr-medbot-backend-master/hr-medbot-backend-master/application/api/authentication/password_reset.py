from __future__ import annotations

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

import random
import time
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel

import diskcache as dc

from database import session_scope
from database.models.user import User
import requests
import os
import hmac
import bcrypt
import re
import secrets


# ------------ Infobip ------------

API_URL = os.getenv("SMS_API_URL")
API_KEY = os.getenv("SMS_API_KEY")


def send_sms(to: str, message: str):
    headers = {
        "Authorization": f"App {API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "messages": [
            {
                "destinations": [
                    {"to": to}
                ],
                "text": message,
            }
        ]
    }
    response = requests.post(API_URL, headers=headers, json=data)
    return response.json()

# ------------ Configuration ------------

CACHE_DIR = "/tmp/password_reset_cache"
PIN_TTL_SECONDS = 15 * 60          # 15 minutes
COOLDOWN_SECONDS = 3 * 60          # 3 minutes
# Maximum allowed attempts before requiring a new PIN request
MAX_PIN_ATTEMPTS = 5
PIN_LENGTH = 6

cache = dc.Cache(CACHE_DIR)

PASS_RESET_ROUTER = APIRouter()

# ------------ Schemas ------------

class PasswordResetRequest(BaseModel):
    phone: str | None = None
    username: str | None = None
    
    def __init__(self, **data):
        super().__init__(**data)
        if not self.phone and not self.username:
            raise ValueError("Either phone or username must be provided")
        if self.phone and self.username:
            raise ValueError("Provide either phone or username, not both")

class PasswordResetReset(BaseModel):
    phone: str | None = None
    username: str | None = None
    pin: str
    new_password: str
    
    def __init__(self, **data):
        super().__init__(**data)
        if not self.phone and not self.username:
            raise ValueError("Either phone or username must be provided")
        if self.phone and self.username:
            raise ValueError("Provide either phone or username, not both")


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


# ------------ Helpers ------------

def _generate_pin(length: int = PIN_LENGTH) -> str:
    return ''.join(secrets.choice('0123456789') for _ in range(length))

def _get_user_by_phone(db, phone: str) -> User | None:
    return db.query(User).filter(User.phone_number == phone).first()

def _get_user_by_username(db, username: str) -> User | None:
    return db.query(User).filter(User.username == username).first()

def _get_user_by_identifier(db, phone: str | None = None, username: str | None = None) -> User | None:
    """Get user by either phone number or username."""
    if phone:
        return _get_user_by_phone(db, phone)
    elif username:
        return _get_user_by_username(db, username)
    return None

# Safe TTL helper – works even if diskcache.Cache lacks a ``ttl`` method.
# Returns remaining seconds-to-live for *key*, or ``None`` if key absent/without expiry.
def _ttl(key: str) -> int | None:
    ttl_method = getattr(cache, "ttl", None)
    if callable(ttl_method):
        return ttl_method(key)  # type: ignore[arg-type]
    # Fallback: derive TTL from separately stored expiry timestamp
    expires_at: float | None = cache.get(f"__exp:{key}")  # type: ignore[assignment]
    if expires_at is None:
        return None
    remaining = int(expires_at - time.time())
    return max(0, remaining)

# Helper to set cache value while tracking expiry timestamp for TTL fallback
def _set(key: str, value, expire: int | None = None) -> None:
    """Wrapper around ``cache.set`` that also stores an expiry marker
    for accurate TTL retrieval via :pyfunc:`_ttl` when the underlying
    Cache implementation lacks a native ``ttl()`` method.

    Args:
        key: Cache key
        value: Value to store
        expire: Seconds before the key expires; ``None`` for no expiry
    """
    if expire is not None:
        cache.set(key, value, expire=expire)
        cache.set(f"__exp:{key}", time.time() + expire, expire=expire)
    else:
        cache.set(key, value)

# Additional helpers ---------------------------------------------------------

def _delete_keys(*keys: str) -> None:
    """Delete cache keys and their associated expiry markers."""
    for key in keys:
        cache.delete(key)
        cache.delete(f"__exp:{key}")


def _rate_limit_guard(cooldown_key: str, otp_key: str) -> None:
    """Raise 429 if the caller is still in cooldown."""
    if cache.get(cooldown_key) is None:
        return  # no cooldown in place

    retry_after = _ttl(cooldown_key) or COOLDOWN_SECONDS
    pin_validity_remaining = _ttl(otp_key) or 0

    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "message": "You can request a new PIN only once every 3 minutes",
            "retry_after": retry_after,
            "pin_validity": pin_validity_remaining,
        },
        headers={"Retry-After": str(retry_after)},
    )


def _ensure_user_exists(phone: str | None = None, username: str | None = None) -> None:
    """Validate that a user with this phone or username exists, else 404."""
    with session_scope() as db:
        user = _get_user_by_identifier(db, phone, username)
        if user is None:
            identifier_type = "phone number" if phone else "username"
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{identifier_type.title()} not found")


def _create_and_store_pin(phone: str | None = None, username: str | None = None) -> str:
    """Generate a PIN, persist it & cooldown markers, and return the PIN."""
    identifier = phone or username
    otp_key = f"otp:{identifier}"
    cooldown_key = f"cooldown:{identifier}"

    pin = _generate_pin()
    _set(otp_key, pin, PIN_TTL_SECONDS)
    _set(cooldown_key, 1, COOLDOWN_SECONDS)
    # Attempts tracking zeroed for each request
    tries_key = f"tries:{identifier}"
    _set(tries_key, 0, PIN_TTL_SECONDS)
    return pin


def _send_pin_sms(phone: str, pin: str) -> None:
    message = f"Your verification code is {pin}. It is valid for 15 minutes."

    send_sms(phone, message)

def _get_user_phone_for_sms(phone: str | None = None, username: str | None = None) -> str:
    """Get the phone number for SMS sending. If phone is provided, use it. If username is provided, get phone from user."""
    if phone:
        return phone
    elif username:
        with session_scope() as db:
            user = _get_user_by_username(db, username)
            if user is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Username not found")
            if not user.phone_number:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="User has no phone number associated with their account")
            return user.phone_number
    else:
        raise ValueError("Either phone or username must be provided")


# ------------ Endpoints ------------

@PASS_RESET_ROUTER.post("/request")
async def request_password_reset(data: PasswordResetRequest):
    """
    Password reset by sending a PIN to the user's phone number.
    Can be requested using either phone number or username.
    """
    phone = data.phone.strip() if data.phone else None
    username = data.username.strip() if data.username else None
    
    # Validate phone number if provided
    if phone and not validate_phone_number(phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format")
    
    # Get the phone number for SMS (either provided or from user record)
    sms_phone = _get_user_phone_for_sms(phone, username)
    
    # Use the identifier (phone or username) for cache keys
    identifier = phone or username
    cooldown_key = f"cooldown:{identifier}"
    otp_key = f"otp:{identifier}"
    
    _rate_limit_guard(cooldown_key, otp_key)
    _ensure_user_exists(phone, username)
    pin = _create_and_store_pin(phone, username)
    
    try:
        _send_pin_sms(sms_phone, pin)
    except Exception as exc:
        _delete_keys(otp_key, cooldown_key)
        raise HTTPException(status_code=500, detail=f"Failed to send SMS: {exc}")

    return {
        "message": "Verification code sent",
        "retry_after": COOLDOWN_SECONDS,
        "pin_validity": PIN_TTL_SECONDS,
    }


@PASS_RESET_ROUTER.post("/reset")
async def reset_password(data: PasswordResetReset):
    """
    Reset a user's password by providing a PIN sent to their phone number.
    Can be reset using either phone number or username.
    """
    phone = data.phone.strip() if data.phone else None
    username = data.username.strip() if data.username else None
    
    # Validate phone number if provided
    if phone and not validate_phone_number(phone):
        raise HTTPException(status_code=400, detail="Invalid phone number format")
    
    # Use the identifier (phone or username) for cache keys
    identifier = phone or username
    otp_key = f"otp:{identifier}"
    tries_key = f"tries:{identifier}"

    # Check remaining attempts
    attempts = cache.get(tries_key) or 0
    attempts = int(attempts) + 1
    if attempts > MAX_PIN_ATTEMPTS:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many incorrect attempts; request a new PIN")
    
    _set(tries_key, attempts, PIN_TTL_SECONDS)
    stored_pin: str | None = cache.get(otp_key)
    # Constant-time compare to avoid timing attacks
    if stored_pin is None or not hmac.compare_digest(str(stored_pin), str(data.pin)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired PIN")

    new_hash = get_password_hash(data.new_password)

    with session_scope(write_enabled=True) as db:
        user = _get_user_by_identifier(db, phone, username)
        if user is None:
            identifier_type = "phone number" if phone else "username"
            raise HTTPException(status_code=404, detail=f"{identifier_type.title()} not found")
        user.hashed_password = new_hash
        db.add(user)
        db.flush()
        db.refresh(user)

    # Invalidate PIN and attempts after successful reset
    _delete_keys(otp_key, tries_key)

    return {"message": "Password reset successfully"}
