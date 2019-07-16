from django.db import models
from django.conf import settings

from olympia.amo.models import ModelBase
from olympia.discovery.models import DiscoveryItem


class PrimaryHero(ModelBase):
    image = models.CharField(max_length=255)
    background_color = models.CharField(max_length=7)
    enabled = models.BooleanField(db_index=True, null=False, default=False,)
    disco_addon = models.OneToOneField(DiscoveryItem, on_delete=models.CASCADE)

    @property
    def image_path(self):
        return f'{settings.STATIC_URL}img/icons/hero/{self.image}'


class SecondaryHero(ModelBase):
    headline = models.CharField(max_length=50)
    copy = models.CharField(max_length=100)
    link_url = models.CharField(max_length=255)
    link_text = models.CharField(max_length=20)

    @property
    def link(self):
        return {
            'href': self.link_url,
            'text': self.link_text,
        }


class SecondaryHeroModule(ModelBase):
    shelf = models.OneToOneField(SecondaryHero, on_delete=models.CASCADE)
    icon = models.CharField(max_length=255)
    copy = models.CharField(max_length=50)
    link_url = models.CharField(max_length=255)
    link_text = models.CharField(max_length=20)
    enabled = models.BooleanField(db_index=True, null=False, default=False,)

    @property
    def icon_path(self):
        return f'{settings.STATIC_URL}img/icons/hero/{self.image}'

    @property
    def link(self):
        return {
            'href': self.link_url,
            'text': self.link_text,
        }
