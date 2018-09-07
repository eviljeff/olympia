# -*- coding: utf-8 -*-
from six import text_type


def generate_translations(item):
    """Generate French and Spanish translations for the given `item`."""
    fr_prefix = u'(français) '
    es_prefix = u'(español) '
    oldname = text_type(item.name)
    item.name = {'en': oldname,
                 'fr': fr_prefix + oldname,
                 'es': es_prefix + oldname}
    item.save()
