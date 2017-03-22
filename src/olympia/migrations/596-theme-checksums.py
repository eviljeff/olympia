#!/usr/bin/env python

from __future__ import absolute_import
from addons.models import Persona
from addons.tasks import calc_checksum
from amo.utils import chunked


def run():
    """Calculate checksums for all themes."""
    pks = Persona.objects.filter(checksum='').values_list('id', flat=True)
    for chunk in chunked(pks, 1000):
        [calc_checksum.delay(pk) for pk in chunk]
