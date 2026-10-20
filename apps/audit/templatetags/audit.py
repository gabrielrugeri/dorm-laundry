from django import template

from apps.audit.actions import label

register = template.Library()


@register.filter
def action_label(code):
    """The human-readable name of an audit action code."""
    return label(code)


@register.filter
def plain_changes(event):
    """The event's changes as (label, old, new) in plain words."""
    from apps.audit.display import describe_changes

    return describe_changes(event)
