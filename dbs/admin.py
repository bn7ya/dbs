from __future__ import annotations

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import views
from .forms import BackupScheduleForm
from .models import (
    AnomalyEvent,
    AuditEvent,
    BackupRecord,
    BackupSchedule,
    KnownLocation,
    Panel,
    SecurityPolicy,
)


class SuperuserOnlyAdmin(admin.ModelAdmin):
    audit_as = ""

    def audit_target(self, obj):
        return str(obj)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if self.audit_as:
            fields = sorted(form.changed_data)
            views._audit(
                request,
                f"{self.audit_as}.{'update' if change else 'add'}",
                target=self.audit_target(obj),
                detail=", ".join(fields),
                data={"fields": fields},
            )

    def delete_model(self, request, obj):
        target = self.audit_target(obj)
        super().delete_model(request, obj)
        if self.audit_as:
            views._audit(request, f"{self.audit_as}.delete", target=target)

    def delete_queryset(self, request, queryset):
        targets = [self.audit_target(obj) for obj in queryset]
        super().delete_queryset(request, queryset)
        if self.audit_as:
            for target in targets:
                views._audit(request, f"{self.audit_as}.delete", target=target)

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


@admin.register(BackupRecord)
class BackupRecordAdmin(SuperuserOnlyAdmin):
    audit_as = "backup.record"
    list_display = ("filename", "created_at", "size_bytes", "database", "created_by", "restore_link")
    list_filter = ("database",)
    search_fields = ("filename", "sha256")
    readonly_fields = (
        "filename",
        "location",
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
                "jobs/<int:pk>/",
                self.admin_site.admin_view(views.job),
                name="dbs_job",
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
        ("Last run", {"fields": readonly_fields}),
    )

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_permission(request):
            raise PermissionDenied
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
                "database": obj.database,
                "fields": sorted(form.changed_data),
            },
        )


@admin.register(SecurityPolicy)
class SecurityPolicyAdmin(SuperuserOnlyAdmin):
    audit_as = "security.policy"
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
    list_display = ("created_at", "who", "action", "target_name", "status", "duration")
    list_filter = ("action", "status")
    search_fields = ("action", "target_name", "detail")
    list_select_related = ("actor",)

    @admin.display(description="by")
    def who(self, obj):
        return obj.actor_name or "-"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(KnownLocation)
class KnownLocationAdmin(SuperuserOnlyAdmin):
    audit_as = "security.location"
    list_display = ("user", "label", "latitude", "longitude", "radius_km")

    def audit_target(self, obj):
        return f"{obj.user.get_username()}: {obj.label}"


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
                "connection/",
                self.admin_site.admin_view(views.connection),
                name="dbs_connection",
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
