import os
from six.moves.urllib_parse import urlparse

from olympia.conf.settings_base import env, Settings

class LocalSettings(Settings):
    WSGI_APPLICATION = 'olympia.wsgi.application'

    DEBUG = True

    # These apps are great during development.
    INSTALLED_APPS = Settings.INSTALLED_APPS + ('olympia.landfill',)

    @property
    def FILESYSTEM_CACHE_ROOT(self):
        return os.path.join(self.TMP_PATH, 'cache')

    # We are setting memcached here to make sure our local setup is as close
    # to our production system as possible.
    CACHES = {
        'default': {
            'BACKEND': 'django.core.cache.backends.memcached.MemcachedCache',
            'LOCATION': os.environ.get('MEMCACHE_LOCATION', 'localhost:11211'),
        },
    }

    # If you're not running on SSL you'll want this to be False.
    SESSION_COOKIE_SECURE = False
    SESSION_COOKIE_DOMAIN = None

    CELERY_TASK_ALWAYS_EAGER = False

    # Locally we typically don't run more than 1 elasticsearch node. So we set
    # replicas to zero.
    ES_DEFAULT_NUM_REPLICAS = 0

    SITE_URL = os.environ.get('OLYMPIA_SITE_URL') or 'http://localhost:8000'
    @property
    def DOMAIN(self):
        return urlparse(self.SITE_URL).netloc
    @property
    def SERVICES_DOMAIN(self):
        return self.DOMAIN
    @property
    def SERVICES_URL(self):
        return self.SITE_URL

    CODE_MANAGER_URL = (
        os.environ.get('CODE_MANAGER_URL') or 'http://localhost:3000')

    @property
    def ALLOWED_HOSTS(self):
        return self.ALLOWED_HOSTS + [self.SERVICES_DOMAIN]

    # Default AMO user id to use for tasks (from users.json fixture in zadmin).
    TASK_USER_ID = 10968

    # Set to True if we're allowed to use X-SENDFILE.
    XSENDFILE = False

    ALLOW_SELF_REVIEWS = True

    @property
    def AES_KEYS(self):
        return {
            'api_key:secret': os.path.join(
                self.ROOT, 'src', 'olympia', 'api', 'tests', 'assets',
                'test-api-key.txt'),
        }

    # FxA config for local development only.
    FXA_CONFIG = {
        'default': {
            'client_id': env('FXA_CLIENT_ID', default='f336377c014eacf0'),
            'client_secret': env(
                'FXA_CLIENT_SECRET',
                default='5a36054059674b09ea56709c85b862c388f2d493d735070868ae8f476e16a80d'),  # noqa
            'content_host': 'https://stable.dev.lcip.org',
            'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
            'profile_host': 'https://stable.dev.lcip.org/profile/v1',
            'redirect_url': 'http://olympia.test/api/v3/accounts/authenticate/',  # noqa
            'scope': 'profile',
        },
        'amo': {
            'client_id': env('FXA_CLIENT_ID', default='0f95f6474c24c1dc'),
            'client_secret': env(
                'FXA_CLIENT_SECRET',
                default='ca45e503a1b4ec9e2a3d4855d79849e098da18b7dfe42b6bc76dfed420fc1d38'),  # noqa
            'content_host': 'https://stable.dev.lcip.org',
            'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
            'profile_host': 'https://stable.dev.lcip.org/profile/v1',
            'redirect_url': 'http://localhost:3000/fxa-authenticate',
            'scope': 'profile',
        },
        'local': {
            'client_id': env('FXA_CLIENT_ID', default='1778aef72d1adfb3'),
            'client_secret': env(
                'FXA_CLIENT_SECRET',
                default='3feebe3c009c1a0acdedd009f3530eae2b88859f430fa8bb951ea41f2f859b18'),  # noqa
            'content_host': 'https://stable.dev.lcip.org',
            'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
            'profile_host': 'https://stable.dev.lcip.org/profile/v1',
            'redirect_url': 'http://localhost:3000/api/v3/accounts/authenticate/?config=local', # noqa
            'scope': 'profile',
        },
        'code-manager': {
            'client_id': env('CODE_MANAGER_FXA_CLIENT_ID', default='a98b671fdd3dfcea'), # noqa
            'client_secret': env(
                'CODE_MANAGER_FXA_CLIENT_SECRET',
                default='d9934865e34bed4739a2dc60046a90d09a5d8336cf92809992dec74a4cff4665'),  # noqa
            'content_host': 'https://stable.dev.lcip.org',
            'oauth_host': 'https://oauth-stable.dev.lcip.org/v1',
            'profile_host': 'https://stable.dev.lcip.org/profile/v1',
            'redirect_url': 'http://olympia.test/api/v4/accounts/authenticate/?config=code-manager', # noqa
            'scope': 'profile',
        },
    }
    ALLOWED_FXA_CONFIGS = ['default', 'amo', 'local', 'code-manager']

    # CSP report endpoint which returns a 204 from addons-nginx in local dev.
    CSP_REPORT_URI = '/csp-report'

    # Allow GA over http + www subdomain in local development.
    HTTP_GA_SRC = 'http://www.google-analytics.com'
    @property
    def CSP_IMG_SRC(self):
        return self.CSP_IMG_SRC+ (self.HTTP_GA_SRC,)
    @property
    def CSP_SCRIPT_SRC(self):
        return self.CSP_SCRIPT_SRC + (self.HTTP_GA_SRC, "'self'")

    # Auth token required to authorize inbound email.
    INBOUND_EMAIL_SECRET_KEY = 'totally-unsecure-secret-string'
    # Validation key we need to send in POST response.
    INBOUND_EMAIL_VALIDATION_KEY = 'totally-unsecure-validation-string'
