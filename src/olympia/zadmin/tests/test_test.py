import pytest

from django.conf import settings


@pytest.mark.static_assets
def test_foo():
    assert settings.FOO != 'default foo'
