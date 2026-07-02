# -*- coding: utf-8 -*-

"""
pretix_furbadge.frontend_views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Same as pretix_furbadge.views, but for the presale frontend views.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from typing import TYPE_CHECKING, Optional

import base64
from django.core.files.base import ContentFile, File
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import TemplateView, View
from isodate import parse_datetime
from pretix.base.models import Event, Order, OrderPosition
from pretix.presale.views import EventViewMixin, eventreverse

from .badge_renderer import BadgeRenderer
from .forms import BadgeDataForm
from .models import BadgeData, ProductBadgeLink

if TYPE_CHECKING:
    from pretix_furbadge.types import PretixRequest

    class BadgePresaleMixinBase(View):

        # We exceptionally use ignore[override] here because PretixRequest IS a HttpRequest just with Pretix added stuff
        def dispatch(self, request: PretixRequest, *args, **kwargs) -> "HttpResponse":  # type: ignore[override]
            ...

else:
    BadgePresaleMixinBase = object


class BadgePresaleMixin(EventViewMixin, BadgePresaleMixinBase):
    """
    Mixin for presale frontend views that handle badge editing, previewing, and avatar uploads.
    """

    def dispatch(self, request, *args, **kwargs) -> "HttpResponse":
        self.order = get_object_or_404(
            Order, event=request.event, code=kwargs.get("order")
        )
        if self.order.secret != kwargs.get("secret"):
            raise Http404("Unknown order")

        self.position = get_object_or_404(
            OrderPosition, order=self.order, pk=kwargs.get("position")
        )

        # Ensure a ProductBadgeLink exists for this item
        try:
            self.badge_link = ProductBadgeLink.objects.get(
                event=request.event, item=self.position.item
            )
        except ProductBadgeLink.DoesNotExist:
            raise Http404("Badge not configured for this product")

        # Get or create BadgeData
        self.badge_data, _ = BadgeData.objects.get_or_create(
            order_position=self.position, defaults={"badge_link": self.badge_link}
        )

        # Enforce edit limits
        from django.utils.timezone import now

        allow_edits = request.event.settings.get("furbadge_allow_edits", as_type=bool)

        deadline = request.event.settings.get("furbadge_edit_deadline")
        if deadline and isinstance(deadline, str):
            deadline = parse_datetime(deadline)

        self.is_locked = not allow_edits or (now() > deadline)

        if self.order.status != Order.STATUS_PAID:
            self.is_locked = True

        if self.is_locked and request.method == "POST":
            # Don't allow POST requests if locked
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Badge editing is currently locked or the order is not paid."
            )

        return super().dispatch(request, *args, **kwargs)


class BadgeEditView(BadgePresaleMixin, TemplateView):
    """
    Badge editor view for the presale frontend. Allows attendees to edit their badge information.
    """

    template_name = "pretix_furbadge/badge_edit.html"

    def get_context_data(self, **kwargs) -> dict:
        self.request: PretixRequest
        ctx = super().get_context_data(**kwargs)
        ctx["order"] = self.order
        ctx["position"] = self.position
        ctx["badge_data"] = self.badge_data
        ctx["is_locked"] = self.is_locked

        event: Event = self.request.event
        nickname_question_id = event.settings.get(
            "furbadge_nickname_question", as_type=int
        )
        hide_text_input = bool(nickname_question_id)

        # Pass form and dynamically handle the input state
        form = BadgeDataForm(instance=self.badge_data)
        if hide_text_input and "badge_text" in form.fields:
            # Prevent backend modification by making it read-only/disabled
            form.fields["badge_text"].disabled = True
            form.fields["badge_text"].required = False

        ctx["form"] = form
        ctx["hide_text_input"] = hide_text_input  # Sent to template

        ctx["avatar_width"] = self.badge_link.badge_type.image_width
        ctx["avatar_height"] = self.badge_link.badge_type.image_height

        ctx["preview_url"] = eventreverse(
            event,
            "plugins:pretix_furbadge:badge.preview",
            kwargs={
                "order": self.order.code,
                "secret": self.order.secret,
                "position": self.position.pk,
            },
        )
        ctx["upload_url"] = eventreverse(
            event,
            "plugins:pretix_furbadge:badge.upload",
            kwargs={
                "order": self.order.code,
                "secret": self.order.secret,
                "position": self.position.pk,
            },
        )
        return ctx

    def post(self, request: PretixRequest, *args, **kwargs):
        event: Event = self.request.event
        nickname_question_id = event.settings.get(
            "furbadge_nickname_question", as_type=int
        )

        form = BadgeDataForm(request.POST, instance=self.badge_data)

        if nickname_question_id and "badge_text" in form.fields:
            form.fields["badge_text"].disabled = True
            form.fields["badge_text"].required = False

        if form.is_valid():
            instance = form.save(commit=False)
            if nickname_question_id:
                instance.badge_text = self.badge_data.badge_text
            instance.save()

            url = eventreverse(
                event,
                "presale:event.order",
                kwargs={
                    "order": self.order.code,
                    "secret": self.order.secret,
                },
            )

            ctx = self.get_context_data()
            return self.render_to_response(ctx)

        ctx = self.get_context_data()
        ctx["form"] = form
        return self.render_to_response(ctx)


class BadgePreviewView(BadgePresaleMixin, View):
    """
    Badge preview view for the presale frontend. Renders a PNG preview of the badge based on current data.
    """

    def get(self, request, *args, **kwargs):
        renderer = BadgeRenderer(self.badge_link.badge_type)
        png_bytes = renderer.render_preview_png(self.badge_data, dpi=150)

        response = HttpResponse(png_bytes, content_type="image/png")
        return response


class AvatarUploadView(BadgePresaleMixin, View):
    """
    Handles avatar uploads for the badge editor in the presale frontend. Accepts base64-encoded image data via POST.
    """

    def post(self, request, *args, **kwargs):
        # Handle cropped avatar upload (assume base64 encoded image in POST data)
        image_data = request.POST.get("image_data")
        if not image_data:
            return JsonResponse(
                {"success": False, "error": "No image data"}, status=400
            )

        format, imgstr = image_data.split(";base64,")
        ext = format.split("/")[-1]

        data = ContentFile(
            base64.b64decode(imgstr), name=f"avatar_{self.position.pk}.{ext}"
        )

        if data.name:
            self.badge_data.avatar.save(data.name, data, save=True)
        else:
            return JsonResponse(
                {"success": False, "error": "Invalid image data"}, status=400
            )

        return JsonResponse({"success": True})


class PublicAttendeeListView(EventViewMixin, TemplateView):
    """
    Renders a public list of attendees who have opted to show their badge information.
    This view is accessible without authentication and despite having a .html template,
    it returns JSON data for usage with external sites.
    """

    template_name = "pretix_furbadge/public_attendee_list.html"

    def get_default_avatar_url(self, event: Event) -> Optional[str]:
        """Determines the URL of the event's configured default avatar setting,

        falling back to a local static placeholder if none is configured.
        """
        # Read the file object using pretix's native types helper
        default_avatar_file = event.settings.get(
            "furbadge_default_avatar", as_type=File
        )

        if default_avatar_file:
            try:
                # If it's a standard storage field, it will have a .url attribute
                if hasattr(default_avatar_file, "url") and default_avatar_file.url:
                    return default_avatar_file.url
                # Fallback safeguard alternative for older configurations
                elif hasattr(default_avatar_file, "name") and default_avatar_file.name:
                    from django.core.files.storage import default_storage

                    return default_storage.url(default_avatar_file.name)
            except Exception:
                pass

        return None

    def render_to_response(self, context, **response_kwargs) -> JsonResponse:
        """Intercepts the template rendering pipeline and returns JSON instead."""

        # 1. Grab the nickname question setting configuration
        self.request: PretixRequest
        event: Event = self.request.event
        nickname_question_id = event.settings.get(
            "furbadge_nickname_question", as_type=int
        )

        # 2. Get the default event configuration image fallback URL
        default_avatar_url = self.get_default_avatar_url(event)

        # 3. Query all authorized records with pre-fetched attributes
        badges = (
            BadgeData.objects.filter(
                order_position__order__event=event,
                show_in_public_list=True,
                order_position__order__status=Order.STATUS_PAID,
            )
            .select_related(
                "order_position", "order_position__item", "order_position__order"
            )
            .prefetch_related("order_position__answers")
            .order_by("badge_text")
        )

        results = []
        for bd in badges:
            item_id = str(bd.order_position.item.id) if bd.order_position.item else ""

            # Determine Nickname fallback logic hierarchy
            display_name = ""
            if bd.badge_text:
                display_name = bd.badge_text.strip()
            elif nickname_question_id and bd.order_position:
                # We will ignore type checking here because the prefetch_related ensures answers are available
                ans = next(
                    (
                        a
                        for a in bd.order_position.answers.all()  # pyright: ignore[reportAttributeAccessIssue]
                        if a.question_id == nickname_question_id
                    ),
                    None,
                )
                if ans and ans.answer:
                    display_name = ans.answer.strip()

            # Determine Avatar source link mapping target
            avatar_url = bd.avatar.url if bd.avatar else default_avatar_url

            data = {
                "nickname": display_name or "Attendee",
                "avatar": avatar_url,
                "order_type": item_id,
            }

            if bd.show_telegram_in_public_list and hasattr(bd, "telegram_username"):
                data["telegram_username"] = bd.telegram_username

            results.append(data)

        return JsonResponse({"attendees": results}, **response_kwargs)
