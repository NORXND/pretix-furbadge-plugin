# -*- coding: utf-8 -*-

"""
pretix_furbadge.forms
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

All fonts around the plugin.

:copyright: (c) 2026 Norbert Dudziak.
:license: Apache-2.0, see LICENSE for more details.
"""

from typing import TYPE_CHECKING

import subprocess
import tempfile
from django import forms
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils.timezone import is_aware, make_aware
from django.utils.translation import gettext_lazy as _
from fontTools.ttLib import TTFont as FTFont
from isodate import parse_datetime
from pathlib import Path
from pretix.base.forms import SettingsForm, logger
from pretix.base.models import Item, Order, Question

# Pretix imports
from pretix.control.forms import ExtFileField, SplitDateTimePickerWidget, mark_safe

from .models import BadgeData, BadgeType, EventFont, ProductBadgeLink, TelegramOrderLink

if TYPE_CHECKING:
    from django_stubs_ext import StrPromise
    from pretix.base.models import Event

    from pretix_furbadge.types import FormsFieldWithQuerySet


class BadgeTypeForm(forms.ModelForm):
    """
    Form for creating and editing BadgeType instances (templates for badges).
    This form includes fields for uploading background and foreground PDFs, selecting fonts,
    and configuring badge layout options.

    See :class:`pretix_furbadge.models.BadgeType` for the model definition and :class:`pretix_furbadge.views.BadgeTypeCreateView`
    or :class:`pretix_furbadge.views.BadgeTypeUpdateView` for usage in views.
    """

    background_pdf = ExtFileField(
        label=_("Background PDF"),
        required=True,
        ext_whitelist=(".pdf",),
        help_text=_("The base layer for the badge."),
    )
    foreground_pdf = ExtFileField(
        label=_("Foreground PDF"),
        required=False,
        ext_whitelist=(".pdf",),
        help_text=_("Overlay on top of the avatar and text."),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # Handle event fonts
        self.fields: dict[str, "FormsFieldWithQuerySet"]  # type: ignore[assignment]
        if "event" in kwargs:
            self.fields["font"].queryset = kwargs["event"].furbadge_fonts.all()
        elif self.instance and hasattr(self.instance, "event"):
            self.fields["font"].queryset = self.instance.event.furbadge_fonts.all()

        # Dynamically show previously uploaded files in help_text
        if self.instance and self.instance.pk:
            if self.instance.background_pdf:
                filename = self.instance.background_pdf.name.split("/")[-1]
                self.fields["background_pdf"].help_text = mark_safe(
                    f'{self.fields["background_pdf"].help_text}<br><strong>{_("Currently uploaded:")}</strong> {filename}'
                )

            if self.instance.foreground_pdf:
                filename = self.instance.foreground_pdf.name.split("/")[-1]
                self.fields["foreground_pdf"].help_text = mark_safe(
                    f'{self.fields["foreground_pdf"].help_text}<br><strong>{_("Currently uploaded:")}</strong> {filename}'
                )

    class Meta:
        model = BadgeType
        fields = [
            "name",
            "is_active",
            "background_pdf",
            "foreground_pdf",
            "font",
            "font_size_max",
            "font_color",
            "text_justify",
            "image_pos_x",
            "image_pos_y",
            "image_width",
            "image_height",
            "avatar_shape",
            "text_pos_x",
            "text_pos_y",
            "text_max_width",
            "text_max_height",
        ]


class EventFontForm(forms.ModelForm):
    """
    Form for creating and editing EventFont instances (fonts used in badges).
    See :class:`pretix_furbadge.models.EventFont` for the model definition and :class:`pretix_furbadge.views.EventFontCreateView`
    or :class:`pretix_furbadge.views.EventFontUpdateView` for usage in views
    """

    font_file = ExtFileField(
        label=_("Font File (TTF/OTF)"),
        required=True,
        ext_whitelist=(".ttf", ".otf"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.font_file:
            filename = self.instance.font_file.name.split("/")[-1]
            base_help = self.fields["font_file"].help_text or ""
            self.fields["font_file"].help_text = mark_safe(
                f'{base_help}<br><strong>{_("Currently uploaded:")}</strong> {filename}'
            )

    def clean_font_file(self):
        uploaded = self.cleaned_data["font_file"]
        raw_bytes = uploaded.read()
        uploaded.seek(0)

        with tempfile.TemporaryDirectory() as tmpdir:
            src_path = Path(tmpdir) / f"upload{Path(uploaded.name).suffix}"
            src_path.write_bytes(raw_bytes)

            try:
                ft = FTFont(str(src_path), lazy=True)
            except Exception:
                raise forms.ValidationError(
                    _("This doesn't look like a valid font file.")
                )

            is_cff = "CFF " in ft or "CFF2" in ft
            ft.close()

            if not is_cff:
                return uploaded  # already TrueType-outline, nothing to do

            # PostScript/CFF outlines - ReportLab can't embed these directly.
            # Convert to TrueType outlines automatically rather than rejecting the upload.
            out_path = Path(tmpdir) / "converted.ttf"
            try:
                subprocess.run(
                    ["otf2ttf", str(src_path), "-o", str(out_path)],
                    check=True,
                    capture_output=True,
                )
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                logger.exception(
                    "Automatic OTF->TTF conversion failed for %s", uploaded.name
                )
                raise forms.ValidationError(
                    _(
                        "This font uses PostScript/CFF outlines and automatic conversion to "
                        "TrueType failed. Please convert it to .ttf manually before uploading."
                    )
                ) from e

            converted_bytes = out_path.read_bytes()
            new_name = Path(uploaded.name).stem + ".ttf"
            return SimpleUploadedFile(
                new_name, converted_bytes, content_type="font/ttf"
            )

    class Meta:
        model = EventFont
        fields = ["name", "font_file"]


class ProductBadgeLinkForm(forms.ModelForm):
    """
    Form for creating and editing ProductBadgeLink instances.
    See :class:`pretix_furbadge.models.ProductBadgeLink` for the model definition and :class:`pretix_furbadge.views.ProductBadgeLinkCreateView`
    or :class:`pretix_furbadge.views.ProductBadgeLinkUpdateView` for usage in views.
    """

    title: StrPromise
    template: str
    item: forms.ModelChoiceField[Item] = forms.ModelChoiceField(
        queryset=Item.objects.none(),
        label=_("Product"),
    )
    badge_type: forms.ModelChoiceField[BadgeType] = forms.ModelChoiceField(
        queryset=BadgeType.objects.none(), label=_("Badge Type"), required=False
    )

    class Meta:
        model = ProductBadgeLink
        fields = ["item", "badge_type"]

    def __init__(self, *args, **kwargs) -> None:
        self.event = kwargs.pop("event")
        super().__init__(*args, **kwargs)
        self.fields: dict[str, "FormsFieldWithQuerySet"]  # type: ignore[assignment]
        self.fields["item"].queryset = self.event.items.all()
        self.fields["badge_type"].queryset = self.event.furbadge_types.all()


class FurbadgeSettingsForm(SettingsForm):
    """
    Event settings form for the furbadge plugin. This form allows event organizers to configure global
    settings related to badge editing, preview overlays, nickname questions, and default avatars.

    See :class:`pretix_furbadge.models.EventSettings` for the model definition and
    :class:`pretix_furbadge.views.FurbadgeSettingsView` for usage in views.
    """

    furbadge_allow_edits: forms.BooleanField = forms.BooleanField(
        label=_("Allow Badge Edits"),
        help_text=_("If enabled, attendees can edit their badge data."),
        required=False,
    )
    furbadge_edit_deadline: forms.SplitDateTimeField = forms.SplitDateTimeField(
        label=_("Badge Edit Deadline"),
        required=False,
        widget=SplitDateTimePickerWidget(),
    )
    furbadge_preview_overlay_pdf: ExtFileField = ExtFileField(
        label=_("Preview Overlay PDF"),
        help_text=_("Global overlay watermark applied only in previews."),
        required=False,
        ext_whitelist=(".pdf",),
    )
    furbadge_nickname_question: forms.ModelChoiceField[Question] = (
        forms.ModelChoiceField(
            label=_("Question for Badge Nickname"),
            queryset=Question.objects.none(),
            required=False,
            help_text=_(
                "Select the pretix question used to pull the attendee's badge nickname. If not selected, the badge text will be an optional preference."
            ),
        )
    )
    furbadge_public_list_question: forms.ModelChoiceField[Question] = (
        forms.ModelChoiceField(
            label=_("Question for Public List Visibility"),
            queryset=Question.objects.none(),
            required=False,
            help_text=_(
                "Select the pretix question used to decide whether the attendee should appear in the public attendee list."
            ),
        )
    )
    furbadge_default_avatar: ExtFileField = ExtFileField(
        label=_("Default Avatar"),
        help_text=_(
            "Default avatar image used when no custom avatar is uploaded. If not set, no avatar will be rendered."
        ),
        required=False,
        ext_whitelist=(".png", ".jpg", ".jpeg"),
    )

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # Parse the initial value for the edit deadline
        deadline_val = self.initial.get("furbadge_edit_deadline")
        if deadline_val and isinstance(deadline_val, str):
            parsed_dt = parse_datetime(deadline_val)
            if parsed_dt:
                # Ensure the parsed datetime is timezone-aware to satisfy Django's internal check
                if not is_aware(parsed_dt):
                    parsed_dt = make_aware(parsed_dt)
                self.initial["furbadge_edit_deadline"] = parsed_dt

        self.obj: Event
        if hasattr(self, "obj") and self.obj:
            # Dynamically bind the queryset of this event's questions
            self.fields: dict[str, "FormsFieldWithQuerySet"]  # type: ignore[assignment]
            self.fields["furbadge_nickname_question"].queryset = (
                self.obj.questions.all()
            )
            self.fields["furbadge_public_list_question"].queryset = (
                self.obj.questions.all()
            )

        file_fields = {
            "furbadge_preview_overlay_pdf": "furbadge_preview_overlay_pdf",
            "furbadge_default_avatar": "furbadge_default_avatar",
        }

        for setting_key, field_name in file_fields.items():
            current_file = self.obj.settings.get(setting_key, as_type=str)
            if current_file:
                filename = current_file.split("/")[-1]
                base_help = self.fields[field_name].help_text or ""
                self.fields[field_name].help_text = mark_safe(
                    f'{base_help}<br><span class="text-success"><strong>{_("Currently uploaded:")}</strong> {filename}</span>'
                )


class BadgeDataForm(forms.ModelForm):
    class Meta:
        model = BadgeData
        fields = ["badge_text"]


class TelegramSettingsForm(SettingsForm):
    """
    Form for configuring Telegram integration settings in the control panel.

    This form handles bot credentials, OIDC client configuration, webhook secrets,
    and email forwarding preferences for the Telegram plugin.

    See :class:`pretix_furbadge.models.TelegramIdentity` for identity management and
    :func:`pretix_furbadge.views.telegram_settings_view` for usage examples.
    """

    furbadge_telegram_enabled = forms.BooleanField(
        label=_("Enable Telegram integration"),
        required=False,
        help_text=_("Allow attendees to connect their Telegram accounts to orders."),
    )

    furbadge_telegram_bot_token = forms.CharField(
        label=_("Bot token from @BotFather"),
        widget=forms.PasswordInput(render_value=True),
        help_text=_("The bot token obtained from Telegram's BotFather."),
    )

    furbadge_telegram_bot_username = forms.CharField(
        label=_("Bot username (without @)"),
        help_text=_("Used to build deep links in web_app buttons. Ex: 'YourEventBot'."),
    )

    furbadge_telegram_client_id = forms.CharField(
        label=_("OIDC client ID"),
        required=False,
        help_text=_(
            "Telegram's OpenID Connect client identifier for the Login Widget."
        ),
    )

    furbadge_telegram_client_secret = forms.CharField(
        label=_("OIDC client secret"),
        widget=forms.PasswordInput(render_value=True),
        help_text=_("Secret key for OIDC authentication with Telegram."),
    )

    furbadge_telegram_webhook_secret = forms.CharField(
        label=_("Webhook secret token"),
        required=False,
        help_text=_(
            "Pass this as secret_token when setting the webhook URL via BotFather."
        ),
    )

    furbadge_telegram_consent_text = forms.CharField(
        label=_("Consent checkbox text"),
        widget=forms.Textarea,
        help_text=_("Text displayed next to the consent checkbox on the order page."),
    )

    class Meta:
        """Configuration metadata for TelegramSettingsForm."""

        pass


class TelegramLoginPromptWidget(forms.Widget):
    """
    The widget for the telegram login in checkout.
    """

    def __init__(
        self,
        connect_url,
        already_linked=False,
        disconnect_url=None,
        username=None,
        first_name=None,
        *args,
        **kwargs,
    ):
        self.connect_url = connect_url
        self.already_linked = already_linked
        self.disconnect_url = disconnect_url
        self.username = username
        self.first_name = first_name
        super().__init__(*args, **kwargs)

    def render(self, name, value, attrs=None, renderer=None):
        if self.already_linked:
            tg_name = self.username or "Unknown User"
            if self.first_name:
                tg_name = f"{self.first_name} ({tg_name})"

            return mark_safe(
                '<div class="furbadge-telegram-inline-prompt text-muted">'
                f"{_('Connected via Telegram as %(name)s.') % {'name': tg_name}} "
                f"{_('Not you? <a href=\"%(url)s\">Disconnect</a>.') % {'url': self.disconnect_url}}"
                "</div>"
            )

        return mark_safe(
            f'<div class="furbadge-telegram-inline-prompt">'
            f"{_('or <a href=\"%(url)s\">connect via Telegram</a> to make email optional') % {'url': self.connect_url}}"
            f"</div>"
        )

    def value_from_datadict(self, data, files, name):
        return None  # not a real input — never contributes data on submit


class TelegramLoginPromptField(forms.Field):
    """Renders a prompt only. Always optional, never validates anything."""

    widget = TelegramLoginPromptWidget
    required = False

    def clean(self, value):
        return None


class TelegramPreferencesForm(forms.ModelForm):
    """
    Form to update Telegram preferences ofr an order.
    """

    def __init__(self, *args, no_email=False, **kwargs):
        self.no_email = no_email
        super().__init__(*args, **kwargs)

        if no_email:
            self.fields["telegram_delivery_mode"].choices = [
                ("telegram_only", _("Telegram only")),
            ]
        else:
            self.fields["telegram_delivery_mode"].choices = [
                ("email_only", _("Email only")),
                ("email_and_telegram", _("Email and Telegram")),
                ("telegram_only", _("Telegram only")),
            ]

    def clean_telegram_delivery_mode(self):
        mode = self.cleaned_data["telegram_delivery_mode"]

        if self.no_email and mode != "telegram_only":
            raise forms.ValidationError(
                _("Without an email address, only Telegram delivery is available.")
            )

        return mode

    class Meta:
        model = TelegramOrderLink
        fields = ["telegram_delivery_mode", "public_share"]


class TelegramOrderEmailAddition(forms.ModelForm):
    """
    Mini form to add an email address to an existing order, if the user has connected via Telegram
    but didn't provide an email.
    """

    class Meta:
        model = Order
        fields = ["email"]
