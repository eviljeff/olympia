from __future__ import absolute_import
from django.core import management

from olympia.amo.tests import TestCase
from olympia.access.acl import action_allowed_user
from olympia.users.models import UserProfile


class TestCommand(TestCase):
    fixtures = ['zadmin/group_admin', 'zadmin/users']

    def test_group_management(self):
        user = UserProfile.objects.get(pk=10968)
        assert not action_allowed_user(user, 'Admin', '%')

        management.call_command('addusertogroup', '10968', '1')
        del user.groups_list
        assert action_allowed_user(user, 'Admin', '%')

        management.call_command('removeuserfromgroup', '10968', '1')
        del user.groups_list
        assert not action_allowed_user(user, 'Admin', '%')
