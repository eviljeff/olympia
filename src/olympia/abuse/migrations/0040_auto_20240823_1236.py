# Generated by Django 4.2.15 on 2024-08-23 12:36

from django.db import migrations

from olympia.core.db.migrations import RenameWaffleSwitch


class Migration(migrations.Migration):

    dependencies = [
        ('abuse', '0039_alter_cinderdecision_action_and_more'),
    ]

    operations = [
        RenameWaffleSwitch('dsa-cinder-escalations-review', 'dsa-cinder-forwarded-review'),
    ]
