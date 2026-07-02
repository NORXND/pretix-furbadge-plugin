# -*- coding: utf-8 -*-

"""
pretix_furbadge.models
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Models for the pretix_furbadge plugin.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from django.db import models
from django.utils.translation import gettext_lazy as _
from pretix.base.models import Event, Item, LoggedModel, OrderPosition


class EventFont(LoggedModel):
    """
    Represents a font that can be used for badge text in the pretix_furbadge plugin.
    """

    event: models.ForeignKey = models.ForeignKey(
        "pretixbase.Event", on_delete=models.CASCADE, related_name="furbadge_fonts"
    )
    name: models.CharField = models.CharField(
        max_length=190, verbose_name=_("Font Name")
    )
    font_file: models.FileField = models.FileField(
        upload_to="furbadge/fonts/",
        verbose_name=_("Font File (TTF/OTF)"),
        help_text=_("Upload your TTF or OTF font file."),
    )

    def __str__(self):
        return self.name


class BadgeType(LoggedModel):
    """
    Represents a badge type configuration (template) for the pretix_furbadge plugin.
    Each badge type defines the layout, fonts, and other settings for generating badges.
    """

    event: models.ForeignKey = models.ForeignKey(
        "pretixbase.Event", on_delete=models.CASCADE, related_name="furbadge_types"
    )
    name: models.CharField = models.CharField(max_length=190, verbose_name=_("Name"))

    background_pdf: models.FileField = models.FileField(
        upload_to="furbadge/backgrounds/",
        verbose_name=_("Background PDF"),
        help_text=_("The base layer for the badge."),
    )
    foreground_pdf: models.FileField = models.FileField(
        upload_to="furbadge/foregrounds/",
        blank=True,
        null=True,
        verbose_name=_("Foreground PDF"),
        help_text=_("Overlay on top of the avatar and text."),
    )

    font: models.ForeignKey = models.ForeignKey(
        EventFont,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        verbose_name=_("Font"),
    )
    font_size_max: models.DecimalField = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=48.0,
        verbose_name=_("Max Font Size (pt)"),
    )
    font_color: models.CharField = models.CharField(
        max_length=9, default="#000000", verbose_name=_("Font Color (Hex)")
    )

    TEXT_JUSTIFY_CHOICES = (
        ("left", _("Left")),
        ("center", _("Center")),
        ("right", _("Right")),
    )
    text_justify: models.CharField = models.CharField(
        max_length=10,
        choices=TEXT_JUSTIFY_CHOICES,
        default="center",
        verbose_name=_("Text Justify"),
    )

    # Avatar constraints (1:1 aspect ratio assumed)
    image_pos_x: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.0,
        verbose_name=_("Image Position X (mm)"),
        help_text=_("From top-left of page."),
    )
    image_pos_y: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.0,
        verbose_name=_("Image Position Y (mm)"),
        help_text=_("From top-left of page."),
    )
    image_width: models.DecimalField = models.DecimalField(
        max_digits=8, decimal_places=2, default=50.0, verbose_name=_("Image Width (mm)")
    )
    image_height: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=50.0,
        verbose_name=_("Image Height (mm)"),
    )

    # Text block constraints
    text_pos_x: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.0,
        verbose_name=_("Text Position X (mm)"),
        help_text=_("Anchor point (depends on justify)."),
    )
    text_pos_y: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=0.0,
        verbose_name=_("Text Position Y (mm)"),
        help_text=_("Baseline anchor point."),
    )
    text_max_width: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=50.0,
        verbose_name=_("Text Max Width (mm)"),
    )
    text_max_height: models.DecimalField = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        default=20.0,
        verbose_name=_("Text Max Height (mm)"),
    )

    is_active: models.BooleanField = models.BooleanField(
        default=True, verbose_name=_("Active")
    )

    def __str__(self):
        return self.name


class ProductBadgeLink(LoggedModel):
    """
    Defines a link between a product (item) and a badge type for a specific event.
    This allows the pretix_furbadge plugin to determine which badge type to use for each
    """

    event: Event = models.ForeignKey(
        "pretixbase.Event", on_delete=models.CASCADE, related_name="furbadge_links"
    )
    item: models.ForeignKey = models.ForeignKey(
        "pretixbase.Item",
        on_delete=models.CASCADE,
        related_name="furbadge_links",
        verbose_name=_("Product"),
    )  # pyright: ignore[reportAssignmentType]
    badge_type: models.ForeignKey = models.ForeignKey(
        BadgeType, on_delete=models.CASCADE, verbose_name=_("Badge Type")
    )  # type: ignore

    class Meta:
        unique_together = (("event", "item"),)

    def __str__(self):
        return f"{self.item} -> {self.badge_type}"


class BadgeData(models.Model):
    order_position: models.OneToOneField = models.OneToOneField(
        "pretixbase.OrderPosition",
        on_delete=models.CASCADE,
        related_name="furbadge_data",
    )  # type: ignore
    badge_link: models.ForeignKey = models.ForeignKey(
        ProductBadgeLink, on_delete=models.PROTECT
    )  # type: ignore
    avatar: models.ImageField = models.ImageField(
        upload_to="furbadge/avatars/", blank=True, null=True, verbose_name=_("Avatar")
    )
    badge_text: models.CharField = models.CharField(
        max_length=32, blank=True, verbose_name=_("Badge Text")
    )

    # Preferences
    telegram_username: models.CharField = models.CharField(
        max_length=64, blank=True, verbose_name=_("Telegram Username")
    )
    show_in_public_list: models.BooleanField = models.BooleanField(
        default=False, verbose_name=_("Show me in public attendee list")
    )
    show_telegram_in_public_list: models.BooleanField = models.BooleanField(
        default=False, verbose_name=_("Show my Telegram in public list")
    )

    updated_at: models.DateTimeField = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Badge for {self.order_position}"
