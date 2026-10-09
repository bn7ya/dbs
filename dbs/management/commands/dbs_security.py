from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from dbs import audit
from dbs.conf import setting
from dbs.models import AnomalyEvent, AuditEvent, Lockout, SecurityPolicy, SessionEvent
from dbs.security import detector

ACTIONS = ("status", "unlock", "policy", "retrain", "reset-baseline", "events", "purge")

DEFAULT_RETENTION_DAYS = 90


class Command(BaseCommand):
    help = "Inspect and unlock the admin session guard."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=ACTIONS, nargs="?", default="status")
        parser.add_argument("username", nargs="?", help="Whose account to act on.")

    def handle(self, *args, **options):
        action = options["action"]
        handler = getattr(self, "_" + action.replace("-", "_"))
        handler(options)

    def _status(self, options):
        policy = SecurityPolicy.load()
        self.stdout.write(
            f"level                {policy.get_level_display()}"
            f"{'' if policy.configured else '  (setup not completed)'}"
        )
        self.stdout.write(f"warn at              {policy.warn_threshold}")
        self.stdout.write(f"log out at           {policy.logout_threshold}")
        self.stdout.write(f"learning period      {policy.learning_logins} events")
        self.stdout.write(f"enforcement          {setting('DBS_ANOMALY_ENFORCE', True)}")
        self.stdout.write(f"browser location     {setting('DBS_GEOLOCATION', False)}")
        self.stdout.write(f"recorded events      {SessionEvent.objects.count()}")
        self.stdout.write(f"anomalies            {AnomalyEvent.objects.count()}")
        locked = list(Lockout.objects.select_related("user"))
        if locked:
            names = ", ".join(entry.user.get_username() for entry in locked)
            self.stdout.write(self.style.WARNING(f"locked out           {names}"))
        else:
            self.stdout.write("locked out           nobody")

    def _unlock(self, options):
        user = self._user(options)
        removed, _ = Lockout.objects.filter(user=user).delete()
        detector.forget(user.pk)
        audit.record(
            "security.unlock",
            target=user.get_username(),
            detail="cleared from the command line",
        )
        if removed:
            self.stdout.write(self.style.SUCCESS(f"{user.get_username()} can log in again."))
        else:
            self.stdout.write(f"{user.get_username()} was not locked out.")

    def _policy(self, options):
        policy = SecurityPolicy.load()
        self.stdout.write(f"expected networks: {policy.expected_networks or 'none'}")
        self.stdout.write(f"trusted networks:  {policy.trusted_networks or 'none'}")
        self.stdout.write(f"settings trusted:  {setting('DBS_TRUSTED_NETWORKS', ()) or 'none'}")
        self.stdout.write(f"notify:            {policy.notify_emails or 'nobody'}")
        self.stdout.write(f"collect location:  {policy.collect_location}")

    def _retrain(self, options):
        from dbs.security import baseline

        detector.forget()
        baseline.reset()
        baseline.base_calibration()
        self.stdout.write(self.style.SUCCESS("Base and per-user models will refit."))

    def _reset_baseline(self, options):
        user = self._user(options)
        removed, _ = SessionEvent.objects.filter(user=user).delete()
        detector.forget(user.pk)
        self.stdout.write(f"Dropped {removed} recorded events for {user.get_username()}.")

    def _events(self, options):
        for event in AnomalyEvent.objects.select_related("user")[:20]:
            reasons = "; ".join(event.reasons) or "model score"
            self.stdout.write(
                f"{event.created_at:%Y-%m-%d %H:%M}  {event.user.get_username():<16} "
                f"{event.action_taken:<7} {event.score:.2f}  {reasons}"
            )

    def _purge(self, options):
        days = int(setting("DBS_SECURITY_RETENTION_DAYS", DEFAULT_RETENTION_DAYS))
        cutoff = timezone.now() - timedelta(days=days)
        events, _ = SessionEvent.objects.filter(created_at__lt=cutoff).delete()
        anomalies, _ = AnomalyEvent.objects.filter(created_at__lt=cutoff).delete()
        audit, _ = AuditEvent.objects.filter(created_at__lt=cutoff).delete()
        detector.forget()
        self.stdout.write(
            self.style.SUCCESS(
                f"Removed {events} events, {anomalies} anomalies and {audit} audit "
                f"rows older than {days} days."
            )
        )

    def _user(self, options):
        username = options.get("username")
        if not username:
            raise CommandError("Name the account, for example: dbs security unlock alice")
        model = get_user_model()
        try:
            return model._default_manager.get(**{model.USERNAME_FIELD: username})
        except model.DoesNotExist:
            raise CommandError(f"No account named {username!r}.") from None
