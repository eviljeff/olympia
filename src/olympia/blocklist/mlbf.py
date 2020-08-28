import json
import os
import secrets
from collections import defaultdict

from django.conf import settings
from django.core.files.storage import default_storage as storage
from django.utils.functional import cached_property

from filtercascade import FilterCascade
from filtercascade.fileformats import HashAlgorithm
from olympia.amo.utils import sorted_groupby

import olympia.core.logger
from olympia.constants.blocklist import BASE_REPLACE_THRESHOLD


log = olympia.core.logger.getLogger('z.amo.blocklist')


def generate_diffs(previous, current):
    previous = set(previous)
    current = set(current)
    extras = current - previous
    deletes = previous - current
    return extras, deletes


class BloomFilterData():
    KEY_FORMAT = '{guid}:{version}'

    def __init__(self, id_):
        # simplify later code by assuming always a string
        self.id = str(id_)

    @property
    def _blocked_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'blocked.json')

    @cached_property
    def blocked_json(self):
        with storage.open(self._blocked_path, 'r') as json_file:
            return json.load(json_file)

    def write_blocked_json(self):
        blocked_path = self._blocked_path
        with storage.open(blocked_path, 'w') as json_file:
            log.info("Writing to file {}".format(blocked_path))
            json.dump(self.blocked_json, json_file)

    @property
    def _not_blocked_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'notblocked.json')

    @cached_property
    def not_blocked_json(self):
        with storage.open(self._not_blocked_path, 'r') as json_file:
            return json.load(json_file)

    def write_not_blocked_json(self):
        not_blocked_path = self._not_blocked_path
        with storage.open(not_blocked_path, 'w') as json_file:
            log.info("Writing to file {}".format(not_blocked_path))
            json.dump(self.not_blocked_json, json_file)

    @property
    def filter_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'filter')

    @property
    def _stash_path(self):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, 'stash.json')

    @cached_property
    def stash_json(self):
        with storage.open(self._stash_path, 'r') as json_file:
            return json.load(json_file)

    def blocks_changed_since_previous(self, previous_bloom_filter):
        try:
            # compare base with current blocks
            extras, deletes = generate_diffs(
                previous_bloom_filter.blocked_json, self.blocked_json)
            return len(extras) + len(deletes)
        except FileNotFoundError:
            # when previous_bloom_filter._blocked_path doesn't exist
            return len(self.blocked_json)

    def should_reset_base_filter(self, previous_bloom_filter):
        try:
            # compare base with current blocks
            extras, deletes = generate_diffs(
                previous_bloom_filter.blocked_json, self.blocked_json)
            return (len(extras) + len(deletes)) > BASE_REPLACE_THRESHOLD
        except FileNotFoundError:
            # when previous_base_mlfb._blocked_path doesn't exist
            return True


class BloomFilterDBData(BloomFilterData):
    @classmethod
    def hash_filter_inputs(cls, input_list):
        """Returns a set"""
        return {
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version) in input_list}

    @classmethod
    def fetch_blocked_from_db(cls):
        from olympia.files.models import File
        from olympia.blocklist.models import Block

        blocks = Block.objects.all()
        blocks_guids = [block.guid for block in blocks]

        file_qs = File.objects.filter(
            version__addon__addonguid__guid__in=blocks_guids,
            is_signed=True,
            is_webextension=True,
        ).order_by('version_id').values(
            'version__addon__addonguid__guid',
            'version__version',
            'version_id')
        addons_versions = defaultdict(list)
        for file_ in file_qs:
            addon_key = file_['version__addon__addonguid__guid']
            addons_versions[addon_key].append(
                (file_['version__version'], file_['version_id']))

        all_versions = {}
        # collect all the blocked versions
        for block in blocks:
            is_all_versions = (
                block.min_version == Block.MIN and
                block.max_version == Block.MAX)
            versions = {
                version_id: (block.guid, version)
                for version, version_id in addons_versions[block.guid]
                if is_all_versions or block.is_version_blocked(version)}
            all_versions.update(versions)
        return all_versions

    @cached_property
    def blocked_json(self):
        blocked_ids_to_versions = self.fetch_blocked_from_db()
        blocked = blocked_ids_to_versions.values()
        # cache version ids so query in not_blocked_json is efficient
        self._version_excludes = blocked_ids_to_versions.keys()
        return list(self.hash_filter_inputs(blocked))

    @classmethod
    def fetch_all_versions_from_db(cls, excluding_version_ids=None):
        from olympia.versions.models import Version

        qs = (
            Version.unfiltered.exclude(id__in=excluding_version_ids or ())
                   .values_list('addon__addonguid__guid', 'version'))
        return list(qs)

    @cached_property
    def not_blocked_json(self):
        # see fetch_blocked_json - we need self._version_excludes populated
        self.blocked_json
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_json doesn't contain any blocked_json.
        return list(
            self.hash_filter_inputs(
                self.fetch_all_versions_from_db(self._version_excludes)) -
            set(self.blocked_json))


def generate_mlbf(stats, blocked, not_blocked):
    log.info('Starting to generating bloomfilter')

    cascade = FilterCascade(
        defaultHashAlg=HashAlgorithm.SHA256,
        salt=secrets.token_bytes(16),
    )

    error_rates = sorted((len(blocked), len(not_blocked)))
    cascade.set_crlite_error_rates(
        include_len=error_rates[0], exclude_len=error_rates[1])

    stats['mlbf_blocked_count'] = len(blocked)
    stats['mlbf_notblocked_count'] = len(not_blocked)

    cascade.initialize(include=blocked, exclude=not_blocked)

    stats['mlbf_version'] = cascade.version
    stats['mlbf_layers'] = cascade.layerCount()
    stats['mlbf_bits'] = cascade.bitCount()

    log.info(
        f'Filter cascade layers: {cascade.layerCount()}, '
        f'bit: {cascade.bitCount()}')

    cascade.verify(include=blocked, exclude=not_blocked)
    return cascade


