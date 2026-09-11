from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0005_sentemail"),
    ]

    operations = [
        migrations.AlterField(
            model_name="admission",
            name="status",
            field=models.CharField(
                choices=[
                    ("submitted", "Application submitted"),
                    ("under_review", "Under review"),
                    ("admitted", "Admitted"),
                    ("declined", "Not admitted"),
                    ("withdrawn", "Withdrawn"),
                    ("deferred", "Deferred"),
                ],
                default="admitted",
                max_length=16,
            ),
        ),
    ]
