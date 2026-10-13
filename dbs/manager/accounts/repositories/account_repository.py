from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q, QuerySet
from django.utils import timezone

from dbs.manager.accounts.models import Account, RecoveryCode
from dbs.manager.permissions import Role


class AccountRepository:
    def of(self, user: Any) -> Account:
        account, _ = Account.objects.select_related("user").get_or_create(
            user=user, defaults={"role": Role.VIEWER}
        )
        return account

    def find(self, user_id: Any) -> Account | None:
        return Account.objects.select_related("user").filter(user_id=user_id).first()

    def find_by_username(self, username: str) -> Account | None:
        return (
            Account.objects.select_related("user")
            .filter(user__username__iexact=username)
            .first()
        )

    def master(self) -> Account | None:
        return Account.objects.select_related("user").filter(role=Role.MASTER).first()

    def adopt_orphans(self) -> None:
        orphans = get_user_model().objects.filter(manager_account__isnull=True)
        Account.objects.bulk_create(
            [Account(user=user, role=Role.VIEWER) for user in orphans],
            ignore_conflicts=True,
        )

    def listed(self) -> QuerySet[Account]:
        return (
            Account.objects.select_related("user")
            .annotate(
                recovery_codes_left=Count(
                    "recovery_codes", filter=Q(recovery_codes__used_at__isnull=True)
                )
            )
            .order_by("user__username")
        )

    def update(self, account: Account, **fields: Any) -> Account:
        for name, value in fields.items():
            setattr(account, name, value)
        account.save(update_fields=list(fields))
        return account

    def claim_step(self, account: Account, step: int) -> bool:
        claimed = (
            Account.objects.filter(pk=account.pk)
            .filter(Q(totp_last_step__isnull=True) | Q(totp_last_step__lt=step))
            .update(totp_last_step=step)
        )
        if claimed:
            account.totp_last_step = step
        return claimed == 1

    def replace_recovery_codes(self, account: Account, digests: list[str]) -> None:
        with transaction.atomic():
            RecoveryCode.objects.filter(account=account).delete()
            RecoveryCode.objects.bulk_create(
                [RecoveryCode(account=account, digest=digest) for digest in digests]
            )

    def use_recovery_code(self, account: Account, digest: str) -> bool:
        return (
            RecoveryCode.objects.filter(
                account=account, digest=digest, used_at__isnull=True
            ).update(used_at=timezone.now())
            == 1
        )

    def recovery_codes_left(self, account: Account) -> int:
        return RecoveryCode.objects.filter(
            account=account, used_at__isnull=True
        ).count()

    def forget_two_factor(self, account: Account) -> Account:
        with transaction.atomic():
            RecoveryCode.objects.filter(account=account).delete()
            return self.update(
                account,
                totp_secret_sealed=None,
                totp_enrolled_at=None,
                totp_last_step=None,
            )

    def hand_over(self, current: Account, successor: Account) -> None:
        with transaction.atomic():
            self.update(current, role=Role.ADMIN)
            self.update(successor, role=Role.MASTER)
