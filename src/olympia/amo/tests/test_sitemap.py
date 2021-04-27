import datetime
import os
from collections import namedtuple
from unittest import mock

from django.conf import settings
from django.test import override_settings
from django.urls import reverse

from olympia import amo
from olympia.addons.models import AddonCategory
from olympia.amo.sitemap import (
    AccountSitemap,
    AddonSitemap,
    AMOSitemap,
    build_sitemap,
    CategoriesSitemap,
    CollectionSitemap,
    get_sitemap_path,
    get_sitemap_section_pages,
    sitemaps,
)
from olympia.amo.tests import (
    addon_factory,
    collection_factory,
    license_factory,
    user_factory,
)
from olympia.constants.categories import CATEGORIES

from .test_views import TEST_SITEMAPS_DIR


def test_addon_sitemap():
    addon_a = addon_factory(
        privacy_policy='privacy!',
        eula='eula!',
        version_kw={'license': license_factory()},
    )
    # addon_factory generates licenses by default, but always with a builtin >0
    addon_b = addon_factory()
    addon_b.update(last_updated=datetime.datetime(2020, 1, 1, 1, 1, 1))
    addon_c = addon_factory(
        eula='only eula', version_kw={'license': license_factory(builtin=1)}
    )
    addon_d = addon_factory(privacy_policy='only privacy')
    addon_factory(status=amo.STATUS_NOMINATED)  # shouldn't show up
    sitemap = AddonSitemap()
    assert list(sitemap.items()) == [
        (addon_d.last_updated, addon_d.slug, 'detail'),
        (addon_c.last_updated, addon_c.slug, 'detail'),
        (addon_a.last_updated, addon_a.slug, 'detail'),
        (addon_b.last_updated, addon_b.slug, 'detail'),
        (addon_d.last_updated, addon_d.slug, 'privacy'),
        (addon_a.last_updated, addon_a.slug, 'privacy'),
        (addon_c.last_updated, addon_c.slug, 'eula'),
        (addon_a.last_updated, addon_a.slug, 'eula'),
        (addon_a.last_updated, addon_a.slug, 'license'),
    ]
    for item in sitemap.items():
        assert sitemap.location(item) == reverse(
            'addons.' + item.urlname, args=[item.slug]
        )
        assert '/en-US/firefox/' in sitemap.location(item)
        assert sitemap.lastmod(item) == item.last_updated


def test_amo_sitemap():
    sitemap = AMOSitemap()
    for item in sitemap.items():
        assert sitemap.location(item) == reverse(item)


def test_categories_sitemap():
    sitemap = CategoriesSitemap()
    # without any addons we should still generate a url for each category
    empty_cats = list(sitemap.items())
    assert empty_cats == [
        *(
            (category, 1)
            for category in CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION].values()
        ),
        *(
            (category, 1)
            for category in CATEGORIES[amo.FIREFOX.id][amo.ADDON_STATICTHEME].values()
        ),
    ]
    # add some addons and check we generate extra pages when frontend would paginate
    bookmarks_category = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['bookmarks']
    shopping_category = CATEGORIES[amo.FIREFOX.id][amo.ADDON_EXTENSION]['shopping']
    AddonCategory.objects.create(
        addon=addon_factory(category=bookmarks_category), category=shopping_category
    )
    AddonCategory.objects.create(
        addon=addon_factory(category=shopping_category), category=bookmarks_category
    )
    addon_factory(category=bookmarks_category)
    addon_factory(category=shopping_category, status=amo.STATUS_NOMINATED)
    # should be 3 addons in shopping (one not public, so 2 public), and 3 in bookmarks

    patched_drf_setting = dict(settings.REST_FRAMEWORK)
    patched_drf_setting['PAGE_SIZE'] = 2
    with override_settings(REST_FRAMEWORK=patched_drf_setting):
        cats_with_addons = list(sitemap.items())
    # only one extra url, for a second bookmarks category page, because PAGE_SIZE = 2
    extra = (bookmarks_category, 2)
    assert extra in cats_with_addons
    assert set(cats_with_addons) - set(empty_cats) == {extra}


