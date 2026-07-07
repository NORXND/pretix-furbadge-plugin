# pretix Furbadge Plugin

A Pretix plugin for generating and managing custom furry convention badges - and few more things like Telegram integration.

This is by any means not a "general purpose" plugin - it was made to solve our shortcomings of Pretix's built-in badges plugin and is rather tailored for usage within furry events in Poland; hence, it also contains some additional features that are useful in that particular use case.

Originally made for [Futrobrzeg](https://futrobrzeg.pl) organized by [Seaside Paws Foundation](https://nadmorskielapy.org.pl)

## Features

- Create and manage different badge types/templates with customization options as follows:
  - Custom background from uploaded PDF (sets badge's size)
  - Set size and position for user-uploaded avatar
  - Choose between rectangular or circular avatar rendering
  - Set size, position, justify and bounding box (size downscale) for text
  - Usage of custom fonts from uploaded TTF/OTF
- Powerful badge system for attendees:
  - Ability to upload & crop any image as avatar
  - Set text (nickname) for the badge - either via Pretix's built-in question or via integrated form field
  - Add optional Telegram username for contact
  - Set privacy preferences (public list)
- Extensive badge management:
  - Setting badge type per product
  - Preview (with and without overlay) for admins
  - PDF export (singlular and batch)
  - Ability to edit badge data
- API for public attendees list
- Telegram integration for:
  - Connecting Telegram identities to orders from the order page
  - Forwarding outgoing emails to connected Telegram users
  - Basic bot commands for orders, badges, and QR delivery
  - Webhook-based bot handling for event-scoped bots

## Installation

Install from source:

```bash
pip install -e .[dev]
```

For a local development setup, you can also use the included helper scripts:

```bash
./compile-locales.sh
./gen-locales.sh
```

## Configuring Telegram

You will have to create a bot via [@BotFather](https://t.me/BotFather) then fill all the needed information in Telegram settings.

In the bot config, you will have to change the login widget type to OAuth2 and set these redirect URLs:

`https://<your-pretix-host>/<organizer>/<event>/furbadge/telegram/checkout/callback/`
`https://<your-pretix-host>/<organizer>/<event>/furbadge/telegram/connect/callback/`

You will also need to add commands and webhook information:

```bash
curl "https://api.telegram.org/bot<api-token-from-botfather>/setWebhook" \
     -d "url=https://<your-pretix-host>/<organizer>/<event>/furbadge/telegram/webhook/" \
     -d "secret_token=<furbadge_telegram_webhook_secret>"
```

`furbadge_telegram_webhook_secret` is any string you choose - you have to also include it in Telegram settings in pretix - one easy way to generate such secure string is:

```bash
python3 -c "import secrets; print(secrets.token_hex(16))"
```

You can also add command list with descriptions with this request:

```bash
curl "https://api.telegram.org/bot<api-token-from-botfather>/setMyCommands" \
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
```

**IMPORTANT:** Do **not** use the "Match orders based on email address" - Pretix really does not like having no email connected to the order, we utilize the only (looks like unfinished or at least highly unpolished) feature Pretix authors have left which is the "PRETIX_EMAIL_NONE_VALUE" - that makes all orders appear to the system as from the same email. From what I've found Pretix does **not** check that condition on matching orders - and that poses a real security/privacy threat.

In addition, while default value is `none@well-known.pretix.eu` which is probably a dead address, for privacy reasons I would suggest setting your own created dead address.

## Development

This project uses Python and pretix plugin conventions.

Recommended checks before opening a pull request:

```bash
python -m pip install -U pip
pip install -e .[dev]
python -m compileall pretix_furbadge
python -m pytest -q
python -m mypy pretix_furbadge --config-file pyproject.toml
python -m pyright
```

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
