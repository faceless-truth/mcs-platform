"""MCS Platform - Account Views with Invitation-Based Signup and TOTP 2FA"""
import io
import base64
import pyotp
import qrcode
from django.conf import settings
from django.contrib.auth import views as auth_views, login as auth_login
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.mail import send_mail
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags

from .models import User, Invitation
from .forms import (
    MCSLoginForm,
    TOTPVerifyForm,
    InvitationForm,
    InvitationSignupForm,
    UserCreateForm,
    UserEditForm,
)


# ---------------------------------------------------------------------------
# Login with 2FA
# ---------------------------------------------------------------------------

class MCSLoginView(auth_views.LoginView):
    """
    Step 1 of login: username + password.
    If the user has 2FA enabled, store their pk in session and redirect to TOTP verify.
    If not, log them in directly.
    """
    template_name = "accounts/login.html"
    authentication_form = MCSLoginForm
    redirect_authenticated_user = True

    def form_valid(self, form):
        user = form.get_user()
        if user.has_2fa:
            # Store user pk in session for 2FA step, don't log in yet
            self.request.session["2fa_user_pk"] = str(user.pk)
            self.request.session["2fa_next"] = self.request.POST.get("next", "")
            return redirect("accounts:totp_verify")
        # No 2FA — log in directly
        return super().form_valid(form)


def totp_verify_view(request):
    """
    Step 2 of login: TOTP verification.
    Only accessible if the user passed step 1 (username + password).
    """
    user_pk = request.session.get("2fa_user_pk")
    if not user_pk:
        return redirect("accounts:login")

    user = get_object_or_404(User, pk=user_pk)

    if request.method == "POST":
        form = TOTPVerifyForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["totp_code"]
            totp = pyotp.TOTP(user.totp_secret)
            if totp.verify(code, valid_window=1):
                # Code valid — complete login
                del request.session["2fa_user_pk"]
                next_url = request.session.pop("2fa_next", "")
                auth_login(request, user)
                return redirect(next_url or settings.LOGIN_REDIRECT_URL)
            else:
                form.add_error("totp_code", "Invalid code. Please try again.")
    else:
        form = TOTPVerifyForm()

    return render(request, "accounts/totp_verify.html", {
        "form": form,
        "user_name": user.get_full_name() or user.username,
    })


# ---------------------------------------------------------------------------
# Invitation Management (Admin only)
# ---------------------------------------------------------------------------

@login_required
def invitation_list(request):
    """List all invitations. Admin only."""
    if not request.user.is_admin:
        messages.error(request, "You do not have permission to manage invitations.")
        return redirect("core:dashboard")

    # Auto-expire old invitations
    Invitation.objects.filter(
        status=Invitation.Status.PENDING,
        expires_at__lte=timezone.now(),
    ).update(status=Invitation.Status.EXPIRED)

    invitations = Invitation.objects.all()
    return render(request, "accounts/invitation_list.html", {"invitations": invitations})


@login_required
def invitation_create(request):
    """Create and send a new invitation. Admin only."""
    if not request.user.is_admin:
        messages.error(request, "You do not have permission to send invitations.")
        return redirect("core:dashboard")

    # Check user limit (7 users max)
    active_users = User.objects.filter(is_active=True).count()
    pending_invitations = Invitation.objects.filter(status=Invitation.Status.PENDING).count()
    if active_users + pending_invitations >= 7:
        messages.error(request, "Maximum of 7 users reached. Deactivate a user or revoke a pending invitation first.")
        return redirect("accounts:invitation_list")

    if request.method == "POST":
        form = InvitationForm(request.POST)
        if form.is_valid():
            invitation = form.save(commit=False)
            invitation.invited_by = request.user
            invitation.save()

            # Send invitation email
            _send_invitation_email(request, invitation)

            messages.success(
                request,
                f"Invitation sent to {invitation.first_name} {invitation.last_name} ({invitation.email})."
            )
            return redirect("accounts:invitation_list")
    else:
        form = InvitationForm()

    return render(request, "accounts/invitation_form.html", {
        "form": form,
        "title": "Send Invitation",
    })


@login_required
def invitation_resend(request, pk):
    """Resend an invitation email. Admin only."""
    if not request.user.is_admin:
        messages.error(request, "You do not have permission.")
        return redirect("core:dashboard")

    invitation = get_object_or_404(Invitation, pk=pk)
    if not invitation.is_valid:
        # Reset expiry and status
        invitation.expires_at = timezone.now() + timezone.timedelta(days=7)
        invitation.status = Invitation.Status.PENDING
        invitation.save(update_fields=["expires_at", "status"])

    _send_invitation_email(request, invitation)
    messages.success(request, f"Invitation resent to {invitation.email}.")
    return redirect("accounts:invitation_list")


@login_required
def invitation_revoke(request, pk):
    """Revoke a pending invitation. Admin only."""
    if not request.user.is_admin:
        messages.error(request, "You do not have permission.")
        return redirect("core:dashboard")

    invitation = get_object_or_404(Invitation, pk=pk)
    if invitation.status == Invitation.Status.PENDING:
        invitation.status = Invitation.Status.REVOKED
        invitation.save(update_fields=["status"])
        messages.success(request, f"Invitation for {invitation.email} revoked.")
    return redirect("accounts:invitation_list")


