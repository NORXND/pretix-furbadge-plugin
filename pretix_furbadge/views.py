# -*- coding: utf-8 -*-

"""
pretix_furbadge.views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Admin views for all the badges stuff.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from typing import TYPE_CHECKING

import logging
from django.http import (
    Http404,
    HttpResponse,
)
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.views.generic import (
    CreateView,
    DeleteView,
    ListView,
    UpdateView,
    View,
)
from pretix.base.models import OrderPosition, Organizer
from pretix.control.permissions import EventPermissionRequiredMixin
from pretix.control.views.event import (
    EventSettingsFormView,
    EventSettingsViewMixin,
)
from typing_extensions import override

from .badge_renderer import BadgeRenderer
from .forms import (
    BadgeTypeForm,
    EventFontForm,
    FurbadgeSettingsForm,
    TelegramSettingsForm,
)
from .models import BadgeData, BadgeType, EventFont, ProductBadgeLink

if TYPE_CHECKING:
    from django_stubs_ext import QuerySetAny
    from pretix.base.models import Event, Order, Organizer

    from pretix_furbadge.types import PretixRequest

logger = logging.getLogger(__name__)


class EventFontListView(EventPermissionRequiredMixin, ListView):
    """
    Displays a list of custom fonts available for the current event's badges.
    """

    model = EventFont
    template_name = "pretix_furbadge/font_list.html"
    context_object_name = "fonts"
    permission = "can_change_event_settings"

    def get_queryset(self) -> QuerySetAny:
        self.request: PretixRequest
        event: Event = self.request.event
        return event.furbadge_fonts.all()


class EventFontCreateView(EventPermissionRequiredMixin, CreateView):
    """
    Displays a form for creating a new custom font for the current event's badges.
    """

    model = EventFont
    form_class = EventFontForm
    template_name = "pretix_furbadge/font_form.html"
    permission = "can_change_event_settings"

    def form_valid(self, form) -> HttpResponse:
        self.request: PretixRequest
        form.instance.event = self.request.event
        return super().form_valid(form)

    @override
    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_furbadge:font.list",
            kwargs={
                "organizer": self.request.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class EventFontUpdateView(EventPermissionRequiredMixin, UpdateView):
    """
    Displays a form for updating an existing custom font for the current event's badges.
    Pretty much the same as :class:`EventFontCreateView`.
    """

    model = EventFont
    form_class = EventFontForm
    template_name = "pretix_furbadge/font_form.html"
    permission = "can_change_event_settings"

    def get_queryset(self) -> QuerySetAny:
        self.request: PretixRequest
        event: Event = self.request.event
        return event.furbadge_fonts.all()

    @override
    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_furbadge:font.list",
            kwargs={
                "organizer": self.request.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class EventFontDeleteView(EventPermissionRequiredMixin, DeleteView):
    """
    Displays a confirmation page for deleting an existing custom font for the current event's badges.
    """

    model = EventFont
    template_name = "pretix_furbadge/font_delete.html"
    permission = "can_change_event_settings"

    def get_queryset(self) -> QuerySetAny:
        self.request: PretixRequest
        event: Event = self.request.event
        return event.furbadge_fonts.all()

    @override
    def get_success_url(self) -> str:
        return reverse(
            "plugins:pretix_furbadge:font.list",
            kwargs={
                "organizer": self.request.organizer.slug,
                "event": self.request.event.slug,
            },
        )


class FurbadgeSettingsView(EventSettingsViewMixin, EventSettingsFormView):
    """
    Displays a form for editing the furbadge plugin settings for the current event.
    For available options, see :class:`FurbadgeSettingsForm`.
    """

    model = getattr(EventSettingsFormView, "model", None)
    form_class = FurbadgeSettingsForm
    template_name = "pretix_furbadge/settings.html"
    permission = "can_change_event_settings"

    def get_success_url(self) -> str:
        self.request: PretixRequest
        organizer: Organizer = self.request.organizer
        event: Event = self.request.event
        return reverse(
            "plugins:pretix_furbadge:plugin_settings",
            kwargs={
                "organizer": organizer.slug,
                "event": event.slug,
            },
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        return form


class TelegramSettingsView(EventSettingsViewMixin, EventSettingsFormView):
    """
    Control panel view for configuring Telegram integration settings.

    This view handles the configuration of bot credentials, OIDC client setup,
    webhook secrets, and email forwarding preferences in the event's control panel.

    See :class:`pretix_furbadge.forms.TelegramSettingsForm` for form details and
    :func:`pretix_furbadge.views.telegram_connect_start_view` for related functionality.
    """

    model = getattr(TelegramSettingsForm, "model", None)
    form_class = TelegramSettingsForm
    template_name = "pretix_furbadge/telegram_settings.html"
    permission = "can_change_event_settings"

    def get_success_url(self):
        return reverse(
            "plugins:pretix_furbadge:telegram.settings",
            kwargs={
                "organizer": self.request.event.organizer.slug,
                "event": self.request.event.slug,
            },
        )

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        return form


class BadgeTypeListView(EventPermissionRequiredMixin, ListView):
    """
    Displays a list of badge types available for the current event.
    """

    model = BadgeType
    template_name = "pretix_furbadge/type_list.html"
    context_object_name = "badge_types"
    permission = "can_change_event_settings"

    def get_queryset(self) -> QuerySetAny:
        self.request: PretixRequest
        event: Event = self.request.event
        return event.furbadge_types.all()


class BadgeTypeCreateView(EventPermissionRequiredMixin, CreateView):
    """
    Displays a form for creating a new badge type for the current event.
    """

    model = BadgeType
    form_class = BadgeTypeForm
    template_name = "pretix_furbadge/type_form.html"
    permission = "can_change_event_settings"

    @override
    def form_valid(self, form) -> HttpResponse:
        self.request: PretixRequest
        form.instance.event = self.request.event
        return super().form_valid(form)

    @override
    def get_success_url(self) -> str:
        organizer: Organizer = self.request.organizer
        event: Event = self.request.event
        return reverse(
            "plugins:pretix_furbadge:type.list",
            kwargs={
                "organizer": organizer.slug,
                "event": event.slug,
            },
        )


class BadgeTypeUpdateView(EventPermissionRequiredMixin, UpdateView):
    """
    Displays a form for updating an existing badge type for the current event.
    """

    model = BadgeType
    form_class = BadgeTypeForm
    template_name = "pretix_furbadge/type_form.html"
    permission = "can_change_event_settings"

    def get_queryset(self) -> QuerySetAny:
        self.request: PretixRequest
        event: Event = self.request.event
        return event.furbadge_types.all()

    def get_success_url(self) -> str:
        organizer: Organizer = self.request.organizer
        event: Event = self.request.event
        return reverse(
            "plugins:pretix_furbadge:type.list",
            kwargs={
                "organizer": organizer.slug,
                "event": event.slug,
            },
        )


class BadgeTypeDeleteView(EventPermissionRequiredMixin, DeleteView):
    """
    Displays a form for deleting an existing badge type for the current event.
    """

    model = BadgeType
    template_name = "pretix_furbadge/type_delete.html"
    permission = "can_change_event_settings"

    def get_queryset(self) -> QuerySetAny:
        self.request: PretixRequest
        event: Event = self.request.event
        return event.furbadge_types.all()

    def get_success_url(self) -> str:
        organizer: Organizer = self.request.organizer
        event: Event = self.request.event
        return reverse(
            "plugins:pretix_furbadge:type.list",
            kwargs={
                "organizer": organizer.slug,
                "event": event.slug,
            },
        )


class AdminBadgePreviewView(EventPermissionRequiredMixin, View):
    """
    Returns admin badge preview as a PNG image for a given order position.
    The preview can optionally include a preview overlay.
    """

    permission = "can_view_orders"

    def get(
        self,
        request: PretixRequest,
        organizer: Organizer,
        event: str,
        position: OrderPosition,
    ):
        _pos = get_object_or_404(OrderPosition, order__event=request.event, pk=position)
        include_overlay = request.GET.get("overlay", "1") == "1"

        try:
            pos = _pos
            badge_data = pos.furbadge_data
        except BadgeData.DoesNotExist:
            raise Http404("Badge data not configured for this position.")

        badge_link = badge_data.badge_link
        if not isinstance(badge_link, ProductBadgeLink):
            raise Http404("Badge link is invalid.")
        if badge_link.badge_type is None:
            raise Http404("Badge type not configured for this link.")
        renderer = BadgeRenderer(badge_link.badge_type)
        png_bytes = renderer.render_preview_png(
            badge_data, include_overlay=include_overlay
        )

        response = HttpResponse(png_bytes, content_type="image/png")
        return response


class AdminBadgeExportView(EventPermissionRequiredMixin, View):
    """
    Returns a PDF badge export for a given order position.
    """

    permission = "can_view_orders"

    def get(
        self,
        request: PretixRequest,
        organizer: Organizer,
        event: str,
        position: OrderPosition,
    ):
        pos = get_object_or_404(OrderPosition, order__event=request.event, pk=position)

        try:
            badge_data: BadgeData = (
                pos.furbadge_data  # pyright: ignore[reportAttributeAccessIssue]
            )
        except BadgeData.DoesNotExist:
            raise Http404("Badge data not configured for this position.")

        badge_link = badge_data.badge_link
        if not isinstance(badge_link, ProductBadgeLink):
            raise Http404("Badge link is invalid.")
        if badge_link.badge_type is None:
             raise Http404("Badge type not configured for this link.")
        renderer = BadgeRenderer(badge_link.badge_type)
        pdf_bytes = renderer.render(badge_data, include_overlay=False)

        response = HttpResponse(pdf_bytes, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="badge_{pos.order.code}_{pos.positionid}.pdf"'
        )
        return response
