import mimetypes

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.functional import classproperty

import requests

from olympia import amo
from olympia.amo.utils import (
    backup_storage_enabled,
    copy_file_to_backup_storage,
    create_signed_url_for_file_backup,
)


class CinderEntity:
    # This queue is for reports that T&S / TaskUs look at
    _queue = 'content-infringement'
    type = None  # Needs to be defined by subclasses

    @classproperty
    def queue(cls):
        return f'{settings.CINDER_QUEUE_PREFIX}{cls._queue}'

    @property
    def id(self):
        # Ideally override this in subclasses to be more efficient
        return self.get_str(self.get_attributes().get('id', ''))

    def get_str(self, field_content):
        return str(field_content or '')

    def get_attributes(self):
        raise NotImplementedError

    def get_context(self):
        raise NotImplementedError

    def get_entity_data(self):
        return {'entity_type': self.type, 'attributes': self.get_attributes()}

    def get_relationship_data(self, to, relationship_type):
        return {
            'source_id': self.id,
            'source_type': self.type,
            'target_id': to.id,
            'target_type': to.type,
            'relationship_type': relationship_type,
        }

    def get_extended_attributes(self):
        # Extended attributes are only returned with reports (not as part of
        # relationships or reporter data for instance) as they require as they
        # are more expensive to compute. Media that we need to make a copy of
        # are typically returned there instead of in get_attributes().
        return {}

    def build_report_payload(self, *, report_text, category, reporter):
        context = self.get_context()
        if reporter:
            reporter_entity_data = reporter.get_entity_data()
            if reporter_entity_data not in context['entities']:
                context['entities'] += [reporter.get_entity_data()]
            context['relationships'] += [
                reporter.get_relationship_data(self, 'amo_reporter_of')
            ]
        entity_attributes = {**self.get_attributes(), **self.get_extended_attributes()}
        return {
            'queue_slug': self.queue,
            'entity_type': self.type,
            'entity': entity_attributes,
            'reasoning': report_text,
            # FIXME: pass category in report_metadata ?
            # 'report_metadata': ??
            'context': context,
        }

    def report(self, *, report_text, category, reporter):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}create_report'
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }
        data = self.build_report_payload(
            report_text=report_text, category=category, reporter=reporter
        )
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            return response.json().get('job_id')
        else:
            raise ConnectionError(response.content)

    def appeal(self, *, decision_id, appeal_text, appealer):
        if self.type is None:
            # type needs to be defined by subclasses
            raise NotImplementedError
        url = f'{settings.CINDER_SERVER_URL}appeal'
        headers = {
            'accept': 'application/json',
            'content-type': 'application/json',
            'authorization': f'Bearer {settings.CINDER_API_TOKEN}',
        }
        data = {
            'queue_slug': self.queue,
            'appealer_entity_type': appealer.type,
            'appealer_entity': appealer.get_attributes(),
            'reasoning': appeal_text,
            'decision_to_appeal_id': decision_id,
        }
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 201:
            return response.json().get('external_id')
        else:
            raise ConnectionError(response.content)


class CinderUser(CinderEntity):
    type = 'amo_user'

    def __init__(self, user):
        self.user = user

    @property
    def id(self):
        return self.get_str(self.user.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'created': self.get_str(self.user.created),
            'email': self.user.email,
            'fxa_id': self.user.fxa_id,
            'name': self.user.display_name,
        }

    def get_extended_attributes(self):
        data = {}
        if (
            self.user.picture_type
            and backup_storage_enabled()
            and storage.exists(self.user.picture_path)
        ):
            filename = copy_file_to_backup_storage(
                self.user.picture_path, self.user.picture_type
            )
            data['avatar'] = {
                'value': create_signed_url_for_file_backup(filename),
                'mime_type': self.user.picture_type,
            }
        data.update(
            {
                'average_rating': int(self.user.averagerating or 0),
                'num_addons_listed': self.user.num_addons_listed,
                'biography': self.get_str(self.user.biography),
                'homepage': self.get_str(self.user.homepage),
                'location': self.get_str(self.user.location),
                'occupation': self.get_str(self.user.occupation),
            }
        )
        return data

    def get_context(self):
        cinder_addons = [
            CinderAddon(addon)
            for addon in self.user.addons.all()
            .only_translations()
            .select_related('promotedaddon')
        ]
        return {
            'entities': [
                cinder_addon.get_entity_data() for cinder_addon in cinder_addons
            ],
            'relationships': [
                self.get_relationship_data(cinder_addon, 'amo_author_of')
                for cinder_addon in cinder_addons
            ],
        }


class CinderUnauthenticatedReporter(CinderEntity):
    type = 'amo_unauthenticated_reporter'

    def __init__(self, name, email):
        self.name = name
        self.email = email

    def get_attributes(self):
        return {
            'id': f'{self.name} : {self.email}',
            'name': self.name,
            'email': self.email,
        }

    def get_context(self):
        return {}

    def report(self, *args, **kwargs):
        # It doesn't make sense to report a non fxa user
        raise NotImplementedError

    def appeal(self, *args, **kwargs):
        # It doesn't make sense to report a non fxa user
        raise NotImplementedError


