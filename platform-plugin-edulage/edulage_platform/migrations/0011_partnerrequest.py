import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0010_staffinvitation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name="identityaudit",
            name="event",
            field=models.CharField(
                choices=[
                    ("linked", "Existing account linked to EduLage identity"),
                    ("created", "Account created for EduLage identity"),
                    ("link_refused", "Account link refused"),
                    ("login_refused", "Sign-in refused (identity not active)"),
                    ("admission_applied", "Pending admission applied at first login"),
                    ("roles_synced", "Roles synchronised"),
                    ("suspended", "Account suspended"),
                    ("reactivated", "Account reactivated"),
                    ("support_lookup", "OEC support looked up a learner"),
                    ("invited", "Staff invitation sent"),
                    ("invite_revoked", "Staff invitation withdrawn"),
                    ("invite_accepted", "Staff invitation accepted"),
                    ("partner_requested", "Institution partnership requested"),
                    ("partner_approved", "Institution partnership approved"),
                    ("partner_declined", "Institution partnership declined"),
                ],
                max_length=32,
            ),
        ),
        migrations.CreateModel(
            name="PartnerRequest",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("institution_name", models.CharField(max_length=160)),
                ("short_name", models.CharField(blank=True, help_text="Proposed institution code (Open edX org short name)", max_length=16)),
                ("country", models.CharField(blank=True, max_length=80)),
                ("website", models.URLField(blank=True)),
                ("contact_name", models.CharField(max_length=120)),
                ("contact_email", models.EmailField(db_index=True, max_length=254)),
                ("contact_role", models.CharField(blank=True, max_length=120)),
                ("message", models.TextField(blank=True)),
                ("status", models.CharField(choices=[("pending", "Pending review"), ("approved", "Approved"), ("declined", "Declined")], db_index=True, default="pending", max_length=16)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("decided", models.DateTimeField(blank=True, null=True)),
                ("note", models.TextField(blank=True, help_text="Reason sent to the contact on decline; internal note on approval")),
                ("decided_by", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
                ("invitation", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to="edulage_platform.staffinvitation")),
            ],
            options={"ordering": ["-created"]},
        ),
    ]
