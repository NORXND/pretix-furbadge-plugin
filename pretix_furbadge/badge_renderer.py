# -*- coding: utf-8 -*-

"""
pretix_furbadge.exporter
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The core of the plugin - the badge renderer.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from typing import Any, cast

import io
import logging
import os
from django.core.files import File
from django.utils.translation import gettext as _
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

logger = logging.getLogger(__name__)


class BadgeRenderer:
    """
    The actual place where the magic happens - the badge renderer.
    Provides methods to render a badge into a PDF or PNG, with support for custom fonts, text fitting, and optional overlays.
    """

    def __init__(self, badge_type):
        self.badge_type = badge_type

    def _register_font(self):
        """Registers custom fonts safely, explicitly returning 'Helvetica' if it fails"""
        if self.badge_type.font and self.badge_type.font.font_file:
            try:
                potential_font_name = f"CustomFont_{self.badge_type.font.id}"

                # If already registered in ReportLab's global state, use it right away
                try:
                    pdfmetrics.getFont(potential_font_name)
                    return potential_font_name
                except KeyError:
                    # Not registered yet, let's try to register it
                    font_path = self.badge_type.font.font_file.path
                    if os.path.exists(font_path):
                        pdfmetrics.registerFont(TTFont(potential_font_name, font_path))
                        return potential_font_name
            except Exception:
                logger.exception(
                    "Failed to register custom badge font, falling back to Helvetica"
                )

        return "Helvetica"

    def _calculate_font_size(self, text, font_name, c):
        """Binary search to find max font size that fits the constraints with safety fallbacks"""
        # Safeguard: Verify the font profile actually exists in ReportLab
        try:
            pdfmetrics.getFont(font_name)
        except KeyError:
            font_name = "Helvetica"

        max_size = float(self.badge_type.font_size_max)
        max_width_pt = float(self.badge_type.text_max_width) * mm

        low = 1.0
        high = max_size
        best_size = low

        for _i in range(15):  # 15 iterations binary search
            mid = (low + high) / 2
            try:
                width = c.stringWidth(text, font_name, mid)
            except Exception:
                width = c.stringWidth(text, "Helvetica", mid)  # Hard fallback

            if width <= max_width_pt:
                best_size = mid
                low = mid
            else:
                high = mid

        return best_size

    def render(self, badge_data, include_overlay=False) -> bytes:
        """Composites layers into a single PDF with image and text placeholders"""
        event = badge_data.badge_link.event

        if not self.badge_type.background_pdf:
            raise ValueError(_("Background PDF is required"))

        # Read background safely
        bg_reader = PdfReader(self.badge_type.background_pdf.path)
        if not bg_reader.pages:
            raise ValueError(_("Background PDF layout contains no readable pages."))

        bg_page = bg_reader.pages[0]
        page_width = float(bg_page.mediabox.width)
        page_height = float(bg_page.mediabox.height)

        # Render overlay (avatar + text)
        packet = io.BytesIO()
        c = canvas.Canvas(packet, pagesize=(page_width, page_height))

        # --- AVATAR DRAWING ---
        avatar_source = None
        if (
            badge_data.avatar
            and hasattr(badge_data.avatar, "path")
            and os.path.exists(badge_data.avatar.path)
        ):
            avatar_source = (
                badge_data.avatar.path
            )  # keep as path string, don't wrap in BytesIO
        else:
            # Default fallback
            default_avatar_file = event.settings.get(
                "furbadge_default_avatar", as_type=File
            )
            if default_avatar_file:
                avatar_source = default_avatar_file.name

        if avatar_source:
            # The drawing
            try:
                is_bytes = isinstance(avatar_source, bytes)
                img = Image.open(
                    io.BytesIO(avatar_source) if is_bytes else avatar_source
                )
                img.verify()
                img.close()

                draw_source = io.BytesIO(avatar_source) if is_bytes else avatar_source

                w_pt = float(self.badge_type.image_width) * mm
                h_pt = float(self.badge_type.image_height) * mm

                x_top_left = float(self.badge_type.image_pos_x) - (
                    float(self.badge_type.image_width) / 2
                )
                y_top_left = float(self.badge_type.image_pos_y) - (
                    float(self.badge_type.image_height) / 2
                )

                x_pt = x_top_left * mm
                y_pt = page_height - (y_top_left * mm) - h_pt

                if self.badge_type.avatar_shape == "circle":
                    canvas_obj = cast(Any, c)
                    canvas_obj.saveState()

                    path = canvas_obj.beginPath()

                    path.circle(x_pt + (w_pt / 2), y_pt + (h_pt / 2), w_pt / 2)

                    canvas_obj.clipPath(path, stroke=0, fill=0)

                    canvas_obj.drawImage(
                        draw_source, x_pt, y_pt, width=w_pt, height=h_pt, mask="auto"
                    )
                    canvas_obj.restoreState()
                else:
                    c.drawImage(
                        draw_source, x_pt, y_pt, width=w_pt, height=h_pt, mask="auto"
                    )
            except Exception:
                logger.exception("Could not draw badge avatar image, skipping")

        # --- TEXT DRAWING ---
        text = ""
        nickname_question_id = event.settings.get(
            "furbadge_nickname_question", as_type=int
        )

        # Try pulling from the configured pretix question answer structure
        if nickname_question_id and badge_data.order_position:
            ans = badge_data.order_position.answers.filter(
                question_id=nickname_question_id
            ).first()
            if ans and ans.answer:
                text = ans.answer.strip()

        # Fall back to manual local data if question answer wasn't populated/found
        if not text and badge_data.badge_text:
            text = badge_data.badge_text.strip()

        # Last resort fallback layouts
        if not text:
            text = badge_data.order_position.attendee_name or _("Attendee")

        font_name = self._register_font()
        font_size = self._calculate_font_size(text, font_name, c)

        # Guard font engine assignment right before canvas rendering actions
        try:
            c.setFont(font_name, font_size)
        except Exception:
            font_name = "Helvetica"
            c.setFont(font_name, font_size)

        # Parse color #RRGGBB
        color_hex = (
            self.badge_type.font_color.lstrip("#")
            if self.badge_type.font_color
            else "000000"
        )
        if len(color_hex) == 6:
            r = int(color_hex[0:2], 16) / 255.0
            g = int(color_hex[2:4], 16) / 255.0
            b = int(color_hex[4:6], 16) / 255.0
            c.setFillColorRGB(r, g, b)

        anchor_x = float(self.badge_type.text_pos_x) * mm
        anchor_y = page_height - (float(self.badge_type.text_pos_y) * mm)

        if self.badge_type.text_justify == "left":
            c.drawString(anchor_x, anchor_y, text)
        elif self.badge_type.text_justify == "right":
            c.drawRightString(anchor_x, anchor_y, text)
        else:
            c.drawCentredString(anchor_x, anchor_y, text)

        c.save()
        packet.seek(0)
        overlay_reader = PdfReader(packet)
        overlay_page = overlay_reader.pages[0]

        # Merge background and overlay
        bg_page.merge_page(overlay_page)

        # Merge foreground if exists
        if self.badge_type.foreground_pdf:
            try:
                fg_reader = PdfReader(self.badge_type.foreground_pdf.path)
                fg_page = fg_reader.pages[0]
                bg_page.merge_page(fg_page)
            except Exception:
                logger.exception("Could not merge badge foreground PDF, skipping")

        # Merge preview overlay if requested (from event settings)
        if include_overlay:
            preview_pdf = event.settings.get(
                "furbadge_preview_overlay_pdf", as_type=File
            )
            if preview_pdf:
                try:
                    if not preview_pdf.closed:
                        preview_pdf.close()
                    preview_pdf.open("rb")
                    try:
                        overlay_bytes = preview_pdf.read()
                    finally:
                        preview_pdf.close()

                    ov_reader = PdfReader(io.BytesIO(overlay_bytes))
                    ov_page = ov_reader.pages[0]
                    bg_page.merge_page(ov_page)
                except FileNotFoundError:
                    logger.warning(
                        "Configured badge preview overlay PDF is missing from storage, skipping"
                    )

        writer = PdfWriter()
        writer.add_page(bg_page)

        out_pdf = io.BytesIO()
        writer.write(out_pdf)
        out_pdf.seek(0)
        return out_pdf.read()

    def render_preview_png(self, badge_data, dpi=150, include_overlay=True) -> bytes:
        """Returns PNG bytes for the preview with exact PDF dimensions"""
        try:
            from pdf2image import convert_from_bytes
            from pypdf import PdfReader

            pdf_bytes = self.render(badge_data, include_overlay=include_overlay)
            if not pdf_bytes:
                return b""

            pdf_file = io.BytesIO(pdf_bytes)
            reader = PdfReader(pdf_file)
            if not reader.pages:
                return b""

            page = reader.pages[0]
            mediabox = page.mediabox

            orig_width = float(mediabox.width)
            orig_height = float(mediabox.height)

            pixel_width = int((orig_width / 72) * dpi)
            pixel_height = int((orig_height / 72) * dpi)

            images = convert_from_bytes(
                pdf_bytes, dpi=dpi, size=(pixel_width, pixel_height), use_cropbox=True
            )

            if not images:
                return b""

            out_img = io.BytesIO()
            images[0].save(out_img, format="PNG")
            return out_img.getvalue()

        except ImportError:
            return b""
