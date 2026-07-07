from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("pretix_furbadge", "0003_badgetype_avatar_shape"),
    ]

    operations = [
        migrations.AddField(
            model_name="badgedata",
            name="telegram_delivery_mode",
            field=models.CharField(
                choices=[
                    ("email_only", "Email only"),
                    ("email_and_telegram", "Email and Telegram"),
                    ("telegram_only", "Telegram only"),
                ],
                default="email_only",
                help_text="Choose how outgoing emails should be delivered when this order is connected to Telegram.",
                max_length=18,
                verbose_name="Telegram email delivery",
            ),
        ),
    ]
