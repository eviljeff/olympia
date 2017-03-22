from __future__ import absolute_import
from django import forms
from django.utils.translation import ugettext_lazy as _

from olympia import amo
from olympia.compat import FIREFOX_COMPAT
import six


APPVER_CHOICES = [
    (info['main'], '%s %s' % (six.text_type(amo.FIREFOX.pretty), info['main']))
    for info in FIREFOX_COMPAT
]


class AppVerForm(forms.Form):
    appver = forms.ChoiceField(choices=[('', _('All'))] + APPVER_CHOICES,
                               required=False)
