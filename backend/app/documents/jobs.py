"""Document generation job handlers."""

import uuid

from app.documents.service import generate_pack
from app.framework.models import Procurement
from app.ingestion.storage import get_object_storage
from app.jobs.runner import JobContext, register_handler
from app.tenancy.models import Tenant

PACK_JOB_TYPE = "documents.moderation_pack"


def handle_pack_generation(context: JobContext) -> None:
    procurement_id = uuid.UUID(str(context.payload["procurement_id"]))
    file_format = str(context.payload.get("format", "docx"))
    generated_by_raw = context.payload.get("generated_by")
    generated_by = uuid.UUID(str(generated_by_raw)) if generated_by_raw else None

    procurement = context.session.get(Procurement, procurement_id)
    if procurement is None:
        raise ValueError("The procurement was not found.")
    tenant = context.session.get(Tenant, context.tenant_id)
    if tenant is None:
        raise ValueError("The tenant was not found.")
    generate_pack(
        context.session,
        context.recorder,
        get_object_storage(),
        tenant_schema=tenant.schema_name,
        procurement=procurement,
        file_format=file_format,
        generated_by=generated_by,
    )


def register() -> None:
    register_handler(PACK_JOB_TYPE, handle_pack_generation)
