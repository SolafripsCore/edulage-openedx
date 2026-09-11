import opaque_keys.edx.django.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0003_login_refused_event"),
    ]

    operations = [
        migrations.CreateModel(
            name="CourseListing",
            fields=[
                ("id", models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_key", opaque_keys.edx.django.models.CourseKeyField(max_length=255, unique=True)),
                (
                    "institution",
                    models.CharField(help_text="EduLage institution slug / Open edX org short name", max_length=64),
                ),
                ("institution_name", models.CharField(max_length=160)),
                ("institution_logo", models.URLField(blank=True)),
                ("institution_url", models.URLField(blank=True, help_text="Institution profile on edulage.org")),
                (
                    "programme_title",
                    models.CharField(blank=True, help_text="Parent programme, if the run is part of one", max_length=200),
                ),
                ("programme_url", models.URLField(blank=True, help_text="Programme page on edulage.org")),
                (
                    "classification",
                    models.CharField(
                        choices=[
                            ("degree", "Degree programme"),
                            ("postgraduate", "Postgraduate programme"),
                            ("professional", "Professional programme"),
                            ("certificate", "Certificate course"),
                            ("short", "Short course"),
                            ("executive", "Executive education"),
                            ("open", "Open course"),
                            ("cpd", "Continuing professional development"),
                        ],
                        default="short",
                        max_length=16,
                    ),
                ),
                (
                    "credential",
                    models.CharField(blank=True, help_text="e.g. MSc, PGD, Certificate of completion", max_length=64),
                ),
                (
                    "delivery_mode",
                    models.CharField(blank=True, help_text="e.g. Fully online, Online + OEC exams", max_length=32),
                ),
                ("modified", models.DateTimeField(auto_now=True)),
            ],
        ),
    ]
