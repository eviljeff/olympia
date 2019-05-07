"""This is the standard development settings file.

If you need to overload settings, please do so in a local_settings.py file (it
won't be tracked in git).

"""
from olympia.conf.local.settings import LocalSettings


LocalSettings.apply(globals())


# If you have settings you want to overload, put them in a local_settings.py.
try:
    from local_settings import *  # noqa
except ImportError:
    import warnings
    import traceback

    warnings.warn('Could not import local_settings module. {}'.format(
        traceback.format_exc()))
