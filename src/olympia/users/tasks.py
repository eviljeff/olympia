import olympia.core.logger
from olympia.amo.celery import task
from olympia.amo.decorators import set_modified_on
from olympia.amo.utils import SafeStorage, resize_image

from .models import UserProfile


task_log = olympia.core.logger.getLogger('z.task')


@task
def delete_photo(pk, **kw):
    task_log.info('[1@None] Deleting photo for user: %s.' % pk)

    user = UserProfile(id=pk)
    storage = SafeStorage(root_setting='MEDIA_ROOT', rel_location='userpics')
    storage.delete(user.picture_path)
    storage.delete(user.picture_path_original)


@task
@set_modified_on
def resize_photo(src, dst, locally=False, **kw):
    """Resizes userpics to 200x200"""
    task_log.info('[1@None] Resizing photo: %s' % dst)

    try:
        resize_image(src, dst, (200, 200))
        return True
    except Exception as e:
        task_log.error('Error saving userpic: %s' % e)


@task(rate_limit='15/m')
def update_user_ratings_task(data, **kw):
    task_log.info(
        "[%s@%s] Updating add-on author's ratings."
        % (len(data), update_user_ratings_task.rate_limit)
    )
    for pk, rating in data:
        UserProfile.objects.filter(pk=pk).update(averagerating=round(float(rating), 2))
