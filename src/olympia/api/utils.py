from django.conf import settings

from extended_choices import Choices
from extended_choices.helpers import ChoiceEntry


def is_gate_active(request, name):
    """Check if a specific gate is active for the current API version.
    Note that `request` has to be a :class:`~rest_framework.request.Request`
    object that has `version` attached.
    We're not examining Django request objects.
    """
    gates = settings.DRF_API_GATES.get(getattr(request, 'version', None), None)
    if not gates:
        return False

    return name in gates


class APIChoiceEntry(ChoiceEntry):
    @property
    def api_value(self):
        return str(self.value).lower() if self.value else self.value


class APIChoices(Choices):
    """Like a regular extended_choices.Choices class, with an extra api_choices
    property that exposes constants in lower-case, meant to be used as choices
    in an API."""

    ChoiceEntryClass = APIChoiceEntry

    @property
    def api_choices(self):
        return tuple((entry[1], entry[0].lower()) for entry in self.entries)


class APIChoicesWithNone(APIChoices):
    """Like APIChoices, but also returns 'None' as a valid choice for `choices`
    and `api_choices` properties."""

    @property
    def choices(self):
        return ((None, 'None'),) + super().choices

    @property
    def api_choices(self):
        return ((None, None),) + super().api_choices
