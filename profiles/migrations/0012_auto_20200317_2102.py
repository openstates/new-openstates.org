# Generated by Django 2.2.10 on 2020-03-17 21:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("profiles", "0011_usagereport")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="api_key",
            field=models.CharField(default="", max_length=40),
        ),
        migrations.AddField(
            model_name="profile",
            name="api_tier",
            field=models.SlugField(
                choices=[
                    ("inactive", "Not Yet Activated"),
                    ("suspended", "Suspended"),
                    ("demo", "Demo"),
                    ("unlimited", "Unlimited"),
                    ("default", "Default (new user)"),
                    ("bronze", "Bronze"),
                    ("silver", "Silver"),
                ],
                default="inactive",
            ),
        ),
    ]