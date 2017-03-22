from __future__ import absolute_import
from django.contrib import admin

from . import models


admin.site.register(models.Config)
admin.site.disable_action('delete_selected')

admin.site.register(models.DownloadSource)
