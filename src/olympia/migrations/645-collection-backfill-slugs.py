from __future__ import absolute_import
from mkt.collections.models import Collection


def run():
    """Backfill slugs."""
    for c in Collection.objects.all():
        c.save()
