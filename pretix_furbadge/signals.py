# -*- coding: utf-8 -*-

"""
pretix_furbadge.signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Signal handlers for the pretix_furbadge plugin.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

import logging
from django import forms
from django.conf import settings
from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import (
    email_filter,
    global_email_filter,
    order_placed,
    register_data_exporters,
)
from pretix.control.signals import (
    item_forms,
    nav_event_settings,
    order_info,
    order_position_buttons,
)
from pretix.presale.signals import (
    contact_form_fields,
    contact_form_fields_overrides,
    order_info_top,
    order_meta_from_request,
    question_form_fields_overrides,
)
from pretix.presale.views import eventreverse
from pretix.presale.views.cart import (
    cart_session,
)

from .bot.telegram_api import tg_send_message
from .forms import (
    ProductBadgeLinkForm,
    TelegramLoginPromptField,
    TelegramLoginPromptWidget,
    TelegramOrderEmailAddition,
    TelegramPreferencesForm,
)
from .models import BadgeData, ProductBadgeLink, TelegramIdentity, TelegramOrderLink

logger = logging.getLogger(__name__)


def send_telegram_notification(chat_id, subject, body, event=None):
    text = f"{subject}\n\n{body}".strip()
    tg_send_message(chat_id, text, event=event)


@receiver(nav_event_settings, dispatch_uid="furbadge_nav_settings")
def navbar_settings(sender, request, **kwargs):
    """
    Appends the "Furry Badges" settings link to the Pretix event sidebar navigation.
    """
    url = request.resolver_match
    is_active = url.namespace == "plugins:pretix_furbadge"
    return [
        {
            "label": _("Furry Badges"),
            "url": reverse(
                "plugins:pretix_furbadge:settings",
                kwargs={
                    "event": request.event.slug,
                    "organizer": request.organizer.slug,
                },
            ),
            "active": is_active,
        }
    ]


@receiver(item_forms, dispatch_uid="furbadge_item_forms")
def control_item_forms(sender, request, item, **kwargs):
    """
    Adds the "Furry Badge" form to the Pretix item edit page in the control panel.
    This form allows event organizers to configure badge settings for each item.
    """
    try:
        inst = ProductBadgeLink.objects.get(item=item, event=sender)
    except ProductBadgeLink.DoesNotExist:
        inst = ProductBadgeLink(item=item, event=sender)

    form = ProductBadgeLinkForm(
        data=request.POST if request.method == "POST" else None,
        instance=inst,
        event=sender,
        prefix="furbadge",
    )
    form.fields.pop("item")

    form.title = _("Furry Badges")
    form.template = "pretix_furbadge/item_form.html"
    return form


@receiver(order_position_buttons, dispatch_uid="furbadge_order_position_buttons")
def add_custom_button(sender, order, position, request, **kwargs):
    """
    Adds custom buttons to the order position view in the control panel.
    These buttons allow event organizers to preview, edit, and export badges for each order position.
    """

    # Only show if a badge link is configured for this item
    if not ProductBadgeLink.objects.filter(event=sender, item=position.item).exists():
        return ""

    # Check if data exists
    badge_data = BadgeData.objects.filter(order_position=position).first()

    buttons = []
    if badge_data:
        edit_url = reverse(
            "plugins:pretix_furbadge:badge.edit",
            kwargs={
                "organizer": sender.organizer.slug,
                "event": sender.slug,
                "order": order.code,
                "secret": order.secret,
                "position": position.pk,
            },
        )
        preview_url = reverse(
            "plugins:pretix_furbadge:admin.preview",
            kwargs={
                "organizer": sender.organizer.slug,
                "event": sender.slug,
                "position": position.pk,
            },
        )
        raw_preview_url = reverse(
            "plugins:pretix_furbadge:admin.preview",
            kwargs={
                "organizer": sender.organizer.slug,
                "event": sender.slug,
                "position": position.pk,
            },
        )
        export_url = reverse(
            "plugins:pretix_furbadge:admin.export",
            kwargs={
                "organizer": sender.organizer.slug,
                "event": sender.slug,
                "position": position.pk,
            },
        )
        buttons.append(
            f'<a href="{edit_url}" class="btn btn-default btn-xs" style="margin-left: 1px;" target="_blank"><i class="fa fa-picture-o"></i> {str(_("Edit Badge (User View)"))}</a>'
        )
        buttons.append(
            f'<a href="{preview_url}" class="btn btn-default btn-xs" style="margin-left: 1px;" target="_blank"><i class="fa fa-picture-o"></i> {str(_("Preview Badge"))}</a>'
        )
        buttons.append(
            f'<a href="{raw_preview_url}?overlay=0" class="btn btn-default btn-xs" style="margin-left: 1px;" target="_blank"><i class="fa fa-picture-o"></i> {str(_("Preview Raw Badge"))}</a>'
        )
        buttons.append(
            f'<a href="{export_url}" class="btn btn-default btn-xs" style="margin-left: 1px;" target="_blank"><i class="fa fa-download"></i> {str(_("Export Badge PDF"))}</a>'
        )

    return "".join(buttons)


@receiver(
    question_form_fields_overrides,
    dispatch_uid="furbadge_question_form_fields_overrides",
)
def add_email_to_order(sender, request, position, **kwargs):
    """
    Adds the email field to the order form if the user has connected their Telegram account.
    This allowed it to be disabled.
    """
    if "/modify" in request.path:
        order = position.order
        if not order.email or order.email == settings.PRETIX_EMAIL_NONE_VALUE:
            return {
                "email": {
                    "disabled": False,
                    "required": False,
                }
            }

    return {}


@receiver(order_info, dispatch_uid="furbadge_telegram_order_info")
def add_telegram_info(sender, order, **kwargs):
    """
    Adds Telegram account information to the order details view in the control panel.
    This includes the linked Telegram username and options to manage the connection.
    """

    telegram_enabled = bool(
        sender.settings.get("furbadge_telegram_enabled", as_type=bool)
    )
    if not telegram_enabled:
        return ""

    link = TelegramOrderLink.objects.filter(order=order).first()

    username = ""
    safe_username = ""

    if link:
        username = link.identity.username or link.identity.first_name or ""
        safe_username = escape(username)

    request = kwargs.get("request")

    html = render_to_string(
        "pretix_furbadge/telegram_order_admin.html",
        {
            "order": order,
            "event": sender,
            "safe_username": safe_username,
            "confirm_msg": _(
                "Are you sure you want to disconnect your Telegram account?"
            ),
            "telegram_linked": bool(link),
            "telegram_preference_form": TelegramPreferencesForm(instance=link),
            "telegram_email_addition_form": TelegramOrderEmailAddition(instance=order),
            "no_email": order.email == settings.PRETIX_EMAIL_NONE_VALUE,
        },
        request=request,
    )

    return html


@receiver(order_info_top, dispatch_uid="furbadge_order_info_top")
def presale_order_info_top(sender, order, request, **kwargs):
    """
    Add the badge edit/preview link-to banner in order page for attendees.
    This is displayed in the order details view in the presale frontend.
    """

    # Fetch positions along with item info and custom badge data
    positions = order.positions.select_related("item").all()

    item_ids = {p.item_id for p in positions}

    linked_item_ids = set(
        ProductBadgeLink.objects.filter(event=sender, item_id__in=item_ids).values_list(
            "item_id", flat=True
        )
    )

    if not linked_item_ids:
        return ""

    # Grab the configured question ID using the event sender settings
    nickname_question_id = sender.settings.get(
        "furbadge_nickname_question", as_type=int
    )

    badge_positions = []
    for p in positions:
        if p.item_id not in linked_item_ids:
            continue

        badge_data: BadgeData = BadgeData.objects.filter(order_position=p).first()
        display_name = ""

        if nickname_question_id:
            # Using your snippet logic targeted at the order position
            ans = p.answers.filter(question_id=nickname_question_id).first()
            if ans and ans.answer:
                display_name = ans.answer.strip()
        elif badge_data and badge_data.badge_text:
            display_name = badge_data.badge_text.strip()

        # Attach computed string (defaults to empty string if both checks fail)
        p.computed_badge_display_name = display_name

        if badge_data and badge_data.has_badge:
            badge_positions.append(p)

    telegram_enabled = bool(
        sender.settings.get("furbadge_telegram_enabled", as_type=bool)
    )
    telegram_linked = False
    telegram_link_instance = None
    telegram_username = ""
    telegram_connect_url = ""
    telegram_disconnect_url = ""
    telegram_candisconnect = False
    telegram_public_share = False

    if order.email and order.email != settings.PRETIX_EMAIL_NONE_VALUE:
        telegram_candisconnect = True

    if telegram_enabled:
        link = TelegramOrderLink.objects.filter(order=order).first()
        if link:
            telegram_linked = True
            telegram_link_instance = link
            telegram_username = link.identity.username or link.identity.first_name or ""
            badge_data = BadgeData.objects.filter(order_position__order=order).first()
            telegram_public_share = bool(
                getattr(badge_data, "show_telegram_in_public_list", False)
            )
            telegram_disconnect_url = reverse(
                "plugins:pretix_furbadge:telegram.disconnect",
                kwargs={
                    "organizer": sender.organizer.slug,
                    "event": sender.slug,
                    "order": order.code,
                    "secret": order.secret,
                },
            )
        else:
            telegram_connect_url = eventreverse(
                sender,
                "plugins:pretix_furbadge:telegram.connect.start",
                kwargs={"order": order.code, "secret": order.secret},
            )

    return render_to_string(
        "pretix_furbadge/order_info.html",
        {
            "order": order,
            "event": sender,
            "has_badges": len(badge_positions) > 0,
            "badge_positions": badge_positions,
            "telegram_enabled": telegram_enabled,
            "telegram_linked": telegram_linked,
            "telegram_username": telegram_username,
            "telegram_connect_url": telegram_connect_url,
            "telegram_disconnect_url": telegram_disconnect_url,
            "telegram_candisconnect": telegram_candisconnect,
            "telegram_public_share": telegram_public_share,
            "telegram_consent_text": sender.settings.get(
                "furbadge_telegram_consent_text", as_type=str
            ),
            "telegram_preference_form": TelegramPreferencesForm(
                instance=telegram_link_instance
            ),
            "telegram_email_addition_form": TelegramOrderEmailAddition(instance=order),
            "no_email": not order.email
            or order.email == settings.PRETIX_EMAIL_NONE_VALUE,
            "telegram_email": settings.PRETIX_EMAIL_NONE_VALUE,
        },
        request=request,
    )


@receiver(email_filter, dispatch_uid="furbadge_telegram_email_filter")
def on_event_email(sender, message, order=None, **kwargs):
    """
    Email filter that forwards event-related emails to the user's linked Telegram account if they have opted in.
    This allows users to receive notifications via Telegram in addition to email.
    """
    try:
        if order is None:
            return message
        links = TelegramOrderLink.objects.filter(order=order).select_related("identity")
        for link in links:
            delivery_mode = (
                getattr(link, "telegram_delivery_mode", "email_only")
                if link
                else "email_only"
            )
            if delivery_mode == "email_only":
                continue

            send_telegram_notification(
                chat_id=link.identity.chat_id or link.identity.telegram_user_id,
                subject=message.subject or "(no subject)",
                body=message.body or "",
                event=sender,
            )
    except Exception:
        logger.exception("Failed to forward event email to Telegram")
    return message


@receiver(global_email_filter, dispatch_uid="furbadge_telegram_global_email_filter")
def on_global_email(sender, message, order=None, **kwargs):
    """
    Global email filter that forwards global emails to the user's linked Telegram account if they have opted in.
    """
    if order is None:
        return message
    try:
        links = TelegramOrderLink.objects.filter(order=order).select_related("identity")
        for link in links:
            delivery_mode = (
                getattr(link, "telegram_delivery_mode", "email_only")
                if link
                else "email_only"
            )

            if delivery_mode == "email_only":
                continue

            send_telegram_notification(
                chat_id=link.identity.chat_id or link.identity.telegram_user_id,
                subject=message.subject or "(no subject)",
                body=message.body or "",
                event=order.event,
            )
    except Exception:
        logger.exception("Failed to forward global email to Telegram")
    return message


@receiver(register_data_exporters, dispatch_uid="furbadge_export")
def register_badge_exporter(sender, **kwargs):
    """
    Registers the BadgePDFExporter with Pretix's data export system, allowing event organizers to export badge data in PDF format.
    """
    from .exporter import BadgePDFExporter

    return BadgePDFExporter


@receiver(order_placed, dispatch_uid="furbadge_order_placed")
def furbadge_order_placed(sender, order, **kwargs):
    """
    Fired immediately after an order is successfully finalized.
    We verify if any items require a badge, and initialize an empty database
    record for them so they show up cleanly on the attendee dashboard.
    """
    for pos in order.positions.all():
        try:
            link = ProductBadgeLink.objects.get(event=sender, item=pos.item)
        except ProductBadgeLink.DoesNotExist:
            continue

        # Initialize an empty/default row so the customer has a database entry ready to update later
        BadgeData.objects.get_or_create(
            order_position=pos, defaults={"badge_link": link}
        )


@receiver(contact_form_fields, dispatch_uid="furbadge_telegram_contact_field")
def telegram_contact_field(sender, request, **kwargs):
    """
    Adds the Telegram login prompt field to the contact form during checkout.
    This allows users to connect their Telegram account during the checkout process.
    """
    
    if not sender.settings.get("furbadge_telegram_enabled", as_type=bool):
        return {}

    pretix_cart_session = cart_session(request)
    data = pretix_cart_session.get(  # pyright: ignore[reportOptionalMemberAccess]
        "furbadge_telegram_checkout", {}
    )

    already_linked = bool(data and data.get("verified"))

    connect_url = reverse(
        "plugins:pretix_furbadge:telegram.checkout.start",
        kwargs={
            "organizer": sender.organizer.slug,
            "event": sender.slug,
        },
    )

    disconnect_url = reverse(
        "plugins:pretix_furbadge:telegram.checkout.disconnect",
        kwargs={
            "organizer": sender.organizer.slug,
            "event": sender.slug,
        },
    )

    pretix_cart_session = cart_session(request)
    contact_form_data = (
        pretix_cart_session.get(  # pyright: ignore[reportOptionalMemberAccess]
            "contact_form_data", {}
        )
    )
    contact_form_data["furbadge_telegram"] = data.get("username") if data else None

    if "/checkout/questions" in request.path:
        if already_linked:
            if contact_form_data.get("email") == settings.PRETIX_EMAIL_NONE_VALUE:
                contact_form_data["email"] = ""

            return {
                "furbadge_telegram": TelegramLoginPromptField(
                    widget=TelegramLoginPromptWidget(
                        connect_url=connect_url,
                        already_linked=already_linked,
                        disconnect_url=disconnect_url,
                        username=data.get("username") if data else None,
                        first_name=data.get("first_name") if data else None,
                    ),
                    initial=data.get("username") if data else None,
                    label="Telegram",
                ),
                "email": forms.EmailField(
                    label=_("Email"),
                    validators=[],
                    required=False,
                    initial="",
                    widget=forms.EmailInput(
                        attrs={"autocomplete": "section-contact email"}
                    ),
                ),
            }

        return {
            "furbadge_telegram": TelegramLoginPromptField(
                widget=TelegramLoginPromptWidget(
                    connect_url=connect_url,
                    already_linked=already_linked,
                    disconnect_url=disconnect_url,
                    username=data.get("username") if data else None,
                    first_name=data.get("first_name") if data else None,
                ),
                initial=data.get("username") if data else None,
                label="Telegram",
            ),
            "email": forms.EmailField(
                label=_("Email"),
                validators=[],
                required=False,
                initial=None,
                widget=forms.EmailInput(
                    attrs={"autocomplete": "section-contact email"}
                ),
            ),
        }

    if already_linked:
        return {
            "furbadge_telegram": TelegramLoginPromptField(
                widget=TelegramLoginPromptWidget(
                    connect_url=connect_url,
                    already_linked=already_linked,
                    disconnect_url=disconnect_url,
                    username=data.get("username") if data else None,
                    first_name=data.get("first_name") if data else None,
                ),
                label="Telegram",
                initial=data.get("username") if data else None,
            ),
        }
    else:
        return {}


@receiver(
    contact_form_fields_overrides, dispatch_uid="furbadge_telegram_contact_override"
)
def telegram_contact_override(sender, request, order=None, **kwargs):
    """
    Overrides the contact form fields during checkout to pre-fill and disable the email field if the user has connected their Telegram account.
    This ensures that users who rely on Telegram for notifications do not need to provide an email address
    """
    pretix_cart_session = cart_session(request)
    data = pretix_cart_session.get(  # pyright: ignore[reportOptionalMemberAccess]
        "furbadge_telegram_checkout", {}
    )
    if not data or not data.get("verified"):
        return {}
    if request.method == "POST" and not request.POST.get("email", "").strip():
        return {
            "email": {
                "initial": settings.PRETIX_EMAIL_NONE_VALUE,
                "disabled": True,
            }
        }

    return {}


@receiver(order_placed, dispatch_uid="furbadge_telegram_order_placed")
def link_telegram_on_order_placed(sender, order, **kwargs):
    """
    Fired immediately after an order is successfully finalized.
    This signal handler checks if the user has connected their Telegram account during checkout and links it to
    the order.
    """
    telegram_data = (order.meta_info_data or {}).get("furbadge_telegram")
    if not telegram_data:
        return  # Telegram wasn't connected for this order — untouched, as normal

    if not order.email:
        # Buyer left it blank, relying on Telegram — fill the dummy now,
        # after the fact, rather than ever having pre-filled the form.
        order.email = settings.PRETIX_EMAIL_NONE_VALUE
        order.save(update_fields=["email"])

    identity, _ = TelegramIdentity.objects.get_or_create(
        event=order.event,
        telegram_user_id=telegram_data["telegram_user_id"],
    )
    identity.username = telegram_data.get("username")
    identity.chat_id = telegram_data.get("chat_id")
    identity.bot_access_granted = True
    identity.consent_given = True
    identity.consent_given_at = timezone.now()
    identity.save()
    TelegramOrderLink.objects.get_or_create(
        identity=identity, order=order, event=order.event
    )


@receiver(order_meta_from_request, dispatch_uid="furbadge_telegram_order_meta")
def telegram_order_meta(sender, request, **kwargs):
    pretix_cart_session = cart_session(request)
    data = pretix_cart_session.get(  # pyright: ignore[reportOptionalMemberAccess]
        "furbadge_telegram_checkout", {}
    )
    if not data or not data.get("verified"):
        return {}
    return {"furbadge_telegram": data}
