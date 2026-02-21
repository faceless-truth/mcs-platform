"""MCS Platform - Account Forms"""
from django import forms
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.exceptions import ValidationError
from .models import User, Invitation


class MCSLoginForm(AuthenticationForm):
    username = forms.CharField(
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "placeholder": "Username",
            "autofocus": True,
        })
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Password",
        })
    )


class TOTPVerifyForm(forms.Form):
    """Form for entering TOTP code during login."""
    totp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg text-center",
            "placeholder": "000000",
            "autofocus": True,
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "style": "letter-spacing: 0.5em; font-size: 1.5rem;",
        }),
        label="Authenticator Code",
        help_text="Enter the 6-digit code from your authenticator app.",
    )


class InvitationForm(forms.ModelForm):
    """Form for creating a new invitation."""
    class Meta:
        model = Invitation
        fields = ("email", "first_name", "last_name", "role")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"

    def clean_email(self):
        email = self.cleaned_data["email"].lower().strip()
        if User.objects.filter(email=email).exists():
            raise ValidationError("A user with this email address already exists.")
        pending = Invitation.objects.filter(
            email=email,
            status=Invitation.Status.PENDING,
        ).exists()
        if pending:
            raise ValidationError("A pending invitation already exists for this email address.")
        return email


class InvitationSignupForm(forms.Form):
    """Form for accepting an invitation and setting up account."""
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={
            "class": "form-control",
            "autofocus": True,
        }),
        help_text="Choose a username for logging in.",
    )
    password1 = forms.CharField(
        label="Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
        }),
        help_text="Must be at least 12 characters.",
    )
    password2 = forms.CharField(
        label="Confirm Password",
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
        }),
    )
    totp_code = forms.CharField(
        max_length=6,
        min_length=6,
        widget=forms.TextInput(attrs={
            "class": "form-control form-control-lg text-center",
            "placeholder": "000000",
            "autocomplete": "one-time-code",
            "inputmode": "numeric",
            "pattern": "[0-9]*",
            "style": "letter-spacing: 0.5em; font-size: 1.5rem;",
        }),
        label="Authenticator Code",
        help_text="Scan the QR code above with your authenticator app, then enter the 6-digit code.",
    )

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username=username).exists():
            raise ValidationError("This username is already taken.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password1")
        p2 = cleaned_data.get("password2")
        if p1 and p2 and p1 != p2:
            self.add_error("password2", "Passwords do not match.")
        if p1 and len(p1) < 12:
            self.add_error("password1", "Password must be at least 12 characters.")
        if p1:
            from django.contrib.auth.password_validation import validate_password
            from django.core.exceptions import ValidationError as DjangoValidationError
            try:
                validate_password(p1)
            except DjangoValidationError as e:
                for error in e.messages:
                    self.add_error("password1", error)
        return cleaned_data


class UserCreateForm(UserCreationForm):
    class Meta:
        model = User
        fields = ("username", "email", "first_name", "last_name", "role", "phone")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs["class"] = "form-control"


class UserEditForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ("email", "first_name", "last_name", "role", "phone", "is_active")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs["class"] = "form-check-input"
            else:
                field.widget.attrs["class"] = "form-control"
