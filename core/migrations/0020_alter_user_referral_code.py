# Generated by Django 5.0.2 on 2025-05-30 11:34

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_user_referral_code_user_referred_by'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='referral_code',
            field=models.CharField(blank=True, help_text='Unique referral code for this user', max_length=50, null=True, verbose_name='referral code'),
        ),
    ]
