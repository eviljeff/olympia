"""Reindex add-ons to fix stale data left by changes to the post_save
handler."""

from __future__ import absolute_import
from addons.cron import reindex_addons


reindex_addons()
