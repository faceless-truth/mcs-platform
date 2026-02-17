"""
Management command to poll for new bank statement emails.

Usage:
    python manage.py poll_bank_statements          # Run once
    python manage.py poll_bank_statements --loop    # Run continuously (every 5 min)

This command checks bankstatements@mcands.com.au for new emails with PDF
attachments, extracts transactions, classifies them with AI (including GST
handling), and creates ReviewJobs in StatementHub.
"""
import time

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Poll for new bank statement emails and process them"

    def add_arguments(self, parser):
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Run continuously, polling every 5 minutes",
        )
        parser.add_argument(
            "--interval",
            type=int,
            default=300,
            help="Polling interval in seconds (default: 300 = 5 minutes)",
        )

    def handle(self, *args, **options):
        from review.email_ingestion import process_all_new_emails

        loop = options["loop"]
        interval = options["interval"]

        if loop:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Starting email polling loop (every {interval}s)..."
                )
            )
            while True:
                self._poll_once()
                time.sleep(interval)
        else:
            self._poll_once()

    def _poll_once(self):
        from review.email_ingestion import process_all_new_emails

        self.stdout.write("Checking for new bank statement emails...")
        try:
            jobs = process_all_new_emails()
            if jobs:
                for job in jobs:
                    self.stdout.write(
                        self.style.SUCCESS(
                            f"  Processed: {job.client_name} — "
                            f"{job.total_transactions} transactions"
                            f"{' (GST)' if job.is_gst_registered else ''}"
                        )
                    )
            else:
                self.stdout.write("  No new emails found.")
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"  Error: {e}"))
