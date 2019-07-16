from rest_framework import serializers

from olympia.amo.templatetags.jinja_helpers import absolutify
from olympia.discovery.serializers import DiscoverySerializer

from .models import PrimaryHero, SecondaryHero, SecondaryHeroModule


class PrimaryHeroShelfSerializer(serializers.ModelSerializer):
    featured_image = serializers.SerializerMethodField()
    discovery = DiscoverySerializer(source='disco_addon')

    class Meta:
        model = PrimaryHero
        fields = ('featured_image', 'background_color', 'discovery')

    def get_featured_image(self, obj):
        return absolutify(obj.image_path)


class SecondaryHeroItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecondaryHeroModule
        fields = ('icon_path', 'copy', 'link')


class SecondaryHeroShelfSerializer(serializers.ModelSerializer):
    items = SecondaryHeroItemSerializer(
        source='secondaryheromodule', many=True)

    class Meta:
        model = SecondaryHero
        fields = ('headline', 'copy', 'link', 'items')
