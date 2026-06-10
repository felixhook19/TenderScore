"""Tenant schema-name derivation tests."""

import pytest

from app.tenancy.service import TenantProvisioningError, schema_name_for


def test_derives_a_clean_slug() -> None:
    assert schema_name_for("Sandford District Council") == "tenant_sandford_district_council"


def test_strips_punctuation_and_case() -> None:
    assert schema_name_for("  Borough of Example-on-Sea!  ") == "tenant_borough_of_example_on_sea"


def test_respects_postgres_identifier_limit() -> None:
    name = "A" * 100
    assert len(schema_name_for(name)) <= 63


def test_rejects_names_without_letters() -> None:
    with pytest.raises(TenantProvisioningError):
        schema_name_for("123 456")


def test_rejects_empty_names() -> None:
    with pytest.raises(TenantProvisioningError):
        schema_name_for("   ")
