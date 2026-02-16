"""
Django management command to import Access Ledger ZIP exports.

Usage:
    python manage.py import_access_ledger /path/to/HL_FOOT.zip
    python manage.py import_access_ledger /path/to/HL_FOOT.zip --replace
    python manage.py import_access_ledger /path/to/*.zip  # Bulk import
"""
import glob
import os

from django.core.management.base import BaseCommand, CommandError

from core.access_ledger_import import import_access_ledger_zip


class Command(BaseCommand):
    help = "Import Access Ledger ZIP export(s) into StatementHub"

    def add_arguments(self, parser):
        parser.add_argument(
            "zip_files",
            nargs="+",
            type=str,
            help="Path(s) to Access Ledger ZIP file(s). Supports glob patterns.",
        )
        parser.add_argument(
            "--replace",
            action="store_true",
            default=False,
            help="Replace existing entity data if entity already exists.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            default=False,
            help="Parse and validate without saving to database.",
        )

    def handle(self, *args, **options):
        zip_paths = []
        for pattern in options["zip_files"]:
            expanded = glob.glob(pattern)
            if expanded:
                zip_paths.extend(expanded)
            else:
                zip_paths.append(pattern)

        if not zip_paths:
            raise CommandError("No ZIP files specified.")

        replace = options["replace"]
        dry_run = options["dry_run"]

        total_entities = 0
        total_years = 0
        total_tb = 0
        total_dep = 0
        failed = []

        for zip_path in zip_paths:
            if not os.path.exists(zip_path):
                self.stderr.write(self.style.ERROR(f"File not found: {zip_path}"))
                failed.append(zip_path)
                continue

            self.stdout.write(f"\nImporting: {os.path.basename(zip_path)}")
            self.stdout.write("-" * 60)

            try:
                if dry_run:
                    self.stdout.write(self.style.WARNING("  DRY RUN — no data will be saved"))

                result = import_access_ledger_zip(
                    zip_path,
                    replace_existing=replace,
                )

                entity = result["entity"]
                if entity:
                    self.stdout.write(f"  Entity: {entity.entity_name}")
                    self.stdout.write(f"  Type: {entity.entity_type}")
                    self.stdout.write(f"  ABN: {entity.abn or 'N/A'}")
                    self.stdout.write(
                        f"  Created: {'Yes' if result['entity_created'] else 'No (existing)'}"
                    )

                self.stdout.write(f"  Years imported: {result['years_imported']}")
                self.stdout.write(f"  Trial balance lines: {result['total_tb_lines']}")
                self.stdout.write(f"  Depreciation assets: {result['total_dep_assets']}")
                self.stdout.write(f"  Officers created: {result['officers_created']}")

                if result["warnings"]:
                    for w in result["warnings"]:
                        self.stdout.write(self.style.WARNING(f"  WARNING: {w}"))

                if result["errors"]:
                    for e in result["errors"]:
                        self.stderr.write(self.style.ERROR(f"  ERROR: {e}"))
                    failed.append(zip_path)
                else:
                    total_entities += 1
                    total_years += result["years_imported"]
                    total_tb += result["total_tb_lines"]
                    total_dep += result["total_dep_assets"]

            except Exception as e:
                self.stderr.write(self.style.ERROR(f"  FAILED: {str(e)}"))
                failed.append(zip_path)

        # Summary
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write(self.style.SUCCESS(f"Import Summary"))
        self.stdout.write(f"  Files processed: {len(zip_paths)}")
        self.stdout.write(f"  Entities imported: {total_entities}")
        self.stdout.write(f"  Total years: {total_years}")
        self.stdout.write(f"  Total TB lines: {total_tb}")
        self.stdout.write(f"  Total dep assets: {total_dep}")

        if failed:
            self.stdout.write(self.style.ERROR(f"  Failed: {len(failed)}"))
            for f in failed:
                self.stdout.write(self.style.ERROR(f"    - {os.path.basename(f)}"))
