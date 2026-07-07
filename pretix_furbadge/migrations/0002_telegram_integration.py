from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_furbadge", "0001_initial"),
    ]

    operations = [
        migrations.CreateModel(
            name="TelegramIdentity",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("telegram_user_id", models.CharField(db_index=True, max_length=64)),
                ("chat_id", models.CharField(blank=True, max_length=64, null=True)),
                ("username", models.CharField(blank=True, max_length=64, null=True)),
                ("first_name", models.CharField(blank=True, max_length=128, null=True)),
                ("bot_access_granted", models.BooleanField(default=False)),
                ("consent_given", models.BooleanField(default=False)),
                ("consent_given_at", models.DateTimeField(blank=True, null=True)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("last_modified", models.DateTimeField(auto_now=True)),
                ("organizer", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_identities", to="pretixbase.organizer")),
            ],
            options={"abstract": False},
        ),
        migrations.CreateModel(
            name="TelegramOrderLink",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("identity", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="order_links", to="pretix_furbadge.telegramidentity")),
                ("order", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="telegram_links", to="pretixbase.order")),
            ],
            options={"abstract": False},
        ),
        migrations.AddConstraint(
            model_name="telegramidentity",
            constraint=models.UniqueConstraint(fields=("organizer", "telegram_user_id"), name="unique_telegram_identity_per_organizer"),
        ),
        migrations.AddConstraint(
            model_name="telegramorderlink",
            constraint=models.UniqueConstraint(fields=("identity", "order"), name="unique_identity_order_link"),
        ),
    ]
