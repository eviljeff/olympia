# Generated by Django 4.2.3 on 2023-07-11 15:50

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('reviewers', '0030_auto_20230622_1231'),
    ]

    operations = [
        migrations.AddField(
            model_name='reviewactionreason',
            name='canned_block_reason',
            field=models.TextField(blank=True),
        ),
    ]
