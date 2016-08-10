import logging

from django.conf import settings
from django.shortcuts import get_object_or_404

from rest_framework import status
from rest_framework.decorators import (api_view, authentication_classes,
                                       permission_classes)
from rest_framework.exceptions import ParseError
from rest_framework.mixins import ListModelMixin, RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet

from olympia import amo
from olympia.activity.serializers import ActivityLogSerializer
from olympia.activity.tasks import process_email
from olympia.addons.views import AddonChildMixin
from olympia.api.permissions import (
    AllowAddonAuthor, AllowReviewer, AllowReviewerUnlisted, AnyOf)
from olympia.devhub.models import ActivityLog
from olympia.versions.models import Version


class VersionReviewNotesViewSet(AddonChildMixin, RetrieveModelMixin,
                                ListModelMixin, GenericViewSet):
    permission_classes = [
        AnyOf(AllowAddonAuthor, AllowReviewer, AllowReviewerUnlisted),
    ]
    serializer_class = ActivityLogSerializer
    queryset = ActivityLog.objects.all()

    def get_queryset(self):
        addon = self.get_addon_object()
        version_object = get_object_or_404(
            Version.unfiltered.filter(addon=addon),
            pk=self.kwargs['version_pk'])
        alog = ActivityLog.objects.for_version(version_object)
        return alog.filter(action__in=amo.LOG_REVIEW_QUEUE_DEVELOPER)

    def get_addon_object(self):
        return super(VersionReviewNotesViewSet, self).get_addon_object(
            permission_classes=self.permission_classes)

    def check_object_permissions(self, request, obj):
        """Check object permissions against the Addon, not the ActivityLog."""
        # Just loading the add-on object triggers permission checks, because
        # the implementation in AddonChildMixin calls AddonViewSet.get_object()
        self.get_addon_object()


log = logging.getLogger('z.amo.mail')


class EmailCreationPermission(object):
    """Permit if client's IP address is allowed."""

    def has_permission(self, request, view):
        auth_token = request.META.get('HTTP_POSTFIX_AUTH_TOKEN', '')
        if not auth_token == settings.POSTFIX_AUTH_TOKEN:
            log.info('Invalid auth token [%s] provided' % (auth_token,))
            return False

        remote_ip = request.META.get('REMOTE_ADDR', '')
        if remote_ip not in settings.ALLOWED_CLIENTS_EMAIL_API:
            log.info('Request from invalid ip address [%s]' % (remote_ip,))
            return False

        return True


@api_view(['POST'])
@authentication_classes(())
@permission_classes((EmailCreationPermission,))
def post_email(request):
    email_body = request.data.get('body')
    if not email_body:
        raise ParseError(
            detail='email_body not present in the POST data.')

    process_email.apply_async((email_body,))
    return Response(status=status.HTTP_201_CREATED)
