import datetime

from django import forms

from olympia.addons.models import Addon

from .models import Block


class MultiBlockForm(forms.Form):
    input_guids = forms.CharField(widget=forms.HiddenInput())
    min_version = forms.ChoiceField(choices=(('0','0'),))
    max_version = forms.ChoiceField(choices=(('*','*'),))
    url = forms.CharField()
    reason = forms.CharField(widget=forms.Textarea())
    include_in_legacy = forms.BooleanField(
        help_text='Include in legacy xml blocklist too, as well as new v3')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request')
        super().__init__(*args, **kwargs)

    def process_input_guids(self, guids, return_objects=False):
        all_guids = set(guids.splitlines())

        block_qs = Block.objects.filter(guid__in=all_guids)
        existing = (
            [(block.guid, block) for block in block_qs]
            if return_objects else
            [(guid, None) for guid in block_qs.values_list('guid', flat=True)])
        remaining = all_guids - {guid for guid, _ in existing}

        addon_qs = Addon.unfiltered.filter(guid__in=remaining).order_by(
            '-average_daily_users')
        to_add = (
            [(addon.guid, Block(addon=addon))
                for addon in addon_qs.only_translations()]
            if return_objects else
            addon_qs.values_list('guid', 'average_daily_users'))
        # to_add = [(addon.guid, None ) for addon in addon_qs]
        invalids = remaining - {guid for guid, _ in to_add}

        assert (len(list(invalids)) + len(list(existing)) + len(list(to_add))) == len(all_guids), list(addon_qs)
        return {
            'invalids': list(invalids),
            'existing': list(existing),
            'to_add': list(to_add),
        }

    def save(self, commit=True):
        common_args = dict(self.cleaned_data)
        common_args.update(updated_by=self.request.user)
        processed_guids = self.process_input_guids(
            common_args.pop('input_guids'), return_objects=commit)

        common_args.update(modified=datetime.datetime.now())
        if commit:
            objects_to_add = [obj for _, obj in processed_guids['to_add']]
            objects_to_update = [obj for _, obj in processed_guids['existing']]
            for obj in objects_to_add + objects_to_update:
                for field, val in common_args.items():
                    setattr(obj, field, val)
            Block.objects.bulk_create(objects_to_add)
            guids_to_update = [guid for guid, _ in processed_guids['existing']]
            Block.objects.filter(guid__in=guids_to_update).update(
                **common_args)
            return (objects_to_add, objects_to_update)
        else:
            guids_to_add = [guid for guid, _ in processed_guids['to_add']]
            guids_to_update = [guid for guid, _ in processed_guids['existing']]
            return (guids_to_add, guids_to_update, common_args)
