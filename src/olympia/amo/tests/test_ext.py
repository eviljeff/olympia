from __future__ import absolute_import
import jingo
import mock
import pytest

from olympia.amo.utils import render


pytestmark = pytest.mark.django_db


@mock.patch('caching.ext.cache._cache_support')
def test_app_in_fragment_cache_key(cache_mock):
    cache_mock.return_value = ''
    request = mock.Mock()
    request.APP.id = '<app>'
    request.user.is_authenticated.return_value = False
    template = jingo.get_env().from_string('{% cache 1 %}{% endcache %}')
    render(request, template)
    assert cache_mock.call_args[0][0].endswith('<app>')


@mock.patch('caching.ext.cache._cache_support')
def test_fragment_cache_key_no_app(cache_mock):
    cache_mock.return_value = 'xx'
    template = jingo.get_env().from_string('{% cache 1 %}{% endcache %}')
    assert template.render() == 'xx'
    assert cache_mock.called
