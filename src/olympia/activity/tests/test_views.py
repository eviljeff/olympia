# -*- coding: utf-8 -*-
import json
import mock
import StringIO

from django.test.utils import override_settings

from olympia import amo
from olympia.activity.models import ActivityLogToken
from olympia.activity.tests.test_serializers import LogMixin
from olympia.activity.tests.test_utils import sample_email
from olympia.activity.views import post_email, EmailCreationPermission
from olympia.amo.tests import (
    addon_factory, APITestClient, req_factory_factory, user_factory, TestCase)
from olympia.amo.urlresolvers import reverse
from olympia.addons.models import AddonUser
from olympia.addons.utils import generate_addon_guid
from olympia.devhub.models import ActivityLog
from olympia.users.models import UserProfile


class ReviewNotesViewSetDetailMixin(LogMixin):
    """Tests that play with addon state and permissions. Shared between review
    note viewset detail tests since both need to react the same way."""
    def _test_url(self):
        raise NotImplementedError

    def _set_tested_url(self, pk=None, version_pk=None, addon_pk=None):
        raise NotImplementedError

    def _login_developer(self):
        user = UserProfile.objects.create(username='author')
        AddonUser.objects.create(user=user, addon=self.addon)
        self.client.login_api(user)

    def _login_reviewer(self, permission='Addons:Review'):
        user = UserProfile.objects.create(username='reviewer')
        self.grant_permission(user, permission)
        self.client.login_api(user)

    def test_get_by_id(self):
        self._login_developer()
        self._test_url()

    def test_get_by_id_reviewer(self):
        self._login_reviewer()
        self._test_url()

    def test_get_anonymous(self):
        response = self.client.get(self.url)
        assert response.status_code == 401

    def test_get_no_rights(self):
        self.client.login_api(UserProfile.objects.create(username='joe'))
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_public_reviewer(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_public_developer(self):
        self.addon.update(status=amo.STATUS_NOMINATED)
        self._login_developer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_simple_reviewer(self):
        self.addon.update(is_listed=False)
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 403

    def test_get_not_listed_specific_reviewer(self):
        self.addon.update(is_listed=False)
        self._login_reviewer(permission='Addons:ReviewUnlisted')
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_not_listed_author(self):
        self.addon.update(is_listed=False)
        self._login_developer()
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_get_deleted(self):
        self.addon.delete()
        self._login_developer()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_reviewer(self):
        self.addon.delete()
        self._login_reviewer()
        response = self.client.get(self.url)
        assert response.status_code == 404

    def test_get_deleted_admin(self):
        self.addon.delete()
        self._login_reviewer(permission='*:*')
        response = self.client.get(self.url)
        assert response.status_code == 200

    def test_disabled_version_reviewer(self):
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._login_reviewer()
        self._test_url()

    def test_disabled_version_developer(self):
        self.version.files.update(status=amo.STATUS_DISABLED)
        self._login_developer()
        self._test_url()

    def test_deleted_version_reviewer(self):
        self.version.delete()
        self._login_reviewer()
        self._test_url()

    def test_deleted_version_developer(self):
        self.version.delete()
        self._login_developer()
        self._test_url()

    def test_get_version_not_found(self):
        self._login_reviewer(permission='*:*')
        self._set_tested_url(version_pk=self.version.pk + 27)
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestReviewNotesViewSetDetail(ReviewNotesViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestReviewNotesViewSetDetail, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.user = user_factory()
        self.version = self.addon.latest_version
        self.note = self.log(u'noôo!', amo.LOG.APPROVE_VERSION,
                             self.days_ago(0))
        self._set_tested_url()

    def _test_url(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['id'] == self.note.pk
        assert result['action_label'] == amo.LOG.APPROVE_VERSION.short
        assert result['comments'] == u'noôo!'

    def _set_tested_url(self, pk=None, version_pk=None, addon_pk=None):
        self.url = reverse('version-reviewnotes-detail', kwargs={
            'addon_pk': addon_pk or self.addon.pk,
            'version_pk': version_pk or self.version.pk,
            'pk': pk or self.note.pk})

    def test_get_note_not_found(self):
        self._login_reviewer(permission='*:*')
        self._set_tested_url(self.note.pk + 42)
        response = self.client.get(self.url)
        assert response.status_code == 404


class TestReviewNotesViewSetList(ReviewNotesViewSetDetailMixin, TestCase):
    client_class = APITestClient

    def setUp(self):
        super(TestReviewNotesViewSetList, self).setUp()
        self.addon = addon_factory(
            guid=generate_addon_guid(), name=u'My Addôn', slug='my-addon')
        self.user = user_factory()
        self.note = self.log(u'noôo!', amo.LOG.APPROVE_VERSION,
                             self.days_ago(1))
        self.note2 = self.log(u'yéss!', amo.LOG.REJECT_VERSION,
                              self.days_ago(0))

        self.version = self.addon.latest_version
        self._set_tested_url()

    def _test_url(self, **kwargs):
        response = self.client.get(self.url, data=kwargs)
        assert response.status_code == 200
        result = json.loads(response.content)
        assert result['results']
        assert len(result['results']) == 2
        result_version = result['results'][0]
        assert result_version['id'] == self.note2.pk
        result_version = result['results'][1]
        assert result_version['id'] == self.note.pk

    def _set_tested_url(self, pk=None, version_pk=None, addon_pk=None):
        self.url = reverse('version-reviewnotes-list', kwargs={
            'addon_pk': addon_pk or self.addon.pk,
            'version_pk': version_pk or self.version.pk})


@override_settings(ALLOWED_CLIENTS_EMAIL_API=['10.10.10.10'])
@override_settings(POSTFIX_AUTH_TOKEN='something')
class TestEmailApi(TestCase):

    def get_request(self, data=None):
        data = data or {}
        datastr = json.dumps(data)
        req = req_factory_factory(reverse('post-email-api'))
        req.META['REMOTE_ADDR'] = '10.10.10.10'
        req.META['HTTP_POSTFIX_AUTH_TOKEN'] = 'something'
        req.META['CONTENT_LENGTH'] = len(datastr)
        req.META['CONTENT_TYPE'] = 'application/json'
        req.POST = data
        req.method = 'POST'
        req._stream = StringIO.StringIO(datastr)
        return req

    def test_basic(self):
        user = user_factory()
        self.grant_permission(user, '*:*')
        addon = addon_factory()
        req = self.get_request(
            data={'body': open(sample_email).read()})

        ActivityLogToken.objects.create(
            user=user, version=addon.latest_version,
            uuid='5a0b8a83d501412589cc5d562334b46b')

        res = post_email(req)
        assert res.status_code == 201
        logs = ActivityLog.objects.for_addons(addon)
        assert logs.count() == 1
        assert logs.get(action=amo.LOG.REVIEWER_REPLY_VERSION.id)

    def test_allowed(self):
        assert EmailCreationPermission().has_permission(
            self.get_request(), None)

    def test_ip_denied(self):
        req = self.get_request()
        req.META['REMOTE_ADDR'] = '10.10.10.1'
        assert not EmailCreationPermission().has_permission(req, None)

    def test_no_postfix_token(self):
        req = self.get_request()
        del req.META['HTTP_POSTFIX_AUTH_TOKEN']
        assert not EmailCreationPermission().has_permission(req, None)

    def test_postfix_token_denied(self):
        req = self.get_request()
        req.META['HTTP_POSTFIX_AUTH_TOKEN'] = 'somethingwrong'
        assert not EmailCreationPermission().has_permission(req, None)

    @mock.patch('olympia.activity.tasks.process_email.apply_async')
    def test_successful(self, _mock):
        req = self.get_request({'body': 'something'})
        res = post_email(req)
        _mock.assert_called_with(('something',))
        assert res.status_code == 201

    def test_bad_request(self):
        """Test with no email body."""
        res = post_email(self.get_request())
        assert res.status_code == 400
