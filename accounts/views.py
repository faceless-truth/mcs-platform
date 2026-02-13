"""MCS Platform - Account Views"""
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from .models import User
from .forms import MCSLoginForm, UserCreateForm, UserEditForm


class MCSLoginView(auth_views.LoginView):
    template_name = "accounts/login.html"
    authentication_form = MCSLoginForm
    redirect_authenticated_user = True


@login_required
def profile_view(request):
    return render(request, "accounts/profile.html")


@login_required
def user_list(request):
    if not request.user.is_admin:
        messages.error(request, "You do not have permission to manage users.")
        return redirect("core:dashboard")
    users = User.objects.all()
    return render(request, "accounts/user_list.html", {"users": users})


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
