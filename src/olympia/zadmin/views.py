from django import http
from django.apps import apps
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.core.files.storage import default_storage as storage
from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.cache import never_cache

import olympia.core.logger

from olympia import amo
from olympia.activity.models import ActivityLog
from olympia.addons.models import Addon
from olympia.amo import messages
from olympia.amo.decorators import (
    json_view, permission_required, post_required)
from olympia.amo.utils import HttpResponseXSendFile, render
from olympia.files.models import File, FileUpload

from .decorators import admin_required


log = olympia.core.logger.getLogger('z.zadmin')


@admin.site.admin_view
def fix_disabled_file(request):
    file_ = None
    if request.method == 'POST' and 'file' in request.POST:
        file_ = get_object_or_404(File, id=request.POST['file'])
        if 'confirm' in request.POST:
            file_.unhide_disabled_file()
            messages.success(request, 'We have done a great thing.')
            return redirect('zadmin.fix-disabled')
    return render(request, 'zadmin/fix-disabled.html',
                  {'file': file_, 'file_id': request.POST.get('file', '')})


@permission_required(amo.permissions.ANY_ADMIN)
def index(request):
    log = ActivityLog.objects.admin_events()[:5]
    return render(request, 'zadmin/index.html', {'log': log})


@admin_required
def addon_search(request):
    ctx = {}
    if 'q' in request.GET:
        q = ctx['q'] = request.GET['q']
        if q.isdigit():
            qs = Addon.objects.filter(id=int(q))
        else:
            qs = Addon.search().query(name__text=q.lower())[:100]
        if len(qs) == 1:
            return redirect('admin:addons_addon_change', qs[0].id)
        ctx['addons'] = qs
    return render(request, 'zadmin/addon-search.html', ctx)


@never_cache
@json_view
def general_search(request, app_id, model_id):
    if not admin.site.has_permission(request):
        raise PermissionDenied

    try:
        model = apps.get_model(app_id, model_id)
    except LookupError:
        raise http.Http404

    limit = 10
    obj = admin.site._registry[model]
    ChangeList = obj.get_changelist(request)
    # This is a hideous api, but uses the builtin admin search_fields API.
    # Expecting this to get replaced by ES so soon, that I'm not going to lose
    # too much sleep about it.
    args = [request, obj.model, [], [], [], [], obj.search_fields, [],
            obj.list_max_show_all, limit, [], obj]
    try:
        # python3.2+ only
        from inspect import signature
        if 'sortable_by' in signature(ChangeList.__init__).parameters:
            args.append('None')  # sortable_by is a django2.1+ addition
    except ImportError:
        pass
    cl = ChangeList(*args)
    qs = cl.get_queryset(request)
    # Override search_fields_response on the ModelAdmin object
    # if you'd like to pass something else back to the front end.
    lookup = getattr(obj, 'search_fields_response', None)
    return [{'value': o.pk, 'label': getattr(o, lookup) if lookup else str(o)}
            for o in qs[:limit]]


@admin_required
def download_file_upload(request, uuid):
    upload = get_object_or_404(FileUpload, uuid=uuid)

    return HttpResponseXSendFile(request, upload.path,
                                 content_type='application/octet-stream')


@admin.site.admin_view
@post_required
@json_view
def recalc_hash(request, file_id):

    file = get_object_or_404(File, pk=file_id)
    file.size = storage.size(file.file_path)
    file.hash = file.generate_hash()
    file.save()

    log.info('Recalculated hash for file ID %d' % file.id)
    messages.success(request,
                     'File hash and size recalculated for file %d.' % file.id)
    return {'success': 1}
