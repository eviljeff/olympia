# Generated by Django 3.2.4 on 2021-07-13 11:31

from django.db import migrations

NEW_TAGS = [
    'adblock',
    'anti malware',
    'anti tracker',
    'antivirus',
    'chat',
    'container',
    'content blocker',
    'coupon',
    'dailymotion',
    'dark mode',
    'dndbeyond',
    'download',
    'duckduckgo',
    'facebook',
    'google',
    'image searchsearch',
    'mp3',
    'music',
    'password manager',
    'pinterest',
    'pixiv',
    'privacy',
    'reddit',
    'roblox',
    'scholar',
    'security',
    'shopping',
    'social media',
    'spotify',
    'streaming',
    'torrent',
    'translate',
    'twitch',
    'twitter',
    'user scripts',
    'video converter',
    'video downloader',
    'vpn',
    'wayback machine',
    'whatsapp',
    'word counter',
    'youtube',
    'zoom',
]


def drop_old_tags(apps, schema_editor):
    Tag = apps.get_model('tags', 'Tag')
    Tag.objects.all().delete()


def add_new_tags(apps, schema_editor):
    Tag = apps.get_model('tags', 'Tag')
    Tag.objects.bulk_create((Tag(tag_text=tag) for tag in NEW_TAGS))


class Migration(migrations.Migration):

    dependencies = [
        ('tags', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(drop_old_tags),
        migrations.RunPython(add_new_tags),
    ]
