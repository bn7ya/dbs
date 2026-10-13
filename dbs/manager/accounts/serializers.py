from __future__ import annotations

from django.contrib.auth.validators import UnicodeUsernameValidator
from rest_framework import serializers

from dbs.manager.accounts.services.account_service import password_max_age
from dbs.manager.permissions import Role

PASSWORD = {"max_length": 128, "trim_whitespace": False, "write_only": True}
CODE = {"max_length": 32, "trim_whitespace": True, "write_only": True}


class SignInSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, trim_whitespace=True)
    password = serializers.CharField(**PASSWORD)


class SignInStepSerializer(serializers.Serializer):
    step = serializers.CharField(read_only=True)


class CodeSerializer(serializers.Serializer):
    code = serializers.CharField(required=False, allow_blank=True, **CODE)
    recovery_code = serializers.CharField(required=False, allow_blank=True, **CODE)

    def validate(self, attrs):
        if not attrs.get("code") and not attrs.get("recovery_code"):
            raise serializers.ValidationError(
                {"code": [serializers.ErrorDetail("Enter a code.", code="required")]}
            )
        return attrs


class EnrollmentSerializer(serializers.Serializer):
    secret = serializers.CharField(read_only=True)
    uri = serializers.CharField(read_only=True)
    issuer = serializers.CharField(read_only=True)
    username = serializers.CharField(read_only=True)


class EnrollSerializer(serializers.Serializer):
    code = serializers.CharField(**CODE)


class IdentitySerializer(serializers.Serializer):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)
    email = serializers.EmailField(read_only=True, allow_blank=True)
    first_name = serializers.CharField(read_only=True, allow_blank=True)
    last_name = serializers.CharField(read_only=True, allow_blank=True)
    is_staff = serializers.BooleanField(read_only=True)
    is_superuser = serializers.BooleanField(read_only=True)
    groups = serializers.ListField(child=serializers.CharField(), read_only=True)
    permissions = serializers.ListField(child=serializers.CharField(), read_only=True)
    role = serializers.CharField(read_only=True, allow_null=True)
    capabilities = serializers.ListField(child=serializers.CharField(), read_only=True)
    two_factor = serializers.BooleanField(read_only=True)
    recovery_codes_left = serializers.IntegerField(read_only=True)
    password_changed_at = serializers.DateTimeField(read_only=True)
    password_expires_at = serializers.DateTimeField(read_only=True)
    password_change_required = serializers.BooleanField(read_only=True)


class SignedInSerializer(serializers.Serializer):
    identity = IdentitySerializer(read_only=True)
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), read_only=True
    )


class SetupSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=200, trim_whitespace=True)
    username = serializers.CharField(
        max_length=150, trim_whitespace=True, validators=[UnicodeUsernameValidator()]
    )
    password = serializers.CharField(**PASSWORD)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(**PASSWORD)
    new_password = serializers.CharField(**PASSWORD)


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(**PASSWORD)


class RecoveryCodesSerializer(serializers.Serializer):
    recovery_codes = serializers.ListField(
        child=serializers.CharField(), read_only=True
    )


class AccountSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="pk", read_only=True)
    username = serializers.CharField(source="user.username", read_only=True)
    role = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(source="user.is_active", read_only=True)
    two_factor = serializers.BooleanField(source="has_two_factor", read_only=True)
    recovery_codes_left = serializers.IntegerField(read_only=True, default=0)
    password_changed_at = serializers.DateTimeField(read_only=True)
    password_expires_at = serializers.SerializerMethodField()
    password_change_required = serializers.BooleanField(read_only=True)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    date_joined = serializers.DateTimeField(source="user.date_joined", read_only=True)

    def get_password_expires_at(self, account) -> str:
        return serializers.DateTimeField().to_representation(
            account.password_changed_at + password_max_age()
        )


class AccountCreateSerializer(serializers.Serializer):
    username = serializers.CharField(
        max_length=150, trim_whitespace=True, validators=[UnicodeUsernameValidator()]
    )
    password = serializers.CharField(**PASSWORD)
    role = serializers.ChoiceField(choices=Role.ASSIGNABLE)


class AccountUpdateSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=Role.ASSIGNABLE, required=False)
    is_active = serializers.BooleanField(required=False)


class HandOverSerializer(serializers.Serializer):
    password = serializers.CharField(**PASSWORD)
    code = serializers.CharField(**CODE)
