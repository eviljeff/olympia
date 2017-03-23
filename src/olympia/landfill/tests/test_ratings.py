# -*- coding: utf-8 -*-
from __future__ import absolute_import
from olympia import amo
from olympia.amo.tests import TestCase
from olympia.addons.models import Addon, Review
from olympia.landfill.ratings import generate_ratings
from olympia.users.models import UserProfile
import six


class RatingsTests(TestCase):

    def setUp(self):
        super(RatingsTests, self).setUp()
        self.addon = Addon.objects.create(type=amo.ADDON_EXTENSION)

    def test_ratings_generation(self):
        generate_ratings(self.addon, 3)
        assert Review.objects.all().count() == 3
        assert UserProfile.objects.count() == 3
        for n, review in enumerate(Review.objects.all().order_by('pk')):
            assert review.addon == self.addon
            assert six.text_type(review.title) == u'Test Review %d' % (n + 1)
            assert review.user.email.endswith('@example.com')
