# Generated by Django 5.0.2 on 2025-05-26 15:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0017_revision_deleted_at'),
    ]

    operations = [
        migrations.AddField(
            model_name='story',
            name='is_default',
            field=models.BooleanField(default=False, verbose_name='is_default'),
        ),
    ]
