from __future__ import annotations

from django.contrib import admin
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import views
from .forms import BackupScheduleForm, BackupTargetForm
from .models import (
    AnomalyEvent,
    AuditEvent,
    BackupRecord,
    BackupSchedule,
    BackupTarget,
    KnownLocation,
    Panel,
    SecurityPolicy,
)


class SuperuserOnlyAdmin(admin.ModelAdmin):
    def has_module_permission(self, request):
        return self._allowed(request)

    def has_view_permission(self, request, obj=None):
        return self._allowed(request)

    def has_add_permission(self, request):
        return self._allowed(request)

    def has_change_permission(self, request, obj=None):
        return self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return self._allowed(request)

    def _allowed(self, request):
        user = getattr(request, "user", None)
        return bool(user and user.is_active and user.is_superuser)


@admin.register(BackupTarget)
class BackupTargetAdmin(SuperuserOnlyAdmin):
    form = BackupTargetForm
    list_display = ("name", "host", "username", "auth_method", "is_default", "console_link")
    search_fields = ("name", "host", "username")

    def get_urls(self):
        return [
            path(
                "<int:pk>/console/",
                self.admin_site.admin_view(views.console),
                name="dbs_console",
            ),
        ] + super().get_urls()

    @admin.display(description="console")
    def console_link(self, obj):
        return format_html('<a href="{}/console/">open</a>', obj.pk)


@admin.register(BackupRecord)
class BackupRecordAdmin(SuperuserOnlyAdmin):
    list_display = ("filename", "created_at", "size_bytes", "target", "created_by", "restore_link")
    list_filter = ("target", "database")
    search_fields = ("filename", "sha256")
    readonly_fields = (
        "filename",
        "location",
        "target",
        "database",
        "created_by",
        "sha256",
        "size_bytes",
        "created_at",
    )

    def get_urls(self):
        return [
            path(
                "create/",
                self.admin_site.admin_view(views.create_backup_view),
                name="dbs_backup_create",
            ),
            path(
                "restore/",
                self.admin_site.admin_view(views.restore_view),
                name="dbs_backup_restore",
            ),
            path(
                "<int:pk>/download/",
                self.admin_site.admin_view(views.download),
                name="dbs_backup_download",
            ),
            path(
                "<int:pk>/restore/",
                self.admin_site.admin_view(views.restore_record),
                name="dbs_backup_restore_record",
            ),
        ] + super().get_urls()

    def has_add_permission(self, request):
        return False

    @admin.display(description="restore")
    def restore_link(self, obj):
        if obj.local_path() is None:
            return ""
        return format_html('<a href="{}/restore/">restore</a>', obj.pk)


@admin.register(BackupSchedule)
class BackupScheduleAdmin(SuperuserOnlyAdmin):
    form = BackupScheduleForm
    readonly_fields = ("next_run_at", "last_run_at", "last_status", "last_error", "updated_by")
    fieldsets = (
        (None, {"fields": ("enabled", "interval", "keep", "database")}),
        ("Off-site copy", {"fields": ("push_target", "keep_remote")}),
        ("Last run", {"fields": readonly_fields}),
    )

    def changelist_view(self, request, extra_context=None):
        schedule = BackupSchedule.load()
        return redirect(reverse("admin:dbs_backupschedule_change", args=[schedule.pk]))

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        if "interval" in form.changed_data or "enabled" in form.changed_data:
            obj.next_run_at = None
        super().save_model(request, obj, form, change)
        views._audit(
            request,
            "schedule.update",
            target=str(obj),
            data={
                "enabled": obj.enabled,
                "interval": obj.interval,
                "keep": obj.keep,
                "keep_remote": obj.keep_remote,
            },
        )


@admin.register(SecurityPolicy)
class SecurityPolicyAdmin(SuperuserOnlyAdmin):
    list_display = ("level", "configured", "warn_threshold", "logout_threshold", "updated_at")

    def has_add_permission(self, request):
        return not SecurityPolicy.objects.exists() and self._allowed(request)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AnomalyEvent)
class AnomalyEventAdmin(SuperuserOnlyAdmin):
    list_display = ("created_at", "user", "score", "action_taken", "remote_addr", "resolved")
    list_filter = ("action_taken", "resolved")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AuditEvent)
class AuditEventAdmin(SuperuserOnlyAdmin):
    list_display = ("created_at", "actor", "action", "target_name", "status", "duration")
    list_filter = ("action", "status")
    search_fields = ("action", "target_name", "detail")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KnownLocation)
class KnownLocationAdmin(SuperuserOnlyAdmin):
    list_display = ("user", "label", "latitude", "longitude", "radius_km")


@admin.register(Panel)
class PanelAdmin(SuperuserOnlyAdmin):
    def has_module_permission(self, request):
        return False

    def get_urls(self):
        return [
            path(
                "setup/",
                self.admin_site.admin_view(views.setup),
                name="dbs_setup",
            ),
            path(
                "guard/",
                self.admin_site.admin_view(views.guard_check),
                name="dbs_guard",
            ),
            path(
                "security/",
                self.admin_site.admin_view(views.security_overview),
                name="dbs_security",
            ),
            path(
                "health/",
                self.admin_site.admin_view(views.health),
                name="dbs_health",
            ),
            path(
                "wiki/",
                self.admin_site.admin_view(views.wiki),
                name="dbs_wiki_index",
            ),
            path(
                "wiki/<slug:page>/",
                self.admin_site.admin_view(views.wiki),
                name="dbs_wiki",
            ),
        ]
