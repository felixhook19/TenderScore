"""User, role and privilege management — every change audited."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit.hashing import state_hash
from app.audit.recorder import AuditRecorder
from app.auth.models import User, UserPrivilege, UserRole
from app.auth.passwords import hash_password
from app.auth.provider import new_totp_secret
from app.auth.roles import KNOWN_PRIVILEGES, Role


class UserManagementError(Exception):
    """Raised on invalid user-management requests; message is safe to show."""


def _user_state_hash(user: User) -> str:
    return state_hash(
        {
            "id": user.id,
            "tenant_id": user.tenant_id,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
        }
    )


def create_user(
    session: Session,
    recorder: AuditRecorder,
    *,
    tenant_id: uuid.UUID,
    email: str,
    display_name: str,
    password: str,
) -> User:
    """Create a user in the given tenant. Returns the user; the TOTP secret
    is on the returned model and is shown exactly once by callers."""
    cleaned_email = email.strip().lower()
    if session.scalar(select(User).where(User.email == cleaned_email)) is not None:
        raise UserManagementError("A user with this email address already exists.")
    if len(password) < 12:
        raise UserManagementError("The password must be at least 12 characters long.")

    user = User(
        tenant_id=tenant_id,
        email=cleaned_email,
        display_name=display_name.strip(),
        password_hash=hash_password(password),
        totp_secret=new_totp_secret(),
    )
    session.add(user)
    session.flush()
    recorder.record(
        "user.created",
        entity_type="user",
        entity_id=str(user.id),
        after_hash=_user_state_hash(user),
        tenant_id=tenant_id,
    )
    return user


def grant_role(
    session: Session, recorder: AuditRecorder, *, user: User, role: Role
) -> None:
    existing = session.get(UserRole, (user.id, role.value))
    if existing is not None:
        raise UserManagementError("The user already holds this role.")
    session.add(UserRole(user_id=user.id, role=role.value, tenant_id=user.tenant_id))
    session.flush()
    recorder.record(
        "rbac.role.granted",
        entity_type="user",
        entity_id=str(user.id),
        after_hash=state_hash({"user_id": user.id, "role": role.value}),
        tenant_id=user.tenant_id,
    )


def revoke_role(
    session: Session, recorder: AuditRecorder, *, user: User, role: Role
) -> None:
    existing = session.get(UserRole, (user.id, role.value))
    if existing is None:
        raise UserManagementError("The user does not hold this role.")
    session.delete(existing)
    session.flush()
    recorder.record(
        "rbac.role.revoked",
        entity_type="user",
        entity_id=str(user.id),
        before_hash=state_hash({"user_id": user.id, "role": role.value}),
        tenant_id=user.tenant_id,
    )


def grant_privilege(
    session: Session, recorder: AuditRecorder, *, user: User, privilege: str
) -> None:
    if privilege not in KNOWN_PRIVILEGES:
        raise UserManagementError("This privilege is not recognised.")
    existing = session.get(UserPrivilege, (user.id, privilege))
    if existing is not None:
        raise UserManagementError("The user already holds this privilege.")
    session.add(UserPrivilege(user_id=user.id, privilege=privilege))
    session.flush()
    recorder.record(
        "rbac.privilege.granted",
        entity_type="user",
        entity_id=str(user.id),
        after_hash=state_hash({"user_id": user.id, "privilege": privilege}),
        tenant_id=user.tenant_id,
    )


def revoke_privilege(
    session: Session, recorder: AuditRecorder, *, user: User, privilege: str
) -> None:
    existing = session.get(UserPrivilege, (user.id, privilege))
    if existing is None:
        raise UserManagementError("The user does not hold this privilege.")
    session.delete(existing)
    session.flush()
    recorder.record(
        "rbac.privilege.revoked",
        entity_type="user",
        entity_id=str(user.id),
        before_hash=state_hash({"user_id": user.id, "privilege": privilege}),
        tenant_id=user.tenant_id,
    )