class CinderAddon(CinderEntity):
    type = 'amo_addon'

    def __init__(self, addon, version=None):
        self.addon = addon
        self.version = version

    @property
    def id(self):
        return self.get_str(self.addon.id)

    def get_attributes(self):
        # FIXME: translate translated fields in reporter's locale, send as
        # dictionaries?
        # We look at the promoted group to tell whether or not the add-on has
        # a badge, but we don't care about the promotion being approved for the
        # current version, it would make more queries and it's not useful for
        # moderation purposes anyway.
        promoted_group = self.addon.promoted_group(currently_approved=False)
        data = {
            'id': self.id,
            'average_daily_users': self.addon.average_daily_users,
            'guid': self.addon.guid,
            'last_updated': self.get_str(self.addon.last_updated),
            'name': self.get_str(self.addon.name),
            'slug': self.addon.slug,
            'summary': self.get_str(self.addon.summary),
            'promoted_badge': self.get_str(
                promoted_group.name if promoted_group.badged else ''
            ),
        }
        return data

    def get_extended_attributes(self):
        data = {}
        if backup_storage_enabled():
            if self.addon.icon_type:
                icon_size = max(amo.ADDON_ICON_SIZES)
                icon_type, _ = mimetypes.guess_type(f'icon.{amo.ADDON_ICON_FORMAT}')
                icon_path = self.addon.get_icon_path(icon_size)
                if icon_type and storage.exists(icon_path):
                    filename = copy_file_to_backup_storage(icon_path, icon_type)
                    data['icon'] = {
                        'value': create_signed_url_for_file_backup(filename),
                        'mime_type': icon_type,
                    }
            previews = []
            preview_objs = list(self.addon.previews.all()) + list(
                # For themes, we automatically generate 2 previews with
                # different sizes and format, we only need to expose one.
                self.addon.current_version.previews.all().filter(
                    position=amo.THEME_PREVIEW_RENDERINGS['amo']['position']
                )
                if self.addon.current_version
                else []
            )
            for preview in preview_objs:
                content_type, _ = mimetypes.guess_type(preview.thumbnail_path)
                if content_type and storage.exists(preview.thumbnail_path):
                    filename = copy_file_to_backup_storage(
                        preview.thumbnail_path, content_type
                    )
                    previews.append(
                        {
                            'value': create_signed_url_for_file_backup(filename),
                            'mime_type': content_type,
                        }
                    )
            if previews:
                data['previews'] = previews

        # Those fields are only shown on the detail page, so we only have them
        # in extended attributes to avoid sending them when we send an add-on
        # as a related entity to something else.
        data['description'] = self.get_str(self.addon.description)
        if self.addon.current_version:
            data['version'] = self.get_str(self.addon.current_version.version)
            data['release_notes'] = self.get_str(
                self.addon.current_version.release_notes
            )
        # In addition, the URL/email fields can't be sent if blank as they
        # would not be considered valid by Cinder.
        for field in ('homepage', 'support_email', 'support_url'):
            if value := getattr(self.addon, field):
                data[field] = self.get_str(value)

        return data

    def get_context(self):
        cinder_users = [CinderUser(author) for author in self.addon.authors.all()]
        return {
            'entities': [cinder_user.get_entity_data() for cinder_user in cinder_users],
            'relationships': [
                cinder_user.get_relationship_data(self, 'amo_author_of')
                for cinder_user in cinder_users
            ],
        }


class CinderRating(CinderEntity):
    type = 'amo_rating'

    def __init__(self, rating):
        self.rating = rating

    @property
    def id(self):
        return self.get_str(self.rating.id)

    def get_attributes(self):
        return {
            'id': self.id,
            'body': self.rating.body,
            'score': self.rating.rating,
        }

    def get_context(self):
        # Note: we are not currently sending the add-on the rating is for as
        # part of the context.
        cinder_user = CinderUser(self.rating.user)
        context = {
            'entities': [cinder_user.get_entity_data()],
            'relationships': [
                cinder_user.get_relationship_data(self, 'amo_rating_author_of'),
            ],
        }
        if reply_to := getattr(self.rating, 'reply_to', None):
            cinder_reply_to = CinderRating(reply_to)
            context['entities'].append(cinder_reply_to.get_entity_data())
            context['relationships'].append(
                cinder_reply_to.get_relationship_data(self, 'amo_rating_reply_to')
            )
        return context


class CinderCollection(CinderEntity):
    type = 'amo_collection'

    def __init__(self, collection):
        self.collection = collection

    @property
    def id(self):
        return self.get_str(self.collection.id)

    def get_attributes(self):
        # FIXME: translate translated fields in reporter's locale, send as
        # dictionaries?
        return {
            'id': self.id,
            'comments': self.collection.get_all_comments(),
            'description': self.get_str(self.collection.description),
            'modified': self.get_str(self.collection.modified),
            'name': self.get_str(self.collection.name),
            'slug': self.collection.slug,
        }

    def get_context(self):
        cinder_user = CinderUser(self.collection.author)
        return {
            'entities': [cinder_user.get_entity_data()],
            'relationships': [
                cinder_user.get_relationship_data(self, 'amo_collection_author_of')
            ],
        }


class CinderAddonHandledByReviewers(CinderAddon):
    # This queue is not monitored on cinder - reports are resolved via AMO instead
    _queue = 'addon-infringement'

    def flag_for_human_review(self, appeal=False):
        from olympia.reviewers.models import NeedsHumanReview

        reason = (
            NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION_APPEAL
            if appeal
            else NeedsHumanReview.REASON_ABUSE_ADDON_VIOLATION
        )
        if self.version:
            NeedsHumanReview.objects.get_or_create(
                version=self.version, reason=reason, is_active=True
            )
        else:
            self.addon.set_needs_human_review_on_latest_versions(
                reason=reason, ignore_reviewed=False, unique_reason=True
            )

    def report(self, *args, **kwargs):
        self.flag_for_human_review(appeal=False)
        return super().report(*args, **kwargs)

    def appeal(self, *args, **kwargs):
        self.flag_for_human_review(appeal=True)
        return super().appeal(*args, **kwargs)
