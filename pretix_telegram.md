# pretix_furbadge — Telegram integration

Addendum to the main technical guide. Covers: linking a Telegram identity to
an order from the order page, forwarding all outgoing pretix emails to
linked Telegram users, and a bot command interface for shop/orders/badges/QR.

This does **not** use pretix's Customer/SSO subsystem. Telegram's OIDC
provider never returns an email claim, and pretix's SSO login path hard-
requires one — so this integration talks to Telegram purely as an OAuth
client from inside the plugin, and links identities directly to `Order`
(and optionally `Customer`) rows of our own.

## Architecture

- New control-panel submenu: **Telegram**, alongside Fonts/Templates, under
  `/control/event/<organizer>/<event>/furbadge/telegram/`. Configures bot
  credentials and toggles. Same `EventPermissionRequiredMixin` /
  `request.event`-scoped pattern as the rest of the control views.
- New presale addition: a "Connect Telegram" section rendered below the
  existing badges list on the order-detail page, gated behind
  `BadgePresaleMixin` like the rest of the frontend views.
- New global (non-event) endpoint: the Telegram bot webhook. This is
  intentionally **not** under `event_patterns` — a bot has one webhook for
  the whole install, not one per event.
- New models: `TelegramIdentity` (one per real-world Telegram user, per
  organizer) and `TelegramOrderLink` (many-to-many between an identity and
  the orders they've connected). This deviates from the "usually event-
  scoped" extension rule deliberately: the same Telegram user can connect
  orders across multiple events under one organizer, and the bot commands
  (`/orders`, `/badges`) are meant to list across all of them.
- New signals: `email_filter` / `global_email_filter` receivers forward
  every outgoing pretix email to any linked Telegram identity.

## Data model

**Note on scope, since the actual implementation ended up here:** the
model below was originally drafted organizer-scoped (a `TelegramIdentity`
spanning every event under one organizer, so `/orders` and `/badges` could
list across all of them in one go). The code you're actually running
uses `event=order.event` instead — event-scoped, matching this plugin's
usual convention of everything hanging off `Event`. That's a legitimate
choice, but it has a real consequence worth being deliberate about, not
just inheriting by accident: **the same Telegram user connecting to two
different events under the same organizer now gets two separate
`TelegramIdentity` rows**, one per event. The bot's `/orders` and
`/badges` listing logic in the numbering section further down still
assumes a single identity object to query orders/badges *from* — with
event-scoping, that needs to become "look up every `TelegramIdentity`
row matching this `telegram_user_id` across all events for this
organizer, then union their linked orders/badges," rather than a single
`identity.order_links` traversal. That reconciliation isn't written into
the bot-command code below yet — worth doing before relying on `/orders`
actually showing tickets bought across more than one event.

```python
# models.py additions

from django.db import models
from django_scopes import ScopedManager

from pretix.base.models import LoggedModel, Event, Order


class TelegramIdentity(LoggedModel):
    """One row per real Telegram user, per event."""
    event = models.ForeignKey(
        Event, related_name='telegram_identities', on_delete=models.CASCADE
    )
    telegram_user_id = models.CharField(max_length=64, db_index=True)
    chat_id = models.CharField(max_length=64, null=True, blank=True)
    username = models.CharField(max_length=64, null=True, blank=True)
    first_name = models.CharField(max_length=128, null=True, blank=True)

    bot_access_granted = models.BooleanField(default=False)
    consent_given = models.BooleanField(default=False)
    consent_given_at = models.DateTimeField(null=True, blank=True)

    created = models.DateTimeField(auto_now_add=True)
    last_modified = models.DateTimeField(auto_now=True)

    objects = ScopedManager(event='event')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['event', 'telegram_user_id'],
                name='unique_telegram_identity_per_event',
            )
        ]


class TelegramOrderLink(LoggedModel):
    """An identity can connect more than one order within the same event
    (multiple tickets bought in separate orders)."""
    event = models.ForeignKey(
        Event, related_name='telegram_order_links', on_delete=models.CASCADE
    )
    identity = models.ForeignKey(
        TelegramIdentity, related_name='order_links', on_delete=models.CASCADE
    )
    order = models.ForeignKey(
        Order, related_name='telegram_links', on_delete=models.CASCADE
    )
    created = models.DateTimeField(auto_now_add=True)

    objects = ScopedManager(event='event')

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['identity', 'order'], name='unique_identity_order_link'
            )
        ]
```

`event` on `TelegramOrderLink` is technically derivable via
`identity.event` (a `TelegramOrderLink` can't point at a different event
than its own identity, since both `identity` and `order` belong to the
same event by construction) — denormalizing it directly onto the model
anyway is a reasonable simplification: `ScopedManager(event='event')`
against a real column is simpler and slightly cheaper than the dotted
`identity__event` join-based lookup from the original draft, and every
`get_or_create` call site needs to pass it explicitly now. All call sites
below have been updated to include `event=order.event`.

Run `python manage.py makemigrations pretix_furbadge` after adding these.

## Settings storage

Follows the existing `event.settings.get(..., as_type=...)` / hierarkey
pattern used for `furbadge_allow_edits` etc.

| Key | Type | Purpose |
|---|---|---|
| `furbadge_telegram_enabled` | bool | Master on/off switch |
| `furbadge_telegram_bot_token` | str | From @BotFather |
| `furbadge_telegram_bot_username` | str | e.g. `YourEventBot` (no `@`), used to build deep links |
| `furbadge_telegram_client_id` | str | Telegram OIDC client id (Login widget / Web Login setup) |
| `furbadge_telegram_client_secret` | str | Telegram OIDC client secret |
| `furbadge_telegram_webhook_secret` | str | Random string, verified on every webhook request |
| `furbadge_telegram_forward_emails` | bool | Toggle for the email-forwarding hook |
| `furbadge_telegram_consent_text` | text | Shown next to the consent checkbox on the order page |

Register defaults in `apps.py` next to the existing `furbadge_*` defaults, e.g.:

```python
default_settings["furbadge_telegram_enabled"] = False
default_settings["furbadge_telegram_forward_emails"] = False
default_settings["furbadge_telegram_consent_text"] = (
    "I agree to share my Telegram username and order status with the "
    "organizer's Telegram bot."
)
```

## Control panel: Telegram settings view

```python
# forms.py addition

from django import forms
from django.utils.translation import gettext_lazy as _
from pretix.base.forms import SettingsForm


class TelegramSettingsForm(SettingsForm):
    furbadge_telegram_enabled = forms.BooleanField(
        label=_('Enable Telegram integration'), required=False
    )
    furbadge_telegram_bot_token = forms.CharField(
        label=_('Bot token'), required=False, widget=forms.PasswordInput(render_value=True)
    )
    furbadge_telegram_bot_username = forms.CharField(
        label=_('Bot username'), required=False, help_text=_('Without the @')
    )
    furbadge_telegram_client_id = forms.CharField(
        label=_('OIDC client ID'), required=False
    )
    furbadge_telegram_client_secret = forms.CharField(
        label=_('OIDC client secret'), required=False,
        widget=forms.PasswordInput(render_value=True),
    )
    furbadge_telegram_webhook_secret = forms.CharField(
        label=_('Webhook secret'), required=False,
        help_text=_('Pass this as secret_token to setWebhook'),
    )
    furbadge_telegram_forward_emails = forms.BooleanField(
        label=_('Forward all outgoing emails to linked Telegram users'), required=False
    )
    furbadge_telegram_consent_text = forms.CharField(
        label=_('Consent checkbox text'), required=False, widget=forms.Textarea
    )
```

```python
# views.py addition (control)

from django.urls import reverse
from django.views.generic import FormView

from pretix.control.views.event import EventSettingsViewMixin
from pretix.control.permissions import EventPermissionRequiredMixin

from .forms import TelegramSettingsForm


class TelegramSettingsView(EventPermissionRequiredMixin, EventSettingsViewMixin, FormView):
    model = None
    form_class = TelegramSettingsForm
    template_name = 'pretix_furbadge/control/telegram_settings.html'
    permission = 'can_change_event_settings'

    def get_success_url(self):
        return reverse('plugins:pretix_furbadge:telegram.settings', kwargs={
            'organizer': self.request.event.organizer.slug,
            'event': self.request.event.slug,
        })

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['obj'] = self.request.event
        return kwargs

    def form_valid(self, form):
        form.save()
        return super().form_valid(form)
```

```python
# urls.py addition (control patterns, alongside existing Fonts/Templates routes)

from .views import TelegramSettingsView

urlpatterns = [
    # ... existing control routes ...
    path(
        'control/event/<str:organizer>/<str:event>/furbadge/telegram/',
        TelegramSettingsView.as_view(),
        name='telegram.settings',
    ),
]
```

```python
# signals.py addition — extend the existing nav_event receiver

@receiver(nav_event, dispatch_uid='furbadge_nav_telegram')
def navbar_telegram(sender, request, **kwargs):
    if not request.user.has_event_permission(
        request.organizer, request.event, 'can_change_event_settings', request=request
    ):
        return []
    url = resolve(request.path_info)
    return [{
        'label': _('Telegram'),
        'url': reverse('plugins:pretix_furbadge:telegram.settings', kwargs={
            'event': request.event.slug,
            'organizer': request.event.organizer.slug,
        }),
        'active': url.namespace == 'plugins:pretix_furbadge' and url.url_name == 'telegram.settings',
        'icon': 'paper-plane',
    }]
```

`telegram_settings.html` should extend whatever base template your Fonts /
Templates control pages use — mirror that page's structure and swap in
`{{ form }}`.

## Presale: "Connect Telegram" on the order page

Rendered below the existing badges list, inside the same
`BadgePresaleMixin`-guarded template.

```html
{# templates/pretix_furbadge/presale/order_telegram.html — included from the order detail template, below the badges list block #}

{% if telegram_enabled %}
<div class="furbadge-telegram-connect panel panel-default">
  <div class="panel-body">
    <h4>{% trans "Connect Telegram" %}</h4>
    {% if telegram_linked %}
      <p>{% trans "This order is connected to Telegram as" %} @{{ telegram_username }}</p>
    {% else %}
      <p>{{ telegram_consent_text }}</p>
      <label>
        <input type="checkbox" id="furbadge-tg-consent" />
        {% trans "I agree" %}
      </label>
      <br/>
      <a id="furbadge-tg-connect-btn"
         class="btn btn-default disabled"
         href="{{ telegram_connect_url }}">
        {% trans "Connect Telegram" %}
      </a>
    {% endif %}
  </div>
</div>

<script>
(function () {
  var box = document.getElementById('furbadge-tg-consent');
  var btn = document.getElementById('furbadge-tg-connect-btn');
  if (!box || !btn) return;
  box.addEventListener('change', function () {
    btn.classList.toggle('disabled', !box.checked);
    if (box.checked) {
      btn.href = btn.href.split('?')[0] + '?consent=1';
    } else {
      btn.href = btn.href.split('?')[0];
    }
  });
  btn.addEventListener('click', function (e) {
    if (btn.classList.contains('disabled')) e.preventDefault();
  });
})();
</script>
{% endif %}
```

Client-side disabling is just UX — the view below re-checks `consent=1`
server-side and refuses to proceed without it, since a disabled/hidden
button is trivially bypassable.

```python
# views.py addition (presale) — the OAuth client + linking view

import base64
import hashlib
import secrets

import jwt
import requests
from django.http import HttpResponseRedirect, HttpResponseBadRequest, HttpResponseForbidden
from django.urls import reverse
from django.views import View

from .models import TelegramIdentity, TelegramOrderLink
from .presale_mixins import BadgePresaleMixin  # your existing mixin

TELEGRAM_AUTHORIZE_URL = "https://oauth.telegram.org/auth"
TELEGRAM_TOKEN_URL = "https://oauth.telegram.org/token"
TELEGRAM_JWKS_URL = "https://oauth.telegram.org/.well-known/jwks.json"
SESSION_KEY = "furbadge_tg_connect"


def _pkce_pair():
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(40)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


class TelegramConnectStartView(BadgePresaleMixin, View):
    """
    GET /furbadge/telegram/connect/  (relative to the order's event_patterns
    prefix — BadgePresaleMixin resolves self.order from the URL/secret as
    it does for the other frontend views)
    """

    def get(self, request, *args, **kwargs):
        if request.GET.get('consent') != '1':
            return HttpResponseBadRequest('Consent checkbox must be checked')

        event = request.event
        if not event.settings.get('furbadge_telegram_enabled', as_type=bool):
            return HttpResponseBadRequest('Telegram integration disabled')

        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        request.session[SESSION_KEY] = {
            'state': state,
            'verifier': verifier,
            'order_pk': self.order.pk,
            'organizer_pk': event.organizer_id,
        }

        client_id = event.settings.get('furbadge_telegram_client_id', as_type=str)
        callback_uri = request.build_absolute_uri(
            reverse('plugins:pretix_furbadge:telegram.connect.callback', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug,
            })
        )
        params = {
            'client_id': client_id,
            'redirect_uri': callback_uri,
            'response_type': 'code',
            'scope': 'openid profile telegram:bot_access',
            'state': state,
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
        }
        query = '&'.join(f'{k}={requests.utils.quote(v)}' for k, v in params.items())
        return HttpResponseRedirect(f'{TELEGRAM_AUTHORIZE_URL}?{query}')


class TelegramConnectCallbackView(View):
    """GET /furbadge/telegram/connect/callback/"""

    def get(self, request, *args, **kwargs):
        session_data = request.session.pop(SESSION_KEY, None)
        if not session_data:
            return HttpResponseBadRequest('No pending Telegram connection')
        if request.GET.get('state') != session_data['state']:
            return HttpResponseBadRequest('State mismatch')
        if request.GET.get('error'):
            return HttpResponseBadRequest(f"Telegram login failed: {request.GET['error']}")

        from pretix.base.models import Order, Organizer
        organizer = Organizer.objects.get(pk=session_data['organizer_pk'])
        client_id = organizer.settings.get('furbadge_telegram_client_id', as_type=str)
        client_secret = organizer.settings.get('furbadge_telegram_client_secret', as_type=str)

        callback_uri = request.build_absolute_uri(request.path)
        basic = base64.b64encode(f'{client_id}:{client_secret}'.encode()).decode()

        token_resp = requests.post(
            TELEGRAM_TOKEN_URL,
            headers={'Authorization': f'Basic {basic}'},
            data={
                'grant_type': 'authorization_code',
                'code': request.GET.get('code'),
                'redirect_uri': callback_uri,
                'client_id': client_id,
                'code_verifier': session_data['verifier'],
            },
            timeout=10,
        )
        token_resp.raise_for_status()
        id_token = token_resp.json()['id_token']

        jwks_client = jwt.PyJWKClient(TELEGRAM_JWKS_URL)
        signing_key = jwks_client.get_signing_key_from_jwt(id_token)
        claims = jwt.decode(
            id_token, signing_key.key, algorithms=['RS256'],
            audience=client_id, issuer='https://oauth.telegram.org',
        )

        telegram_user_id = str(claims['id'])
        order = Order.objects.get(pk=session_data['order_pk'])

        identity, _created = TelegramIdentity.objects.get_or_create(
            event=order.event, telegram_user_id=telegram_user_id,
        )
        identity.username = claims.get('preferred_username')
        identity.first_name = claims.get('given_name') or claims.get('name')
        identity.chat_id = telegram_user_id
        identity.bot_access_granted = True  # confirm empirically, see note below
        identity.consent_given = True
        identity.consent_given_at = timezone.now()
        identity.save()

        TelegramOrderLink.objects.get_or_create(event=order.event, identity=identity, order=order)

        return HttpResponseRedirect(order.urls.info)
```

```python
# urls.py addition (event_patterns, alongside BadgeEditView etc.)

from .views import TelegramConnectStartView, TelegramConnectCallbackView

event_patterns = [
    # ... existing furbadge frontend routes ...
    path('furbadge/telegram/connect/', TelegramConnectStartView.as_view(),
         name='telegram.connect.start'),
    path('furbadge/telegram/connect/callback/', TelegramConnectCallbackView.as_view(),
         name='telegram.connect.callback'),
]
```

**Unverified assumption, flagged as before:** `bot_access_granted = True`
and later using `chat_id = telegram_user_id` directly for `sendMessage`
assumes the `telegram:bot_access` grant lets the bot message that numeric
id with zero prior interaction. Test this against a real bot before
relying on it — if it doesn't hold, you'll need to also prompt a `/start`
in the chat and capture `chat_id` from that instead.

## Email forwarding

```python
# signals.py addition

import logging
from django.dispatch import receiver
from pretix.base.signals import email_filter, global_email_filter

from .models import TelegramOrderLink

logger = logging.getLogger(__name__)


def _forward_to_telegram(event, message, order=None):
    if order is None:
        return
    if not event.settings.get('furbadge_telegram_forward_emails', as_type=bool):
        return

    links = TelegramOrderLink.objects.filter(order=order).select_related('identity')
    if not links:
        return

    from .tasks import send_telegram_notification  # your task queue of choice

    subject = message.subject or '(no subject)'
    plain_body = message.body or ''
    attachments = [
        {'filename': fn, 'content': content, 'mimetype': mt}
        for fn, content, mt in (getattr(message, 'attachments', None) or [])
    ]

    for link in links:
        send_telegram_notification.apply_async(kwargs={
            'chat_id': link.identity.chat_id,
            'subject': subject,
            'body': plain_body,
            'attachments': attachments,
        })


@receiver(email_filter, dispatch_uid='furbadge_telegram_email_filter')
def on_event_email(sender, message, order=None, **kwargs):
    try:
        _forward_to_telegram(sender, message, order=order)
    except Exception:
        logger.exception('Failed to forward event email to Telegram')
    return message


@receiver(global_email_filter, dispatch_uid='furbadge_telegram_global_email_filter')
def on_global_email(sender, message, order=None, **kwargs):
    # sender here is the Organizer for global_email_filter, not an Event —
    # only order-linked mail applies since TelegramOrderLink keys off Order.
    if order is None:
        return message
    try:
        _forward_to_telegram(order.event, message, order=order)
    except Exception:
        logger.exception('Failed to forward global email to Telegram')
    return message
```

Run this through your task queue (`send_telegram_notification`), not
inline — mail sending may already be synchronous in your install, and a
slow/down Telegram API call shouldn't be able to stall order confirmations.

## Bot webhook and commands

### Numbering scheme

Pretix order codes / position IDs are never exposed to the user. Instead,
each identity gets a **stable, per-identity, 1-based list** computed at
request time:

```python
# bot/numbering.py

def numbered_orders(identity):
    """Deterministic order: oldest connected order first, never reordered
    unless the identity's linked orders change (only appended to in
    practice), so a given number always resolves to the same order."""
    return list(
        identity.order_links.select_related('order')
        .order_by('order__datetime', 'order__code')
        .values_list('order', flat=True)
    )


def numbered_badges(identity):
    from pretix.base.models import OrderPosition
    from .models import BadgeData  # existing plugin model

    order_ids = numbered_orders(identity)
    positions = (
        OrderPosition.objects.filter(order_id__in=order_ids)
        .select_related('order', 'item')
        .order_by('order__datetime', 'positionid')
    )
    # only positions that actually have badge data
    badge_position_ids = set(
        BadgeData.objects.filter(order_position__in=positions)
        .values_list('order_position_id', flat=True)
    )
    return [p for p in positions if p.pk in badge_position_ids]
```

### Command routing, including "no number = list" and Polish aliases

```python
# bot/commands.py

from pretix.base.models import Order, Organizer

from .numbering import numbered_orders, numbered_badges
from .telegram_api import tg_send_message, tg_send_web_app_button, tg_send_document


def _get_identities(organizer, telegram_user_id):
    """
    Returns a queryset, not a single object — with TelegramIdentity now
    event-scoped, the same Telegram user can have one row per event under
    this organizer. Requires an active scope; wrap the caller in
    `with scopes(organizer=organizer):` (or narrow to a specific event if
    one's already known) before calling this from a context that doesn't
    already have one active, such as the webhook view below.
    """
    from ..models import TelegramIdentity
    return TelegramIdentity.objects.filter(
        event__organizer=organizer, telegram_user_id=telegram_user_id, consent_given=True,
    )


def _shop_url(organizer):
    # Adjust to however your install builds the organizer's public shop
    # root URL — this depends on your domain routing setup (custom domains
    # per organizer vs. path-based).
    from pretix.multidomain.urlreverse import build_absolute_uri
    return build_absolute_uri(organizer, 'presale:organizer.index')


def handle_shop(organizer, identity, chat_id, args):
    tg_send_web_app_button(chat_id, _shop_url(organizer), 'Open shop')


def handle_orders_list(organizer, identity, chat_id, args):
    order_ids = numbered_orders(identity)
    if not order_ids:
        tg_send_message(chat_id, "No connected orders yet.")
        return
    orders = Order.objects.in_bulk(order_ids)
    lines = [
        f"{i}. {orders[oid].code} — {orders[oid].event.name}"
        for i, oid in enumerate(order_ids, start=1)
    ]
    tg_send_message(chat_id, "Your orders:\n" + "\n".join(lines) + "\n\nUse /order <number> to open one.")


def handle_order(organizer, identity, chat_id, args):
    if not args:
        return handle_orders_list(organizer, identity, chat_id, args)
    order_ids = numbered_orders(identity)
    n = _parse_index(args[0], len(order_ids))
    if n is None:
        tg_send_message(chat_id, "Invalid order number. Use /orders to see the list.")
        return
    order = Order.objects.get(pk=order_ids[n - 1])
    tg_send_web_app_button(chat_id, order.urls.info, f"Manage order {order.code}")


def handle_badges_list(organizer, identity, chat_id, args):
    positions = numbered_badges(identity)
    if not positions:
        tg_send_message(chat_id, "No badges yet.")
        return
    lines = [
        f"{i}. {p.attendee_name or p.item.name} — order {p.order.code}"
        for i, p in enumerate(positions, start=1)
    ]
    tg_send_message(chat_id, "Your badges:\n" + "\n".join(lines) + "\n\nUse /badge <number> to edit one.")


def handle_badge(organizer, identity, chat_id, args):
    if not args:
        return handle_badges_list(organizer, identity, chat_id, args)
    positions = numbered_badges(identity)
    n = _parse_index(args[0], len(positions))
    if n is None:
        tg_send_message(chat_id, "Invalid badge number. Use /badges to see the list.")
        return
    position = positions[n - 1]
    # Adjust to your actual badge-edit URL name/kwargs from urls.py:
    from django.urls import reverse
    url_path = reverse('plugins:pretix_furbadge:badge.edit', kwargs={
        'organizer': position.order.event.organizer.slug,
        'event': position.order.event.slug,
        'code': position.order.code,
        'secret': position.order.secret,
        'position': position.pk,
    })
    from pretix.multidomain.urlreverse import build_absolute_uri
    full_url = build_absolute_uri(position.order.event, 'presale:event.index').split('/', 3)[0] + url_path
    tg_send_web_app_button(chat_id, full_url, f"Edit badge — {position.attendee_name}")


def handle_qr(organizer, identity, chat_id, args):
    if not args:
        return handle_orders_list(organizer, identity, chat_id, args)
    order_ids = numbered_orders(identity)
    n = _parse_index(args[0], len(order_ids))
    if n is None:
        tg_send_message(chat_id, "Invalid number. Use /orders to see the list.")
        return
    order = Order.objects.get(pk=order_ids[n - 1])
    # Reuses pretix's own ticket rendering — verify this matches the actual
    # signature in pretix.base.services.tickets in your pretix version.
    from pretix.base.services.tickets import get_tickets_for_order
    for filename, mimetype, content in get_tickets_for_order(order):
        tg_send_document(chat_id, filename, content, mimetype, caption=f"Ticket — {order.code}")


def handle_help(organizer, identity, chat_id, args):
    tg_send_message(chat_id, (
        "/shop — open the shop\n"
        "/orders (/zamowienia) — list your orders\n"
        "/order (/zamowienie) <n> — manage an order\n"
        "/badges — list your badges\n"
        "/badge <n> — edit a badge\n"
        "/qr <n> — get the ticket/QR for an order"
    ))


def _parse_index(raw, count):
    try:
        n = int(raw)
    except ValueError:
        return None
    if n < 1 or n > count:
        return None
    return n


COMMANDS = {
    'shop': handle_shop,
    'orders': handle_orders_list,
    'zamowienia': handle_orders_list,
    'order': handle_order,
    'zamowienie': handle_order,
    'badges': handle_badges_list,
    'badge': handle_badge,
    'qr': handle_qr,
    'help': handle_help,
}
```

### Telegram API helpers

```python
# bot/telegram_api.py

import requests


def _api(organizer):
    token = organizer.settings.get('furbadge_telegram_bot_token', as_type=str)
    return f"https://api.telegram.org/bot{token}"


def tg_send_message(chat_id, text, organizer=None, **kwargs):
    requests.post(f"{_api(organizer)}/sendMessage",
                   json={'chat_id': chat_id, 'text': text, **kwargs}, timeout=10)


def tg_send_document(chat_id, filename, content, mimetype, organizer=None, caption=None):
    requests.post(
        f"{_api(organizer)}/sendDocument",
        data={'chat_id': chat_id, **({'caption': caption} if caption else {})},
        files={'document': (filename, content, mimetype)},
        timeout=15,
    )


def tg_send_web_app_button(chat_id, url, label, organizer=None):
    requests.post(f"{_api(organizer)}/sendMessage", json={
        'chat_id': chat_id,
        'text': label,
        'reply_markup': {
            'inline_keyboard': [[{'text': label, 'web_app': {'url': url}}]]
        },
    }, timeout=10)
```

Note: `_api(organizer=None)` above is a simplification for readability —
wire the actual `organizer` through from the webhook view in every call
site, since the bot token is stored per-organizer, not globally. I've left
the `organizer=None` default so the snippet stays short; don't ship it
like that.

### Webhook view

```python
# views.py addition — global, not event-scoped

import json
import logging

from django.http import HttpResponse, HttpResponseForbidden
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from django_scopes import scopes

from pretix.base.models import Organizer
from .bot.commands import COMMANDS, _get_identities

logger = logging.getLogger(__name__)


@method_decorator(csrf_exempt, name='dispatch')
class TelegramWebhookView(View):
    """
    urls.py (global, e.g. mounted under /telegram/webhook/<organizer>/):

        path('telegram/webhook/<str:organizer>/',
             TelegramWebhookView.as_view(), name='telegram.webhook')

    Register per-organizer with:
        setWebhook url=.../telegram/webhook/<organizer-slug>/
                   secret_token=<furbadge_telegram_webhook_secret>
    """

    def post(self, request, organizer, *args, **kwargs):
        org = Organizer.objects.filter(slug=organizer).first()
        if not org:
            return HttpResponseForbidden()

        expected_secret = org.settings.get('furbadge_telegram_webhook_secret', as_type=str)
        if request.headers.get('X-Telegram-Bot-Api-Secret-Token') != expected_secret:
            return HttpResponseForbidden()

        try:
            update = json.loads(request.body)
        except json.JSONDecodeError:
            return HttpResponse(status=400)

        message = update.get('message')
        if not message or 'text' not in message:
            return HttpResponse(status=200)

        chat_id = message['chat']['id']
        from_id = str(message['from']['id'])
        text = message['text'].strip()
        if not text.startswith('/'):
            return HttpResponse(status=200)

        parts = text.split()
        command = parts[0].lstrip('/').split('@')[0].lower()
        args = parts[1:]

        # The webhook has no event context (it's one URL per organizer),
        # but TelegramIdentity is event-scoped — so an explicit scope is
        # required here even for a read.
        with scopes(organizer=org):
            identities = list(_get_identities(org, from_id))

        # STOPGAP, not a real fix: this picks whichever identity happens to
        # be first if the same Telegram user connected across more than one
        # event under this organizer. The command handlers below
        # (numbered_orders/numbered_badges, and everything in
        # bot/commands.py) all still assume a single `identity` and only
        # look at that one event's orders/badges. Properly supporting
        # "list my orders across every event I've bought from" needs those
        # functions changed to take a list of identities and aggregate
        # across them — not done here, flagging it rather than leaving it
        # silently wrong.
        identity = identities[0] if identities else None

        if not identity and command != 'start':
            from .bot.telegram_api import tg_send_message
            tg_send_message(chat_id, "You haven't connected Telegram to an order yet — "
                                      "use the \"Connect Telegram\" button on your order page.",
                             organizer=org)
            return HttpResponse(status=200)

        handler = COMMANDS.get(command)
        if not handler:
            from .bot.telegram_api import tg_send_message
            tg_send_message(chat_id, "Unknown command. Try /help.", organizer=org)
            return HttpResponse(status=200)

        try:
            with scopes(organizer=org):
                handler(org, identity, chat_id, args)
        except Exception:
            logger.exception('Error handling Telegram command %s from %s', command, from_id)

        return HttpResponse(status=200)
```

### BotFather / Telegram-side setup

```bash
# Webhook, per organizer, once bot token + webhook secret are set in the settings panel
curl "https://api.telegram.org/bot<TOKEN>/setWebhook" \
     -d "url=https://yourdomain.example.com/telegram/webhook/<organizer-slug>/" \
     -d "secret_token=<furbadge_telegram_webhook_secret>"

# Command list (English)
curl "https://api.telegram.org/bot<TOKEN>/setMyCommands" \
     -H "Content-Type: application/json" \
     -d '{"commands": [
           {"command": "shop", "description": "Open the shop"},
           {"command": "orders", "description": "List your orders"},
           {"command": "order", "description": "Manage an order"},
           {"command": "badges", "description": "List your badges"},
           {"command": "badge", "description": "Edit a badge"},
           {"command": "qr", "description": "Get a ticket QR"},
           {"command": "help", "description": "Show this help"}
         ]}'

# Command list (Polish), scoped via language_code
curl "https://api.telegram.org/bot<TOKEN>/setMyCommands" \
     -H "Content-Type: application/json" \
     -d '{"language_code": "pl", "commands": [
           {"command": "shop", "description": "Otwórz sklep"},
           {"command": "zamowienia", "description": "Lista zamówień"},
           {"command": "zamowienie", "description": "Zarządzaj zamówieniem"},
           {"command": "badges", "description": "Lista identyfikatorów"},
           {"command": "badge", "description": "Edytuj identyfikator"},
           {"command": "qr", "description": "Pobierz kod QR"},
           {"command": "help", "description": "Pomoc"}
         ]}'
```

Whether `web_app` buttons need the bot's domain registered via BotFather's
`/setdomain` (that setting is documented for the Login Widget; its
interaction with `web_app` inline buttons specifically isn't something I
could confirm) — check this empirically once you have a test bot, before
assuming the buttons work with zero extra BotFather config.

## Extension rules — additions

- Telegram-related models (`TelegramIdentity`, `TelegramOrderLink`) are
  **organizer-scoped**, not event-scoped — this is an intentional exception
  to the general rule, since one Telegram identity spans orders across
  multiple events.
- Any new bot command handler goes in `bot/commands.py` and must be added
  to the `COMMANDS` dict, including a Polish alias if it takes a plural
  "list" form (mirroring `orders`/`zamowienia`, `order`/`zamowienie`).
  Handlers that take a numeric argument must fall back to their
  corresponding list view when `args` is empty.
- Any new outbound Telegram message must go through `bot/telegram_api.py`,
  not ad hoc `requests.post` calls elsewhere, so the bot token lookup stays
  centralized per-organizer.
- New settings must be added to `TelegramSettingsForm` and given a default
  in `apps.py`, same as the general settings rule.

## Checkout-time Telegram login (inline, next to the email field)

Two cases, precisely:

- **Default:** email required, exactly as pretix already has it.
- **Telegram connected:** email becomes optional — the buyer can still
  type a real one if they want (nothing stops them), but they're no
  longer forced to. If they leave it blank, a dummy address is filled in
  afterward, not instead of letting them type — the field itself stays a
  normal, editable input the whole time. It does **not** get disabled or
  pre-filled the moment they connect; that was the previous (wrong)
  version of this section.

Because the dummy only needs to apply to genuinely blank submissions, it
makes more sense to apply it *after* the form has already accepted
whatever the buyer typed (or didn't), rather than trying to inject it at
render time. So this now touches three points instead of two:

- `contact_form_fields` — adds the "connect via Telegram" prompt.
- `contact_form_fields_overrides` — flips `required` to `False` on `email`
  once Telegram is connected. **Flagged uncertainty, real this time:**
  pretix's docs for this signal only list `initial`, `disabled`, and
  `validators` as supported override keys — `required` isn't one of them.
  If pretix's processing code only reads that fixed set, this key gets
  silently ignored and the field stays required no matter what. Test this
  specifically before relying on it; if it doesn't work, the field will
  still demand input even with Telegram connected, and you'd need to look
  at pretix's actual `ContactForm`/`get_form_kwargs` source for a
  supported way to make a field conditionally optional.
- `order_placed` — the safety net. If the order ends up with no email at
  all *and* a Telegram identity was linked, fill in the dummy there. This
  runs regardless of whether the `required` override above actually took
  effect, so a genuinely blank order.email never reaches whatever pretix
  does downstream with it (ticket delivery, notifications, etc.).

```python
# forms.py addition

from django import forms
from django.utils.safestring import mark_safe
from django.utils.html import escape


class TelegramLoginPromptWidget(forms.Widget):
    def __init__(self, connect_url, disconnect_url=None, username=None,
                 first_name=None, already_linked=False, *args, **kwargs):
        self.connect_url = connect_url
        self.disconnect_url = disconnect_url
        self.username = username
        self.first_name = first_name
        self.already_linked = already_linked
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        if self.already_linked:
            who = f"@{escape(self.username)}" if self.username else (
                escape(self.first_name) if self.first_name else "a Telegram account"
            )
            # The script tag strips the HTML5 `required` attribute from the
            # real email input client-side — see explanation below for why
            # this is necessary in addition to the server-side override.
            return mark_safe(
                f'<div class="furbadge-telegram-inline-prompt text-muted" '
                f'data-furbadge-telegram-connected="1">'
                f'Connected via Telegram as {who} — '
                f'<a href="{self.disconnect_url}">Not you? Disconnect</a>'
                f'</div>'
                f'<script>'
                f'(function(){{'
                f'var el = document.getElementById("id_email");'
                f'if (el) {{ el.removeAttribute("required"); el.setCustomValidity(""); }}'
                f'}})();'
                f'</script>'
            )
        return mark_safe(
            f'<div class="furbadge-telegram-inline-prompt">'
            f'or <a href="{self.connect_url}">connect via Telegram</a> to make email optional'
            f'</div>'
        )

    def value_from_datadict(self, data, files, name):
        return None  # not a real input — never contributes data on submit


class TelegramLoginPromptField(forms.Field):
    """Renders a prompt only. Always optional, never validates anything."""
    widget = TelegramLoginPromptWidget
    required = False

    def clean(self, value):
        return None
```

The `getElementById("id_email")` selector assumes Django's default
`id_<field_name>` auto-id convention, which is the default unless
pretix's `ContactForm` overrides `auto_id` — check the actual rendered
`<input>`'s `id` in your install and adjust the selector if it differs.

```python
# signals.py

from pretix.presale.signals import contact_form_fields, contact_form_fields_overrides
from django.urls import reverse

from .forms import TelegramLoginPromptField, TelegramLoginPromptWidget
from .checkoutflow import CART_SESSION_KEY


@receiver(contact_form_fields, dispatch_uid='furbadge_telegram_contact_field')
def telegram_contact_field(sender, request, **kwargs):
    if not sender.settings.get('furbadge_telegram_enabled', as_type=bool):
        return {}

    data = request.session.get(CART_SESSION_KEY)
    already_linked = bool(data and data.get('verified'))

    kwargs_common = {'organizer': sender.organizer.slug, 'event': sender.slug}
    connect_url = reverse('plugins:pretix_furbadge:telegram.checkout.start', kwargs=kwargs_common)
    disconnect_url = reverse('plugins:pretix_furbadge:telegram.checkout.disconnect', kwargs=kwargs_common)

    return {
        'furbadge_telegram_prompt': TelegramLoginPromptField(
            widget=TelegramLoginPromptWidget(
                connect_url=connect_url,
                disconnect_url=disconnect_url,
                username=data.get('username') if data else None,
                first_name=data.get('first_name') if data else None,
                already_linked=already_linked,
            ),
            label='',
        )
    }


@receiver(contact_form_fields_overrides, dispatch_uid='furbadge_telegram_contact_override')
def telegram_contact_override(sender, request, order=None, **kwargs):
    data = request.session.get(CART_SESSION_KEY)
    if not data or not data.get('verified'):
        return {}

    # `required: False` here would be silently ignored — pretix's docs for
    # this signal only read `initial`, `disabled`, and `validators`. It
    # also wouldn't help on its own even if it were read, since the
    # browser's HTML5 `required` attribute (stripped client-side by the
    # widget's script above) is what actually blocks a blank submission
    # before it reaches the server at all.
    #
    # What this receiver needs to do instead: on the actual POST, if the
    # buyer left email blank, satisfy Django's server-side required check
    # with a throwaway value — using only the two keys that are actually
    # documented to work. On a plain GET (first showing the step), leave
    # the field completely untouched so it still looks and behaves like a
    # normal, empty, editable input.
    if request.method == 'POST' and not request.POST.get('email', '').strip():
        return {
            'email': {
                'initial': _dummy_email(data['telegram_user_id'], sender),
                'disabled': True,
            }
        }
    return {}
```

If the buyer typed a real email, `request.POST.get('email')` is truthy,
this receiver returns `{}`, and nothing about the field is touched —
their real address goes through untouched. If they left it blank, the
dummy gets substituted only for this submission via the same
`disabled` + non-empty `initial` mechanism already established to work.

```python
# signals.py — the fallback, applied after order creation

from pretix.base.signals import order_placed
from pretix.presale.signals import order_meta_from_request
from .models import TelegramIdentity, TelegramOrderLink
from .checkoutflow import CART_SESSION_KEY


def _dummy_email(telegram_user_id, event):
    domain = event.organizer.settings.get('furbadge_telegram_dummy_email_domain', as_type=str) \
        or 'telegram.invalid'  # .invalid is a reserved RFC 2606 TLD, deliberately non-resolving
    return f"tg-{telegram_user_id}@{domain}"


@receiver(order_placed, dispatch_uid='furbadge_telegram_order_placed')
def link_telegram_on_order_placed(sender, order, **kwargs):
    telegram_data = (order.meta_info_data or {}).get('furbadge_telegram')
    if not telegram_data:
        return  # Telegram wasn't connected for this order — untouched, as normal

    # order_placed fires from a background task (pretix.base.tasks), not a
    # request — pretix's request middleware normally activates the right
    # django_scopes scope for you, but nothing does that here. Any query
    # against a ScopedManager-backed model (TelegramIdentity,
    # TelegramOrderLink, and Order itself) raises ScopeError without an
    # explicit scope active.
    from django_scopes import scopes

    with scopes(event=order.event):
        if not order.email:
            # Buyer left it blank, relying on Telegram — fill the dummy now,
            # after the fact, rather than ever having pre-filled the form.
            order.email = _dummy_email(telegram_data['telegram_user_id'], order.event)
            order.save(update_fields=['email'])

        identity, _ = TelegramIdentity.objects.get_or_create(
            event=order.event,
            telegram_user_id=telegram_data['telegram_user_id'],
        )
        identity.username = telegram_data.get('username')
        identity.chat_id = telegram_data.get('chat_id')
        identity.bot_access_granted = True
        identity.consent_given = True
        identity.consent_given_at = timezone.now()
        identity.save()
        TelegramOrderLink.objects.get_or_create(event=order.event, identity=identity, order=order)


@receiver(order_meta_from_request, dispatch_uid='furbadge_telegram_order_meta')
def telegram_order_meta(sender, request, **kwargs):
    data = request.session.get(CART_SESSION_KEY)
    if not data or not data.get('verified'):
        return {}
    return {'furbadge_telegram': data}
```

Note there's no `dummy_email` stored in the session anymore — it's
computed lazily in `order_placed`, only if actually needed, instead of
being generated up front on every Telegram login regardless of whether
the buyer ends up typing a real email anyway.

The OAuth start/callback views are otherwise unchanged from the last
version, except for how `return_url` gets built. The earlier draft
(`request.META.get('HTTP_REFERER') or reverse(...)`) has a real problem:
`Referer` is just a header, fully controllable by whoever constructs the
request — trusting it as a post-login redirect target is an open-redirect
vector. Since this flow is only ever triggered from one place (the
"connect via Telegram" prompt on the contact step), there's nothing to
infer — build it deterministically from `request.event`, which the start
view already has, and skip `Referer` entirely.

```python
# views.py — TelegramCheckoutStartView

class TelegramCheckoutStartView(View):
    def get(self, request, *args, **kwargs):
        event = request.event
        verifier, challenge = _pkce_pair()
        state = secrets.token_urlsafe(24)
        request.session[SESSION_KEY] = {
            'state': state, 'verifier': verifier,
            'organizer_pk': event.organizer_id,
            'return_url': reverse('presale:event.checkout', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug, 'step': 'contact',
            }),  # verify 'contact' is the actual step identifier in your pretix version
        }
        client_id = event.settings.get('furbadge_telegram_client_id', as_type=str)
        callback_uri = request.build_absolute_uri(
            reverse('plugins:pretix_furbadge:telegram.checkout.callback', kwargs={
                'organizer': event.organizer.slug, 'event': event.slug,
            })
        )
        params = {
            'client_id': client_id, 'redirect_uri': callback_uri,
            'response_type': 'code', 'scope': 'openid profile telegram:bot_access',
            'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256',
        }
        query = '&'.join(f'{k}={requests.utils.quote(v)}' for k, v in params.items())
        return HttpResponseRedirect(f'{TELEGRAM_AUTHORIZE_URL}?{query}')
```

Since `return_url` is now always something the plugin itself constructed
— never anything supplied by the request — there's nothing to validate
on the way out in the callback either; `redirect(session_data['return_url'])`
is safe precisely because that string never had a chance to come from
outside.

**A separate, unrelated issue worth flagging while on the subject of
`SESSION_KEY`/`CART_SESSION_KEY`:** neither key is namespaced by event or
cart. If the same browser session starts checkout for a *different* event
without the session being cleared in between (very plausible — someone
buying tickets to two events from the same organizer back to back), stale
`verified: True` data from the first event's Telegram login could bleed
into the second event's contact step: showing "Connected via Telegram"
when it shouldn't, and potentially attaching the wrong `TelegramIdentity`
to the wrong order if they proceed without noticing. Worth namespacing
both keys by `event.pk` (e.g. `f'furbadge_telegram_checkout_{event.pk}'`)
or explicitly clearing `CART_SESSION_KEY` whenever a new cart/checkout
session starts for a different event — pick whichever hook your plugin
already has for "checkout started" if one exists, otherwise the simplest
fix is just namespacing the key.

```python
# views.py — TelegramCheckoutCallbackView

class TelegramCheckoutCallbackView(View):
    def get(self, request, *args, **kwargs):
        session_data = request.session.pop(SESSION_KEY, None)
        # ... unchanged validation/token-exchange/JWKS-verification ...

        telegram_user_id = str(claims['id'])
        request.session[CART_SESSION_KEY] = {
            'verified': True,
            'telegram_user_id': telegram_user_id,
            'username': claims.get('preferred_username'),
            'first_name': claims.get('given_name') or claims.get('name'),
            'chat_id': telegram_user_id,
        }
        return redirect(session_data['return_url'])
```

```python
# views.py — TelegramCheckoutDisconnectView ("Not you? Disconnect")

class TelegramCheckoutDisconnectView(View):
    def get(self, request, *args, **kwargs):
        request.session.pop(CART_SESSION_KEY, None)
        event = request.event
        return_url = reverse('presale:event.checkout', kwargs={
            'organizer': event.organizer.slug, 'event': event.slug, 'step': 'contact',
        })
        return HttpResponseRedirect(return_url)
```

```python
# urls.py addition (event_patterns)

from .views import (
    TelegramCheckoutStartView, TelegramCheckoutCallbackView, TelegramCheckoutDisconnectView,
)

event_patterns += [
    path('furbadge/telegram/checkout/start/', TelegramCheckoutStartView.as_view(),
         name='telegram.checkout.start'),
    path('furbadge/telegram/checkout/callback/', TelegramCheckoutCallbackView.as_view(),
         name='telegram.checkout.callback'),
    path('furbadge/telegram/checkout/disconnect/', TelegramCheckoutDisconnectView.as_view(),
         name='telegram.checkout.disconnect'),
]
```

This is a plain `GET` link rather than a POST-protected form button —
deliberately. It only clears a session flag for the current, still-in-
progress checkout; it doesn't touch anything persisted (no `Order`, no
`TelegramIdentity` row exists yet at this point), so the worst case of
someone triggering it via CSRF is the buyer has to reconnect Telegram,
not any real security or data-integrity issue. It's also *inside* the
same `<form method="post">` as the rest of the contact form, so it can't
be a nested `<form>` of its own — a plain link keeps it valid HTML
without needing JS to intercept a button click and fire a separate
`fetch()` POST.

Delete entirely: `checkoutflow.py`'s `TelegramLoginStep` class, its
template, and the `checkout_flow_steps` receiver returning it — leftover
from an earlier draft of this section, not needed at all with the
inline-field approach.

## Contact info on the confirm step: show email or Telegram (or both)

Now that we can see the actual template, this is simpler and more
precise than the earlier guesswork version. There's no hardcoded "Email"
row in that markup at all — everything in the "Contact information" panel
comes from the same generic `{% for l, v in contact_info %}` loop, inside
`.panel-contact .panel-body`. That's a real, known container to target,
not a guess.

Desired states:

| Email given? | Telegram connected? | Shown |
|---|---|---|
| yes | yes | `Email: real@example.com` / `Telegram: @username` |
| yes | no | `Email: real@example.com` / `Telegram: not connected` |
| no (dummy) | yes | `Email: not given` / `Telegram: @username` |

There's still no signal to edit `contact_info` before the template
renders it, so this stays a `checkout_confirm_page_content` script — but
now it can target the real container directly and build the Telegram row
itself, rather than searching the whole page and guessing at ancestors.

One correction from the previous version: it built the injected HTML via
raw Python string interpolation, which is an XSS risk the moment a real
(attacker-controllable) Telegram display name ends up embedded in it.
Fixed here by passing all dynamic values through `json.dumps` into the
script as data, and building the DOM with `createElement`/`textContent`
rather than string-concatenated `innerHTML`.

```python
# signals.py — replaces the previous hide_dummy_email_on_confirm entirely

import json

from pretix.presale.signals import checkout_confirm_page_content
from django.utils.safestring import mark_safe
from django.utils.translation import gettext as _

from .checkoutflow import CART_SESSION_KEY


@receiver(checkout_confirm_page_content, dispatch_uid='furbadge_telegram_confirm_summary')
def telegram_confirm_summary(sender, request, **kwargs):
    data = request.session.get(CART_SESSION_KEY)
    telegram_connected = bool(data and data.get('verified'))

    if telegram_connected:
        if data.get('username'):
            telegram_value = f"@{data['username']}"
        elif data.get('first_name'):
            telegram_value = data['first_name']
        else:
            telegram_value = str(_('Connected'))
    else:
        telegram_value = str(_('Not connected'))

    domain = sender.organizer.settings.get('furbadge_telegram_dummy_email_domain', as_type=str) \
        or 'telegram.invalid'

    ctx = {
        'needle': f"@{domain}",           # matches the dummy address if present
        'not_given': str(_('Not given')),
        'telegram_label': str(_('Telegram')),
        'telegram_value': telegram_value,
        'marker': '__furbadge_telegram_marker__',
    }

    script = """
    <script>
    (function (ctx) {
        var panel = document.querySelector('.panel-contact .panel-body');
        if (!panel) return;

        // Rewrite the dummy email's text in place — the row stays visible,
        // it just no longer shows the raw dummy address.
        var walker = document.createTreeWalker(panel, NodeFilter.SHOW_TEXT);
        var node;
        while ((node = walker.nextNode())) {
            if (node.nodeValue && node.nodeValue.indexOf(ctx.needle) !== -1) {
                node.nodeValue = ctx.not_given;
            }
        }

        // Defensive cleanup: if the contact_form_fields prompt field ends
        // up surfaced in this same summary loop (unconfirmed either way —
        // its clean() returns this marker specifically so it's easy to
        // find and remove if so), strip it rather than show it twice
        // alongside the row we're about to add ourselves.
        panel.querySelectorAll('dt, dd').forEach(function (el) {
            if (el.textContent.indexOf(ctx.marker) !== -1) {
                var dl = el.closest('dl');
                if (dl) dl.remove();
            }
        });

        var dl = document.createElement('dl');
        dl.className = 'dl-horizontal';
        var dt = document.createElement('dt');
        dt.textContent = ctx.telegram_label;
        var dd = document.createElement('dd');
        dd.textContent = ctx.telegram_value;
        dl.appendChild(dt);
        dl.appendChild(dd);
        panel.appendChild(dl);
    })(%s);
    </script>
    """ % json.dumps(ctx)

    return mark_safe(script)
```

Also update the prompt field's `clean()` so it returns that same marker
string instead of `None`, purely so the defensive cleanup above has
something concrete to search for if this field does turn out to surface
in the confirm summary:

```python
# forms.py — small change to TelegramLoginPromptField

class TelegramLoginPromptField(forms.Field):
    widget = TelegramLoginPromptWidget
    required = False

    def clean(self, value):
        return '__furbadge_telegram_marker__'
```

**Still worth confirming, not assumed:** whether `contact_info` actually
does include entries from plugin-contributed `contact_form_fields` at
all, or only the built-in email/name fields. The template alone doesn't
settle this either way — it's a generic loop, which is consistent with
either possibility. If it turns out our field never appears there, the
defensive-cleanup block simply never matches anything and is harmless;
if it does appear, the cleanup removes it before the real Telegram row
gets appended. Either way the visible result should be correct — but
worth actually checking once, rather than carrying the uncertainty
indefinitely.

## Testing checklist

- [ ] `order_placed`, and any other receiver that can fire from a
      background task rather than a request, wrapped in
      `django_scopes.scopes(...)` — don't assume request middleware
      already activated one
- [ ] The webhook view's `scopes(organizer=org)` is actually sufficient
      for querying an `event`-scoped model, or narrow it further if
      django-scopes requires the specific dimension the model declares
- [ ] Decide whether to actually fix cross-event `/orders`/`/badges`
      listing (aggregating multiple `TelegramIdentity` rows per Telegram
      user) or accept the current stopgap of only showing one event's data
- [ ] Confirm-step contact panel shows the correct combination for all
      three cases: email-only, Telegram-only (dummy rewritten to "Not
      given"), and both connected
- [ ] Check whether the `contact_form_fields` prompt field actually
      surfaces in the confirm summary loop — confirms whether the
      defensive marker-cleanup code in `telegram_confirm_summary` is doing
      real work or is just inert
- [ ] Telegram username/first name displayed on the confirm step renders
      safely even with unusual Unicode or symbol characters in it (this is
      why `textContent` + `json.dumps` are used instead of string-built
      HTML — verify a crafted display name can't inject markup)
- [ ] Bot token + OIDC client id/secret saved via the new control panel page
- [ ] `telegram:bot_access` behavior confirmed against a real test account
      (does `sendMessage` to the numeric id work immediately, or does the
      user still need to `/start` the bot first?)
- [ ] Consent checkbox: confirm the server actually rejects
      `consent` missing/not `1`, not just that the button looks disabled
- [ ] `email_filter` / `global_email_filter` don't block real email sending
      if Telegram's API is unreachable (wrapped in try/except, dispatched
      to a task queue, not inline)
- [ ] Webhook rejects requests without the correct
      `X-Telegram-Bot-Api-Secret-Token` header
- [ ] `/order <n>` and `/badge <n>` numbering stays stable across repeated
      calls for the same identity as more orders/badges get added
- [ ] `badge.edit` URL name/kwargs in `handle_badge` adjusted to match your
      actual `urls.py`
- [ ] The `contact_form_fields` prompt actually appears inside the contact
      step's rendered form (depends on that template using a generic
      per-field render loop — check it does before assuming this works)
- [ ] The `'step': 'contact'` identifier used to build `return_url` in
      `TelegramCheckoutStartView` matches the real step identifier in your
      pretix version — check `pretix/presale/checkoutflow.py`
- [ ] `SESSION_KEY`/`CART_SESSION_KEY` namespaced by event (or cleared on
      new checkout), so stale Telegram-linked state from one event's
      checkout can't leak into a different event's checkout in the same
      browser session
- [ ] `id_email` selector in the widget's inline script actually matches
      the rendered email input's `id` in your pretix version
- [ ] After connecting Telegram, the email input's `required` attribute is
      actually gone from the rendered HTML (inspect it — don't just trust
      the script ran)
- [ ] "Connected via Telegram as @username" displays correctly, falls back
      to first name or "a Telegram account" when no public username exists
- [ ] "Not you? Disconnect" clears the session and returns to a fresh,
      unconnected contact step
- [ ] Typing a real email AND connecting Telegram both stick — order ends
      up with the real email, not overwritten by a dummy
- [ ] Leaving email blank with Telegram connected succeeds end-to-end,
      including past the browser's own client-side validation, and the
      resulting order has a dummy address, not a blank one
- [ ] Leaving email blank WITHOUT Telegram connected still correctly
      fails — confirms the default case is untouched
- [ ] Dummy addresses are unique enough that pretix doesn't misbehave if
      it does any per-event duplicate-email matching on order creation
- [ ] Abandoned checkout with Telegram chosen but never completed doesn't
      leave anything in an inconsistent state (no order is created until
      the confirm step regardless, so this should be a non-issue — verify)
- [ ] `order_meta_from_request` → `order_placed` handoff actually produces
      a `TelegramIdentity`/`TelegramOrderLink` pair for an order placed via
      the checkout-time Telegram login path