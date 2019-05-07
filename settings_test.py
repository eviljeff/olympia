# -*- coding: utf-8 -*-
import logging
import os

from olympia.conf.local.settings import LocalSettings


class TestSettings(LocalSettings):
    # Make sure the apps needed to test translations and core are present.
    @property
    def INSTALLED_APPS(self):
        apps = self.INSTALLED_APPS + (
            'olympia.translations.tests.testapp',
            'olympia.core.tests.db_tests_testapp',
        )
        # Make sure the debug toolbar isn't used during the tests.
        return [app for app in apps if app != 'debug_toolbar']

    # See olympia.conf.local.settings for documentation:
    IN_TEST_SUITE = True

    # Don't call out to persona in tests.
    AUTHENTICATION_BACKENDS = (
        'olympia.users.backends.TestUserBackend',
    )

    CELERY_TASK_ALWAYS_EAGER = True
    DEBUG = False

    # We won't actually send an email.
    SEND_REAL_EMAIL = True

    SITE_URL = CDN_HOST = 'http://testserver'

    @property
    def STATIC_URL(self):
        return f'{self.CDN_HOST}/static/'
    @property
    def MEDIA_URL(self):
        return f'{self.CDN_HOST}/user-media/'

    # We are setting memcached here to make sure our test setup is as close
    # to our production system as possible.
    CACHES = {
        'default': {
            # `CacheStatTracker` is required for `assert_cache_requests` to
            # work properly
            'BACKEND': 'olympia.lib.cache.CacheStatTracker',
            'LOCATION': os.environ.get('MEMCACHE_LOCATION', 'localhost:11211'),
            'OPTIONS': {
                'ACTUAL_BACKEND': (
                    'django.core.cache.backends.memcached.MemcachedCache'),
            }
        },
    }

    # Overrides whatever storage you might have put in local settings.
    DEFAULT_FILE_STORAGE = 'olympia.amo.utils.LocalFileStorage'

    TASK_USER_ID = 1337

    # Make sure we have no replicas and only one shard to allow for impedent
    # search scoring
    ES_DEFAULT_NUM_REPLICAS = 0
    ES_DEFAULT_NUM_SHARDS = 1

    # Set to True if we're allowed to use X-SENDFILE.
    XSENDFILE = True

    # Don't enable the signing by default in tests, many would fail trying to
    # sign empty or bad zip files, or try posting to the endpoints. We don't
    # want that.
    SIGNING_SERVER = ''

    # Disable addon signing for unittests, too many would fail trying to sign
    # corrupt/bad zip files. These will be enabled explicitly for unittests.
    ENABLE_ADDON_SIGNING = False

    # Limit logging in tests.
    @property
    def LOGGING(self):
        self.LOGGING['loggers'] = {
            '': {
                'handlers': ['null'],
                'level': logging.DEBUG,
                'propogate': False,
            },
            # Need to disable celery logging explicitly. Celery configures it's
            # logging manually and we don't catch their logger in our default
            # config.
            'celery': {
                'handlers': ['null'],
                'level': logging.DEBUG,
                'propagate': False
            },
        }
        return self.LOGGING

    # To speed tests up, crushing uploaded images is disabled in tests except
    # where we explicitly want to test pngcrush.
    PNGCRUSH_BIN = '/bin/true'

    BASKET_API_KEY = 'testkey'


TestSettings.apply(globals())


# If you have settings you want to overload, put them in a local_settings.py.
try:
    from local_settings import *  # noqa
except ImportError:
    import warnings
    import traceback

    warnings.warn('Could not import local_settings module. {}'.format(
        traceback.format_exc()))
