"""Identity provider interface and the development implementation.

The interface is the seam for the production identity provider (Entra ID
SSO is the target; the tenant decision is open and human-owned). Only the
development provider — email + password + TOTP — is built before P4.
"""

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import pyotp
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.models import SessionToken, User
from app.auth.passwords import verify_password
from app.core.config import get_settings


class AuthenticationError(Exception):
    """Raised on any failed authentication step; message is safe to show."""

    def __init__(self, message: str, *, user: User | None = None) -> None:
        super().__init__(message)
        self.user = user


@dataclass(frozen=True)
class AuthChallenge:
    """First factor accepted; a second factor is outstanding."""

    challenge_token: str
    expires_at: datetime
    user: User


@dataclass(frozen=True)
class AuthenticatedIdentity:
    """Fully authenticated session."""

    session_token: str
    expires_at: datetime
    user: User


class IdentityProvider(Protocol):
    """The seam behind which all authentication mechanisms live."""

    def begin_authentication(self, session: Session, email: str, password: str) -> AuthChallenge:
        """Verify the first factor and issue a short-lived challenge."""
        ...

    def complete_authentication(
        self, session: Session, challenge_token: str, code: str
    ) -> AuthenticatedIdentity:
        """Verify the second factor and issue a full session."""
        ...


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_totp_secret() -> str:
    return pyotp.random_base32()


class DevIdentityProvider:
    """Development-grade email + password + TOTP provider."""

    def begin_authentication(self, session: Session, email: str, password: str) -> AuthChallenge:
        settings = get_settings()
        user = session.scalar(select(User).where(User.email == email.strip().lower()))
        if user is None or user.status != "active":
            raise AuthenticationError("Invalid email address or password.")
        if not verify_password(password, user.password_hash):
            raise AuthenticationError("Invalid email address or password.", user=user)

        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.totp_challenge_ttl_minutes)
        session.add(
            SessionToken(
                user_id=user.id,
                token_hash=hash_token(token),
                status="pending_totp",
                expires_at=expires_at,
            )
        )
        session.flush()
        return AuthChallenge(challenge_token=token, expires_at=expires_at, user=user)

    def complete_authentication(
        self, session: Session, challenge_token: str, code: str
    ) -> AuthenticatedIdentity:
        settings = get_settings()
        pending = session.scalar(
            select(SessionToken).where(
                SessionToken.token_hash == hash_token(challenge_token),
                SessionToken.status == "pending_totp",
            )
        )
        if pending is None or pending.expires_at <= datetime.now(UTC):
            raise AuthenticationError("The sign-in challenge is invalid or has expired.")

        user = session.get(User, pending.user_id)
        if user is None or user.status != "active":
            raise AuthenticationError("The sign-in challenge is invalid or has expired.")

        if not pyotp.TOTP(user.totp_secret).verify(code, valid_window=1):
            raise AuthenticationError("The verification code is incorrect.", user=user)

        pending.status = "revoked"
        token = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=settings.session_ttl_minutes)
        session.add(
            SessionToken(
                user_id=user.id,
                token_hash=hash_token(token),
                status="active",
                expires_at=expires_at,
            )
        )
        session.flush()
        return AuthenticatedIdentity(session_token=token, expires_at=expires_at, user=user)


def get_identity_provider() -> IdentityProvider:
    """Resolve the configured identity provider (dev-only until P4)."""
    return DevIdentityProvider()
