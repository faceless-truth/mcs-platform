"""MCS Platform - Custom User Model with Role-Based Access Control"""
import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """
    Custom user model for MCS Platform.
    Extends Django AbstractUser with role-based access and client assignments.
    """

    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        SENIOR_ACCOUNTANT = "senior_accountant", "Senior Accountant"
        ACCOUNTANT = "accountant", "Accountant"
        READ_ONLY = "read_only", "Read Only"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.ACCOUNTANT,
    )
    phone = models.CharField(max_length=50, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["last_name", "first_name"]

    def __str__(self):
        name = self.get_full_name() or self.username
        return f"{name} ({self.get_role_display()})"

    @property
    def is_admin(self):
        return self.role == self.Role.ADMIN

    @property
    def is_senior(self):
        return self.role in (self.Role.ADMIN, self.Role.SENIOR_ACCOUNTANT)

    @property
    def can_finalise(self):
        return self.role in (self.Role.ADMIN, self.Role.SENIOR_ACCOUNTANT)

    @property
    def can_edit(self):
        return self.role in (
            self.Role.ADMIN,
            self.Role.SENIOR_ACCOUNTANT,
            self.Role.ACCOUNTANT,
        )