def test_collection_sitemap(mozilla_user):
    collection_a = collection_factory(
        author=mozilla_user, modified=datetime.datetime(2020, 1, 1, 1, 1, 1)
    )
    collection_b = collection_factory(
        author=mozilla_user, modified=datetime.datetime(2020, 2, 2, 2, 2, 2)
    )

    collection_factory(author=user_factory())  # not mozilla user
    sitemap = CollectionSitemap()
    assert list(sitemap.items()) == [
        (collection_b.modified, collection_b.slug, mozilla_user.id),
        (collection_a.modified, collection_a.slug, mozilla_user.id),
    ]
    for item in sitemap.items():
        assert sitemap.location(item) == reverse(
            'collections.detail', args=[mozilla_user.id, item.slug]
        )
        assert '/en-US/firefox/' in sitemap.location(item)
        assert sitemap.lastmod(item) == item.modified


def test_accounts_sitemap():
    user_with_themes = user_factory()
    user_with_extensions = user_factory()
    user_with_both = user_factory()
    user_factory()  # no addons
    extension = addon_factory(users=(user_with_extensions, user_with_both))
    theme = addon_factory(
        type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
    )
    sitemap = AccountSitemap()
    items = list(sitemap.items())
    assert items == [
        (theme.last_updated, user_with_both.id, 1, 1),
        (theme.last_updated, user_with_themes.id, 1, 1),
        (extension.last_updated, user_with_extensions.id, 1, 1),
    ]
    for item in sitemap.items():
        url = reverse('users.profile', args=[item.id])
        if item[2] > 1 and item[3] > 1:
            assert sitemap.location(item) == url + f'?page_e={item[2]}&page_t={item[3]}'
        elif item[2] > 1:
            assert sitemap.location(item) == url + f'?page_e={item[2]}'
        elif item[3] > 1:
            assert sitemap.location(item) == url + f'?page_t={item[3]}'
        else:
            assert sitemap.location(item) == url
    # add some extra extensions and themes to test pagination
    extra_extension_a = addon_factory(users=(user_with_extensions, user_with_both))
    extra_extension_b = addon_factory(users=(user_with_extensions, user_with_both))
    extra_theme_a = addon_factory(
        type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
    )
    extra_theme_b = addon_factory(
        type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
    )
    extra_theme_c = addon_factory(
        type=amo.ADDON_STATICTHEME, users=(user_with_themes, user_with_both)
    )
    with mock.patch(
        'olympia.amo.sitemap.EXTENSIONS_BY_AUTHORS_PAGE_SIZE', 2
    ), mock.patch('olympia.amo.sitemap.THEMES_BY_AUTHORS_PAGE_SIZE', 3):
        sitemap = AccountSitemap()
        paginated_items = list(sitemap.items())
    assert paginated_items == [
        (extra_theme_c.last_updated, user_with_both.id, 1, 1),
        (extra_theme_c.last_updated, user_with_both.id, 1, 2),
        (extra_theme_c.last_updated, user_with_both.id, 2, 1),
        (extra_theme_c.last_updated, user_with_both.id, 2, 2),
        (extra_theme_c.last_updated, user_with_themes.id, 1, 1),
        (extra_theme_c.last_updated, user_with_themes.id, 1, 2),
        (extra_extension_b.last_updated, user_with_extensions.id, 1, 1),
        (extra_extension_b.last_updated, user_with_extensions.id, 2, 1),
    ]
    # repeat, but after changing some of the addons so they wouldn't be visible
    with mock.patch(
        'olympia.amo.sitemap.EXTENSIONS_BY_AUTHORS_PAGE_SIZE', 2
    ), mock.patch('olympia.amo.sitemap.THEMES_BY_AUTHORS_PAGE_SIZE', 3):
        extra_theme_a.update(status=amo.STATUS_NOMINATED)
        sitemap = AccountSitemap()
        assert list(sitemap.items()) == [
            # now only one page of themes for both users
            (extra_theme_c.last_updated, user_with_both.id, 1, 1),
            (extra_theme_c.last_updated, user_with_both.id, 2, 1),
            (extra_theme_c.last_updated, user_with_themes.id, 1, 1),
            (extra_extension_b.last_updated, user_with_extensions.id, 1, 1),
            (extra_extension_b.last_updated, user_with_extensions.id, 2, 1),
        ]
        user_with_both.addonuser_set.filter(addon=extra_extension_a).update(
            listed=False
        )
        assert list(sitemap.items()) == [
            (extra_theme_c.last_updated, user_with_both.id, 1, 1),
            (extra_theme_c.last_updated, user_with_themes.id, 1, 1),
            (extra_extension_b.last_updated, user_with_extensions.id, 1, 1),
            # user_with_extensions still has 2 pages of extensions though
            (extra_extension_b.last_updated, user_with_extensions.id, 2, 1),
        ]
        extra_theme_c.delete()
        assert list(sitemap.items()) == [
            # the date used for lastmod has changed
            (extra_theme_b.last_updated, user_with_both.id, 1, 1),
            (extra_theme_b.last_updated, user_with_themes.id, 1, 1),
            (extra_extension_b.last_updated, user_with_extensions.id, 1, 1),
            # user_with_extensions still has 2 pages of extensions though
            (extra_extension_b.last_updated, user_with_extensions.id, 2, 1),
        ]
        # and check that deleting roles works too
        user_with_both.addonuser_set.filter(addon=extra_theme_b).update(
            role=amo.AUTHOR_ROLE_DELETED
        )
        assert list(sitemap.items()) == [
            # the date used for lastmod has changed, and the order too
            (extra_theme_b.last_updated, user_with_themes.id, 1, 1),
            (extra_extension_b.last_updated, user_with_both.id, 1, 1),
            (extra_extension_b.last_updated, user_with_extensions.id, 1, 1),
            (extra_extension_b.last_updated, user_with_extensions.id, 2, 1),
        ]


