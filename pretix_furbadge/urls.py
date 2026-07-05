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
    re_path(
        r"^control/event/(?P<organizer>[^/]+)/(?P<event>[^/]+)/furbadge/telegram/$",
        views.TelegramSettingsView.as_view(),
        name="telegram.settings",
    ),
]

event_patterns = [
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
        r"^furbadge/telegram/connect/(?P<order>[^/]+)/(?P<secret>[^/]+)/$",
        frontend_views.TelegramConnectStartView.as_view(),
        name="telegram.connect.start",
        require_live=False,
    ),
    event_url(
        r"^furbadge/telegram/disconnect/(?P<order>[^/]+)/(?P<secret>[^/]+)/$",
        frontend_views.TelegramDisconnectView.as_view(),
        name="telegram.disconnect",
        require_live=False,
    ),
    event_url(
        r"^furbadge/telegram/connect/callback/$",
        frontend_views.TelegramConnectCallbackView.as_view(),
        name="telegram.connect.callback",
        require_live=False,
    ),
    event_url(
        r"^furbadge/public_attendees/$",
        frontend_views.PublicAttendeeListView.as_view(),
        name="public_attendees",
        require_live=False,
    ),
    event_url(
        r"^furbadge/telegram/checkout/start/$",
        frontend_views.TelegramCheckoutStartView.as_view(),
        name="telegram.checkout.start",
        require_live=False,
    ),
    event_url(
        r"^furbadge/telegram/checkout/callback/$",
        frontend_views.TelegramCheckoutCallbackView.as_view(),
        name="telegram.checkout.callback",
        require_live=False,
    ),
    event_url(
        r"^furbadge/telegram/checkout/disconnect/$",
        frontend_views.TelegramCheckoutDisconnectView.as_view(),
        name="telegram.checkout.disconnect",
    ),
    event_url(
        r"^furbadge/telegram/preferences/(?P<order>[^/]+)/(?P<secret>[^/]+)/$",
        frontend_views.TelegramPreferencesView.as_view(),
        name="telegram.preferences",
    ),
    event_url(
        r"^furbadge/telegram/webhook/$",
        frontend_views.TelegramWebhookView.as_view(),
        name="telegram.webhook",
    ),
]
