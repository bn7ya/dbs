from __future__ import annotations

import ipaddress
import os

from django import forms
from django.core.validators import validate_email
from django.db import connections

from .exceptions import ConfigurationError
from .models import BackupSchedule, SecurityLevel
from .retention import MAXIMUM_KEEP
from .security.guard import MINIMUM_PREFIX


def clean_networks(raw, *, field):
    cleaned = []
    for line in (raw or "").replace(",", "\n").split("\n"):
        candidate = line.strip()
        if not candidate:
            continue
        try:
            network = ipaddress.ip_network(candidate, strict=False)
        except ValueError:
            raise forms.ValidationError(
                f"{candidate!r} is not a network. Write one CIDR per line, "
                "for example 203.0.113.0/24."
            ) from None
        if field == "trusted" and network.prefixlen < MINIMUM_PREFIX[network.version]:
            raise forms.ValidationError(
                f"{candidate} covers too much of the internet to be trusted. "
                f"Use a prefix of /{MINIMUM_PREFIX[network.version]} or narrower."
            )
        cleaned.append(str(network))
    return "\n".join(cleaned)


class CreateBackupForm(forms.Form):
    database = forms.ChoiceField(choices=(), initial="default")
    passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave empty to use the passphrase derived from SECRET_KEY.",
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["database"].choices = [
            (alias, alias) for alias in sorted(connections)
        ]


class RestoreUploadForm(forms.Form):
    backup = forms.FileField(label="Backup file (.dbs)")
    passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave empty to use the passphrase derived from SECRET_KEY.",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        label="Dry run",
        help_text="Rehearse the restore in a transaction that is rolled back.",
    )
    flush = forms.BooleanField(
        required=False,
        label="Replace instead of merge",
        help_text="Delete existing rows of the backed-up models first.",
    )


class RestoreRecordForm(forms.Form):
    passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave empty to use the passphrase derived from SECRET_KEY.",
    )
    dry_run = forms.BooleanField(
        required=False,
        initial=True,
        label="Dry run",
        help_text="Rehearse the restore in a transaction that is rolled back.",
    )
    flush = forms.BooleanField(
        required=False,
        label="Replace instead of merge",
        help_text="Delete existing rows of the backed-up models first.",
    )
    confirm = forms.CharField(
        required=False,
        label="Type the file name to restore for real",
    )

    def __init__(self, *args, filename="", **kwargs):
        super().__init__(*args, **kwargs)
        self.filename = filename

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("dry_run") and cleaned.get("confirm", "").strip() != self.filename:
            raise forms.ValidationError(
                f"Type {self.filename} to restore for real, or tick Dry run."
            )
        return cleaned


class SetupForm(forms.Form):
    level = forms.ChoiceField(
        choices=SecurityLevel.choices,
        initial=SecurityLevel.BALANCED,
        widget=forms.RadioSelect,
        label="How strict should the guard be?",
    )
    expected_networks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Networks you log in from",
        help_text="One CIDR per line, for example 203.0.113.0/24.",
    )
    trusted_networks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        label="Networks that are never enforced against",
        help_text="Your office or VPN range. Requests from here are scored but never logged out.",
    )
    collect_location = forms.BooleanField(
        required=False,
        label="Use my browser location as a signal",
        help_text="Adds distance and impossible-travel detection. A location can only raise a risk score, never lower one.",
    )
    latitude = forms.FloatField(required=False, widget=forms.HiddenInput)
    longitude = forms.FloatField(required=False, widget=forms.HiddenInput)
    notify_emails = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        label="Notify these addresses",
    )

    def clean_expected_networks(self):
        return clean_networks(self.cleaned_data["expected_networks"], field="expected")

    def clean_trusted_networks(self):
        return clean_networks(self.cleaned_data["trusted_networks"], field="trusted")

    def clean_notify_emails(self):
        addresses = []
        raw = self.cleaned_data["notify_emails"]
        for line in (raw or "").replace(",", "\n").split("\n"):
            candidate = line.strip()
            if not candidate:
                continue
            validate_email(candidate)
            addresses.append(candidate)
        return "\n".join(addresses)


class BackupScheduleForm(forms.ModelForm):
    class Meta:
        model = BackupSchedule
        fields = ("enabled", "interval", "keep", "database")
        help_texts = {
            "interval": "How often to back up: 30m, 6h, 1d.",
            "keep": f"How many backups to keep in DBS_BACKUP_DIR, at most {MAXIMUM_KEEP}.",
        }

    def clean_interval(self):
        from .scheduling import parse_interval
        from .schedule_runner import MINIMUM_INTERVAL_SECONDS

        interval = self.cleaned_data["interval"].strip().lower()
        try:
            seconds = parse_interval(interval)
        except ConfigurationError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if seconds < MINIMUM_INTERVAL_SECONDS:
            raise forms.ValidationError("Back up at most every 5 minutes.")
        return interval

    def clean_keep(self):
        keep = self.cleaned_data["keep"]
        if keep < 1:
            raise forms.ValidationError("Keep at least one backup.")
        if keep > MAXIMUM_KEEP:
            raise forms.ValidationError(
                f"The server keeps at most {MAXIMUM_KEEP} backups in DBS_BACKUP_DIR."
            )
        return keep

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("enabled"):
            from .schedule_runner import backup_directory, unattended_passphrase

            directory = backup_directory()
            if not directory:
                raise forms.ValidationError(
                    "Set DBS_BACKUP_DIR in your settings before turning the schedule on."
                )
            if os.path.isdir(directory) and not os.access(directory, os.W_OK):
                raise forms.ValidationError(f"{directory} is not writable by this process.")
            if unattended_passphrase() is None:
                raise forms.ValidationError(
                    "Scheduled backups need SECRET_KEY or DBS_PASSPHRASE to encrypt with."
                )
        return cleaned
