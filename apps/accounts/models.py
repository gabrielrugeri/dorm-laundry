from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Login account for residents, managers and admins.

    Kept as our own model from the first migration so we can add fields later
    without a painful migration. Profile data lives in `Resident`.
    """
