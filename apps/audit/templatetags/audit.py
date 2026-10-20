from django import template

from apps.audit.actions import label

register = template.Library()


@register.filter
def action_label(code):
    """The human-readable name of an audit action code."""
    return label(code)
