from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0004_courselisting"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SentEmail",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("welcome", "Welcome to EduLage"),
                            ("enrolment", "Enrolment confirmed"),
                            ("certificate", "Credential recorded"),
                        ],
                        max_length=16,
                    ),
                ),
                (
                    "reference",
                    models.CharField(
                        blank=True, help_text="course run key or certificate id; empty for account mail", max_length=255
                    ),
                ),
                ("sent", models.DateTimeField(auto_now_add=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=models.deletion.CASCADE, related_name="edulage_emails", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"unique_together": {("user", "kind", "reference")}},
        ),
    ]
