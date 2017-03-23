from __future__ import absolute_import
import random

from django.utils.crypto import get_random_string

from olympia.addons.models import Review
from olympia.users.models import UserProfile
from six.moves import range


def generate_ratings(addon, num):
    """Given an `addon`, generate `num` random ratings."""
    for n in range(1, num + 1):
        username = 'testuser-{s}'.format(s=get_random_string())
        email = '{username}@example.com'.format(username=username)
        user, _created = UserProfile.objects.get_or_create(
            username=email, email=email, defaults={'display_name': email})
        Review.objects.create(
            addon=addon, user=user, rating=random.randrange(0, 6),
            title='Test Review {n}'.format(n=n), body='review text')
