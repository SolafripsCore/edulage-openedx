import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0009_alter_courselisting_id"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="StaffInvitation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("token", models.CharField(max_length=64, unique=True)),
                ("email", models.EmailField(db_index=True, max_length=254)),
                ("institution", models.CharField(db_index=True, help_text="Open edX org short name", max_length=64)),
                ("role", models.CharField(choices=[("institution_admin", "Institution administrator"), ("programme_admin", "Programme administrator"), ("course_author", "Course author"), ("trainer", "Trainer"), ("instructor", "Instructor"), ("teaching_assistant", "Teaching assistant")], max_length=32)),
                ("course_id", models.CharField(blank=True, help_text="Course run for instructor / TA roles", max_length=255)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("accepted", models.DateTimeField(blank=True, null=True)),
                ("revoked", models.DateTimeField(blank=True, null=True)),
                ("accepted_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("invited_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-created"]},
        ),
    ]