def _send_invitation_email(request, invitation):
    """Send the invitation email with signup link."""
    signup_url = request.build_absolute_uri(f"/accounts/signup/{invitation.token}/")

    subject = "You're invited to StatementHub — MC & S Pty Ltd"
    html_message = render_to_string("accounts/email_invitation.html", {
        "invitation": invitation,
        "signup_url": signup_url,
    })
    plain_message = strip_tags(html_message)

    try:
        send_mail(
            subject=subject,
            message=plain_message,
            from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@statementhub.com.au"),
            recipient_list=[invitation.email],
            html_message=html_message,
            fail_silently=False,
        )
    except Exception as e:
        # Log but don't crash — the invitation link is still valid
        messages.warning(
            request,
            f"Invitation created but email could not be sent ({e}). "
            f"You can share the signup link manually: {signup_url}"
        )


# ---------------------------------------------------------------------------
# Invitation Signup (Public — no login required)
# ---------------------------------------------------------------------------

def invitation_signup_view(request, token):
    """
    Accept an invitation: set username, password, and configure TOTP 2FA.
    """
    invitation = get_object_or_404(Invitation, token=token)

    if not invitation.is_valid:
        return render(request, "accounts/invitation_invalid.html", {
            "invitation": invitation,
        })

    # Generate a TOTP secret for this signup session
    if "signup_totp_secret" not in request.session:
        request.session["signup_totp_secret"] = pyotp.random_base32()

    totp_secret = request.session["signup_totp_secret"]
    totp = pyotp.TOTP(totp_secret)
    provisioning_uri = totp.provisioning_uri(
        name=invitation.email,
        issuer_name="StatementHub",
    )

    # Generate QR code as base64 image
    qr_img = qrcode.make(provisioning_uri, box_size=6, border=2)
    buffer = io.BytesIO()
    qr_img.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    if request.method == "POST":
        form = InvitationSignupForm(request.POST)
        if form.is_valid():
            code = form.cleaned_data["totp_code"]
            if totp.verify(code, valid_window=1):
                # Create the user
                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    email=invitation.email,
                    password=form.cleaned_data["password1"],
                    first_name=invitation.first_name,
                    last_name=invitation.last_name,
                    role=invitation.role,
                    totp_secret=totp_secret,
                    totp_confirmed=True,
                )

                # Mark invitation as accepted
                invitation.status = Invitation.Status.ACCEPTED
                invitation.accepted_at = timezone.now()
                invitation.created_user = user
                invitation.save()

                # Clean up session
                del request.session["signup_totp_secret"]

                # Log the user in
                auth_login(request, user)
                messages.success(
                    request,
                    f"Welcome to StatementHub, {user.first_name}! Your account is set up with two-factor authentication."
                )
                return redirect(settings.LOGIN_REDIRECT_URL)
            else:
                form.add_error("totp_code", "Invalid authenticator code. Please scan the QR code and try again.")
    else:
        # Pre-fill suggested username from email
        suggested_username = invitation.email.split("@")[0].lower().replace(".", "_")
        form = InvitationSignupForm(initial={"username": suggested_username})

    return render(request, "accounts/invitation_signup.html", {
        "form": form,
        "invitation": invitation,
        "qr_base64": qr_base64,
        "totp_secret": totp_secret,
    })


# ---------------------------------------------------------------------------
# User Management (Admin only)
# ---------------------------------------------------------------------------

@login_required
def profile_view(request):
    return render(request, "accounts/profile.html")


@login_required
def user_list(request):
    if not request.user.is_admin:
        messages.error(request, "You do not have permission to manage users.")
        return redirect("core:dashboard")
    users = User.objects.all()
    invitations = Invitation.objects.filter(status=Invitation.Status.PENDING)
    return render(request, "accounts/user_list.html", {
        "users": users,
        "invitations": invitations,
    })


@login_required
def user_create(request):
    if not request.user.is_admin:
        messages.error(request, "You do not have permission to create users.")
        return redirect("core:dashboard")
    if request.method == "POST":
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            messages.success(request, f"User {user.username} created successfully.")
            return redirect("accounts:user_list")
    else:
        form = UserCreateForm()
    return render(request, "accounts/user_form.html", {"form": form, "title": "Create User"})


@login_required
def user_edit(request, pk):
    if not request.user.is_admin:
        messages.error(request, "You do not have permission to edit users.")
        return redirect("core:dashboard")
    user = get_object_or_404(User, pk=pk)
    if request.method == "POST":
        form = UserEditForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, f"User {user.username} updated successfully.")
            return redirect("accounts:user_list")
    else:
        form = UserEditForm(instance=user)
    return render(request, "accounts/user_form.html", {"form": form, "title": f"Edit User: {user.username}"})


@login_required
def user_reset_2fa(request, pk):
    """Reset a user's TOTP 2FA. Admin only. User will need to re-setup on next login."""
    if not request.user.is_admin:
        messages.error(request, "You do not have permission.")
        return redirect("core:dashboard")
    user = get_object_or_404(User, pk=pk)
    user.totp_secret = ""
    user.totp_confirmed = False
    user.save(update_fields=["totp_secret", "totp_confirmed"])
    messages.success(request, f"2FA reset for {user.get_full_name() or user.username}. They will need to set up 2FA again.")
    return redirect("accounts:user_list")
