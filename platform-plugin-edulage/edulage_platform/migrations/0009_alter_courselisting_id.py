from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("edulage_platform", "0008_sentemail_receipt_kind"),
    ]

    operations = [
        migrations.AlterField(
            model_name="courselisting",
            name="id",
            field=models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
        ),
    ]
