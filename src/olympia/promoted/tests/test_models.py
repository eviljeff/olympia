from unittest import mock

from django.conf import settings

from olympia import amo, core
from olympia.activity.models import ActivityLog
from olympia.amo.tests import addon_factory, TestCase, user_factory, version_factory
from olympia.constants import applications, promoted
from olympia.promoted.models import (
    PromotedAddon,
    PromotedApproval,
)
from olympia.versions.utils import get_review_due_date


class TestPromotedAddon(TestCase):
    def test_basic(self):
        promoted_addon = PromotedAddon.objects.create(
            addon=addon_factory(), group_id=promoted.SPONSORED.id
        )
        assert promoted_addon.group == promoted.SPONSORED
        assert promoted_addon.application_id is None
        assert promoted_addon.all_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        promoted_addon.update(application_id=applications.FIREFOX.id)
        assert promoted_addon.all_applications == [applications.FIREFOX]

    def test_is_approved_applications(self):
        addon = addon_factory()
        promoted_addon = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.LINE.id
        )
        assert addon.promotedaddon
        # Just having the PromotedAddon instance isn't enough
        assert addon.promotedaddon.approved_applications == []

        # the current version needs to be approved also
        promoted_addon.approve_for_version(addon.current_version)
        addon.reload()
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

        # but not if it's for a different type of promotion
        promoted_addon.update(group_id=promoted.SPONSORED.id)
        assert addon.promotedaddon.approved_applications == []
        # unless that group has an approval too
        PromotedApproval.objects.create(
            version=addon.current_version,
            group_id=promoted.SPONSORED.id,
            application_id=applications.FIREFOX.id,
        )
        addon.reload()
        assert addon.promotedaddon.approved_applications == [applications.FIREFOX]

        # for promoted groups that don't require pre-review though, there isn't
        # a per version approval, so a current_version is sufficient and all
        # applications are seen as approved.
        promoted_addon.update(group_id=promoted.STRATEGIC.id)
        assert addon.promotedaddon.approved_applications == [
            applications.FIREFOX,
            applications.ANDROID,
        ]

    def test_auto_approves_addon_when_saved_for_immediate_approval(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        assert promo.group == promoted.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.immediate_approval == False
        promo.group_id = promoted.RECOMMENDED.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED

        # then with a group thats immediate_approval == True
        promo.group_id = promoted.SPOTLIGHT.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX]
        assert PromotedApproval.objects.count() == 1
        assert promo.addon.promoted_group() == promoted.SPOTLIGHT

        # test the edge case where the application was changed afterwards
        promo.application_id = 0
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == [amo.FIREFOX, amo.ANDROID]
        assert PromotedApproval.objects.count() == 2

    def test_addon_flagged_for_human_review_when_saved(self):
        # empty case with no group set
        promo = PromotedAddon.objects.create(
            addon=addon_factory(), application_id=amo.FIREFOX.id
        )
        listed_ver = promo.addon.current_version
        # throw in an unlisted version too
        unlisted_ver = version_factory(addon=promo.addon, channel=amo.CHANNEL_UNLISTED)
        assert promo.group == promoted.NOT_PROMOTED
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()

        # first test with a group.flag_for_human_review == False
        promo.group_id = promoted.RECOMMENDED.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert not listed_ver.reload().needs_human_review
        assert not unlisted_ver.reload().needs_human_review

        # then with a group thats flag_for_human_review == True but pretend
        # the version has already been reviewed by a human (so it's not
        # necessary to flag it as needing human review again).
        promo.addon.current_version.update(human_review_date=self.days_ago(1))
        promo.group_id = promoted.NOTABLE.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert not listed_ver.reload().needs_human_review
        assert not listed_ver.due_date
        assert not unlisted_ver.reload().needs_human_review
        assert not unlisted_ver.due_date

        # then with a group thats flag_for_human_review == True without the
        # version having been reviewed by a human but not signed: also not
        # flagged.
        promo.addon.current_version.update(human_review_date=None)
        promo.group_id = promoted.NOTABLE.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert not listed_ver.reload().needs_human_review
        assert not listed_ver.due_date
        assert not unlisted_ver.reload().needs_human_review
        assert not unlisted_ver.due_date

        # then with a group thats flag_for_human_review == True without the
        # version having been reviewed by a human but signed: this time we
        # should flag it.
        promo.addon.current_version.file.update(is_signed=True)
        promo.addon.current_version.update(human_review_date=None)
        promo.group_id = promoted.NOTABLE.id
        promo.save()
        promo.addon.reload()
        assert promo.approved_applications == []  # doesn't approve immediately
        assert not PromotedApproval.objects.exists()
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert listed_ver.reload().needs_human_review
        assert not unlisted_ver.reload().needs_human_review
        self.assertCloseToNow(listed_ver.due_date, now=get_review_due_date())
        assert not unlisted_ver.due_date

        # But we should only flag before the add-on is approved for Promoted
        promo.addon.current_version.update(needs_human_review=False)
        promo.approve_for_version(listed_ver)
        assert promo.addon.reload().promoted_group() == promoted.NOTABLE
        promo.save()
        promo.addon.reload()
        assert not listed_ver.reload().needs_human_review

    def test_disabled_and_deleted_versions_flagged_for_human_review(self):
        addon = addon_factory(
            file_kw={'status': amo.STATUS_DISABLED, 'is_signed': True}
        )
        version = addon.find_latest_version(None, exclude=(), deleted=True)
        promo = PromotedAddon.objects.create(
            addon=addon, application_id=amo.FIREFOX.id, group_id=promoted.NOTABLE.id
        )
        assert promo.addon.promoted_group() == promoted.NOT_PROMOTED
        assert version.reload().needs_human_review
        self.assertCloseToNow(version.due_date, now=get_review_due_date())

        # And if deleted too
        version.update(needs_human_review=False, due_date=None)
        version.delete()
        promo.save()
        assert version.reload().needs_human_review
        self.assertCloseToNow(version.due_date, now=get_review_due_date())

        # even if the add-on is deleted
        version.update(needs_human_review=False, due_date=None)
        addon.delete()
        promo.save()
        assert version.reload().needs_human_review
        self.assertCloseToNow(version.due_date, now=get_review_due_date())

    @mock.patch('olympia.lib.crypto.tasks.sign_file')
    def test_approve_for_addon(self, mock_sign_file):
        core.set_user(user_factory())
        task_user = user_factory(id=settings.TASK_USER_ID)
        promo = PromotedAddon.objects.create(
            addon=addon_factory(
                version_kw={'version': '0.123a'},
                file_kw={'filename': 'webextension.xpi'},
            ),
            group_id=promoted.SPOTLIGHT.id,
        )
        file_ = promo.addon.current_version.file
        # SPOTLIGHT doesnt have special signing states so won't be resigned
        promo.addon.reload()
        promo.addon.promoted_group() == promoted.NOT_PROMOTED
        promo.approve_for_addon()
        promo.addon.reload()
        promo.addon.promoted_group() == promoted.SPOTLIGHT
        assert promo.addon.current_version.version == '0.123a'
        mock_sign_file.assert_not_called()

        # VERIFIED does though.
        promo.update(group_id=promoted.VERIFIED.id)
        promo.addon.reload()
        promo.addon.promoted_group() == promoted.NOT_PROMOTED
        promo.approve_for_addon()
        promo.addon.reload()
        promo.addon.promoted_group() == promoted.VERIFIED
        assert promo.addon.current_version.version == '0.123a.1-signed'
        mock_sign_file.assert_called_with(file_)
        assert (
            ActivityLog.objects.for_addons((promo.addon,))
            .filter(action=amo.LOG.VERSION_RESIGNED.id)
            .exists()
        )
        alog = ActivityLog.objects.filter(action=amo.LOG.VERSION_RESIGNED.id).get()
        assert alog.user == task_user
        assert '0.123a.1-signed</a> re-signed (previously 0.123a)' in (str(alog))

    def test_get_resigned_version_number(self):
        addon = addon_factory(
            version_kw={'version': '0.123a'},
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        promo = PromotedAddon.objects.create(addon=addon, group_id=promoted.VERIFIED.id)
        assert addon.current_version is not None
        assert promo.get_resigned_version_number() is None

        addon.current_version.file.update(status=amo.STATUS_APPROVED)
        assert promo.get_resigned_version_number() == '0.123a.1-signed'

        addon.current_version.update(version='123.4.1-signed')
        assert promo.get_resigned_version_number() == '123.4.1-signed-2'

        addon.current_version.update(version='123.4.1-signed-2')
        assert promo.get_resigned_version_number() == '123.4.1-signed-3'

        addon.current_version.delete()
        addon.reload()
        assert addon.current_version is None
        assert promo.get_resigned_version_number() is None

    def test_signal(self):
        addon = addon_factory(file_kw={'status': amo.STATUS_AWAITING_REVIEW})
        unlisted = version_factory(
            addon=addon,
            channel=amo.CHANNEL_UNLISTED,
            file_kw={'status': amo.STATUS_AWAITING_REVIEW},
        )
        assert not addon.current_version.due_date
        assert not unlisted.due_date

        # If add-on is added to a pre-review promoted group it should get a due date
        promo = PromotedAddon.objects.create(
            addon=addon, group_id=promoted.RECOMMENDED.id
        )
        assert addon.current_version.reload().due_date
        assert not unlisted.reload().due_date  # not unlisted

        # but not if the group isn't prereview
        promo.update(group_id=promoted.STRATEGIC.id)
        assert not addon.current_version.reload().due_date
        assert not unlisted.reload().due_date  # not unlisted
