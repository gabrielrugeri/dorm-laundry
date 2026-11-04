"""Create and switch off dormitory staff accounts, for superusers on the server.

    python manage.py dormitory_admin create --dormitory demo --username olga \\
        --role admin --name "Ольга Комендантова"
    python manage.py dormitory_admin link --username olga
    python manage.py dormitory_admin deactivate --username olga --reason "Left the job"

`create` and `link` print a one-time link where the person chooses their
password (valid for 7 days, until it is used). Nobody, not even the
superuser, ever knows the password. Send the link privately to that person.
`deactivate` switches the account off and logs it out everywhere; its
history stays. Every action is recorded in the change history.

The link needs the app's public address: PUBLIC_BASE_URL (on Railway, the
generated domain by default) or --base-url. See docs/SUPERUSER.md.
"""

from django.conf import settings
from django.contrib.auth.models import Group
from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts import roles
from apps.accounts.activation import staff_password_url
from apps.accounts.decorators import is_staff_member
from apps.accounts.models import StaffProfile, User
from apps.audit.services import record
from apps.dorms.models import Dormitory

ROLES = {"admin": roles.ADMIN, "manager": roles.MANAGER}


class Command(BaseCommand):
    help = "Create, give a password link to, or switch off a dormitory admin or manager."

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", required=True)
        create = actions.add_parser("create", help="Create an account and print its link.")
        create.add_argument("--dormitory", required=True, help="The dormitory's slug.")
        create.add_argument("--username", required=True)
        create.add_argument("--role", choices=sorted(ROLES), default="admin")
        create.add_argument("--name", default="", help="Full name, shown in the header.")
        create.add_argument("--base-url", default="")
        link = actions.add_parser("link", help="Print a new password link.")
        link.add_argument("--username", required=True)
        link.add_argument("--base-url", default="")
        deactivate = actions.add_parser("deactivate", help="Switch the account off.")
        deactivate.add_argument("--username", required=True)
        deactivate.add_argument("--reason", required=True)

    def handle(self, *args, **options):
        getattr(self, f"_{options['action']}")(options)

    # --- Actions ---------------------------------------------------------------------

    def _create(self, options):
        base_url = self._base_url(options)
        try:
            dormitory = Dormitory.objects.get(slug=options["dormitory"])
        except Dormitory.DoesNotExist:
            raise CommandError(f"No dormitory with the slug {options['dormitory']!r}.") from None
        username = options["username"].strip()
        if not username or User.objects.filter(username__iexact=username).exists():
            raise CommandError(f"The username {username!r} is empty or already taken.")
        first, _, last = options["name"].strip().partition(" ")
        with transaction.atomic():
            user = User(username=username, first_name=first, last_name=last)
            user.set_unusable_password()  # chosen by the person, with the link
            user.save()
            user.groups.add(Group.objects.get(name=ROLES[options["role"]]))
            StaffProfile.objects.create(user=user, dormitory=dormitory)
            record(
                actor=None,
                action="staff.create",
                target=user,
                after={"role": options["role"], "dormitory": dormitory.name},
                reason="manage.py dormitory_admin create",
                dormitory=dormitory,
            )
        self.stdout.write(
            self.style.SUCCESS(f"Created {options['role']} {username!r} for {dormitory.name}.")
        )
        self._print_link(user, base_url)

    def _link(self, options):
        base_url = self._base_url(options)
        user = self._staff(options["username"])
        if not user.is_active:
            raise CommandError("This account is switched off. Nothing to do.")
        record(
            actor=None,
            action="staff.password_link",
            target=user,
            reason="manage.py dormitory_admin link",
            dormitory=user.staff_profile.dormitory,
        )
        self._print_link(user, base_url)

    def _deactivate(self, options):
        user = self._staff(options["username"])
        reason = options["reason"].strip()
        if not reason:
            raise CommandError("Give a reason (--reason).")
        with transaction.atomic():
            user.is_active = False
            user.save(update_fields=["is_active"])
            ended = _end_sessions(user)
            record(
                actor=None,
                action="staff.deactivate",
                target=user,
                reason=reason,
                dormitory=user.staff_profile.dormitory,
            )
        self.stdout.write(
            self.style.SUCCESS(f"Switched off {user.username!r}; {ended} login(s) ended.")
        )

    # --- Helpers ---------------------------------------------------------------------

    def _base_url(self, options):
        base_url = (options.get("base_url") or settings.PUBLIC_BASE_URL).strip()
        if not base_url.startswith(("https://", "http://")):
            raise CommandError(
                "Set PUBLIC_BASE_URL (e.g. https://laundry.example.ru) or pass --base-url."
            )
        return base_url

    def _staff(self, username):
        user = User.objects.filter(username__iexact=username.strip()).first()
        if user is None or not is_staff_member(user) or not hasattr(user, "staff_profile"):
            raise CommandError(f"No dormitory admin or manager called {username!r}.")
        if user.is_superuser:
            raise CommandError("This is a superuser: manage it with Django's own commands.")
        return user

    def _print_link(self, user, base_url):
        self.stdout.write(
            "One-time link to choose the password (valid for "
            f"{settings.PASSWORD_RESET_TIMEOUT // 86400} days). Send it privately:"
        )
        self.stdout.write(staff_password_url(base_url, user))


def _end_sessions(user):
    """Log `user` out on every device. Sessions are few; read each one."""
    ended = 0
    for session in Session.objects.all().iterator():
        if session.get_decoded().get("_auth_user_id") == str(user.pk):
            session.delete()
            ended += 1
    return ended
