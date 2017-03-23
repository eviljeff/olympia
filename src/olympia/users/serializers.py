from __future__ import absolute_import
from rest_framework import serializers

from olympia.amo.helpers import absolutify
from olympia.users.models import UserProfile


class BaseUserSerializer(serializers.ModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = UserProfile
        fields = ('id', 'name', 'url')

    def get_url(self, obj):
        return absolutify(obj.get_url_path())
