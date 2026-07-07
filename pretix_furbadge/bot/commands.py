import io

from django.utils.translation import gettext as _
from pretix.base.models import Order, OrderPosition
from pretix.presale.views import eventreverse
import segno

from ..models import BadgeData, TelegramIdentity
from .telegram_api import tg_send_document, tg_send_message, tg_send_web_app_button


def get_identity(event, telegram_user_id):
    return TelegramIdentity.objects.filter(
        event=event,
        telegram_user_id=telegram_user_id,
        consent_given=True,
    ).first()


def _parse_index(raw, count):
    try:
        n = int(raw)
    except ValueError:
        return None
    if n < 1 or n > count:
        return None
    return n


def _numbered_orders(identity):
    if not identity:
        return []
    return list(
        identity.order_links.select_related("order")
        .order_by("order__datetime", "order__code")
        .values_list("order", flat=True)
    )


def _numbered_badges(identity):
    order_ids = _numbered_orders(identity)
    if not order_ids:
        return []

    positions = (
        OrderPosition.objects.filter(order_id__in=order_ids)
        .select_related("order", "item")
        .order_by("order__datetime", "positionid")
    )
    badge_position_ids = set(
        BadgeData.objects.filter(order_position__in=positions).values_list(
            "order_position_id", flat=True
        )
    )
    return [p for p in positions if p.pk in badge_position_ids]


def handle_shop(event, identity, chat_id, args, request):
    if not event or not event.slug:
        tg_send_message(chat_id, _("The shop is currently unavailable."), event=event)
        return

    url = eventreverse(
        request.event,
        "presale:event.index",
    )

    full_url = request.build_absolute_uri(url)

    tg_send_web_app_button(chat_id, full_url, _("Open shop"), event=event)


def handle_orders_list(event, identity, chat_id, args, request):
    order_ids = _numbered_orders(identity)
    if not order_ids:
        tg_send_message(chat_id, _("No connected orders yet."), event=event)
        return

    orders = Order.objects.in_bulk(order_ids)
    lines = [
        f"{i}. {orders[oid].code} — {orders[oid].event.name}"
        for i, oid in enumerate(order_ids, start=1)
        if oid in orders
    ]

    message = _(
        "Your orders:\n{orders}\n\nUse /order <number or ID> to open one."
    ).format(orders="\n".join(lines))
    tg_send_message(chat_id, message, event=event)


def handle_order(event, identity, chat_id, args, request):
    if not args:
        return handle_orders_list(event, identity, chat_id, args, request)

    arg = args[0].strip().upper()

    # Clean the input in case they prefixed it with the event slug
    code_query = arg

    order_ids = _numbered_orders(identity)
    n = _parse_index(arg, len(order_ids) if order_ids else 0)
    order = None

    if n is not None:
        # Treat as an index from the user's connected list
        order_pk = order_ids[n - 1]
        order = Order.objects.filter(pk=order_pk).first()

    if not order:
        # Allow lookup by code, but only within the user's connected orders
        order = Order.objects.filter(pk__in=order_ids, code__iexact=code_query).first()
    if not order:
        tg_send_message(
            chat_id,
            _("Invalid order number or ID. Use /orders to see the list."),
            event=event,
        )
        return

    url = eventreverse(
        request.event,
        "presale:event.order",
        kwargs={
            "order": order.code,
            "secret": order.secret,
        },
    )

    full_url = request.build_absolute_uri(url)

    tg_send_web_app_button(
        chat_id,
        full_url,
        _("Manage order {order_code}").format(order_code=order.code),
        event=event,
    )


def handle_badges_list(event, identity, chat_id, args, request):
    positions = _numbered_badges(identity)
    if not positions:
        tg_send_message(chat_id, _("No badges yet."), event=event)
        return

    lines = [
        f"{i}. {p.attendee_name or p.item.name} — "
        + _("order {order_code}").format(order_code=p.order.code)
        for i, p in enumerate(positions, start=1)
    ]

    message = _(
        "Your badges:\n{badges}\n\nUse /badge <number or Order ID> to edit one."
    ).format(badges="\n".join(lines))
    tg_send_message(chat_id, message, event=event)


