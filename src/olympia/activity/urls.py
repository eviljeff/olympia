from django.conf.urls import url

from . import views

urlpatterns = [
    url(r'^mail/', views.post_email, name='post-email-api'),
]
