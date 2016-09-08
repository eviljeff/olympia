import commonware.log
from olympia.amo.celery import task
from olympia.activity.utils import add_email_to_activity_log


log = commonware.log.getLogger('z.task')


@task
def process_email(email_text, **kwargs):
    """Parse emails and save activity log entry."""
    res = add_email_to_activity_log(email_text)
    if not res:
        log.error('Failed to save email.')
