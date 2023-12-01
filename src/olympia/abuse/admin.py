from django.contrib import admin
from django.core.paginator import Paginator
from django.db.models import Count
from django.template import loader

from olympia import amo
from olympia.access import acl
from olympia.addons.models import Addon, AddonApprovalsCounter
from olympia.amo.admin import AMOModelAdmin, DateRangeFilter, FakeChoicesMixin
from olympia.ratings.models import Rating
from olympia.translations.utils import truncate_text

from .models import AbuseReport, CinderPolicy


class AbuseReportTypeFilter(admin.SimpleListFilter):
    # Human-readable title to be displayed in the sidebar just above the filter options.
    title = 'type'

    # Parameter for the filter that will be used in the URL query.
    parameter_name = 'type'

    def lookups(self, request, model_admin):
        """
        Returns a list of tuples. The first element in each
        tuple is the coded value for the option that will
        appear in the URL query. The second element is the
        human-readable name for the option that will appear
        in the right sidebar.
        """
        return (
            ('user', 'Users'),
            ('collection', 'Collections'),
            ('rating', 'Ratings'),
            ('addon', 'Add-ons'),
        )

    def queryset(self, request, queryset):
        """
        Returns the filtered queryset based on the value
        provided in the query string and retrievable via
        `self.value()`.
        """
        if self.value() == 'user':
            return queryset.filter(user__isnull=False)
        elif self.value() == 'collection':
            return queryset.filter(collection__isnull=False)
        elif self.value() == 'rating':
            return queryset.filter(rating__isnull=False)
        elif self.value() == 'addon':
            return queryset.filter(guid__isnull=False)
        return queryset


class MinimumReportsCountFilter(FakeChoicesMixin, admin.SimpleListFilter):
    """
    Custom filter for minimum reports count param.

    Does *not* do the actual filtering of the queryset, as it needs to be done
    with an aggregate query after all filters have been applied. That part is
    implemented in the model admin, see AbuseReportAdmin.get_search_results().

    Needs FakeChoicesMixin for the fake choices the template will be using.

    Original idea:
    https://hakibenita.com/how-to-add-a-text-filter-to-django-admin
    """

    template = 'admin/abuse/abusereport/minimum_reports_count_filter.html'
    title = 'minimum reports count (grouped by guid)'
    parameter_name = 'minimum_reports_count'

    def lookups(self, request, model_admin):
        """
        Fake lookups() method required to show the filter.
        """
        return ((),)

    def queryset(self, request, queryset):
        return queryset


