import django.db.models.deletion
import opaque_keys.edx.django.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name="Admission",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("course_key", opaque_keys.edx.django.models.CourseKeyField(db_index=True, max_length=255)),
                ("application_id", models.CharField(help_text="EduLage application identifier", max_length=64)),
                ("institution", models.CharField(help_text="EduLage institution slug / Open edX org short name", max_length=64)),
                ("status", models.CharField(choices=[("admitted", "Admitted"), ("withdrawn", "Withdrawn"), ("deferred", "Deferred")], default="admitted", max_length=16)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("modified", models.DateTimeField(auto_now=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edulage_admissions", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "course_key")}},
        ),
        migrations.CreateModel(
            name="ManagedRole",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(max_length=64)),
                ("org", models.CharField(blank=True, max_length=64)),
                ("course_id", models.CharField(blank=True, max_length=255)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="edulage_roles", to=settings.AUTH_USER_MODEL)),
            ],
            options={"unique_together": {("user", "role", "org", "course_id")}},
        ),
    ]
