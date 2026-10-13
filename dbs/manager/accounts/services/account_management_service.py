from __future__ import annotations

from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import QuerySet
from rest_framework.exceptions import ErrorDetail, ValidationError

from dbs.manager.accounts.exceptions import (
    AccountInactive,
    AccountNotFound,
    InvalidCode,
    MasterProtected,
    OwnAccount,
)
from dbs.manager.accounts.models import Account
from dbs.manager.accounts.repositories import AccountRepository, UserRepository
from dbs.manager.accounts.services.account_service import (
    AccountService,
    password_errors,
)
from dbs.manager.accounts.services.two_factor_service import TwoFactorService
from dbs.manager.activity.services import ActivityService
from dbs.manager.permissions import Capability, Role, requires

NAME_TAKEN = "An account with this name already exists."
ROLE_UNKNOWN = "Choose admin, operator or viewer."


class Action:
    CREATE = "account.create"
    ROLE = "account.role"
    DISABLE = "account.disable"
    ENABLE = "account.enable"
    TWO_FACTOR_RESET = "account.two_factor_reset"
    PASSWORD_EXPIRE = "account.password_expire"
    MASTER = "account.master"


class AccountManagementService:
    def __init__(self, user: Any) -> None:
        self.user = user
        self.users = UserRepository()
        self.accounts = AccountRepository()
        self.activity = ActivityService(user)

    @requires(Capability.ACCOUNTS_MANAGE)
    def list(self) -> QuerySet[Account]:
        self.accounts.adopt_orphans()
        return self.accounts.listed()

    @requires(Capability.ACCOUNTS_MANAGE)
    def get(self, account_id: Any) -> Account:
        found = self.accounts.listed().filter(pk=account_id).first()
        if found is None:
            raise AccountNotFound()
        return found

    @requires(Capability.ACCOUNTS_MANAGE)
    def create(self, *, username: str, password: str, role: str) -> Account:
        first = not self.users.any_exist()
        errors: dict[str, list[ErrorDetail]] = {}
        if not first and role not in Role.ASSIGNABLE:
            errors["role"] = [ErrorDetail(ROLE_UNKNOWN, code="invalid_choice")]
        if self.users.find_by_username(username) is not None:
            errors["username"] = [ErrorDetail(NAME_TAKEN, code="name_taken")]
        try:
            validate_password(password, user=self.users.unsaved(username))
        except DjangoValidationError as exc:
            errors["password"] = password_errors(exc)
        if errors:
            raise ValidationError(errors)
        with transaction.atomic():
            if first:
                user = self.users.create_superuser(username=username, password=password)
            else:
                user = self.users.create(
                    username=username,
                    password=password,
                    role=role,
                    password_change_required=True,
                )
            account = self.accounts.of(user)
            self.activity.record(
                Action.CREATE, target=username, detail={"role": account.role}
            )
        return account

    @requires(Capability.ACCOUNTS_MANAGE)
    def set_role(self, account_id: Any, role: str) -> Account:
        account = self._other(account_id)
        if role not in Role.ASSIGNABLE:
            raise ValidationError(
                {"role": [ErrorDetail(ROLE_UNKNOWN, code="invalid_choice")]}
            )
        if account.role == role:
            return account
        with transaction.atomic():
            self.accounts.update(account, role=role)
            self.activity.record(
                Action.ROLE, target=account.user.get_username(), detail={"role": role}
            )
        return account

    @requires(Capability.ACCOUNTS_MANAGE)
    def set_active(self, account_id: Any, active: bool) -> Account:
        account = self._other(account_id)
        if account.user.is_active == active:
            return account
        with transaction.atomic():
            if active:
                self.users.activate(account.user)
            else:
                self.users.deactivate(account.user)
            self.activity.record(
                Action.ENABLE if active else Action.DISABLE,
                target=account.user.get_username(),
            )
        return account

    @requires(Capability.ACCOUNTS_MANAGE)
    def reset_two_factor(self, account_id: Any) -> Account:
        account = self._found(account_id)
        if self.user is not None and account.pk == self.user.pk:
            raise OwnAccount()
        with transaction.atomic():
            TwoFactorService(account).reset()
            self.activity.record(
                Action.TWO_FACTOR_RESET, target=account.user.get_username()
            )
        return account

    @requires(Capability.ACCOUNTS_MANAGE)
    def require_password_change(self, account_id: Any) -> Account:
        account = self._other(account_id)
        with transaction.atomic():
            self.accounts.update(account, password_change_required=True)
            self.activity.record(
                Action.PASSWORD_EXPIRE, target=account.user.get_username()
            )
        return account

    @requires(Capability.ACCOUNTS_MANAGE)
    def hand_over(self, account_id: Any, password: str, code: str) -> Account:
        current = self.accounts.of(self.user)
        successor = self._other(account_id)
        AccountService(self.user).confirm_password(password)
        if not TwoFactorService(current).verify(code):
            raise InvalidCode()
        return self._hand_over(current, successor)

    @requires(Capability.ACCOUNTS_MANAGE)
    def make_master(self, account_id: Any) -> Account:
        successor = self._found(account_id)
        current = self.accounts.master()
        if current is not None and current.pk == successor.pk:
            return successor
        if not successor.user.is_active:
            raise AccountInactive()
        if current is None:
            with transaction.atomic():
                self.accounts.update(successor, role=Role.MASTER)
                self.activity.record(
                    Action.MASTER, target=successor.user.get_username()
                )
            return successor
        return self._hand_over(current, successor)

    def _hand_over(self, current: Account, successor: Account) -> Account:
        if not successor.user.is_active:
            raise AccountInactive()
        with transaction.atomic():
            self.accounts.hand_over(current, successor)
            self.activity.record(
                Action.MASTER,
                target=successor.user.get_username(),
                detail={"from": current.user.get_username()},
            )
        return self.accounts.listed().get(pk=successor.pk)

    def _found(self, account_id: Any) -> Account:
        account = self.accounts.find(account_id)
        if account is None:
            raise AccountNotFound()
        return account

    def _other(self, account_id: Any) -> Account:
        account = self._found(account_id)
        if account.is_master:
            raise MasterProtected()
        if self.user is not None and account.pk == self.user.pk:
            raise OwnAccount()
        return account