def handle_badge(event, identity, chat_id, args, request):
    if not args:
        return handle_badges_list(event, identity, chat_id, args, request)

    arg = args[0].strip().upper()

    # Clean event slug from input if present
    search_arg = arg
    if event and event.slug and search_arg.startswith(f"{event.slug.upper()}-"):
        search_arg = search_arg[len(event.slug) + 1 :]

    # Separate code from possible position ID (e.g., ABCDE-1)
    code_part = search_arg.split("-")[0]
    pos_part = search_arg.split("-")[1] if "-" in search_arg else None

    positions = _numbered_badges(identity)
    n = _parse_index(arg, len(positions) if positions else 0)
    position = None

    if n is not None:
        # Treat as an index from the user's connected list
        position = positions[n - 1]

    if not position:
        # Fallback: search globally across the event
        order = Order.objects.filter(event=event, code__iexact=code_part).first()
        if order:
            badge_positions = list(
                OrderPosition.objects.filter(
                    order=order, id__in=BadgeData.objects.values("order_position_id")
                )
            )

            if len(badge_positions) == 1:
                position = badge_positions[0]
            elif len(badge_positions) > 1:
                if pos_part:
                    for p in badge_positions:
                        if str(p.positionid) == pos_part:
                            position = p
                            break
                if not position:
                    tg_send_message(
                        chat_id,
                        _(
                            "Order {order_code} has multiple badges. Please specify the badge (e.g., {order_code}-1)."
                        ).format(order_code=code_part),
                        event=event,
                    )
                    return

    if not position:
        tg_send_message(
            chat_id,
            _("Invalid badge number or Order ID. Use /badges to see the list."),
            event=event,
        )
        return

    url = eventreverse(
        request.event,
        "plugins:pretix_furbadge:badge.edit",
        kwargs={
            "order": position.order.code,
            "secret": position.order.secret,
            "position": position.pk,
        },
    )

    full_url = request.build_absolute_uri(url)

    tg_send_web_app_button(
        chat_id,
        full_url,
        _("Edit your badge for order {order_code}").format(
            order_code=position.order.code
        ),
        event=event,
    )


def handle_qr(event, identity, chat_id, args, request):
    if not args:
        return handle_orders_list(event, identity, chat_id, args, request)

    arg = args[0].strip().upper()

    code_query = arg
    if event and event.slug and code_query.startswith(f"{event.slug.upper()}-"):
        code_query = code_query[len(event.slug) + 1 :]

    order_ids = _numbered_orders(identity)
    n = _parse_index(arg, len(order_ids) if order_ids else 0)
    order = None

    if n is not None:
        order_pk = order_ids[n - 1]
        order = Order.objects.filter(pk=order_pk).first()

    if not order:
        order = Order.objects.filter(event=event, code__iexact=code_query).first()

    if not order:
        tg_send_message(
            chat_id,
            _("Invalid number or Order ID. Use /orders to see the list."),
            event=event,
        )
        return

    # Check if tickets/downloads are allowed yet
    if getattr(order, "status", None) != Order.STATUS_PAID and not getattr(
        order, "ticket_download_available", False
    ):
        tg_send_message(
            chat_id,
            _(
                "Tickets are not yet available for order {order_code} (status: {status})."
            ).format(order_code=order.code, status=order.get_status_display()),
            event=event,
        )
        return

    try:
        positions = order.positions.filter()
        if not positions.exists():
            tg_send_message(
                chat_id,
                _("No ticket items found for this order."),
                event=event,
            )
            return

        for position in positions:
            qr_text = position.secret
            if not qr_text:
                continue

            qr = segno.make(qr_text, error="M")
            out = io.BytesIO()
            qr.save(out, kind="png", scale=12)
            out.seek(0)

            photo_content = out.getvalue()
            filename = f"ticket_qr_{order.code}_{position.positionid}.png"

            tg_send_document(
                chat_id=chat_id,
                filename=filename,
                content=photo_content,
                mimetype="image/png",
                event=event,
                caption=_("Ticket QR Code — {order_code} ({item})").format(
                    order_code=order.code, item=position.item.name
                ),
                parse_mode="HTML",
            )

    except Exception as e:
        tg_send_message(
            chat_id,
            _(
                "An error occurred while generating the QR code photo for order {order_code}. Please try again later."
            ).format(order_code=order.code),
            event=event,
        )


def handle_help(event, identity, chat_id, args, request):
    help_text = _(
        "/shop — open the shop\n"
        "/orders — list your orders\n"
        "/order <n or ID> — manage an order\n"
        "/badges — list your badges\n"
        "/badge <n or ID> — edit a badge\n"
        "/qr <n or ID> — get the ticket/QR for an order"
    )
    tg_send_message(chat_id, help_text, event=event)


COMMANDS = {
    "shop": handle_shop,
    "orders": handle_orders_list,
    "order": handle_order,
    "badges": handle_badges_list,
    "badge": handle_badge,
    "qr": handle_qr,
    "help": handle_help,
}
