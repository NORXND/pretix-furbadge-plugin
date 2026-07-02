# -*- coding: utf-8 -*-

"""
pretix_furbadge.signals
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Signal handlers for the pretix_furbadge plugin.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from django.dispatch import receiver
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from pretix.base.signals import order_placed, register_data_exporters
from pretix.control.signals import (
    item_forms,
    nav_event_settings,
    order_position_buttons,
)
from pretix.presale.signals import order_info_top

from .forms import ProductBadgeLinkForm
from .models import BadgeData, ProductBadgeLink


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

        badge_data = BadgeData.objects.filter(order_position=p).first()
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
        badge_positions.append(p)

    return render_to_string(
        "pretix_furbadge/order_info.html",
        {
            "order": order,
            "event": sender,
            "badge_positions": badge_positions,
        },
        request=request,
    )


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
