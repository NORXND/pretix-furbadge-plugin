# -*- coding: utf-8 -*-

"""
pretix_furbadge.urls
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All routes for the pretix_furbadge plugin are defined here.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from django.urls import re_path
from pretix.multidomain import event_url

from . import frontend_views, views

urlpatterns = [
    # Control panel - Settings
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/settings/$",
        views.FurbadgeSettingsView.as_view(),
        name="plugin_settings",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/$",
        views.FurbadgeSettingsView.as_view(),
        name="settings",
    ),
    # Control panel - Badge Type CRUD
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/types/$",
        views.BadgeTypeListView.as_view(),
        name="type.list",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/types/create/$",
        views.BadgeTypeCreateView.as_view(),
        name="type.create",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/types/(?P<pk>\d+)/$",
        views.BadgeTypeUpdateView.as_view(),
        name="type.update",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/types/(?P<pk>\d+)/delete/$",
        views.BadgeTypeDeleteView.as_view(),
        name="type.delete",
    ),
    # Control panel - EventFont CRUD
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/fonts/$",
        views.EventFontListView.as_view(),
        name="font.list",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/fonts/create/$",
        views.EventFontCreateView.as_view(),
        name="font.create",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/fonts/(?P<pk>\d+)/$",
        views.EventFontUpdateView.as_view(),
        name="font.update",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/fonts/(?P<pk>\d+)/delete/$",
        views.EventFontDeleteView.as_view(),
        name="font.delete",
    ),
    # Control panel - Badge preview/export per order position
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/preview/(?P<position>\d+)/$",
        views.AdminBadgePreviewView.as_view(),
        name="admin.preview",
    ),
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/export/(?P<position>\d+)/$",
        views.AdminBadgeExportView.as_view(),
        name="admin.export",
    ),
]

event_patterns = [
    # Frontend (presale) - Attendee badge editing
    event_url(
        r"^furbadge/(?P<order>[^/]+)/(?P<secret>[^/]+)/(?P<position>\d+)/$",
        frontend_views.BadgeEditView.as_view(),
        name="badge.edit",
        require_live=False,
    ),
    event_url(
        r"^furbadge/(?P<order>[^/]+)/(?P<secret>[^/]+)/(?P<position>\d+)/preview/$",
        frontend_views.BadgePreviewView.as_view(),
        name="badge.preview",
        require_live=False,
    ),
    event_url(
        r"^furbadge/(?P<order>[^/]+)/(?P<secret>[^/]+)/(?P<position>\d+)/upload/$",
        frontend_views.AvatarUploadView.as_view(),
        name="badge.upload",
        require_live=False,
    ),
    event_url(
        r"^furbadge/public_attendees/$",
        frontend_views.PublicAttendeeListView.as_view(),
        name="public_attendees",
        require_live=False,
    ),
]