def generate_and_write_mlbf(data):
    stats = {}

    data.write_blocked_json()
    data.write_not_blocked_json()

    bloomfilter = generate_mlbf(
        stats=stats,
        blocked=data.blocked_json,
        not_blocked=data.not_blocked_json)

    # write bloomfilter
    mlbf_path = data.filter_path
    with storage.open(mlbf_path, 'wb') as filter_file:
        log.info("Writing to file {}".format(mlbf_path))
        bloomfilter.tofile(filter_file)
        stats['mlbf_filesize'] = os.stat(mlbf_path).st_size

    log.info(json.dumps(stats))


class PeriodicBloomFilterData(BloomFilterDBData):

    @classmethod
    def hash_filter_inputs(cls, input_list):
        """Returns a set"""
        return {
            cls.KEY_FORMAT.format(guid=guid, version=version)
            for (guid, version, _) in input_list}

    @classmethod
    def fetch_blocked_from_db_with_periods(cls):
        from olympia.files.models import File
        from olympia.blocklist.models import Block

        blocks = Block.objects.all()
        blocks_guids = [block.guid for block in blocks]

        file_qs = File.objects.filter(
            version__addon__addonguid__guid__in=blocks_guids,
            is_signed=True,
            is_webextension=True,
        ).order_by('version_id').values(
            'version__addon__addonguid__guid',
            'version__version',
            'version_id',
            'modified')  # TODO: store&get the actual signing datetime
        addons_versions = defaultdict(list)
        for file_ in file_qs:
            addon_key = file_['version__addon__addonguid__guid']
            addons_versions[addon_key].append(
                (file_['version__version'],
                 file_['version_id'],
                 file_['modified']))

        version_ids = []
        block_pairs = []

        # collect all the blocked versions
        for block in blocks:
            is_all_versions = (
                block.min_version == Block.MIN and
                block.max_version == Block.MAX)
            for version, version_id, ts in addons_versions[block.guid]:
                if is_all_versions or block.is_version_blocked(version):
                    version_ids.append(version_id)
                    block_pairs.append((block.guid, version, ts))

        return version_ids, block_pairs

    def _group_into_periods(self, data):
        return sorted_groupby(
            data, lambda val: int(val[2].timestamp() // 90))

    @cached_property
    def blocked_periods_json(self):
        _version_excludes, blocked = self.fetch_blocked_from_db_with_periods()
        # cache version ids so query in not_blocked_json is efficient
        self._version_excludes = _version_excludes

        periods = self._group_into_periods(blocked)
        # print([(x, y) for x, y in periods])
        return {
            start: list(self.hash_filter_inputs(inputs))
            for start, inputs in periods}

    @classmethod
    def fetch_all_versions_from_db_periods(cls, excluding_version_ids=None):
        from olympia.files.models import File

        qs = (
            File.objects.exclude(version_id__in=excluding_version_ids or ())
                .values_list(
                    'version__addon__addonguid__guid',
                    'version__version',
                    'modified'))  # TODO: store&get the actual signing datetime
        return list(qs)

    @cached_property
    def not_blocked_periods_json(self):
        # see blocked_json - we need self._version_excludes populated
        self.blocked_periods_json
        not_blocked = self.fetch_all_versions_from_db_periods(
            self._version_excludes)
        # even though we exclude all the version ids in the query there's an
        # edge case where the version string occurs twice for an addon so we
        # ensure not_blocked_json doesn't contain any blocked_json.
        return {
            start: list(
                self.hash_filter_inputs(inputs) -
                set(self.blocked_periods_json.get(start, ())))
            for start, inputs in self._group_into_periods(not_blocked)}

    def get_filter_path(self, period):
        return os.path.join(
            settings.MLBF_STORAGE_PATH, self.id, f'{period}.filter')


def generate_and_write_periodic_mlbf(periodic_data):
    total_stats = []

    # periodic_data.write_blocked_json()
    # periodic_data.write_not_blocked_json()

    for from_ts, blocked in periodic_data.blocked_periods_json.items():
        stats = {}
        not_blocked = periodic_data.not_blocked_periods_json.get(from_ts) or ()
        print(blocked, not_blocked)
        bloomfilter = generate_mlbf(
            stats=stats,
            blocked=blocked,
            not_blocked=not_blocked)

        # write bloomfilter
        mlbf_path = periodic_data.get_filter_path(from_ts)
        with storage.open(mlbf_path, 'wb') as filter_file:
            log.info("Writing to file {}".format(mlbf_path))
            bloomfilter.tofile(filter_file)
            stats['mlbf_filesize'] = os.stat(mlbf_path).st_size
        total_stats.append(stats)

    log.info(json.dumps(total_stats))


def generate_and_write_stash(data, previous_data):
    # compare previous with current blocks
    extras, deletes = generate_diffs(
        previous_data.blocked_json, data.blocked_json)
    data.stash_json = {
        'blocked': list(extras),
        'unblocked': list(deletes),
    }
    # write stash
    stash_path = data._stash_path
    with storage.open(stash_path, 'w') as json_file:
        log.info("Writing to file {}".format(stash_path))
        json.dump(data.stash_json, json_file)
