import json
from datetime import datetime

from django.core.management.base import BaseCommand

import olympia.core.logger

from olympia.blocklist.mlbf import (
    PeriodicDatabaseMLBF, generate_and_write_periodic_mlbf)


log = olympia.core.logger.getLogger('z.amo.blocklist')


class Command(BaseCommand):
    help = ('Export AMO blocklist to filter cascade blob')

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            'id',
            help="CT baseline identifier",
            metavar=('ID'))
        parser.add_argument(
            '--addon-guids-input',
            help='Path to json file with [[guid, version, sign_date],...] '
                 'data for all addons. If not provided will be generated from '
                 'Addons&Versions in the database',
            default=None)
        parser.add_argument(
            '--block-guids-input',
            help='Path to json file with [[guid, version, sign_date],...] '
                 'data for Blocks.  If not provided will be generated from '
                 'Blocks in the database',
            default=None)

    def load_json(self, json_path):
        with open(json_path) as json_file:
            data = json.load(json_file)
        return [
            (record[0], record[1], datetime.fromtimestamp(record[2]))
            for record in data]

    def handle(self, *args, **options):
        log.debug('Exporting periodic blocklists to file')
        mlbfs = PeriodicDatabaseMLBF(options.get('id'))

        if options.get('block_guids_input'):
            periods = PeriodicDatabaseMLBF.group_into_periods(
                self.load_json(options.get('block_guids_input')))
            mlbfs.blocked_items = {
                start: list(PeriodicDatabaseMLBF.hash_filter_inputs(inputs))
                for start, inputs in periods}
        if options.get('addon_guids_input'):
            periods = PeriodicDatabaseMLBF.group_into_periods(
                self.load_json(options.get('addon_guids_input')))
            mlbfs.not_blocked_items = {
                start: list(PeriodicDatabaseMLBF.hash_filter_inputs(inputs))
                for start, inputs in periods}

        generate_and_write_periodic_mlbf(mlbfs)
