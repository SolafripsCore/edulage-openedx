from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import opaque_keys.edx.django.models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0006_application_statuses"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name="courselisting",
            name="enrolment_policy",
            field=models.CharField(
                choices=[
                    ("admission", "Admission required"),
                    ("open_free", "Open enrolment — free"),
                    ("open_paid", "Open enrolment — paid"),
                ],
                default="admission",
                help_text="Set by the institution's course admin in Studio (Advanced settings → Other course settings → edulage)",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="courselisting",
            name="price",
            field=models.DecimalField(decimal_places=2, default=0, help_text="Fixed price for open_paid runs", max_digits=12),
        ),
        migrations.AddField(
            model_name="courselisting",
            name="currency",
            field=models.CharField(default="NGN", max_length=3),
        ),
        migrations.CreateModel(
            name="Payment",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_key", opaque_keys.edx.django.models.CourseKeyField(db_index=True, max_length=255)),
                ("institution", models.CharField(db_index=True, help_text="Open edX org short name of the run", max_length=64)),
                ("reference", models.CharField(help_text="Our reference, passed to Paystack", max_length=64, unique=True)),
                ("amount", models.DecimalField(decimal_places=2, help_text="Major units (e.g. NGN), price at checkout", max_digits=12)),
                ("currency", models.CharField(default="NGN", max_length=3)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("initialized", "Initialised"),
                            ("success", "Successful"),
                            ("failed", "Failed"),
                            ("abandoned", "Abandoned"),
                        ],
                        db_index=True,
                        default="initialized",
                        max_length=16,
                    ),
                ),
                ("email", models.EmailField(help_text="Customer e-mail sent to Paystack", max_length=254)),
                ("paystack_id", models.CharField(blank=True, help_text="Paystack transaction id", max_length=32)),
                ("channel", models.CharField(blank=True, max_length=32)),
                ("paid_at", models.DateTimeField(blank=True, null=True)),
                ("gateway_response", models.CharField(blank=True, max_length=255)),
                ("enrolled", models.BooleanField(default=False)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="edulage_payments", to=settings.AUTH_USER_MODEL
                    ),
                ),
            ],
            options={"ordering": ["-created"]},
        ),
    ]
