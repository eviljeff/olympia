from __future__ import absolute_import
from django.dispatch import Signal

logged_out = Signal(providing_args=['request', 'response'])
