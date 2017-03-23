# -*- coding: utf-8 -*-
from __future__ import absolute_import
import logging
import mock

import olympia.core.logger
from olympia.amo.tests import TestCase
from olympia.users.models import UserProfile


class LoggerTests(TestCase):
    @mock.patch('olympia.core.get_remote_addr', lambda: '127.0.0.1')
    @mock.patch('olympia.core.get_user', lambda: UserProfile(username=u'fôo'))
    def test_get_logger_adapter(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '127.0.0.1',
                'USERNAME': u'fôo',
            }
        }
        assert log.process('test msg', {}) == ('test msg', expected_kwargs)

    @mock.patch('olympia.core.get_remote_addr', lambda: '127.0.0.1')
    @mock.patch('olympia.core.get_user', lambda: None)
    def test_logger_adapter_user_is_none(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '127.0.0.1',
                'USERNAME': '<anon>',
            }
        }
        assert log.process('test msg', {}) == ('test msg', expected_kwargs)

    @mock.patch('olympia.core.get_remote_addr', lambda: None)
    @mock.patch('olympia.core.get_user', lambda: UserProfile(username='bar'))
    def test_logger_adapter_addr_is_none(self):
        log = olympia.core.logger.getLogger('test')
        expected_kwargs = {
            'extra': {
                'REMOTE_ADDR': '',
                'USERNAME': 'bar',
            }
        }
        assert log.process('test msg', {}) == ('test msg', expected_kwargs)

    def test_formatter(self):
        formatter = olympia.core.logger.Formatter()
        record = logging.makeLogRecord({})
        formatter.format(record)
        assert 'USERNAME' in record.__dict__
        assert 'REMOTE_ADDR' in record.__dict__
