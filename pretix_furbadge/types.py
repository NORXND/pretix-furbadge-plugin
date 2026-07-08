# -*- coding: utf-8 -*-

"""
pretix_furbadge.types
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Typing utilities and such.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.forms import Field
    from django.http import HttpRequest
    from django_stubs_ext import QuerySetAny
    from pretix.base.models import Event, Order, OrderPosition, Organizer

    from pretix_furbadge.models import BadgeData

    class PretixRequest(HttpRequest):
        event: Event
        organizer: Organizer

    class OrderPositionWithBadgeData(OrderPosition):
        furbadge_data: BadgeData

    class FormsFieldWithQuerySet(Field):
        queryset: QuerySetAny
