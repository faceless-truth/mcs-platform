# Generated manually on 2026-02-22

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0024_platform_upgrades_v2'),
    ]

    operations = [
        migrations.AlterUniqueTogether(
            name='workpapernote',
            unique_together={('financial_year', 'account_code', 'note_type')},
        ),
    ]
