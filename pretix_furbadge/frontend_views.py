# -*- coding: utf-8 -*-

"""
pretix_furbadge.frontend_views
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Same as pretix_furbadge.views, but for the presale frontend views.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from __future__ import annotations

from logging import Logger
from typing import TYPE_CHECKING, Any, Optional

import base64
import hashlib
import json
import jwt
import requests  # type: ignore[import-untyped]
import secrets
from django.conf import settings
from django.core.files.base import ContentFile, File
from django.http import (
    Http404,
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.utils.translation import gettext_lazy as _
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import TemplateView, View
from isodate import parse_datetime
from pretix.base.models import Event, Order, OrderPosition
from pretix.presale.views import EventViewMixin, eventreverse
from .bot.telegram_api import tg_send_message

from pretix_furbadge.bot.commands import COMMANDS, get_identity

from pretix.presale.views.cart import (
    cart_session,
)

from .badge_renderer import BadgeRenderer
from .forms import BadgeDataForm, TelegramOrderEmailAddition, TelegramPreferencesForm
from .models import BadgeData, ProductBadgeLink, TelegramIdentity, TelegramOrderLink

TELEGRAM_AUTHORIZE_URL = "https://oauth.telegram.org/auth"
TELEGRAM_TOKEN_URL = "https://oauth.telegram.org/token"
TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
SESSION_KEY = "furbadge_tg_connect"


def _question_answer_is_true(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {
        "1",
        "true",
        "yes",
        "y",
        "on",
        "enabled",
        "show",
        "public",
        "publicly",
    }


def _badge_is_publicly_listed(badge_data: BadgeData, event: Event) -> bool:
    public_question_id = event.settings.get(
        "furbadge_public_list_question", as_type=int
    )
    if public_question_id and badge_data.order_position:
        answer = badge_data.order_position.answers.filter(
            question_id=public_question_id
        ).first()
        if answer and answer.answer is not None:
            return _question_answer_is_true(answer.answer)
    return bool(badge_data.show_in_public_list)


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    return verifier, challenge


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

    def dispatch(self, request: Any, *args: Any, **kwargs: Any) -> "HttpResponse":
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

        if deadline is not None:
            if deadline and isinstance(deadline, str):
                deadline = parse_datetime(deadline)

            self.is_locked = not allow_edits or (now() > deadline)
        else:
            self.is_locked = not allow_edits

        if self.order.status != Order.STATUS_PAID:
            self.is_locked = True

        if self.is_locked and request.method == "POST":
            # Don't allow POST requests if locked
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied(
                "Badge editing is currently locked or the order is not paid."
            )

        return super().dispatch(request, *args, **kwargs)


class TelegramOrderMixin(EventViewMixin):
    """
    Helper mixin for managing view with orders.
    """
    def dispatch(self, request: Any, *args: Any, **kwargs: Any):
        self.order = get_object_or_404(
            Order, event=request.event, code=kwargs.get("order")
        )
        if self.order.secret != kwargs.get("secret"):
            raise Http404("Unknown order")
        return super().dispatch(request, *args, **kwargs)


class TelegramConnectStartView(TelegramOrderMixin, View):
    """
    This is a view that redirects user to Telegram's OAuth2 authorization endpoint to initiate the connection process.
    """
    def get(self, request, *args, **kwargs):
        if request.GET.get("consent") != "1":
            return HttpResponseBadRequest("Consent checkbox must be checked")

        event = request.event
        if not event.settings.get("furbadge_telegram_enabled", as_type=bool):
            return HttpResponseBadRequest("Telegram integration disabled")

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        request.session[SESSION_KEY] = {
            "state": state,
            "verifier": verifier,
            "order_pk": self.order.pk,
            "event_slug": event.slug,
        }

        client_id = event.settings.get("furbadge_telegram_client_id", as_type=str)
        callback_uri = request.build_absolute_uri(
            eventreverse(
                event,
                "plugins:pretix_furbadge:telegram.connect.callback",
            )
        )
        params = {
            "client_id": client_id,
            "redirect_uri": callback_uri,
            "response_type": "code",
            "scope": "openid profile telegram:bot_access",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        query = "&".join(
            f"{k}={requests.utils.quote(str(v))}" for k, v in params.items()
        )
        return HttpResponseRedirect(f"{TELEGRAM_AUTHORIZE_URL}?{query}")


class TelegramDisconnectView(TelegramOrderMixin, View):
    """
    This is a view that disconnects a Telegram identity from an order. It deletes the corresponding TelegramOrderLink.
    """
    def get(self, request, *args, **kwargs):
        link = TelegramOrderLink.objects.filter(
            order=self.order, event=request.event
        ).first()

        if link:
            link.delete()

        url = eventreverse(
            request.event,
            "presale:event.order",
            kwargs={
                "order": self.order.code,
                "secret": self.order.secret,
            },
        )
        return HttpResponseRedirect(url)


class TelegramConnectCallbackView(EventViewMixin, View):
    """
    This is the view called FROM Telegram on user login - it links the account to the order.
    """
    def get(self, request, *args, **kwargs):
        session_data = request.session.pop(SESSION_KEY, None)
        if not session_data:
            return HttpResponseBadRequest("No pending Telegram connection")
        if request.GET.get("state") != session_data["state"]:
            return HttpResponseBadRequest("State mismatch")
        if request.GET.get("error"):
            return HttpResponseBadRequest(
                f"Telegram login failed: {request.GET['error']}"
            )

        client_id = request.event.settings.get(
            "furbadge_telegram_client_id", as_type=str
        )
        client_secret = request.event.settings.get(
            "furbadge_telegram_client_secret", as_type=str
        )
        callback_uri = request.build_absolute_uri(
            eventreverse(
                request.event,
                "plugins:pretix_furbadge:telegram.connect.callback",
                kwargs={
                    "event": request.event.slug,
                },
            )
        )

        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        token_resp = requests.post(
            TELEGRAM_TOKEN_URL,
            headers={"Authorization": f"Basic {basic}"},
            data={
                "grant_type": "authorization_code",
                "code": request.GET.get("code"),
                "redirect_uri": callback_uri,
                "client_id": client_id,
                "code_verifier": session_data["verifier"],
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        id_token = token_resp.json()["id_token"]

        signing_key = jwt.PyJWKClient(TELEGRAM_JWKS_URL).get_signing_key_from_jwt(
            id_token
        )
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://oauth.telegram.org",
            leeway=60,
        )

        telegram_user_id = str(claims["id"])
        order = Order.objects.get(pk=session_data["order_pk"])

        identity, _created = TelegramIdentity.objects.get_or_create(
            event=request.event,
            telegram_user_id=telegram_user_id,
        )
        identity.username = claims.get("preferred_username")
        identity.first_name = claims.get("given_name") or claims.get("name")
        identity.chat_id = telegram_user_id
        identity.bot_access_granted = True
        identity.consent_given = True
        identity.consent_given_at = timezone.now()
        identity.save()

        TelegramOrderLink.objects.get_or_create(
            identity=identity, order=order, event=request.event
        )

        url = eventreverse(
            request.event,
            "presale:event.order",
            kwargs={
                "order": order.code,
                "secret": order.secret,
            },
        )

        return HttpResponseRedirect(url)


class TelegramPreferencesView(EventViewMixin, View):
    """
    This view allows to update the telegram preferences.
    """
    def post(self, request: PretixRequest, *args, **kwargs) -> HttpResponse:
        order = get_object_or_404(
            Order,
            event=request.event,
            code=kwargs["order"],
        )

        if order.secret != kwargs["secret"]:
            raise Http404("Unknown order")

        link = get_object_or_404(TelegramOrderLink, order=order)

        no_email = not order.email or order.email == settings.PRETIX_EMAIL_NONE_VALUE

        preference_form = TelegramPreferencesForm(
            request.POST,
            instance=link,
            no_email=no_email,
        )

        email_form = None
        if no_email:
            email_form = TelegramOrderEmailAddition(
                request.POST,
                instance=order,
            )

        if preference_form.is_valid():
            preference_form.save(commit=True)

        if email_form:
            if email_form.is_valid():
                email_form.save(commit=True)

        return HttpResponseRedirect(
            eventreverse(
                request.event,
                "presale:event.order",
                kwargs={
                    "organizer": request.event.organizer.slug,
                    "event": request.event.slug,
                    "order": order.code,
                    "secret": order.secret,
                },
            )
        )


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
        has_telegram_link = TelegramOrderLink.objects.filter(order=self.order).exists()
        ctx["has_telegram_link"] = has_telegram_link
        badge_data = self.badge_data
        ctx["telegram_public_share"] = bool(
            getattr(badge_data, "show_telegram_in_public_list", False)
            if badge_data is not None
            else False
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
            if not _badge_is_publicly_listed(bd, event):
                continue
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

            # Show telegram?
            if bd.order_position and bd.order_position.order:
                # Evaluate the prefetched query set in memory
                active_link = next(
                    (
                        link for link in bd.order_position.order.telegram_links.all()
                        if link.public_share
                    ),
                    None
                )
                if active_link and active_link.identity.username:
                    data["telegram"] = active_link.identity.username

            results.append(data)

        return JsonResponse({"attendees": results}, **response_kwargs)


class TelegramCheckoutStartView(EventViewMixin, View):
    """Same PKCE/OAuth mechanics as TelegramConnectStartView, but stores
    the result against the cart session instead of an existing Order,
    since no Order exists yet at this point in checkout."""

    def get(self, request, *args, **kwargs):
        event = request.event
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        request.session[SESSION_KEY] = {
            "state": state,
            "verifier": verifier,
            "event_pk": event.id,
            "checkout_flow": True,
        }
        client_id = event.settings.get("furbadge_telegram_client_id", as_type=str)
        callback_uri = request.build_absolute_uri(
            reverse(
                "plugins:pretix_furbadge:telegram.checkout.callback",
                kwargs={
                    "organizer": event.organizer.slug,
                    "event": event.slug,
                },
            )
        )
        params = {
            "client_id": client_id,
            "redirect_uri": callback_uri,
            "response_type": "code",
            "scope": "openid profile telegram:bot_access",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
        query = "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
        return HttpResponseRedirect(f"{TELEGRAM_AUTHORIZE_URL}?{query}")


class TelegramCheckoutCallbackView(EventViewMixin, View):
    """
    Same as TelegramConnectCallbackView, but stores the result against the cart session instead of an existing Order,
    since no Order exists yet at this point in checkout.
    """
    
    def get(self, request, *args, **kwargs):
        session_data = request.session.pop(SESSION_KEY, None)
        if not session_data or request.GET.get("state") != session_data["state"]:
            return HttpResponseBadRequest("Invalid or expired Telegram login attempt")
        if request.GET.get("error"):
            return HttpResponseBadRequest(
                f"Telegram login failed: {request.GET['error']}"
            )

        client_id = request.event.settings.get(
            "furbadge_telegram_client_id", as_type=str
        )
        client_secret = request.event.settings.get(
            "furbadge_telegram_client_secret", as_type=str
        )
        callback_uri = request.build_absolute_uri(request.path)
        basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

        data = {
            "grant_type": "authorization_code",
            "code": request.GET.get("code"),
            "redirect_uri": callback_uri,
            "client_id": client_id,
            "code_verifier": session_data["verifier"],
        }

        token_resp = requests.post(
            TELEGRAM_TOKEN_URL,
            headers={"Authorization": f"Basic {basic}"},
            data=data,
            timeout=10,
        )
        token_resp.raise_for_status()
        id_token = token_resp.json()["id_token"]

        jwks_client = jwt.PyJWKClient(TELEGRAM_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256"],
            audience=client_id,
            issuer="https://oauth.telegram.org",
            leeway=60,
        )

        telegram_user_id = str(claims["id"])

        telegram_user_id = str(claims["id"])

        pretix_cart_session = cart_session(request)
        pretix_cart_session["furbadge_telegram_checkout"] = { # pyright: ignore[reportOptionalSubscript]
                "verified": True,
                "telegram_user_id": telegram_user_id,
                "username": claims.get("preferred_username"),
                "first_name": claims.get("given_name") or claims.get("name"),
                "chat_id": telegram_user_id,
            }

        return_url = reverse(
            "presale:event.checkout",
            kwargs={
                "organizer": request.event.organizer,
                "event": request.event,
                "step": "contact",
            },
        )

        return redirect(return_url)


class TelegramCheckoutDisconnectView(View):
    """
    Same as TelegramDisconnectView, but removes the Telegram connection from the cart session instead of an existing Order,
    since no Order exists yet at this point in checkout.
    """
    def get(self, request, *args, **kwargs):
        pretix_cart_session = cart_session(request)
        pretix_cart_session["furbadge_telegram_checkout"] = {} # pyright: ignore[reportOptionalSubscript]

        event = request.event
        return_url = reverse(
            "presale:event.checkout",
            kwargs={
                "organizer": event.organizer.slug,
                "event": event.slug,
                "step": "questions",
            },
        )
        return HttpResponseRedirect(return_url)


@method_decorator(csrf_exempt, name="dispatch")
class TelegramWebhookView(EventViewMixin, View):
    """
    Webhook endpoint for receiving Telegram bot updates. This view processes incoming messages and commands from users, 
    linking them to their orders if applicable.
    """

    def post(self, request, *args, **kwargs):
        event = request.event
        if not event:
            return HttpResponseForbidden()

        expected_secret = event.settings.get(
            "furbadge_telegram_webhook_secret", as_type=str
        )
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != expected_secret:
            return HttpResponseForbidden()

        try:
            update = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse(status=400)

        message = update.get("message")
        if not message or "text" not in message:
            return HttpResponse(status=200)

        chat_id = message["chat"]["id"]
        from_id = str(message["from"]["id"])
        text = message["text"].strip()
        if not text.startswith("/"):
            return HttpResponse(status=200)

        parts = text.split()
        command = parts[0].lstrip("/").split("@")[0].lower()
        args = parts[1:]

        identity = get_identity(event, from_id)
        if not identity and command != "start":
            tg_send_message(
                chat_id,
                _("You haven't connected Telegram to an order yet — "
                'use the "Connect Telegram" button on your order page.'),
                event=event,
            )
            return HttpResponse(status=200)

        handler = COMMANDS.get(command)
        if not handler:
            tg_send_message(chat_id, _("Unknown command. Try /help."), event=event)
            return HttpResponse(status=200)

        try:
            handler(event, identity, chat_id, args, request)
        except Exception:
            Logger.exception(
                "Error handling Telegram command %s from %s", command, from_id
            )

        return HttpResponse(status=200)
