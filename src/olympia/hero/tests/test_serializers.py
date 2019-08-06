from olympia import amo
from olympia.amo.tests import addon_factory, TestCase
from olympia.discovery.models import DiscoveryItem
from olympia.discovery.serializers import DiscoveryAddonSerializer

from ..models import GRADIENT_START_COLOR, PrimaryHero, SecondaryHero
from ..serializers import (
    ExternalAddonSerializer, PrimaryHeroShelfSerializer,
    SecondaryHeroShelfSerializer)


class TestPrimaryHeroShelfSerializer(TestCase):
    def test_basic(self):
        addon = addon_factory(summary='Summary')
        hero = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon,
                custom_heading='Its a héading!'),
            image='foo.png',
            gradient_color='#123456')
        data = PrimaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'featured_image': hero.image_path,
            'heading': 'Its a héading!',
            'description': '<blockquote>Summary</blockquote>',
            'gradient': {
                'start': GRADIENT_START_COLOR,
                'end': '#123456'
            },
            'addon': DiscoveryAddonSerializer(instance=addon).data,
        }

    def test_external_addon(self):
        addon = addon_factory(
            summary='Summary', homepage='https://foo.baa', version_kw={
                'channel': amo.RELEASE_CHANNEL_UNLISTED})
        hero = PrimaryHero.objects.create(
            disco_addon=DiscoveryItem.objects.create(
                addon=addon,
                custom_heading='Its a héading!'),
            image='foo.png',
            gradient_color='#123456',
            is_external=True)
        assert PrimaryHeroShelfSerializer(instance=hero).data == {
            'featured_image': hero.image_path,
            'heading': 'Its a héading!',
            'description': '<blockquote>Summary</blockquote>',
            'gradient': {
                'start': GRADIENT_START_COLOR,
                'end': '#123456'
            },
            'external': ExternalAddonSerializer(instance=addon).data,
        }
        assert ExternalAddonSerializer(instance=addon).data == {
            'id': addon.id,
            'guid': addon.guid,
            'homepage': {'en-US': str(addon.homepage)},
            'name': {'en-US': str(addon.name)},
            'type': 'extension',
        }


class TestSecondaryHeroShelfSerializer(TestCase):
    def test_basic(self):
        hero = SecondaryHero.objects.create(
            headline='Its a héadline!', description='description')
        data = SecondaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'headline': 'Its a héadline!',
            'description': 'description',
            'cta': None,
        }
        hero.update(cta_url='/extensions/', cta_text='Go here')
        data = SecondaryHeroShelfSerializer(instance=hero).data
        assert data == {
            'headline': 'Its a héadline!',
            'description': 'description',
            'cta': {
                'url': 'http://testserver/extensions/',
                'text': 'Go here',
            },
        }