def test_get_sitemap_section_pages():
    addon_factory()
    addon_factory()
    addon_factory()
    assert list(sitemaps.keys()) == [
        'amo',
        'addons',
        'categories',
        'collections',
        'users',
    ]

    pages = get_sitemap_section_pages()
    assert pages == [
        ('amo', 1),
        ('addons', 1),
        ('categories', 1),
        ('collections', 1),
        ('users', 1),
    ]
    with mock.patch.object(AddonSitemap, 'limit', 2):
        pages = get_sitemap_section_pages()
        assert pages == [
            ('amo', 1),
            ('addons', 1),
            ('addons', 2),
            ('categories', 1),
            ('collections', 1),
            ('users', 1),
        ]


def test_build_sitemap():
    # test the index sitemap build first
    with mock.patch('olympia.amo.sitemap.get_sitemap_section_pages') as pages_mock:
        pages_mock.return_value = [
            ('amo', 1),
            ('addons', 1),
            ('addons', 2),
        ]
        built = build_sitemap()

        with open(os.path.join(TEST_SITEMAPS_DIR, 'sitemap.xml')) as sitemap:
            assert built == sitemap.read()

    # then a section build
    def items_mock(self):
        AddonValuesList = namedtuple('AddonValuesList', 'last_updated,slug,urlname')
        return [
            AddonValuesList(
                datetime.datetime(2020, 10, 2, 0, 0, 0), 'delicious-pierogi', 'detail'
            ),
            AddonValuesList(
                datetime.datetime(2020, 10, 1, 0, 0, 0), 'swanky-curry', 'detail'
            ),
            AddonValuesList(
                datetime.datetime(2020, 9, 30, 0, 0, 0), 'spicy-pierogi', 'detail'
            ),
        ]

    with mock.patch.object(AddonSitemap, 'items', items_mock):
        built = build_sitemap('addons')

        with open(os.path.join(TEST_SITEMAPS_DIR, 'sitemap-addons-2.xml')) as sitemap:
            assert built == sitemap.read()


def test_get_sitemap_path():
    path = settings.SITEMAP_STORAGE_PATH
    assert get_sitemap_path() == f'{path}/sitemap.xml'
    assert get_sitemap_path('foo') == f'{path}/sitemap-foo.xml'
    assert get_sitemap_path('foo', 1) == f'{path}/sitemap-foo.xml'
    assert get_sitemap_path('foo', 2) == f'{path}/sitemap-foo-2.xml'
