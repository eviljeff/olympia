#!/usr/bin/env python

from __future__ import absolute_import
from celeryutils import task

from mkt.webapps.models import AddonExcludedRegion
from amo.decorators import write


@task
@write
def _task(**kw):
    # 3 - Canada
    # 5 - Australia
    # 6 - New Zealand
    AddonExcludedRegion.objects.filter(region__in=[3, 5, 6]).delete()


def run():
    """Mark mobile-compatible apps as compatible for Firefox OS as well."""
    _task()
