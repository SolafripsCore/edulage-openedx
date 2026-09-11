from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0002_hardening"),
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
                ],
                max_length=32,
            ),
        ),
    ]
