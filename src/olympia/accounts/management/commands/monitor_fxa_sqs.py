from django.conf import settings
from django.core.management.base import BaseCommand

from kombu.utils.debug import setup_logging

from olympia.accounts.utils import process_sqs_queue


class Command(BaseCommand):
    """Monitor and process the AWS SQS queue for Firefox Account events.
    This function polls the specified SQS queue for account-related events,
    processing each as it is found.  It polls indefinitely and does not return;
    to interrupt execution you'll need to e.g. SIGINT the process.
    """
    help = 'Monitor the AWS SQS queue for FxA events.'

    def add_arguments(self, parser):
        """Handle command arguments."""
        parser.add_argument(
            '--queue',
            action='store',
            dest='queue_url',
            default=settings.FXA_SQS_CONFIG['aws_queue_url'],
            help='Monitor specified SQS queue, rather than default.')
        parser.add_argument(
            '--region',
            action='store',
            dest='aws_region',
            default=settings.FXA_SQS_CONFIG['aws_region'],
            help='Use specified AWS region, rather than default.')

    def handle(self, *args, **options):
        queue_url = options['queue_url']
        aws_region = options['aws_region']
        queue_wait_time = settings.FXA_SQS_CONFIG['wait_time']
        # setup root logger
        setup_logging(loglevel='INFO', loggers=[''])

        process_sqs_queue(queue_url, aws_region, queue_wait_time)
