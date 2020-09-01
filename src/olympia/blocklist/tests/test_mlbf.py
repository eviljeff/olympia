from datetime import datetime
import json
import os
from random import randint
import tempfile
from unittest import mock

import pytest
from filtercascade import FilterCascade

from olympia import amo
from olympia.addons.models import GUID_REUSE_FORMAT
from olympia.amo.tests import (
    addon_factory, TestCase, user_factory, version_factory)
from olympia.blocklist.models import Block
from olympia.blocklist.mlbf import (
    DatabaseMLBF, generate_diffs, generate_mlbf,
    generate_and_write_mlbf, generate_and_write_periodic_mlbf,
    generate_and_write_stash, MLBF, PeriodicDatabaseMLBF, StoredMLBF)
from olympia.files.models import File


class TestMLBF(TestCase):

    def setup_data(self):
        user = user_factory()
        for idx in range(0, 5):
            addon_factory()
        addon = addon_factory()
        addon.current_version.all_files[0].update(
            modified=datetime(2019, 1, 1))
        # one version, 0 - *
        block = Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user)
        block.addon.current_version.all_files[0].update(
            modified=datetime(2019, 1, 1))
        # one version, 0 - 9999
        Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user,
            max_version='9999')
        # one version, 0 - *, unlisted
        Block.objects.create(
            addon=addon_factory(
                version_kw={'channel': amo.RELEASE_CHANNEL_UNLISTED},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user)
        # five versions, but only two within block (123.40, 123.5)
        self.five_ver_block = Block.objects.create(
            addon=addon_factory(
                version_kw={'version': '123.40'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user, max_version='123.45')
        self.five_ver_123_40 = self.five_ver_block.addon.current_version
        self.five_ver_123_5 = version_factory(
            addon=self.five_ver_block.addon, version='123.5', deleted=True,
            file_kw={'is_signed': True, 'is_webextension': True})
        self.five_ver_123_45_1 = version_factory(
            addon=self.five_ver_block.addon, version='123.45.1',
            file_kw={'is_signed': True, 'is_webextension': True})
        # these two would be included if they were signed and webextensions
        self.not_signed_version = version_factory(
            addon=self.five_ver_block.addon, version='123.5.1',
            file_kw={'is_signed': False, 'is_webextension': True})
        self.not_webext_version = version_factory(
            addon=self.five_ver_block.addon, version='123.5.2',
            file_kw={'is_signed': True, 'is_webextension': False})
        # no matching versions (edge cases)
        self.over = Block.objects.create(
            addon=addon_factory(
                version_kw={'version': '0.1'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user,
            max_version='0')
        self.under = Block.objects.create(
            addon=addon_factory(
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user,
            min_version='9999')

        # A blocked addon has been uploaded and deleted before
        reused_2_1_addon = addon_factory(
            # this a previous, superceeded, addon that should be included
            status=amo.STATUS_DELETED,  # they should all be deleted
            version_kw={'version': '2.1'},
            file_kw={'is_signed': True, 'is_webextension': True})
        self.addon_deleted_before_2_1_ver = reused_2_1_addon.versions.all()[0]
        reused_2_5_addon = addon_factory(
            # And this is an earlier addon that should also be included
            status=amo.STATUS_DELETED,  # they should all be deleted
            version_kw={'version': '2.5'},
            file_kw={'is_signed': True, 'is_webextension': True})
        self.addon_deleted_before_2_5_ver = reused_2_5_addon.versions.all()[0]
        current_addon = addon_factory(
            version_kw={'version': '2'},
            file_kw={'is_signed': True, 'is_webextension': True})
        self.addon_deleted_before_unblocked_ver = current_addon.current_version
        self.addon_deleted_before_unsigned_ver = version_factory(
            addon=current_addon, version='2.1',
            # not signed, but shouldn't override the signed 2.1 version
            file_kw={'is_signed': False, 'is_webextension': True})
        version_factory(
            addon=current_addon, version='3.0',
            file_kw={'is_signed': True, 'is_webextension': True})
        reused_2_1_addon.update(
            guid=GUID_REUSE_FORMAT.format(current_addon.id))
        reused_2_5_addon.update(
            guid=GUID_REUSE_FORMAT.format(reused_2_1_addon.id))
        reused_2_1_addon.addonguid.update(guid=current_addon.guid)
        reused_2_5_addon.addonguid.update(guid=current_addon.guid)
        self.addon_deleted_before_block = Block.objects.create(
            guid=current_addon.guid, min_version='2.0.1', updated_by=user)

    def test_fetch_all_versions_from_db(self):
        self.setup_data()
        all_versions = DatabaseMLBF.fetch_all_versions_from_db()
        assert len(all_versions) == File.objects.count() == 5 + 10 + 5
        assert (self.five_ver_block.guid, '123.40') in all_versions
        assert (self.five_ver_block.guid, '123.5') in all_versions
        assert (self.five_ver_block.guid, '123.45.1') in all_versions
        assert (self.five_ver_block.guid, '123.5.1') in all_versions
        assert (self.five_ver_block.guid, '123.5.2') in all_versions
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_versions
        assert under_tuple in all_versions

        assert (self.addon_deleted_before_block.guid, '2') in all_versions
        # this is fine; test_hash_filter_inputs removes duplicates.
        assert all_versions.count(
            (self.addon_deleted_before_block.guid, '2.1')) == 2
        assert (self.addon_deleted_before_block.guid, '2.5') in all_versions
        assert (self.addon_deleted_before_block.guid, '3.0') in all_versions

        # repeat, but with excluded version ids
        excludes = [self.five_ver_123_40.id, self.five_ver_123_5.id]
        all_versions = DatabaseMLBF.fetch_all_versions_from_db(excludes)
        assert len(all_versions) == 18
        assert (self.five_ver_block.guid, '123.40') not in all_versions
        assert (self.five_ver_block.guid, '123.5') not in all_versions
        assert (self.five_ver_block.guid, '123.45.1') in all_versions
        assert (self.five_ver_block.guid, '123.5.1') in all_versions
        assert (self.five_ver_block.guid, '123.5.2') in all_versions
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple in all_versions
        assert under_tuple in all_versions

    def test_fetch_blocked_from_db(self):
        self.setup_data()
        blocked_versions = DatabaseMLBF.fetch_blocked_from_db()

        # check the values - the tuples used to generate the mlbf
        blocked_guids = blocked_versions.values()
        assert len(blocked_guids) == 8, blocked_guids
        assert (self.five_ver_block.guid, '123.40') in blocked_guids
        assert (self.five_ver_block.guid, '123.5') in blocked_guids
        assert (self.five_ver_block.guid, '123.45.1') not in blocked_guids
        assert (self.five_ver_block.guid, '123.5.1') not in blocked_guids
        assert (self.five_ver_block.guid, '123.5.2') not in blocked_guids
        over_tuple = (self.over.guid, self.over.addon.current_version.version)
        under_tuple = (
            self.under.guid, self.under.addon.current_version.version)
        assert over_tuple not in blocked_guids
        assert under_tuple not in blocked_guids
        assert (self.addon_deleted_before_block.guid, '2.1') in blocked_guids
        assert (self.addon_deleted_before_block.guid, '2.5') in blocked_guids
        assert (self.addon_deleted_before_block.guid, '3.0') in blocked_guids
        assert (
            (self.addon_deleted_before_block.guid, '2.0') not in blocked_guids)

        # And check the keys, the ids used to filter out the versions
        assert self.five_ver_123_40.id in blocked_versions
        assert self.five_ver_123_5.id in blocked_versions
        assert self.five_ver_123_45_1.id not in blocked_versions
        assert self.not_signed_version.id not in blocked_versions
        assert self.not_webext_version.id not in blocked_versions
        assert self.over.addon.current_version.id not in blocked_versions
        assert self.under.addon.current_version.id not in blocked_versions

        assert self.addon_deleted_before_unblocked_ver.id not in (
            blocked_versions)
        assert self.addon_deleted_before_unsigned_ver.id not in (
            blocked_versions)
        assert self.addon_deleted_before_block.addon.current_version.id in (
            blocked_versions)
        assert self.addon_deleted_before_2_1_ver.id in (
            blocked_versions)
        assert self.addon_deleted_before_2_5_ver.id in (
            blocked_versions)

        # doublecheck if the versions were signed & webextensions they'd be in.
        self.not_signed_version.all_files[0].update(is_signed=True)
        self.not_webext_version.all_files[0].update(is_webextension=True)
        assert len(DatabaseMLBF.fetch_blocked_from_db()) == 10

    def test_fetch_blocked_with_duplicate_version_strings(self):
        """Handling the edge case where an addon (erroronously) has more than
        one version with the same version identififer."""
        self.setup_data()
        blocked_guids = DatabaseMLBF.fetch_blocked_from_db().values()
        assert len(DatabaseMLBF.hash_filter_inputs(blocked_guids)) == 8

        version_factory(
            addon=self.five_ver_block.addon,
            version=self.five_ver_123_40.version,  # copying the same identifer
            file_kw={'is_signed': True, 'is_webextension': True})
        self.five_ver_block.addon.reload()
        assert self.five_ver_block.addon.versions.filter(
            version='123.40').count() == 2
        blocked_guids = DatabaseMLBF.fetch_blocked_from_db().values()
        assert len(DatabaseMLBF.hash_filter_inputs(blocked_guids)) == 8

    def test_hash_filter_inputs(self):
        data = [
            ('guid@', '1.0'),
            ('foo@baa', '999.223a'),
        ]
        assert sorted(DatabaseMLBF.hash_filter_inputs(data)) == [
            'foo@baa:999.223a',
            'guid@:1.0',
        ]
        # check dupes are stripped out too
        data.append(('guid@', '1.0'))
        assert sorted(DatabaseMLBF.hash_filter_inputs(data)) == [
            'foo@baa:999.223a',
            'guid@:1.0',
        ]

    def test_generate_mlbf(self):
        stats = {}
        key_format = MLBF.KEY_FORMAT
        blocked = [
            ('guid1@', '1.0'), ('@guid2', '1.0'), ('@guid2', '1.1'),
            ('guid3@', '0.01b1'),
            # throw in a dupe at the end - should be removed along the way
            ('guid3@', '0.01b1')]
        not_blocked = [
            ('guid10@', '1.0'), ('@guid20', '1.0'), ('@guid20', '1.1'),
            ('guid30@', '0.01b1'), ('guid100@', '1.0'), ('@guid200', '1.0'),
            ('@guid200', '1.1'), ('guid300@', '0.01b1')]
        bfilter = generate_mlbf(
            stats,
            blocked=DatabaseMLBF.hash_filter_inputs(blocked),
            not_blocked=DatabaseMLBF.hash_filter_inputs(not_blocked))
        for entry in blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key in bfilter
        for entry in not_blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key not in bfilter
        assert stats['mlbf_version'] == 2
        assert stats['mlbf_layers'] == 1
        assert stats['mlbf_bits'] == 2160
        with tempfile.NamedTemporaryFile() as out:
            bfilter.tofile(out)
            assert os.stat(out.name).st_size == 300

    @pytest.mark.skip(reason='super slow, so only enable locally')
    def test_generate_mlbf_large(self):
        key_format = MLBF.KEY_FORMAT
        blocked = [
            (f'guid{randint(1,999)}@', f'{randint(0, 99)}.{randint(0, 99)}')
            for x in range(10000)]
        not_blocked = (
            (f'guid{randint(1,999)}@', f'{randint(0, 99)}.{randint(0, 99)}')
            for x in range(50000))
        not_blocked = [pair for pair in not_blocked if pair not in blocked]
        bfilter = generate_mlbf(
            {},
            blocked=DatabaseMLBF.hash_filter_inputs(blocked),
            not_blocked=DatabaseMLBF.hash_filter_inputs(not_blocked))
        for entry in blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key in bfilter
        for entry in not_blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key not in bfilter
        with tempfile.NamedTemporaryFile() as out:
            bfilter.tofile(out)
            assert os.stat(out.name).st_size == 10086

    def test_generate_mlbf_with_more_blocked_than_not_blocked(self):
        key_format = MLBF.KEY_FORMAT
        blocked = [('guid1@', '1.0'), ('@guid2', '1.0')]
        not_blocked = [('guid10@', '1.0')]
        bfilter = generate_mlbf(
            {},
            blocked=DatabaseMLBF.hash_filter_inputs(blocked),
            not_blocked=DatabaseMLBF.hash_filter_inputs(not_blocked))
        for entry in blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key in bfilter
        for entry in not_blocked:
            key = key_format.format(guid=entry[0], version=entry[1])
            assert key not in bfilter

    def test_generate_and_write_mlbf(self):
        self.setup_data()
        mlbf = DatabaseMLBF(123456)
        generate_and_write_mlbf(mlbf)

        with open(mlbf.filter_path, 'rb') as filter_file:
            buffer = filter_file.read()
            bfilter = FilterCascade.from_buf(buffer)

        blocked_versions = mlbf.fetch_blocked_from_db()
        blocked_guids = blocked_versions.values()
        for guid, version_str in blocked_guids:
            key = MLBF.KEY_FORMAT.format(
                guid=guid, version=version_str)
            assert key in bfilter

        all_addons = mlbf.fetch_all_versions_from_db(blocked_versions.keys())
        for guid, version_str in all_addons:
            # edge case where a version_str exists in both
            if (guid, version_str) in blocked_guids:
                continue
            key = mlbf.KEY_FORMAT.format(guid=guid, version=version_str)
            assert key not in bfilter

        # Occasionally a combination of salt generated with secrets.token_bytes
        # and the version str generated in version_factory results in a
        # collision in layer 1 of the bloomfilter, leading to a second layer
        # being generated.  When this happens the bitCount and size is larger.
        expected_size, expected_bit_count = (
            (203, 1384) if bfilter.layerCount() == 1 else (393, 2824))
        assert os.stat(mlbf.filter_path).st_size == expected_size, (
            blocked_guids, all_addons)
        assert bfilter.bitCount() == expected_bit_count, (
            blocked_guids, all_addons)

    def test_generate_and_write_periodic_mlbf(self):
        self.setup_data()
        mlbfs = PeriodicDatabaseMLBF(123456)
        generate_and_write_periodic_mlbf(mlbfs)

        excluding_versions, blocked_guids = (
            mlbfs.fetch_blocked_from_db_with_periods())
        blocked_guids = dict(
            PeriodicDatabaseMLBF.group_into_periods(blocked_guids))
        all_addons = mlbfs.fetch_all_versions_from_db_periods(
            excluding_versions)
        all_addons = dict(
            PeriodicDatabaseMLBF.group_into_periods(all_addons))
        dupe_2_1_file = self.addon_deleted_before_unsigned_ver.all_files[0]
        dupe_2_1_tuple = (
            dupe_2_1_file.addon.guid,
            dupe_2_1_file.version.version,
            dupe_2_1_file.modified)

        assert len(mlbfs.blocked_items) == 2
        bfilters = []
        filter_paths = []
        for period in mlbfs.blocked_items:
            with open(mlbfs.get_filter_path(period), 'rb') as filter_file:
                buffer = filter_file.read()
                bfilter = FilterCascade.from_buf(buffer)
            filter_paths.append(mlbfs.get_filter_path(period))

            for (guid, version_str, timestamp) in blocked_guids[period]:
                key = MLBF.KEY_FORMAT.format(
                    guid=guid, version=version_str)
                assert key in bfilter

            for (guid, version_str, timestamp) in all_addons[period]:
                # edge case where a version_str exists in both
                if (guid, version_str, timestamp) == dupe_2_1_tuple:
                    continue
                key = MLBF.KEY_FORMAT.format(
                    guid=guid, version=version_str)
                assert key not in bfilter
            bfilters.append(bfilter)

        expected_size, expected_bit_count = 120, 720
        assert os.stat(filter_paths[0]).st_size == (
            expected_size), (blocked_guids, all_addons)
        assert bfilters[0].bitCount() == expected_bit_count, (
            blocked_guids, all_addons)

        expected_size, expected_bit_count = 238, 1664
        assert os.stat(filter_paths[1]).st_size == expected_size, (
            blocked_guids, all_addons)
        assert bfilters[1].bitCount() == expected_bit_count, (
            blocked_guids, all_addons)

    def test_generate_diffs(self):
        old_versions = [
            ('guid1@', '1.0'), ('@guid2', '1.0'), ('@guid2', '1.1'),
            ('guid3@', '0.01b1')]
        new_versions = [
            ('guid1@', '1.0'), ('guid3@', '0.01b1'), ('@guid2', '1.1'),
            ('new_guid@', '0.01b1'), ('new_guid@', '24')]
        extras, deletes = generate_diffs(old_versions, new_versions)
        assert extras == {('new_guid@', '0.01b1'), ('new_guid@', '24')}
        assert deletes == {('@guid2', '1.0')}

    def test_write_stash(self):
        self.setup_data()
        old_mlbf = DatabaseMLBF('old')
        generate_and_write_mlbf(old_mlbf)
        new_mlbf = DatabaseMLBF('new_no_change')
        generate_and_write_mlbf(new_mlbf)
        generate_and_write_stash(new_mlbf, old_mlbf)
        empty_stash = {'blocked': [], 'unblocked': []}
        with open(new_mlbf._stash_path) as stash_file:
            assert json.load(stash_file) == empty_stash
        assert new_mlbf.stash_json == empty_stash
        # add a new Block and delete one
        Block.objects.create(
            addon=addon_factory(
                guid='fooo@baaaa',
                version_kw={'version': '999'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        self.five_ver_123_5.delete(hard=True)
        newer_mlbf = DatabaseMLBF('new_one_change')
        generate_and_write_mlbf(newer_mlbf)
        generate_and_write_stash(newer_mlbf, new_mlbf)
        full_stash = {
            'blocked': ['fooo@baaaa:999'],
            'unblocked': [f'{self.five_ver_block.guid}:123.5']}
        with open(newer_mlbf._stash_path) as stash_file:
            assert json.load(stash_file) == full_stash
        assert newer_mlbf.stash_json == full_stash

    def test_should_reset_base_filter_and_blocks_changed_since_previous(self):
        self.setup_data()
        base_mlbf = DatabaseMLBF('base')
        # should handle the files not existing
        assert base_mlbf.should_reset_base_filter(
            StoredMLBF('no_files'))
        assert base_mlbf.blocks_changed_since_previous(
            StoredMLBF('no_files'))
        generate_and_write_mlbf(base_mlbf)

        no_change_mlbf = DatabaseMLBF('no_change')
        generate_and_write_mlbf(no_change_mlbf)
        assert not no_change_mlbf.should_reset_base_filter(base_mlbf)
        assert not no_change_mlbf.blocks_changed_since_previous(base_mlbf)

        # make some changes
        Block.objects.create(
            addon=addon_factory(
                guid='fooo@baaaa',
                version_kw={'version': '999'},
                file_kw={'is_signed': True, 'is_webextension': True}),
            updated_by=user_factory())
        self.five_ver_123_5.delete(hard=True)
        small_change_mlbf = DatabaseMLBF('small_change')
        generate_and_write_mlbf(small_change_mlbf)
        # but the changes were small (less than threshold) so no need for new
        # base filter
        assert not small_change_mlbf.should_reset_base_filter(base_mlbf)
        # there _were_ changes though
        assert small_change_mlbf.blocks_changed_since_previous(base_mlbf)
        # double check what the differences were
        diffs = generate_diffs(
            previous=base_mlbf.blocked_items,
            current=small_change_mlbf.blocked_items)
        assert diffs == (
            {'fooo@baaaa:999'}, {f'{self.five_ver_block.guid}:123.5'})

        # so lower the threshold
        to_patch = 'olympia.blocklist.mlbf.BASE_REPLACE_THRESHOLD'
        with mock.patch(to_patch, 1):
            assert small_change_mlbf.should_reset_base_filter(base_mlbf)
            assert small_change_mlbf.blocks_changed_since_previous(base_mlbf)
