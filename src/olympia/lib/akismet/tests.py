# -*- coding: utf-8 -*-
from datetime import datetime

from django.conf import settings

import mock

from olympia.amo.tests import addon_factory, TestCase, user_factory
from olympia.ratings.models import Rating

from .models import AkismetReport


class TestAkismetReportsModel(TestCase):

    def setUp(self):
        patcher = mock.patch('olympia.lib.akismet.models.requests.post')
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        self.post.return_value.status_code = 200
        self.post.return_value.json.return_value = {}

    def test_create_for_rating(self):
        user = user_factory()
        addon = addon_factory()
        rating = Rating.objects.create(
            addon=addon, user=user, rating=4, body='spám?',
            ip_address='1.23.45.67')
        ua = 'foo/baa'
        referrer = 'https://mozilla.org/'
        report = AkismetReport.create_for_rating(rating, ua, referrer)

        assert report.rating_instance == rating
        data = report._get_data()
        assert data == {
            'blog': settings.SITE_URL,
            'user_ip': rating.ip_address,
            'user_agent': ua,
            'referrer': referrer,
            'permalink': addon.get_url_path(),
            'comment_type': 'user-review',
            'comment_author': user.username,
            'comment_author_email': user.email,
            'comment_content': rating.body,
            'comment_date_gmt': rating.modified,
            'comment_post_modified_gmt': addon.last_updated,
            'blog_charset': 'utf-8',
            'is_test': not settings.AKISMET_REAL_SUBMIT,
        }

    def _create_report(self, kws=None):
        defaults = dict(
            comment_type='user-review',
            user_ip='9.8.7.6.5',
            user_agent='Agent Bond',
            referrer='á4565',
            user_name='steve',
            user_email='steve@steve.com',
            content_link='https://addons.mozilla.org',
            content_modified=datetime.now(),
            comment='spammy McSpam?',
            comment_modified=datetime.now(),
        )
        if kws:
            defaults.update(**kws)
        instance = AkismetReport.objects.create(**defaults)
        return instance

    def test_comment_check(self):
        report = self._create_report()

        self.post.return_value.json.return_value = True
        result = report.comment_check()
        assert result == report.result == AkismetReport.MAYBE_SPAM

        self.post.return_value.headers = {'X-akismet-pro-tip': 'discard'}
        result = report.comment_check()
        assert result == report.result == AkismetReport.DEFINITE_SPAM

        self.post.return_value.json.return_value = False
        # Headers should be ignored, so we won't bother resetting it.
        result = report.comment_check()
        assert result == report.result == AkismetReport.HAM
