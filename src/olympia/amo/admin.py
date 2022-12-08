import functools
import operator

from django.contrib import admin
from django.contrib.admin.views.main import ChangeList, ChangeListSearchForm, SEARCH_VAR
from django.core.exceptions import FieldDoesNotExist
from django.db import models
from django.db.models.constants import LOOKUP_SEP

from .models import FakeEmail


class CommaSearchInAdminChangeListSearchForm(ChangeListSearchForm):
    def clean(self):
        self.cleaned_data = super().clean()
        search_term = self.cleaned_data[SEARCH_VAR]
        if ',' in search_term:
            self.cleaned_data[SEARCH_VAR] = ','.join(
                term.strip() for term in search_term.split(',') if term.strip()
            )
        return self.cleaned_data


class CommaSearchInAdminChangeList(ChangeList):
    """Custom ChangeList companion for CommaSearchInAdminMixin, allowing to
    have a custom search form."""

    search_form_class = CommaSearchInAdminChangeListSearchForm


class CommaSearchInAdminMixin:
    def get_changelist(self, request, **kwargs):
        return CommaSearchInAdminChangeList

    def get_search_id_field(self, request):
        """
        Return the field to use when all search terms are numeric.

        Default is to return pk, but in some cases it'll make more sense to
        return a foreign key.
        """
        return 'pk'

    def lookup_spawns_duplicates(self, opts, lookup_path):
        """
        Return True if 'distinct()' should be used to query the given lookup
        path. Used by get_search_results() as a replacement of the version used
        by django, which doesn't consider our translation fields as needing
        distinct (but they do).
        """
        # The utility function was admin.utils.lookup_needs_distinct in django3.2;
        # it was renamed to admin.utils.lookup_spawns_duplicates in django4.0
        lookup_function = getattr(
            admin.utils, 'lookup_spawns_duplicates', None
        ) or getattr(admin.utils, 'lookup_needs_distinct')
        rval = lookup_function(opts, lookup_path)
        lookup_fields = lookup_path.split(LOOKUP_SEP)
        # Not pretty but looking up the actual field would require truly
        # resolving the field name, walking to any relations we find up until
        # the last one, that would be a lot of work for a simple edge case.
        if any(
            field_name in lookup_fields
            for field_name in ('localized_string', 'localized_string_clean')
        ):
            rval = True
        return rval

    def get_search_results(self, request, queryset, search_term):
        """
        Return a tuple containing a queryset to implement the search,
        and a boolean indicating if the results may contain duplicates.

        Originally copied from Django's, but with the following differences:
        - The operator joining the query parts is dynamic: if the search term
          contain a comma and no space, then the comma is used as the separator
          instead, and the query parts are joined by OR, not AND, allowing
          admins to search by a list of ids, emails or usernames and find all
          objects in that list.
        - If the search terms are all numeric and there is more than one, then
          we also restrict the fields we search to the one returned by
          get_search_id_field(request) using a __in ORM lookup directly.

        """
        # Apply keyword searches.
        def construct_search(field_name):
            if field_name.startswith('^'):
                return '%s__istartswith' % field_name[1:]
            elif field_name.startswith('='):
                return '%s__iexact' % field_name[1:]
            elif field_name.startswith('@'):
                return '%s__icontains' % field_name[1:]
            # Use field_name if it includes a lookup.
            opts = queryset.model._meta
            lookup_fields = field_name.split(models.constants.LOOKUP_SEP)
            # Go through the fields, following all relations.
            prev_field = None
            for path_part in lookup_fields:
                if path_part == 'pk':
                    path_part = opts.pk.name
                try:
                    field = opts.get_field(path_part)
                except FieldDoesNotExist:
                    # Use valid query lookups.
                    if prev_field and prev_field.get_lookup(path_part):
                        return field_name
                else:
                    prev_field = field
                    if hasattr(field, 'get_path_info'):
                        # Update opts to follow the relation.
                        opts = field.get_path_info()[-1].to_opts
            # Otherwise, use the field with icontains.
            return '%s__icontains' % field_name

        may_have_duplicates = False
        search_fields = self.get_search_fields(request)
        filters = []
        joining_operator = operator.and_
        if not (search_fields and search_term):
            # return early if we have nothing special to do
            return queryset, may_have_duplicates
        # Do our custom logic if a `,` is present. Note that our custom search
        # form (CommaSearchInAdminChangeListSearchForm) does some preliminary
        # cleaning when it sees a comma, trimming whitespace around each term.
        if ',' in search_term:
            separator = ','
            joining_operator = operator.or_
        else:
            separator = None
        search_terms = search_term.split(separator)
        if len(search_terms) >= self.minimum_search_terms_to_search_by_id and all(
            term.isnumeric() for term in search_terms
        ):
            # if we have at least minimum_search_terms_to_search_by_id terms
            # they are all numeric, we're doing a bulk id search
            orm_lookup = '%s__in' % self.get_search_id_field(request)
            queryset = queryset.filter(**{orm_lookup: search_terms})
        else:
            orm_lookups = [
                construct_search(str(search_field)) for search_field in search_fields
            ]
            for bit in search_terms:
                or_queries = [
                    models.Q(**{orm_lookup: bit}) for orm_lookup in orm_lookups
                ]

                q_for_this_term = models.Q(functools.reduce(operator.or_, or_queries))
                filters.append(q_for_this_term)

            may_have_duplicates |= any(
                # Use our own lookup_spawns_duplicates(), not django's.
                self.lookup_spawns_duplicates(self.opts, search_spec)
                for search_spec in orm_lookups
            )

            if filters:
                queryset = queryset.filter(functools.reduce(joining_operator, filters))
        return queryset, may_have_duplicates

    # Triggering a search by id only isn't always what the admin wants for an
    # all numeric query, but on the other hand is a nice optimization.
    # The default is 2 so that if there is a field in search_fields for which
    # it makes sense to search using a single numeric term, that still works,
    # the id-only search is only triggered for 2 or more terms. This should be
    # overriden by ModelAdmins where it makes sense to do so.
    minimum_search_terms_to_search_by_id = 2


@admin.register(FakeEmail)
class FakeEmailAdmin(admin.ModelAdmin):
    list_display = (
        'created',
        'message',
    )
    actions = ['delete_selected']
    view_on_site = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
