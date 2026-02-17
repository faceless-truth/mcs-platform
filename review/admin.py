from django.contrib import admin
from .models import ReviewJob, PendingTransaction, ReviewActivity


@admin.register(ReviewJob)
class ReviewJobAdmin(admin.ModelAdmin):
    list_display = ["client_name", "file_name", "status", "flagged_count", "confirmed_count", "received_at"]
    list_filter = ["status"]
    search_fields = ["client_name", "file_name"]


@admin.register(PendingTransaction)
class PendingTransactionAdmin(admin.ModelAdmin):
    list_display = ["job", "date", "description", "amount", "is_confirmed"]
    list_filter = ["is_confirmed"]


@admin.register(ReviewActivity)
class ReviewActivityAdmin(admin.ModelAdmin):
    list_display = ["activity_type", "title", "created_at"]
    list_filter = ["activity_type"]
