from rest_framework.mixins import ListModelMixin
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet

from .models import PrimaryHero, SecondaryHero
from .serializers import (
    PrimaryHeroShelfSerializer, SecondaryHeroShelfSerializer)


class ShelfViewSet(ListModelMixin, GenericViewSet):
    pagination_class = None

    def get_queryset(self):
        return super().get_queryset().filter(enabled=True).order_by('?')

    def get_first_data(self):
        return self.serializer_class(instance=self.get_queryset().first()).data


class PrimaryHeroShelfViewSet(ShelfViewSet):
    queryset = PrimaryHero.objects
    serializer_class = PrimaryHeroShelfSerializer


class SecondaryHeroShelfViewSet(ShelfViewSet):
    queryset = SecondaryHero.objects
    serializer_class = SecondaryHeroShelfSerializer


class HeroShelvesView(APIView):
    def get(self, request, format=None):
        output = {
            'primary': PrimaryHeroShelfViewSet().get_first_data(),
            'secondary': SecondaryHeroShelfViewSet().get_first_data(),
        }
        return Response(output)
