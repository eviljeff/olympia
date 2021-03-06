# Generated by Django 2.2.9 on 2020-01-17 06:09

from django.db import migrations, models
import django_extensions.db.fields.json


def set_block_and_to_block_from_processed_guids(apps, schema_editor):
    BlockSubmission = apps.get_model('blocklist', 'BlockSubmission')
    Block = apps.get_model('blocklist', 'Block')
    for submission in BlockSubmission.objects.exclude(processed_guids={}):
        processed = submission.processed_guids
        # First get the completed blocks and convert the ids into fks
        blocked_ids = (id_ for id_, _ in processed.get('blocks_saved', []))
        blocks = Block.objects.filter(id__in=blocked_ids)
        for block in blocks:
            block.submission.add(submission)
        # Then backfill the to_block property
        to_block_guids = processed.get('toblock_guids', [])
        submission.update(to_block=[
            {'guid': guid, 'id': 0, 'average_daily_users': 0}
            for guid in to_block_guids])


class Migration(migrations.Migration):

    dependencies = [
        ('blocklist', '0008_blocksubmission'),
    ]

    operations = [
        migrations.AddField(
            model_name='block',
            name='submission',
            field=models.ManyToManyField(to='blocklist.BlockSubmission'),
        ),
        migrations.AddField(
            model_name='blocksubmission',
            name='to_block',
            field=django_extensions.db.fields.json.JSONField(default=[]),
        ),
        migrations.RunPython(set_block_and_to_block_from_processed_guids),
        migrations.RemoveField(
            model_name='blocksubmission',
            name='processed_guids',
        ),
    ]
