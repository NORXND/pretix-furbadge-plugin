# -*- coding: utf-8 -*-

"""
pretix_furbadge.exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Expose badge exporter.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from typing import TYPE_CHECKING

import io
import zipfile
from collections import OrderedDict
from django import forms
from django.utils.translation import gettext_lazy as _
from pretix.base.exporter import BaseExporter

from .badge_renderer import BadgeRenderer
from .models import BadgeData

if TYPE_CHECKING:
    from typing import Literal

    from django_stubs_ext import StrPromise
    from pretix.base.models import Event


class BadgePDFExporter(BaseExporter):
    """
    Exposes an exporter for badge PDFs (or PNGs) in a ZIP file.
    """

    identifier: Literal["furbadge_pdf"] = "furbadge_pdf"
    verbose_name: 'StrPromise' = _("Badge PDFs (ZIP)")

    @property
    def export_form_fields(self) -> OrderedDict[str, forms.Field]:
        self.event: "Event"
        return OrderedDict(
            [
                (
                    "badge_type",
                    forms.ModelChoiceField(
                        queryset=self.event.furbadge_types.all(),
                        label=_("Badge Type"),
                        required=False,
                        help_text=_("Leave empty to export all badge types."),
                    ),
                ),
                (
                    "include_overlay",
                    forms.BooleanField(
                        label=_("Include preview overlay"), required=False
                    ),
                ),
                (
                    "output_format",
                    forms.ChoiceField(
                        choices=[("pdf", "PDF"), ("png", "PNG (150 DPI)")],
                        label=_("Output Format"),
                        initial="pdf",
                    ),
                ),
            ]
        )

    def render(self, form_data):
        qs = BadgeData.objects.filter(badge_link__event=self.event).select_related(
            "order_position", "order_position__order", "badge_link__badge_type"
        )

        badge_type = form_data.get("badge_type")
        if badge_type:
            qs = qs.filter(badge_link__badge_type=badge_type)

        include_overlay = form_data.get("include_overlay", False)
        out_format = form_data.get("output_format", "pdf")

        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for badge in qs:
                renderer = BadgeRenderer(badge.badge_link.badge_type)

                # Naming: OrderCode_PositionID_Nickname
                text = ""
                nickname_question_id = self.event.settings.get(
                    "furbadge_nickname_question", as_type=int
                )

                # Try pulling from the configured pretix question answer structure
                if nickname_question_id and badge.order_position:
                    ans = badge.order_position.answers.filter( # pyright: ignore[reportAttributeAccessIssue]
                        question_id=nickname_question_id
                    ).first()
                    if ans and ans.answer:
                        text = ans.answer.strip()

                # Fall back to manual local data if question answer wasn't populated/found
                if not text and badge.badge_text:
                    text = badge.badge_text.strip()

                # sanitize
                name_part = "".join(
                    [c for c in text if c.isalpha() or c.isdigit() or c == " "]
                ).rstrip()
                base_name = f"{badge.order_position.order.code}_{badge.order_position.positionid}_{name_part}"

                if out_format == "pdf":
                    pdf_bytes = renderer.render(badge, include_overlay=include_overlay)
                    zf.writestr(f"{base_name}.pdf", pdf_bytes)
                else:
                    png_bytes = renderer.render_preview_png(
                        badge, dpi=150, include_overlay=include_overlay
                    )
                    if png_bytes:
                        zf.writestr(f"{base_name}.png", png_bytes)

        return "badges.zip", "application/zip", zip_buffer.getvalue()
