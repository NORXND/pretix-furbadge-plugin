# pretix Furbadge Plugin

A Pretix plugin for generating and managing custom furry convention badges - and few more things like Telegram integration.

This is by any means not a "general purpose" plugin - it was made to solve our shortcomings of Pretix's built-in badges plugin and is rather tailored for usage within furry events in Poland; hence, it also contains some additional features that are useful in that particular use case.

Originally made for [Futrobrzeg](https://futrobrzeg.pl) organized by [Seaside Paws Foundation](https://nadmorskielapy.org.pl)

## Features

- Create and manage different badge types/templates with customization options as follows:
  - Custom background from uploaded PDF (sets badge's size)
  - Set size and position for user-uploaded avatar
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
- [SOON] Telegram Integration for:
  - Mail messages CC
  - List and manage orders/badges
  - Embed shop/order/badge edit in Telegram
  - Fast QR code delivery via Telegram
  - (Maybe) No e-mail requirement

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

## Development

This project uses Python and pretix plugin conventions.

Recommended checks before opening a pull request:

```bash
python -m pip install -U pip
pip install -e .[dev]
python -m compileall pretix_furbadge
python -m pytest
```

## License

This project is licensed under the Apache License 2.0. See [LICENSE](LICENSE) for details.
