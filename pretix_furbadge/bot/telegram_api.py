import html
import logging
import re
import requests  # type: ignore[import-untyped]

# Set up a logger to catch API errors without crashing your app
logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"(https?://[^\s<>\"]+|www\.[^\s<>\"]+)", re.IGNORECASE)


def auto_linkify(text):
    """
    1. Sanitizes the entire text for Telegram HTML.
    2. Finds raw URLs and safely wraps them in HTML <a> tags.
    """
    if not text:
        return text

    # Escape the text completely so things like <n> become &lt;n&gt;
    # This prevents Telegram's HTML entity parser from crashing.
    escaped_text = html.escape(str(text))

    def replace_url(match):
        url = match.group(1)

        # Unescape just the URL part since html.escape turns & to &amp;
        # inside the URL, which we don't want breaking the actual href address.
        raw_url = html.unescape(url)

        # Add protocol wrapper if it's just a raw 'www.' link
        href = raw_url if raw_url.lower().startswith("http") else f"https://{raw_url}"
        safe_href = html.escape(href, quote=True)

        # Return the safe HTML anchor tag wrapping the cleanly escaped display URL
        return f'<a href="{safe_href}">{url}</a>'

    # Safe regex substitution over the clean text
    return URL_REGEX.sub(replace_url, escaped_text)


def _api(event):
    token = event.settings.get("furbadge_telegram_bot_token", as_type=str)
    return f"https://api.telegram.org/bot{token}"


def tg_send_message(chat_id, text, event=None, parse_mode="HTML", **kwargs):
    """
    Sends a message. Safely handles raw text, escapes illegal tags like <n>,
    and converts raw links to clickable HTML formatting safely.
    """
    if parse_mode == "HTML":
        text = auto_linkify(text)

    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}

    try:
        response = requests.post(
            f"{_api(event)}/sendMessage",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        error_details = getattr(e.response, "text", "")
        logger.error(
            f"Failed to send Telegram message to {chat_id}: {e}. Details: {error_details}"
        )


def tg_send_document(
    chat_id, filename, content, mimetype, event=None, caption=None, parse_mode="HTML"
):
    """
    Sends a document/photo. Safely parses captions containing raw characters.
    """
    if caption and parse_mode == "HTML":
        caption = auto_linkify(caption)

    data = {
        "chat_id": chat_id,
        "parse_mode": parse_mode,
    }
    if caption:
        data["caption"] = caption

    try:
        response = requests.post(
            f"{_api(event)}/sendDocument",
            data=data,
            files={"document": (filename, content, mimetype)},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        error_details = getattr(e.response, "text", "")
        logger.error(
            f"Failed to send Telegram document to {chat_id}: {e}. Details: {error_details}"
        )


def tg_send_photo(
    chat_id, filename, content, event=None, caption=None, parse_mode="HTML"
):
    """
    Sends a native photo to Telegram using multipart/form-data.
    """
    if caption and parse_mode == "HTML":
        caption = auto_linkify(caption)

    data = {
        "chat_id": chat_id,
        "parse_mode": parse_mode,
    }
    if caption:
        data["caption"] = caption

    try:
        response = requests.post(
            f"{_api(event)}/sendPhoto",
            data=data,
            # Telegram expects the key name to be 'photo'
            files={"photo": (filename, content, "image/png")},
            timeout=15,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        error_details = getattr(e.response, "text", "")
        logger.error(
            f"Failed to send Telegram photo to {chat_id}: {e}. Details: {error_details}"
        )


def tg_send_web_app_button(chat_id, url, label, event=None, parse_mode="HTML"):
    """
    Sends a message containing an inline Web App button. Sanitizes text and label strings.
    """
    # Run the descriptive label through the linkifier to catch any raw characters (<, >, &)
    button_label = auto_linkify(label) if parse_mode == "HTML" else label

    payload = {
        "chat_id": chat_id,
        "text": button_label,
        "parse_mode": parse_mode,
        "reply_markup": {
            "inline_keyboard": [[{"text": label, "web_app": {"url": url}}]]
        },
    }

    try:
        response = requests.post(
            f"{_api(event)}/sendMessage",
            json=payload,
            timeout=10,
        )
        response.raise_for_status()
    except requests.RequestException as e:
        error_details = getattr(e.response, "text", "")
        logger.error(
            f"Failed to send Web App button to {chat_id}: {e}. Details: {error_details}"
        )
