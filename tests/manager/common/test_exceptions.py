from __future__ import annotations

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404
from rest_framework import serializers
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    ErrorDetail,
    NotFound,
    ValidationError,
)

from dbs.manager.common.exceptions import error_code_of, exception_handler


class Unreachable(APIException):
    default_code = "ssh_unreachable"


def envelope(exc):
    return exception_handler(exc, {"view": None}).data["error"]


def test_field_errors_carry_their_codes():
    serializer = serializers.Serializer(data={})
    serializer.fields["name"] = serializers.CharField()
    serializer.fields["port"] = serializers.IntegerField()
    serializer.is_valid()

    error = envelope(ValidationError(serializer.errors))

    assert error["code"] == "invalid"
    assert error["fields"] == {"name": ["required"], "port": ["required"]}


def test_a_validation_error_without_a_field_carries_its_own_code():
    error = envelope(
        ValidationError("That is not a host key.", code="invalid_host_key")
    )

    assert error["code"] == "invalid_host_key"
    assert "fields" not in error


def test_nested_field_errors_are_flattened_to_codes():
    detail = ErrorDetail("Use an absolute path.", code="absolute_path_required")
    error = envelope(ValidationError({"file_roots": {0: [detail]}}))

    assert error["fields"] == {"file_roots": ["absolute_path_required"]}


def test_other_errors_keep_their_class_code():
    assert envelope(NotFound())["code"] == "not_found"


def test_djangos_own_errors_answer_with_drfs_codes():
    assert envelope(Http404())["code"] == "not_found"
    assert envelope(DjangoPermissionDenied())["code"] == "permission_denied"


def test_a_field_error_is_its_first_code_wherever_it_is_nested():
    first = ErrorDetail("Use an absolute path.", code="absolute_path_required")
    second = ErrorDetail("Fill in this field.", code="required")

    assert error_code_of(
        ValidationError({"roots": {0: [first]}, "name": [second]})
    ) == ("absolute_path_required")


def test_a_validation_error_without_a_field_is_its_own_code():
    assert error_code_of(ValidationError("Not a key.", code="invalid_host_key")) == (
        "invalid_host_key"
    )


def test_a_validation_error_with_no_code_in_it_is_invalid():
    assert error_code_of(ValidationError({})) == "invalid"


def test_an_api_error_is_its_class_code():
    assert error_code_of(Unreachable()) == "ssh_unreachable"
    assert (
        error_code_of(AuthenticationFailed("Wrong password."))
        == "authentication_failed"
    )


def test_djangos_own_errors_are_drfs_codes():
    assert error_code_of(Http404()) == "not_found"
    assert error_code_of(DjangoPermissionDenied()) == "permission_denied"


def test_anything_else_is_unexpected():
    assert error_code_of(RuntimeError("boom")) == "unexpected"
    assert error_code_of(SystemExit(1)) == "unexpected"
