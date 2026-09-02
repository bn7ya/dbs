from __future__ import annotations

from django import forms

from .models import AuthMethod, BackupTarget, SecurityLevel

KEEP_HELP = "Leave empty to keep the stored value."


class BackupTargetForm(forms.ModelForm):
    password = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), help_text=KEEP_HELP
    )
    key_material = forms.CharField(
        required=False, widget=forms.Textarea(attrs={"rows": 4}), help_text=KEEP_HELP
    )
    key_passphrase = forms.CharField(
        required=False, widget=forms.PasswordInput(render_value=False), help_text=KEEP_HELP
    )

    class Meta:
        model = BackupTarget
        fields = (
            "name",
            "host",
            "port",
            "username",
            "remote_dir",
            "auth_method",
            "key_filename",
            "known_hosts",
            "auto_add_host_key",
            "connect_timeout",
            "is_default",
            "notes",
        )

    def clean(self):
        data = super().clean()
        method = data.get("auth_method")
        if method == AuthMethod.KEY_FILE and not data.get("key_filename"):
            self.add_error("key_filename", "A key file path is required for this method.")
        if method == AuthMethod.PASSWORD and not data.get("password") and not self._stored(
            "secret_password"
        ):
            self.add_error("password", "A password is required for this method.")
        if method == AuthMethod.KEY_MATERIAL and not data.get("key_material") and not self._stored(
            "secret_key_material"
        ):
            self.add_error("key_material", "Paste the private key for this method.")
        if not data.get("known_hosts") and not data.get("auto_add_host_key"):
            self.add_error(
                "known_hosts",
                "Give a known_hosts file, or tick auto-add to accept an unknown host key.",
            )
        return data

    def _stored(self, field) -> bool:
        return bool(self.instance.pk and getattr(self.instance, field))

    def save(self, commit=True):
        target = super().save(commit=False)
        for form_field, model_field in (
            ("password", "secret_password"),
            ("key_material", "secret_key_material"),
            ("key_passphrase", "secret_key_passphrase"),
        ):
            given = self.cleaned_data.get(form_field)
            if given:
                setattr(target, model_field, given)
        if commit:
            target.save()
        return target


class CreateBackupForm(forms.Form):
    database = forms.CharField(initial="default")
    destination = forms.ChoiceField(choices=(), required=False)
    passphrase = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave empty to use the passphrase derived from SECRET_KEY.",
    )
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        choices = [("", "Download to my browser")]
        choices += [
            (str(target.pk), f"Push to {target.name}")
            for target in BackupTarget.objects.all()
        ]
        self.fields["destination"].choices = choices


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
