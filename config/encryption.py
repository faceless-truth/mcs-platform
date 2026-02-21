"""
Field-level encryption utilities for sensitive data.

Uses Fernet symmetric encryption with a key derived from Django's SECRET_KEY.
All PII, OAuth tokens, and secrets are encrypted at rest in the database.
"""
import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models


def _get_fernet():
    """Derive a Fernet key from Django's SECRET_KEY."""
    key = hashlib.sha256(settings.SECRET_KEY.encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_value(value):
    """Encrypt a string value. Returns base64-encoded ciphertext."""
    if not value:
        return ""
    f = _get_fernet()
    return f.encrypt(value.encode()).decode()


def decrypt_value(value):
    """Decrypt a base64-encoded ciphertext. Returns plaintext string."""
    if not value:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(value.encode()).decode()
    except (InvalidToken, Exception):
        # If decryption fails, the value may be stored in plaintext (pre-migration).
        # Return as-is for backward compatibility during migration period.
        return value


class EncryptedCharField(models.CharField):
    """
    A CharField that transparently encrypts data at rest.
    Values are encrypted before saving and decrypted when reading.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value) if value else value

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value) if value else value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        # Report as our custom field for migrations
        path = "config.encryption.EncryptedCharField"
        return name, path, args, kwargs


class EncryptedTextField(models.TextField):
    """
    A TextField that transparently encrypts data at rest.
    Used for longer values like OAuth tokens.
    """

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return encrypt_value(value) if value else value

    def from_db_value(self, value, expression, connection):
        return decrypt_value(value) if value else value

    def deconstruct(self):
        name, path, args, kwargs = super().deconstruct()
        path = "config.encryption.EncryptedTextField"
        return name, path, args, kwargs
