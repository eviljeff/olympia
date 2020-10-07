import json
from unittest import mock

from django.conf import settings
from django.utils.encoding import force_text

from olympia import amo
from olympia.amo.tests import (
    addon_factory, APITestClient, ESTestCase, reverse_ns)
from olympia.constants.promoted import RECOMMENDED, VERIFIED_ONE, VERIFIED_TWO
from olympia.promoted.models import PromotedAddon
from olympia.shelves.models import Shelf, ShelfManagement


class TestShelfViewSet(ESTestCase):
    client_class = APITestClient

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()

        # Shouldn't be necessary, but just in case.
        cls.empty_index('default')

        addon_factory(
            name='test addon test01', type=amo.ADDON_EXTENSION,
            average_daily_users=46812, weekly_downloads=132, summary=None)
        addon_factory(
            name='test addon test02', type=amo.ADDON_STATICTHEME,
            average_daily_users=18981, weekly_downloads=145, summary=None)
        addon_ext = addon_factory(
            name='test addon test03', type=amo.ADDON_EXTENSION,
            average_daily_users=482, weekly_downloads=506, summary=None)
        addon_theme = addon_factory(
            name='test addon test04', type=amo.ADDON_STATICTHEME,
            average_daily_users=8838, weekly_downloads=358, summary=None)

        PromotedAddon.objects.create(
            addon=addon_ext, group_id=RECOMMENDED.id
        ).approve_for_version(version=addon_ext.current_version)

        PromotedAddon.objects.create(
            addon=addon_theme, group_id=RECOMMENDED.id
        ).approve_for_version(version=addon_theme.current_version)

        cls.refresh()

    def setUp(self):
        self.url = reverse_ns('shelves-list')

        shelf_a = Shelf.objects.create(
            title='Recommended extensions',
            endpoint='search',
            criteria='?promoted=recommended&sort=random&type=extension',
            footer_text='See more recommended extensions')
        shelf_b = Shelf.objects.create(
            title='Enhanced privacy extensions',
            endpoint='collections',
            criteria='privacy-matters',
            footer_text='See more enhanced privacy extensions')
        shelf_c = Shelf.objects.create(
            title='Popular themes',
            endpoint='search',
            criteria='?sort=users&type=statictheme',
            footer_text='See more popular themes')

        self.hpshelf_a = ShelfManagement.objects.create(
            shelf=shelf_a,
            position=3)
        self.hpshelf_b = ShelfManagement.objects.create(
            shelf=shelf_b,
            position=2)
        ShelfManagement.objects.create(
            shelf=shelf_c,
            position=1)

        self.search_url = reverse_ns('addon-search') + shelf_a.criteria

        self.collections_url = reverse_ns('collection-addon-list', kwargs={
            'user_pk': settings.TASK_USER_ID,
            'collection_slug': shelf_b.criteria})

    def test_no_enabled_shelves_empty_view(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        assert response.json() == {
            'count': 0,
            'next': None,
            'page_count': 1,
            'page_size': 25,
            'previous': None,
            'results': []}

    def test_only_enabled_shelves_in_view(self):
        self.hpshelf_a.update(enabled=True)
        self.hpshelf_b.update(enabled=True)
        # don't enable shelf_c

        with self.assertNumQueries(4):
            response = self.client.get(self.url)
        assert response.status_code == 200

        result = json.loads(response.content)

        assert len(result['results']) == 2

        assert result['results'][0]['title'] == 'Enhanced privacy extensions'
        assert result['results'][0]['url'] == self.collections_url
        assert result['results'][0]['endpoint'] == 'collections'
        assert result['results'][0]['criteria'] == 'privacy-matters'
        assert result['results'][0]['footer_text'] == (
            'See more enhanced privacy extensions')
        assert result['results'][0]['footer_pathname'] == ''
        assert result['results'][0]['addons'] is None

        assert result['results'][1]['title'] == 'Recommended extensions'
        assert result['results'][1]['url'] == self.search_url
        assert result['results'][1]['endpoint'] == 'search'
        assert result['results'][1]['criteria'] == (
            '?promoted=recommended&sort=random&type=extension')
        assert result['results'][1]['footer_text'] == (
            'See more recommended extensions')
        assert result['results'][1]['footer_pathname'] == ''
        assert result['results'][1]['addons'][0]['name']['en-US'] == (
            'test addon test03')
        assert result['results'][1]['addons'][0]['promoted']['category'] == (
            'recommended')
        assert result['results'][1]['addons'][0]['type'] == 'extension'


class TestSponsoredShelfViewSet(ESTestCase):
    client_class = APITestClient

    def setUp(self):
        super().setUp()
        self.url = reverse_ns('sponsored-shelf-list')

        self.sponsored_ext = addon_factory(
            name='test addon test01', type=amo.ADDON_EXTENSION)
        self.make_addon_promoted(
            self.sponsored_ext, VERIFIED_ONE, approve_version=True)
        self.sponsored_theme = addon_factory(
            name='test addon test02', type=amo.ADDON_STATICTHEME)
        self.make_addon_promoted(
            self.sponsored_theme, VERIFIED_ONE, approve_version=True)
        self.verified_ext = addon_factory(
            name='test addon test03', type=amo.ADDON_EXTENSION)
        self.make_addon_promoted(
            self.verified_ext, VERIFIED_TWO, approve_version=True)
        self.not_promoted = addon_factory(name='test addon test04')
        self.refresh()

    def tearDown(self):
        super().tearDown()
        self.empty_index('default')
        self.refresh()

    def perform_search(self, *, url=None, data=None, expected_status=200,
                       expected_queries=0, page_size=6, **headers):
        url = url or self.url
        with self.assertNumQueries(expected_queries):
            response = self.client.get(url, data, **headers)
        assert response.status_code == expected_status, response.content
        data = json.loads(force_text(response.content))
        assert data['next'] is None
        assert data['previous'] is None
        assert data['page_size'] == page_size
        assert data['page_count'] == 1
        assert data['impression_url'] == reverse_ns(
            'sponsored-shelf-impression')
        assert data['impression_data'] is None
        return data

    def test_no_adzerk_addons(self):
        with mock.patch('olympia.shelves.views.get_addons_from_adzerk') as get:
            get.return_value = {}
            data = self.perform_search()
            get.assert_called_with(6)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_basic(self):
        with mock.patch('olympia.shelves.views.get_addons_from_adzerk') as get:
            get.return_value = {
                str(self.sponsored_ext.id): {
                    'addon_id': str(self.sponsored_ext.id),
                    'impression': '123456',
                    'click': 'abcdef'},
                str(self.sponsored_theme.id): {
                    'addon_id': str(self.sponsored_theme.id),
                    'impression': '012345',
                    'click': 'bcdefg'},
            }
            data = self.perform_search()
            get.assert_called_with(6), get.call_args
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert {itm['id'] for itm in data['results']} == {
            self.sponsored_ext.pk, self.sponsored_theme.pk}

    def test_adzerk_returns_none_sponsored(self):
        with mock.patch('olympia.shelves.views.get_addons_from_adzerk') as get:
            get.return_value = {
                str(self.sponsored_ext.id): {
                    'addon_id': str(self.sponsored_ext.id),
                    'impression': '123456',
                    'click': 'abcdef'},
                str(self.sponsored_theme.id): {
                    'addon_id': str(self.sponsored_theme.id),
                    'impression': '012345',
                    'click': 'bcdefg'},
                str(self.verified_ext.id): {
                    'addon_id': str(self.verified_ext.id),
                    'impression': '55656',
                    'click': 'efef'},
                str(self.not_promoted.id): {
                    'addon_id': str(self.not_promoted.id),
                    'impression': '735754',
                    'click': 'jydh'},
                '0': {
                    'addon_id': '0',
                    'impression': '',
                    'click': ''},
            }
            data = self.perform_search()
            get.assert_called_with(6)
        # non sponsored are ignored
        assert data['count'] == 2
        assert len(data['results']) == 2
        assert {itm['id'] for itm in data['results']} == {
            self.sponsored_ext.pk, self.sponsored_theme.pk}

    def test_page_size(self):
        with mock.patch('olympia.shelves.views.get_addons_from_adzerk') as get:
            get.return_value = {}
            data = self.perform_search(
                url=self.url + '?page_size=4', page_size=4)
            get.assert_called_with(4)
        assert data['count'] == 0
        assert len(data['results']) == 0

    def test_impression_endpoint(self):
        url = reverse_ns('sponsored-shelf-impression')
        with self.assertNumQueries(0):
            response = self.client.post(url)
        assert response.status_code == 200

    def test_click_endpoint(self):
        url = reverse_ns('sponsored-shelf-click')
        with self.assertNumQueries(0):
            response = self.client.post(url)
        assert response.status_code == 200