class AbuseReportAdmin(AMOModelAdmin):
    class Media(AMOModelAdmin.Media):
        css = {
            'all': (
                'css/admin/amoadmin.css',
                'css/admin/abuse_reports.css',
            )
        }

    actions = ('delete_selected', 'mark_as_valid', 'mark_as_suspicious')
    date_hierarchy = 'modified'
    list_display = (
        'target_name',
        'guid',
        'type',
        'state',
        'distribution',
        'reason',
        'message_excerpt',
        'created',
    )
    list_filter = (
        AbuseReportTypeFilter,
        'state',
        'reason',
        ('created', DateRangeFilter),
        MinimumReportsCountFilter,
    )
    list_select_related = ('user', 'collection', 'rating')
    # Shouldn't be needed because those fields should all be readonly, but just
    # in case we change our mind, FKs should be raw id fields as usual in our
    # admin tools.
    raw_id_fields = ('user', 'collection', 'rating', 'reporter')
    # All fields except state must be readonly - the submitted data should
    # not be changed, only the state for triage.
    readonly_fields = (
        'created',
        'modified',
        'reporter',
        'reporter_name',
        'reporter_email',
        'country_code',
        'guid',
        'user',
        'collection',
        'rating',
        'message',
        'client_id',
        'addon_name',
        'addon_summary',
        'addon_version',
        'addon_signature',
        'application',
        'application_version',
        'application_locale',
        'operating_system',
        'operating_system_version',
        'install_date',
        'addon_install_origin',
        'addon_install_method',
        'addon_install_source',
        'addon_install_source_url',
        'report_entry_point',
        'addon_card',
        'location',
    )
    fieldsets = (
        ('Abuse Report Core Information', {'fields': ('state', 'reason', 'message')}),
        (
            'Abuse Report Data',
            {
                'fields': (
                    'created',
                    'modified',
                    'reporter',
                    'reporter_name',
                    'reporter_email',
                    'country_code',
                    'client_id',
                    'addon_signature',
                    'application',
                    'application_version',
                    'application_locale',
                    'operating_system',
                    'operating_system_version',
                    'install_date',
                    'addon_install_origin',
                    'addon_install_method',
                    'addon_install_source',
                    'addon_install_source_url',
                    'report_entry_point',
                    'location',
                )
            },
        ),
    )
    # The first fieldset is going to be dynamically added through
    # get_fieldsets() depending on the target (add-on, user, rating, collection,
    # or unknown add-on), using the fields below:
    dynamic_fieldset_fields = {
        # User
        'user': (('User', {'fields': ('user',)}),),
        # Collection
        'collection': (('Collection', {'fields': ('collection',)}),),
        # Rating
        'rating': (('Rating', {'fields': ('rating',)}),),
        # Add-on, we only have the guid and maybe some extra addon_*
        # fields that were submitted with the report, we'll try to display the
        # addon card if we can find a matching add-on in the database though.
        'guid': (
            ('Add-on', {'fields': ('addon_card',)}),
            (
                'Submitted Info',
                {'fields': ('addon_name', 'addon_version', 'guid', 'addon_summary')},
            ),
        ),
    }
    view_on_site = False  # Abuse reports have no public page to link to.

    def has_add_permission(self, request):
        # Adding new abuse reports through the admin is useless, so we prevent
        # it.
        return False

    def change_view(self, request, object_id, form_url='', extra_context=None):
        extra_context = extra_context or {}
        extra_context['show_save_and_continue'] = False  # Don't need this.
        return super().change_view(
            request,
            object_id,
            form_url,
            extra_context=extra_context,
        )

    def delete_queryset(self, request, queryset):
        """Given a queryset, soft-delete it from the database."""
        queryset.update(state=AbuseReport.STATES.DELETED)

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not acl.action_allowed_for(request.user, amo.permissions.ABUSEREPORTS_EDIT):
            # You need AbuseReports:Edit for the extra actions.
            actions.pop('mark_as_valid')
            actions.pop('mark_as_suspicious')
        return actions

    def get_search_fields(self, request):
        """
        Return search fields according to the type filter.
        """
        type_ = request.GET.get('type')
        if type_ == 'addon':
            search_fields = (
                'addon_name',
                'guid__startswith',
                'message',
            )
        elif type_ == 'user':
            search_fields = (
                'message',
                'user__id',
                'user__email__like',
            )
        elif type_ == 'collection':
            search_fields = (
                'message',
                'collection__slug',
            )
        elif type_ == 'rating':
            search_fields = (
                'message',
                'rating__id',
                'rating__body__like',
            )
        else:
            search_fields = ()
        return search_fields

    def get_search_id_field(self, request):
        """
        Return the field to use when all search terms are numeric, according to
        the type filter.
        """
        return (
            f'{request_type}_id'
            if request
            and (request_type := request.GET.get('type'))
            and request_type in ('user', 'rating', 'collection')
            else None
        )

    def get_search_results(self, request, qs, search_term):
        """
        Custom get_search_results() method that handles minimum_reports_count.
        """
        minimum_reports_count = request.GET.get('minimum_reports_count')
        if minimum_reports_count:
            # minimum_reports_count has its own custom filter class but the
            # filtering is actually done here, because it needs to happen after
            # all other filters have been applied in order for the aggregate
            # queryset to be correct.
            guids = (
                qs.values_list('guid', flat=True)
                .filter(guid__isnull=False)
                .annotate(Count('guid'))
                .filter(guid__count__gte=minimum_reports_count)
                .order_by()
            )
            qs = qs.filter(guid__in=list(guids))
        qs, use_distinct = super().get_search_results(request, qs, search_term)
        return qs, use_distinct

    def get_fieldsets(self, request, obj=None):
        if obj.user:
            target = 'user'
        elif obj.collection:
            target = 'collection'
        elif obj.rating:
            target = 'rating'
        else:
            target = 'guid'
        return self.dynamic_fieldset_fields[target] + self.fieldsets

    def target_name(self, obj):
        name = obj.user.name if obj.user else obj.addon_name
        return '{} {}'.format(name, obj.addon_version or '')

    target_name.short_description = 'User / Add-on'

    def addon_card(self, obj):
        # Note: this assumes we don't allow guids to be reused by developers
        # when deleting add-ons. That used to be true, so for historical data
        # it may not be the right add-on (for those cases, we don't know for
        # sure what the right add-on is).
        if not obj.guid:
            return ''
        try:
            addon = Addon.unfiltered.get(guid=obj.guid)
        except Addon.DoesNotExist:
            return ''

        template = loader.get_template('reviewers/addon_details_box.html')
        try:
            approvals_info = addon.addonapprovalscounter
        except AddonApprovalsCounter.DoesNotExist:
            approvals_info = None

        # Provide all the necessary context addon_details_box.html needs. Note
        # the use of Paginator() to match what the template expects.
        context = {
            'addon': addon,
            'addon_name': addon.name,
            'approvals_info': approvals_info,
            'reports': Paginator(
                AbuseReport.objects.all().for_addon(addon).exclude(pk=obj.pk), 5
            ).page(1),
            'user_ratings': Paginator(
                (
                    Rating.without_replies.filter(
                        addon=addon, rating__lte=3, body__isnull=False
                    ).order_by('-created')
                ),
                5,
            ).page(1),
            'version': addon.current_version,
        }
        return template.render(context)

    addon_card.short_description = ''

    def distribution(self, obj):
        return obj.get_addon_signature_display() if obj.addon_signature else ''

    distribution.short_description = 'Distribution'

    def reporter_country(self, obj):
        return obj.country_code

    reporter_country.short_description = "Reporter's country"

    def message_excerpt(self, obj):
        return truncate_text(obj.message, 140)[0] if obj.message else ''

    message_excerpt.short_description = 'Message excerpt'

    def mark_as_valid(self, request, qs):
        for obj in qs:
            obj.update(state=AbuseReport.STATES.VALID)
        self.message_user(
            request,
            'The %d selected reports have been marked as valid.' % (qs.count()),
        )

    mark_as_valid.short_description = 'Mark selected abuse reports as valid'

    def mark_as_suspicious(self, request, qs):
        for obj in qs:
            obj.update(state=AbuseReport.STATES.SUSPICIOUS)
        self.message_user(
            request,
            'The %d selected reports have been marked as suspicious.' % (qs.count()),
        )

    mark_as_suspicious.short_description = 'Mark selected abuse reports as suspicious'


class CinderPolicyAdmin(AMOModelAdmin):
    fields = (
        'created',
        'uuid',
        'name',
        'text',
    )
    list_display = (
        'uuid',
        'name',
    )
    readonly_fields = ('created',)
    view_on_site = False


admin.site.register(AbuseReport, AbuseReportAdmin)
admin.site.register(CinderPolicy, CinderPolicyAdmin)
