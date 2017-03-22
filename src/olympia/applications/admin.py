from __future__ import absolute_import
from django.contrib import admin

from .models import AppVersion


class AppVersionAdmin(admin.ModelAdmin):
    list_display = ('version', 'application',)
    model = AppVersion
    ordering = ('-version_int',)


admin.site.register(AppVersion, AppVersionAdmin)
