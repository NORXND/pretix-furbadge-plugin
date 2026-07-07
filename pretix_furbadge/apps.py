# -*- coding: utf-8 -*-

"""
pretix_furbadge.apps
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Pretix Furry Badges! Plugin

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from typing import List

from django.utils.translation import gettext_lazy

from . import __version__

try:
    from pretix.base.plugins import PluginConfig
except ImportError:
    raise RuntimeError("Please use pretix 2.7 or above to run this plugin!")


class PluginApp(PluginConfig):
    default = True
    name = "pretix_furbadge"
    verbose_name = "Furry Badges!"

    class PretixPluginMeta:
        name = gettext_lazy("Furry Badges!")
        author = "Norbert Dudziak"
        description = gettext_lazy(
            "Badge templates for pretix with configurable avatar layouts, circular avatar rendering, and Telegram integration support."
        )
        visible = True
        version = __version__
        category = "FEATURE"
        compatibility = "pretix>=2.7.0"
        settings_links: List[dict] = []
        navigation_links: List[dict] = []

    def ready(self):
        from pretix.base.settings import settings_hierarkey

        from . import signals  # NOQA

        settings_hierarkey.add_default("furbadge_allow_edits", "1", bool)
        settings_hierarkey.add_default("furbadge_edit_deadline", None, type(None))
        settings_hierarkey.add_default("furbadge_telegram_enabled", False, bool)
        settings_hierarkey.add_default("furbadge_telegram_bot_token", "", str)
        settings_hierarkey.add_default("furbadge_telegram_bot_username", "", str)
        settings_hierarkey.add_default("furbadge_telegram_client_id", "", str)
        settings_hierarkey.add_default("furbadge_telegram_client_secret", "", str)
        settings_hierarkey.add_default("furbadge_telegram_webhook_secret", "", str)
        settings_hierarkey.add_default(
            "furbadge_telegram_consent_text",
            (
                "I agree to share my Telegram username and order status with the organizer's Telegram bot."
            ),
            str,
        )
