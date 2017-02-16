# -*- coding: utf-8 -*-
from datetime import datetime, timedelta
import time

from django.conf import settings
from django.core import mail

from olympia import amo
from olympia.amo.tests import TestCase
from olympia.amo.tests import addon_factory, user_factory, version_factory
from olympia.addons.models import Addon, AddonUser
from olympia.versions.models import (
    Version, version_uploaded)
from olympia.files.models import File
from olympia.editors.models import (
    EditorSubscription, RereviewQueueTheme, ReviewerScore, send_notifications,
    ViewFullReviewQueue, ViewPendingQueue,
    ViewUnlistedAllList)
from olympia.users.models import UserProfile


def create_search_ext(name, version_str, addon_status, file_status,
                      channel):
    addon, created_ = Addon.objects.get_or_create(
        name__localized_string=name,
        defaults={'type': amo.ADDON_SEARCH, 'name': name})
    version, created_ = Version.objects.get_or_create(
        addon=addon, version=version_str, defaults={'channel': channel})
    File.objects.create(version=version, filename=u"%s.xpi" % name,
                        platform=amo.PLATFORM_ALL.id, status=file_status)
    # Update status *after* there are files:
    addon = Addon.objects.get(pk=addon.id)
    addon.update(status=addon_status)
    return addon


