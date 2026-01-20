"""create default user

Revision ID: 434f792ffb4e
Revises: 7d89a686b08c
Create Date: 2025-10-22 16:34:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid
import bcrypt


# revision identifiers, used by Alembic.
revision: str = '434f792ffb4e'
down_revision: Union[str, None] = '7d89a686b08c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helper utilities (inline; we avoid importing application modules in migrations)
# ---------------------------------------------------------------------------


def _hash_password(password: str) -> str:
    """Return a bcrypt hash for *password* as UTF-8 string."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


DEFAULT_ADMIN_USERNAME = "admin"
DEFAULT_ADMIN_PASSWORD = "bot-admin-1337"


def upgrade() -> None:
    """Insert a default *admin* user if it does not already exist."""

    bind = op.get_bind()

    # Check existence by username (case-sensitive)
    exists = bind.execute(
        sa.text("SELECT 1 FROM users WHERE username = :u LIMIT 1"),
        {"u": DEFAULT_ADMIN_USERNAME},
    ).fetchone()

    if exists:
        # Admin already present – nothing to do
        return

    hashed_pw = _hash_password(DEFAULT_ADMIN_PASSWORD)

    bind.execute(
        sa.text(
            """
            INSERT INTO users (id, username, hashed_password, is_admin, is_active)
            VALUES (:id, :username, :hashed_password, true, true)
            """
        ),
        {
            "id": str(uuid.uuid4()),
            "username": DEFAULT_ADMIN_USERNAME,
            "hashed_password": hashed_pw,
        },
    )


def downgrade() -> None:
    """Remove the default *admin* user if it was inserted by *upgrade*."""

    bind = op.get_bind()

    bind.execute(
        sa.text("DELETE FROM users WHERE username = :u"),
        {"u": DEFAULT_ADMIN_USERNAME},
    )
