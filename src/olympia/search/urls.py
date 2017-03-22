from __future__ import absolute_import
from django.conf.urls import patterns, url

from . import views


urlpatterns = patterns(
    '',
    url('^(?:es)?$', views.search, name='search.search'),
    url('^ajax$', views.ajax_search, name='search.ajax'),
    url('^suggestions$', views.ajax_search_suggestions,
        name='search.suggestions'),
)