class TestQueue(TestCase):
    """Tests common attributes and coercions that each view must support."""
    __test__ = False  # this is an abstract test case

    def test_latest_version(self):
        addon = self.new_addon()
        v1 = addon.find_latest_version(self.channel)
        v1.update(created=self.days_ago(2))
        v1.all_files[0].update(status=amo.STATUS_PUBLIC)
        version_factory(addon=addon, version='2.0', created=self.days_ago(1),
                        channel=self.channel,
                        file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=addon, version='3.0', created=self.days_ago(0),
                        channel=self.channel,
                        file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        row = self.Queue.objects.get()
        assert row.latest_version == '3.0'

    def test_addons_disabled_by_user_are_hidden(self):
        self.new_addon(version=u'0.1').update(disabled_by_user=True)
        assert list(self.Queue.objects.all()) == []

    def test_addons_disabled_by_admin_are_hidden(self):
        self.new_addon(version=u'0.1').update(status=amo.STATUS_DISABLED)
        assert list(self.Queue.objects.all()) == []

    def test_reviewed_files_are_hidden(self):
        self.new_addon(name='Unreviewed')
        addon_factory(name='Already Reviewed')
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Unreviewed'])

    def test_search_extensions(self):
        self.new_search_ext('Search Tool', '0.1')
        row = self.Queue.objects.get()
        assert row.addon_name == u'Search Tool'
        assert row.addon_type_id == amo.ADDON_SEARCH

    def test_count_all(self):
        # Create two new addons and give each another version.
        version_factory(addon=self.new_addon(), version=u'2.0',
                        channel=self.channel)
        version_factory(addon=self.new_addon(), version=u'2.0',
                        channel=self.channel)
        assert self.Queue.objects.all().count() == 2


class TestPendingQueue(TestQueue):
    __test__ = True
    Queue = ViewPendingQueue
    channel = amo.RELEASE_CHANNEL_LISTED

    def new_addon(self, name=u'Pending', version=u'1.0'):
        addon = addon_factory(
            name=name,
            version_kw={'version': u'0.0.1', 'channel': self.channel})
        version_factory(
            addon=addon, version=version, channel=self.channel,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW, 'no_restart': True})
        return addon

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_PUBLIC, amo.STATUS_AWAITING_REVIEW,
                                 channel=self.channel, **kw)

    def test_waiting_time(self):
        self.new_addon()
        Version.objects.update(created=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None

    def test_flags_admin_review(self):
        self.new_addon().update(admin_review=True)

        q = self.Queue.objects.get()
        assert q.flags == [('admin-review', 'Admin Review')]

    def test_flags_info_request(self):
        self.new_addon().find_latest_version(self.channel).update(
            has_info_request=True)
        q = self.Queue.objects.get()
        assert q.flags == [('info', 'More Information Requested')]

    def test_flags_editor_comment(self):
        self.new_addon().find_latest_version(self.channel).update(
            has_editor_comment=True)

        q = self.Queue.objects.get()
        assert q.flags == [('editor', 'Contains Reviewer Comment')]

    def test_flags_jetpack(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            jetpack_version='1.8')

        q = self.Queue.objects.get()
        assert q.flags == [('jetpack', 'Jetpack Add-on')]

    def test_flags_requires_restart(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            no_restart=False)

        q = self.Queue.objects.get()
        assert q.flags == [('requires_restart', 'Requires Restart')]

    def test_flags_sources_provided(self):
        self.new_addon().find_latest_version(self.channel).update(
            source='/some/source/file')

        q = self.Queue.objects.get()
        assert q.flags == [('sources-provided', 'Sources provided')]

    def test_flags_webextension(self):
        self.new_addon().find_latest_version(self.channel).all_files[0].update(
            is_webextension=True)

        queue = self.Queue.objects.get()
        assert queue.flags == [('webextension', 'WebExtension')]

    def test_no_flags(self):
        self.new_addon()

        q = self.Queue.objects.get()
        assert q.flags == []


class TestFullReviewQueue(TestQueue):
    __test__ = True
    Queue = ViewFullReviewQueue
    channel = amo.RELEASE_CHANNEL_LISTED

    def new_addon(self, name=u'Nominated', version=u'1.0',
                  addon_status=amo.STATUS_NOMINATED,
                  file_status=amo.STATUS_AWAITING_REVIEW):
        addon = addon_factory(
            name=name, status=addon_status,
            version_kw={'version': version, 'channel': self.channel},
            file_kw={'status': file_status})
        return addon

    def new_search_ext(self, name, version, **kw):
        return create_search_ext(name, version,
                                 amo.STATUS_NOMINATED,
                                 amo.STATUS_AWAITING_REVIEW,
                                 channel=self.channel, **kw)

    def test_waiting_time(self):
        self.new_addon()
        Version.objects.update(nomination=datetime.utcnow())
        row = self.Queue.objects.all()[0]
        assert row.waiting_time_days == 0
        # Time zone will be off, hard to test this.
        assert row.waiting_time_hours is not None


class TestUnlistedAllList(TestCase):
    Queue = ViewUnlistedAllList
    channel = amo.RELEASE_CHANNEL_UNLISTED
    fixtures = ['base/users']

    def new_addon(self, name=u'Unlisted', version=u'1.0',
                  addon_status=amo.STATUS_NULL,
                  file_status=amo.STATUS_PUBLIC):
        addon = addon_factory(
            name=name, status=addon_status,
            version_kw={'version': version, 'channel': self.channel},
            file_kw={'status': file_status})
        return addon

    def test_all_addons_are_in_q(self):
        self.new_addon('Public', addon_status=amo.STATUS_PUBLIC,
                       file_status=amo.STATUS_PUBLIC)
        self.new_addon('Nominated', addon_status=amo.STATUS_NOMINATED,
                       file_status=amo.STATUS_AWAITING_REVIEW)
        self.new_addon('Deleted', addon_status=amo.STATUS_PUBLIC,
                       file_status=amo.STATUS_PUBLIC).delete()
        assert sorted(q.addon_name for q in self.Queue.objects.all()) == (
            ['Deleted', 'Nominated', 'Public'])

    def test_authors(self):
        addon = self.new_addon()
        bert = user_factory(username='bert')
        ernie = user_factory(username='ernie')
        AddonUser.objects.create(addon=addon, user=bert)
        AddonUser.objects.create(addon=addon, user=ernie)
        row = self.Queue.objects.all()[0]
        self.assertSetEqual(set(row.authors),
                            {(ernie.id, 'ernie'), (bert.id, 'bert')})

    def test_last_reviewed_version(self):
        today = datetime.today().date()
        addon = self.new_addon(version='1.0')
        v2 = version_factory(addon=addon, version='2.0', channel=self.channel)
        log = amo.log(amo.LOG.APPROVE_VERSION, v2, v2.addon,
                      user=UserProfile.objects.get(pk=999))
        version_factory(addon=addon, version='3.0', channel=self.channel)
        row = self.Queue.objects.all()[0]
        assert row.review_date == today
        assert row.review_version_num == '2.0'
        assert row.review_log_id == log.id

    def test_no_developer_actions(self):
        addon = self.new_addon(version='1.0')
        amo.log(amo.LOG.ADD_VERSION, addon.latest_unlisted_version, addon,
                user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num is None

        ver2 = version_factory(version='2.0', addon=addon,
                               channel=self.channel)
        amo.log(amo.LOG.APPROVE_VERSION, ver2, addon,
                user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num == '2.0'

        ver3 = version_factory(version='3.0', addon=addon,
                               channel=self.channel)
        amo.log(amo.LOG.EDIT_VERSION, ver3, addon,
                user=UserProfile.objects.get(pk=999))
        row = self.Queue.objects.all()[0]
        # v2.0 is still the last reviewed version.
        assert row.review_version_num == '2.0'

    def test_no_automatic_reviews(self):
        ver = self.new_addon(
            name='addon789', version='1.0').latest_unlisted_version
        amo.log(amo.LOG.APPROVE_VERSION, ver, ver.addon,
                user=UserProfile.objects.get(pk=settings.TASK_USER_ID))
        row = self.Queue.objects.all()[0]
        assert row.review_version_num is None

    def test_latest_version(self):
        addon = addon_factory(
            version_kw={'version': u'0.1', 'channel': self.channel,
                        'created': self.days_ago(2)},
            file_kw={'created': self.days_ago(2)})
        version_factory(
            addon=addon, version=u'0.2', channel=self.channel,
            created=self.days_ago(1), file_kw={'created': self.days_ago(1)})
        version_factory(
            addon=addon, version=u'0.3', channel=self.channel)
        row = self.Queue.objects.get()
        assert row.latest_version == '0.3'

    def test_addons_disabled_by_user_are_hidden(self):
        self.new_addon().update(disabled_by_user=True)
        assert list(self.Queue.objects.all()) == []

    def test_addons_disabled_by_admin_are_hidden(self):
        self.new_addon(version=u'0.1').update(status=amo.STATUS_DISABLED)
        assert list(self.Queue.objects.all()) == []

    def test_count_all(self):
        addon1 = self.new_addon()
        version_factory(addon=addon1, version=u'0.2')
        addon2 = self.new_addon()
        version_factory(addon=addon2, version=u'0.2')
        assert self.Queue.objects.all().count() == 2

    def test_mixed_listed(self):
        unlisted_listed = addon_factory(
            status=amo.STATUS_NULL, name=u'UnlistedListed',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=unlisted_listed, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        listed_unlisted = addon_factory(
            status=amo.STATUS_NULL, name=u'ListedUnlisted',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=listed_unlisted, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        just_unlisted = addon_factory(
            status=amo.STATUS_NULL, name=u'JustUnlisted',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_UNLISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=just_unlisted, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_UNLISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        just_listed = addon_factory(
            status=amo.STATUS_NULL, name=u'JustListed',
            version_kw={'version': u'0.1',
                        'channel': amo.RELEASE_CHANNEL_LISTED},
            file_kw={'status': amo.STATUS_PUBLIC})
        version_factory(addon=just_listed, version=u'0.2',
                        channel=amo.RELEASE_CHANNEL_LISTED,
                        file_kw={'status': amo.STATUS_PUBLIC})

        assert self.Queue.objects.all().count() == 3
        assert [addon.addon_name for addon in self.Queue.objects.all()] == [
            'UnlistedListed', 'ListedUnlisted', 'JustUnlisted']
        assert ([addon.latest_version for addon in self.Queue.objects.all()] ==
                ['0.1', '0.2', '0.2'])


class TestEditorSubscription(TestCase):
    fixtures = ['base/addon_3615', 'base/users']

    def setUp(self):
        super(TestEditorSubscription, self).setUp()
        self.addon = Addon.objects.get(pk=3615)
        self.version = self.addon.current_version
        self.user_one = UserProfile.objects.get(pk=55021)
        self.user_two = UserProfile.objects.get(pk=999)
        for user in [self.user_one, self.user_two]:
            EditorSubscription.objects.create(addon=self.addon, user=user)

    def test_email(self):
        es = EditorSubscription.objects.get(user=self.user_one)
        es.send_notification(self.version)
        assert len(mail.outbox) == 1
        assert mail.outbox[0].to == [u'del@icio.us']
        assert mail.outbox[0].subject == (
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_notifications(self):
        send_notifications(sender=self.version)
        assert len(mail.outbox) == 2
        emails = sorted([o.to for o in mail.outbox])
        assert emails == [[u'del@icio.us'], [u'regular@mozilla.com']]

    def test_notifications_clean(self):
        send_notifications(Version, self.version)
        assert EditorSubscription.objects.count() == 0
        mail.outbox = []
        send_notifications(Version, self.version)
        assert len(mail.outbox) == 0

    def test_notifications_beta(self):
        self.version.all_files[0].update(status=amo.STATUS_BETA)
        version_uploaded.send(sender=self.version)
        assert len(mail.outbox) == 0

    def test_signal_edit(self):
        self.version.save()
        assert len(mail.outbox) == 0

    def test_signal_create(self):
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        assert len(mail.outbox) == 2
        assert mail.outbox[0].subject == (
            'Mozilla Add-ons: Delicious Bookmarks Updated')

    def test_signal_create_twice(self):
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        mail.outbox = []
        v = Version.objects.create(addon=self.addon)
        version_uploaded.send(sender=v)
        assert len(mail.outbox) == 0


class TestReviewerScore(TestCase):
    fixtures = ['base/users']

    def setUp(self):
        super(TestReviewerScore, self).setUp()
        self.addon = amo.tests.addon_factory(status=amo.STATUS_NOMINATED)
        self.user = UserProfile.objects.get(email='editor@mozilla.com')

    def _give_points(self, user=None, addon=None, status=None):
        user = user or self.user
        addon = addon or self.addon
        ReviewerScore.award_points(user, addon, status or addon.status)

    def check_event(self, type, status, event, **kwargs):
        self.addon.type = type
        assert ReviewerScore.get_event(self.addon, status, **kwargs) == event

    def test_events_addons(self):
        types = {
            amo.ADDON_ANY: None,
            amo.ADDON_EXTENSION: 'ADDON',
            amo.ADDON_THEME: 'THEME',
            amo.ADDON_DICT: 'DICT',
            amo.ADDON_SEARCH: 'SEARCH',
            amo.ADDON_LPAPP: 'LP',
            amo.ADDON_LPADDON: 'LP',
            amo.ADDON_PLUGIN: 'ADDON',
            amo.ADDON_API: 'ADDON',
            amo.ADDON_PERSONA: 'PERSONA',
        }
        statuses = {
            amo.STATUS_NULL: None,
            amo.STATUS_PENDING: None,
            amo.STATUS_NOMINATED: 'FULL',
            amo.STATUS_PUBLIC: 'UPDATE',
            amo.STATUS_DISABLED: None,
            amo.STATUS_BETA: None,
            amo.STATUS_DELETED: None,
            amo.STATUS_REJECTED: None,
            amo.STATUS_REVIEW_PENDING: None,
        }
        for tk, tv in types.items():
            for sk, sv in statuses.items():
                try:
                    event = getattr(amo, 'REVIEWED_%s_%s' % (tv, sv))
                except AttributeError:
                    try:
                        event = getattr(amo, 'REVIEWED_%s' % tv)
                    except AttributeError:
                        event = None
                self.check_event(tk, sk, event)

    def test_award_points(self):
        self._give_points()
        assert ReviewerScore.objects.all()[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_award_points_bonus(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        bonus_days = 2
        days = amo.REVIEWED_OVERDUE_LIMIT + bonus_days

        bonus_addon = addon_factory(
            status=amo.STATUS_NOMINATED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        bonus_addon.current_version.update(
            nomination=(datetime.now() - timedelta(days=days, minutes=5))
        )
        self._give_points(user2, bonus_addon, amo.STATUS_NOMINATED)
        score = ReviewerScore.objects.get(user=user2)
        expected = (amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
                    (amo.REVIEWED_OVERDUE_BONUS * bonus_days))

        assert score.score == expected

    def test_award_moderation_points(self):
        ReviewerScore.award_moderation_points(self.user, self.addon, 1)
        score = ReviewerScore.objects.all()[0]
        assert score.score == (
            amo.REVIEWED_SCORES.get(amo.REVIEWED_ADDON_REVIEW))
        assert score.note_key == amo.REVIEWED_ADDON_REVIEW

    def test_get_total(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        assert ReviewerScore.get_total(self.user) == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert ReviewerScore.get_total(user2) == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_recent(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        time.sleep(1)  # Wait 1 sec so ordering by created is checked.
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2)
        scores = ReviewerScore.get_recent(self.user)
        assert len(scores) == 2
        assert scores[0].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert scores[1].score == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

    def test_get_leaderboards(self):
        user2 = UserProfile.objects.get(email='regular@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['rank'] == 1
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert leaders['leader_top'][0]['total'] == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL] +
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_UPDATE])
        assert leaders['leader_top'][1]['rank'] == 2
        assert leaders['leader_top'][1]['user_id'] == user2.id
        assert leaders['leader_top'][1]['total'] == (
            amo.REVIEWED_SCORES[amo.REVIEWED_ADDON_FULL])

        self._give_points(
            user=user2, addon=amo.tests.addon_factory(type=amo.ADDON_PERSONA))
        leaders = ReviewerScore.get_leaderboards(
            self.user, addon_type=amo.ADDON_PERSONA)
        assert len(leaders['leader_top']) == 1
        assert leaders['leader_top'][0]['user_id'] == user2.id

    def test_no_admins_or_staff_in_leaderboards(self):
        user2 = UserProfile.objects.get(email='admin@mozilla.com')
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        leaders = ReviewerScore.get_leaderboards(self.user)
        assert leaders['user_rank'] == 1
        assert leaders['leader_near'] == []
        assert leaders['leader_top'][0]['user_id'] == self.user.id
        assert len(leaders['leader_top']) == 1  # Only the editor is here.
        assert user2.id not in [l['user_id'] for l in leaders['leader_top']], (
            'Unexpected admin user found in leaderboards.')

    def test_get_leaderboards_last(self):
        users = []
        for i in range(6):
            users.append(UserProfile.objects.create(username='user-%s' % i))
        last_user = users.pop(len(users) - 1)
        for u in users:
            self._give_points(user=u)
        # Last user gets lower points by reviewing a persona.
        addon = self.addon
        addon.type = amo.ADDON_PERSONA
        self._give_points(user=last_user, addon=addon)
        leaders = ReviewerScore.get_leaderboards(last_user)
        assert leaders['user_rank'] == 6
        assert len(leaders['leader_top']) == 3
        assert len(leaders['leader_near']) == 2

    def test_all_users_by_score(self):
        user2 = UserProfile.objects.get(email='regular@mozilla.com')
        amo.REVIEWED_LEVELS[0]['points'] = 180
        self._give_points()
        self._give_points(status=amo.STATUS_PUBLIC)
        self._give_points(user=user2, status=amo.STATUS_NOMINATED)
        users = ReviewerScore.all_users_by_score()
        assert len(users) == 2
        # First user.
        assert users[0]['total'] == 200
        assert users[0]['user_id'] == self.user.id
        assert users[0]['level'] == amo.REVIEWED_LEVELS[0]['name']
        # Second user.
        assert users[1]['total'] == 120
        assert users[1]['user_id'] == user2.id
        assert users[1]['level'] == ''

    def test_caching(self):
        self._give_points()

        with self.assertNumQueries(1):
            ReviewerScore.get_total(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_total(self.user)

        with self.assertNumQueries(1):
            ReviewerScore.get_recent(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_recent(self.user)

        with self.assertNumQueries(1):
            ReviewerScore.get_leaderboards(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_leaderboards(self.user)

        with self.assertNumQueries(1):
            ReviewerScore.get_breakdown(self.user)
        with self.assertNumQueries(0):
            ReviewerScore.get_breakdown(self.user)

        # New points invalidates all caches.
        self._give_points()

        with self.assertNumQueries(1):
            ReviewerScore.get_total(self.user)
        with self.assertNumQueries(1):
            ReviewerScore.get_recent(self.user)
        with self.assertNumQueries(1):
            ReviewerScore.get_leaderboards(self.user)
        with self.assertNumQueries(1):
            ReviewerScore.get_breakdown(self.user)


class TestRereviewQueueTheme(TestCase):

    def test_manager_soft_delete_addons(self):
        """Test manager excludes soft delete add-ons."""
        # Normal RQT object.
        RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')

        # Deleted add-on RQT object.
        addon = addon_factory(type=amo.ADDON_PERSONA)
        RereviewQueueTheme.objects.create(
            theme=addon.persona, header='', footer='')
        addon.delete()

        assert RereviewQueueTheme.objects.count() == 1
        assert RereviewQueueTheme.unfiltered.count() == 2

    def test_footer_path_without_footer(self):
        rqt = RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')
        assert rqt.footer_path == ''

    def test_footer_url_without_footer(self):
        rqt = RereviewQueueTheme.objects.create(
            theme=addon_factory(type=amo.ADDON_PERSONA).persona, header='',
            footer='')
        assert rqt.footer_url == ''

    def test_filter_for_many_to_many(self):
        # Check https://bugzilla.mozilla.org/show_bug.cgi?id=1142035.
        addon = addon_factory(type=amo.ADDON_PERSONA)
        rqt = RereviewQueueTheme.objects.create(theme=addon.persona)
        assert addon.persona.rereviewqueuetheme_set.get() == rqt

        # Delete the addon: it shouldn't be listed anymore.
        addon.update(status=amo.STATUS_DELETED)
        assert addon.persona.rereviewqueuetheme_set.all().count() == 0
