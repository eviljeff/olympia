from collections import namedtuple

from django.utils.translation import ugettext_lazy as _

from olympia.constants import applications


_PromotedSuperClass = namedtuple(
    '_PromotedSuperClass', [
        # Be careful when adding to this list to adjust defaults too.
        'id',
        'name',
        'api_name',
        'search_ranking_bump',
        'warning',
        'pre_review',
        'admin_review',
        'badged',
        'autograph_signing_states',
    ],
    defaults=(
        # "Since fields with a default value must come after any fields without
        # a default, the defaults are applied to the rightmost parameters"
        0,  # search_ranking_bump
        True,  # warning
        False,  # pre_review
        False,  # admin_review
        False,  # badged
        {},  # autograph_signing_states - should be a dict of App.short: state
    )
)


class PromotedClass(_PromotedSuperClass):
    __slots__ = ()

    def __bool__(self):
        return bool(self.id)


NOT_PROMOTED = PromotedClass(
    id=0,
    name=_('Not Promoted'),
    api_name='not_promoted',
)

RECOMMENDED = PromotedClass(
    id=1,
    name=_('Recommended'),
    api_name='recommended',
    search_ranking_bump=1000,  # TODO: confirm this bump
    warning=False,
    pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'recommended',
        applications.ANDROID.short: 'recommended-android'},
)

VERIFIED_ONE = PromotedClass(
    id=2,
    name=_('Sponsored'),
    api_name='sponsored',
    search_ranking_bump=500,  # TODO: confirm this bump
    warning=False,
    pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'verified',
        applications.ANDROID.short: 'verified'},
)

VERIFIED_TWO = PromotedClass(
    id=3,
    name=_('Verified'),
    api_name='verified',
    warning=False,
    pre_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'verified',
        applications.ANDROID.short: 'verified'},
)

LINE = PromotedClass(
    id=4,
    name=_('By Firefox'),
    api_name='line',
    warning=False,
    pre_review=True,
    admin_review=True,
    badged=True,
    autograph_signing_states={
        applications.FIREFOX.short: 'line',
        applications.ANDROID.short: 'line'},
)

SPOTLIGHT = PromotedClass(
    id=5,
    name=_('Spotlight'),
    api_name='spotlight',
    warning=False,
    pre_review=True,
    admin_review=True,
)

STRATEGIC = PromotedClass(
    id=6,
    name=_('Strategic'),
    api_name='strategic',
    admin_review=True,
)

PROMOTED_GROUPS = [
    NOT_PROMOTED,
    RECOMMENDED,
    VERIFIED_ONE,
    VERIFIED_TWO,
    LINE,
    SPOTLIGHT,
    STRATEGIC,
]

PRE_REVIEW_GROUPS = [group for group in PROMOTED_GROUPS if group.pre_review]

PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS}
ENABLED_PROMOTED_GROUPS_BY_ID = {p.id: p for p in PROMOTED_GROUPS if p}
