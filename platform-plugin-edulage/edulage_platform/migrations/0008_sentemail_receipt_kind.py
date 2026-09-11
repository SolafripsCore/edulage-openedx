from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0007_enrolment_policy_payment"),
    ]

    operations = [
        migrations.AlterField(
            model_name="sentemail",
            name="kind",
            field=models.CharField(
                choices=[
                    ("welcome", "Welcome to EduLage"),
                    ("enrolment", "Enrolment confirmed"),
                    ("certificate", "Credential recorded"),
                    ("receipt", "Payment receipt"),
                ],
                max_length=16,
            ),
        ),
    ]
