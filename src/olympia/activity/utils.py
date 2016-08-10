import base64
import chardet
import datetime
import logging
import quopri
import re
import urllib2
from email import message_from_string
from email.utils import parseaddr

from django.conf import settings
from django.template import Context, loader

from email_reply_parser import EmailReplyParser

from olympia import amo
from olympia.access import acl
from olympia.activity.models import ActivityLogToken
from olympia.amo.helpers import absolutify
from olympia.amo.urlresolvers import reverse
from olympia.amo.utils import send_mail
from olympia.devhub.models import ActivityLog

log = logging.getLogger('z.amo.activity')

# Prefix of the reply to address in devcomm emails.
REPLY_TO_PREFIX = 'reviewreply+'


class ActivityEmailError(ValueError):
    pass


class ActivityEmailEncodingError(ActivityEmailError):
    pass


class ActivityEmailUUIDError(ActivityEmailError):
    pass


class ActivityEmailParser(object):
    """Utility to parse email replies."""
    address_prefix = REPLY_TO_PREFIX

    def __init__(self, email_text):
        """Decode base64 email and turn it into a Django email object."""
        try:
            email_text = base64.standard_b64decode(
                urllib2.unquote(email_text.rstrip()))
        except TypeError:
            log.exception('Decoding error for ActivityEmailParser reply parse')
            raise ActivityEmailEncodingError(
                'Corrupt or invalid base64 encoding')

        self.email = message_from_string(email_text)

        payload = self.email.get_payload()
        if isinstance(payload, list):
            # If multipart, get the plain text part.
            for part in payload:
                # Nested multipart. Go deeper.
                if part.get_content_type() == 'multipart/alternative':
                    payload = part.get_payload()
                    for part in payload:
                        if part.get_content_type() == 'text/plain':
                            # Found the plain text part.
                            payload = part.get_payload()
                            break

                if part.get_content_type() == 'text/plain':
                    # Found the plain text part.
                    payload = part.get_payload()
                    break

        # Decode quoted-printable data and remove non-breaking spaces.
        payload = (quopri.decodestring(payload)
                         .replace('\xc2\xa0', ' '))
        payload = self.extra_email_reply_parse(payload)
        content = self.decode_content(payload)
        self.reply_text = EmailReplyParser.read(content).reply

    def decode_content(self, content):
        charset = self.email.get_content_charset('utf-8')
        try:
            return content.decode(charset)
        except UnicodeDecodeError:
            # Scenarios like no-breaking space in utf-8 which should be latin-1
            # encoding :-/
            charset = chardet.detect(content)
            return content.decode(charset['encoding'])
        except AttributeError:
            return content

    def extra_email_reply_parse(self, email):
        """
        Adds an extra case to the email reply parser where the reply is
        followed by headers like "From: amo-editors@mozilla.org" and
        strips that part out.
        """
        email_header_re = re.compile('From: [^@]+@[^@]+\.[^@]+')
        split_email = email_header_re.split(email)
        if split_email[0].startswith('From: '):
            # In case, it's a bottom reply, return everything.
            return email
        else:
            # Else just return the email reply portion.
            return split_email[0]

    def _get_address_line(self):
        return parseaddr(self.email['to']) or parseaddr(self.email(['reply']))

    def get_uuid(self):
        name, addr = self._get_address_line()

        if addr.startswith(self.address_prefix):
            # Strip everything between "reviewreply+" and the "@" sign.
            uuid = addr[len(self.address_prefix):].split('@')[0]
        else:
            log.exception(
                'TO: address missing or not related to activity emails. (%s)'
                % unicode(self.email).strip())
            raise ActivityEmailUUIDError(
                'TO: address doesn\'t contain activity email uuid (%s)'
                % addr)

        return uuid

    def get_body(self):
        return self.reply_text


def add_email_to_activity_log(email_text):
    log.debug("Saving from email reply")

    try:
        parser = ActivityEmailParser(email_text)
        uuid = parser.get_uuid()
        token = ActivityLogToken.objects.get(uuid=uuid)
    except ActivityLogToken.DoesNotExist:
        log.error('An email was skipped with non-existing uuid %s.' % uuid)
        return False
    except ActivityEmailError:
        # We logged already when the exception occurred.
        return False

    version = token.version
    user = token.user
    if token.is_valid():
        log_type = None

        review_perm = 'Review' if version.addon.is_listed else 'ReviewUnlisted'
        if version.addon.authors.filter(pk=user.pk).exists():
            log_type = amo.LOG.DEVELOPER_REPLY_VERSION
        elif acl.action_allowed_user(user, 'Addons', review_perm):
            log_type = amo.LOG.REVIEWER_REPLY_VERSION

        if log_type:
            note = log_and_notify(log_type, parser.get_body(), user, version)
            log.info('A new note has been created (from %s using tokenid %s).'
                     % (user.id, uuid))
            token.increment_use()
            return note
        else:
            log.error('%s did not have perms to reply to email thread %s.'
                      % (user.email, version.id))
    else:
        log.error('%s tried to use an invalid activity email token for '
                  'version %s.' % (user.email, version.id))

    return False


def log_and_notify(action, comments, note_creator, version):
    log_kwargs = {
        'user': note_creator,
        'created': datetime.datetime.now(),
        'details': {
            'comments': comments,
            'version': version.version}}
    note = amo.log(action, version.addon, version, **log_kwargs)

    # Collect reviewers/others involved with this version.
    log_users = [
        alog.user for alog in ActivityLog.objects.for_version(version)]
    # Collect add-on authors (excl. the person who sent the email.)
    addon_authors = set(version.addon.authors.all()) - {note_creator}
    # Collect reviewers on the thread (again, excl. the email sender)
    reviewer_recipients = set(log_users) - addon_authors - {note_creator}
    author_context_dict = {
        'name': version.addon.name,
        'number': version.version,
        'author': note_creator.name,
        'comments': comments,
        'url': version.addon.get_dev_url('versions'),
        'SITE_URL': settings.SITE_URL,
    }
    reviewer_context_dict = author_context_dict.copy()
    reviewer_context_dict['url'] = absolutify(
        reverse('editors.review', args=[version.addon.pk], add_prefix=False))

    # Not being localised because we don't know the recipients locale.
    subject = 'Mozilla Add-ons: %s Updated' % version.addon.name
    template = loader.get_template('activity/emails/developer.txt')
    send_activity_mail(
        subject, template.render(Context(author_context_dict)), version,
        addon_authors, settings.EDITORS_EMAIL)
    send_activity_mail(
        subject, template.render(Context(reviewer_context_dict)), version,
        reviewer_recipients, settings.EDITORS_EMAIL)
    return note


def send_activity_mail(subject, message, version, recipients, from_email,
                       perm_setting=None):
    for recipient in recipients:
        token, created = ActivityLogToken.objects.get_or_create(
            version=version, user=recipient)
        if not created:
            token.update(use_count=0)
        else:
            # We need .uuid to be a real UUID not just a str.
            token.reload()
            log.info('Created token with UUID %s for user: %s.' % (
                token.uuid, recipient.id))
        reply_to = "%s%s@%s" % (
            REPLY_TO_PREFIX, token.uuid.hex, settings.POSTFIX_DOMAIN)
        log.info('Sending activity email to %s for %s version %s' % (
            recipient, version.addon.pk, version.pk))
        send_mail(
            subject, message, recipient_list=[recipient.email],
            from_email=from_email, use_blacklist=False,
            perm_setting=perm_setting, reply_to=[reply_to])
