"""Tenant-administration endpoints: users, roles and distinct privileges.

Admin-only, strictly scoped to the administrator's own tenant. Every
mutation is audited via the request-bound recorder.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.audit.recorder import AuditRecorder
from app.auth import service
from app.auth.deps import CurrentUser, get_db, get_recorder, require_roles
from app.auth.models import User
from app.auth.roles import Role
from app.auth.service import UserManagementError

router = APIRouter(prefix="/users", tags=["administration"])

_admin_only = require_roles(Role.ADMIN)


class CreateUserRequest(BaseModel):
    email: EmailStr
    display_name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12)


class CreateUserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    totp_secret: str
    detail: str


class RoleRequest(BaseModel):
    role: Role


class PrivilegeRequest(BaseModel):
    privilege: str = Field(min_length=1)


def _load_tenant_user(db: Session, admin: CurrentUser, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None or user.tenant_id != admin.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="The user was not found."
        )
    return user


def _bad_request(error: UserManagementError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error))


@router.post("", response_model=CreateUserResponse, status_code=status.HTTP_201_CREATED)
def create_user(
    body: CreateUserRequest,
    admin: Annotated[CurrentUser, Depends(_admin_only)],
    db: Annotated[Session, Depends(get_db)],
    recorder: Annotated[AuditRecorder, Depends(get_recorder)],
) -> CreateUserResponse:
    try:
        user = service.create_user(
            db,
            recorder,
            tenant_id=admin.tenant_id,
            email=str(body.email),
            display_name=body.display_name,
            password=body.password,
        )
    except UserManagementError as error:
        raise _bad_request(error) from error
    return CreateUserResponse(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        totp_secret=user.totp_secret,
        detail=(
            "Share the TOTP secret with the user over a secure channel; it is "
            "shown only once."
        ),
    )


@router.post("/{user_id}/roles", status_code=status.HTTP_204_NO_CONTENT)
def grant_role(
    user_id: uuid.UUID,
    body: RoleRequest,
    admin: Annotated[CurrentUser, Depends(_admin_only)],
    db: Annotated[Session, Depends(get_db)],
    recorder: Annotated[AuditRecorder, Depends(get_recorder)],
) -> None:
    user = _load_tenant_user(db, admin, user_id)
    try:
        service.grant_role(db, recorder, user=user, role=body.role)
    except UserManagementError as error:
        raise _bad_request(error) from error


@router.delete("/{user_id}/roles/{role}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_role(
    user_id: uuid.UUID,
    role: Role,
    admin: Annotated[CurrentUser, Depends(_admin_only)],
    db: Annotated[Session, Depends(get_db)],
    recorder: Annotated[AuditRecorder, Depends(get_recorder)],
) -> None:
    user = _load_tenant_user(db, admin, user_id)
    try:
        service.revoke_role(db, recorder, user=user, role=role)
    except UserManagementError as error:
        raise _bad_request(error) from error


@router.post("/{user_id}/privileges", status_code=status.HTTP_204_NO_CONTENT)
def grant_privilege(
    user_id: uuid.UUID,
    body: PrivilegeRequest,
    admin: Annotated[CurrentUser, Depends(_admin_only)],
    db: Annotated[Session, Depends(get_db)],
    recorder: Annotated[AuditRecorder, Depends(get_recorder)],
) -> None:
    user = _load_tenant_user(db, admin, user_id)
    try:
        service.grant_privilege(db, recorder, user=user, privilege=body.privilege)
    except UserManagementError as error:
        raise _bad_request(error) from error


@router.delete("/{user_id}/privileges/{privilege}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_privilege(
    user_id: uuid.UUID,
    privilege: str,
    admin: Annotated[CurrentUser, Depends(_admin_only)],
    db: Annotated[Session, Depends(get_db)],
    recorder: Annotated[AuditRecorder, Depends(get_recorder)],
) -> None:
    user = _load_tenant_user(db, admin, user_id)
    try:
        service.revoke_privilege(db, recorder, user=user, privilege=privilege)
    except UserManagementError as error:
        raise _bad_request(error) from error
