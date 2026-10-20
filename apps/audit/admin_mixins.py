"""Make Django admin edits show up in the audit log.

Add `AuditedAdmin` to a ModelAdmin (before admin.ModelAdmin) and every add,
change and delete made through it, including rows edited in inlines, is
recorded with before/after snapshots. Django admin already wraps each save in
a transaction, so the change and its audit event commit together.
"""

from .services import record, snapshot


def _before(obj):
    """The object as stored in the database, before this edit."""
    if obj.pk is None:
        return None
    original = type(obj)._default_manager.filter(pk=obj.pk).first()
    return snapshot(original)


class AuditedAdmin:
    def save_model(self, request, obj, form, change):
        # Remember the old values; the event is written in save_related, after
        # many-to-many fields (e.g. a user's groups, which are their roles) are saved.
        obj._audit_before = _before(obj) if change else None
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        obj = form.instance
        record(
            actor=request.user,
            action="admin.change" if change else "admin.add",
            target=obj,
            before=getattr(obj, "_audit_before", None),
            after=snapshot(obj),
        )

    def delete_model(self, request, obj):
        before = snapshot(obj)
        record(actor=request.user, action="admin.delete", target=obj, before=before)
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        for obj in queryset:
            record(actor=request.user, action="admin.delete", target=obj, before=snapshot(obj))
        super().delete_queryset(request, queryset)

    def save_formset(self, request, form, formset, change):
        """Inline rows (e.g. a dormitory's machines and time slots)."""
        befores = {obj.pk: _before(obj) for obj in formset.get_queryset()}
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            record(
                actor=request.user, action="admin.delete", target=obj, before=befores.get(obj.pk)
            )
            obj.delete()
        for obj in instances:
            adding = obj.pk is None
            obj.save()
            record(
                actor=request.user,
                action="admin.add" if adding else "admin.change",
                target=obj,
                before=None if adding else befores.get(obj.pk),
                after=snapshot(obj),
            )
        formset.save_m2m()
