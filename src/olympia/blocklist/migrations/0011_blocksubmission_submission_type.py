# Generated by Django 2.2.9 on 2020-02-19 07:45

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('blocklist', '0010_merge_20200120_0426'),
    ]

    operations = [
        migrations.AddField(
            model_name='blocksubmission',
            name='action',
            field=models.SmallIntegerField(choices=[(0, 'Add/Change'), (1, 'Delete')], default=0),
        ),
    ]
