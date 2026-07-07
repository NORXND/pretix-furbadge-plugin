from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("pretix_furbadge", "0002_telegram_integration"),
    ]

    operations = [
        migrations.AddField(
            model_name="badgetype",
            name="avatar_shape",
            field=models.CharField(
                choices=[("rect", "Rectangle"), ("circle", "Circle")],
                default="rect",
                help_text="Choose whether the badge avatar is rendered as a rectangle or a circle.",
                max_length=12,
                verbose_name="Avatar Shape",
            ),
        ),
    ]
