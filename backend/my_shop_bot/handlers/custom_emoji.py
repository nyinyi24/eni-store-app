"""Central custom-emoji support for every existing inline button.

Buttons keep their normal Unicode emoji until the admin enables custom emoji
and assigns an ID to the matching button key.
"""
import re

from telebot import types
from database import get_setting, get_product_custom_emoji


BUTTON_EMOJI_KEYS = (
    "shop", "buy_now", "giveaway", "my_orders", "support", "sell_proof", "referral",
    "language", "language_my", "language_en", "home", "back", "refresh", "kpay", "wave", "aya_pay",
    "usdt_erc20", "usdt_bep20", "binance_pay", "approve", "reject",
    "cancel", "confirm", "review", "products", "orders", "users",
    "promotion", "stock", "discount", "admin", "channel", "verify",
    "out_of_stock",
    "admin_products", "admin_orders", "admin_users", "admin_shop", "admin_promotion",
    "admin_referral", "admin_custom_emoji", "admin_add_product", "admin_edit_product",
    "admin_add_stock", "admin_set_stock", "admin_discount", "admin_remove_product",
    "admin_renew", "admin_recent_orders", "admin_search_orders", "admin_monthly_report",
    "admin_yearly_report", "admin_check_renewals", "admin_manual_send", "admin_user_list",
    "admin_active_users", "admin_announcement", "admin_list", "admin_add_admin",
    "admin_remove_admin", "admin_open", "admin_close", "admin_maintenance",
    "admin_start", "admin_pause", "admin_stats", "admin_claims", "admin_guide",
    "admin_add_gift", "admin_add_gift_stock", "admin_gift_list", "admin_pending_manual",
    "admin_promotion_setup", "admin_button_setup", "admin_message_setup",
    "admin_product_setup", "admin_toggle",
)

MESSAGE_EMOJI_KEYS = (
    "welcome_greeting", "welcome_store", "welcome_bot", "welcome_bullet",
    "info", "success", "warning", "error", "money", "product",
    "stock_title", "stock_product", "stock_price", "stock_count", "stock_shop",
    "discount_title", "discount_product", "discount_percent", "discount_regular_price",
    "discount_sale_price", "discount_duration", "discount_end", "discount_shop",
    "language_title",
    "admin_title", "admin_shop_status", "admin_referral_status", "admin_total_users",
    "payment_amount", "payment_order_id", "payment_pay_id", "payment_note",
    "payment_screenshot", "payment_reservation",
    "preorder_title", "preorder_thanks", "preorder_smile",
    "delivery_title", "delivery_product", "delivery_account", "delivery_thanks",
    "delivery_service", "delivery_support",
    "shop_open", "shop_close", "shop_maintenance",
)

_ORIGINAL_BUTTON = types.InlineKeyboardButton


def custom_message_entities(text, emoji_slots):
    """Return custom emoji entities while retaining Unicode as Telegram fallback."""
    if get_setting("custom_emoji_enabled", "off") != "on":
        return None
    entities = []
    for slot in emoji_slots:
        fallback_emoji, setting_key = slot[:2]
        occurrence = slot[2] if len(slot) > 2 else None
        emoji_id = slot[3] if len(slot) > 3 else get_setting(
            f"custom_message_emoji_{setting_key}", ""
        )
        if not emoji_id:
            continue
        starts = []
        search_from = 0
        while True:
            start = text.find(fallback_emoji, search_from)
            if start < 0:
                break
            starts.append(start)
            search_from = start + len(fallback_emoji)
        if occurrence is not None:
            starts = [starts[occurrence]] if occurrence < len(starts) else []
        for start in starts:
            # Telegram offsets are UTF-16 code units, not Python characters.
            offset = len(text[:start].encode("utf-16-le")) // 2
            length = len(fallback_emoji.encode("utf-16-le")) // 2
            entities.append(types.MessageEntity(
                type="custom_emoji", offset=offset, length=length,
                custom_emoji_id=emoji_id,
            ))
    return entities or None


def send_custom_emoji_message(bot, chat_id, html_text, emoji_slots, **kwargs):
    """Send a rich message with optional custom emojis and Unicode fallback.

    Telegram does not allow HTML parse mode and message entities together.
    When custom emoji is enabled, remove the simple HTML formatting and send
    verified custom-emoji entities; otherwise retain the existing HTML message.
    """
    plain_text = re.sub(r"</?[^>]+>", "", html_text)
    entities = custom_message_entities(plain_text, emoji_slots)
    if not entities:
        return bot.send_message(chat_id, html_text, parse_mode="HTML", **kwargs)
    return bot.send_message(chat_id, plain_text, entities=entities, parse_mode="", **kwargs)


def edit_custom_emoji_message(bot, chat_id, message_id, text, emoji_slots, fallback_parse_mode="", **kwargs):
    """Edit a message while using a custom emoji where a configured ID exists."""
    plain_text = re.sub(r"</?[^>]+>", "", text).replace("*", "").replace("`", "")
    entities = custom_message_entities(plain_text, emoji_slots)
    if not entities:
        return bot.edit_message_text(
            text, chat_id, message_id, parse_mode=fallback_parse_mode, **kwargs
        )
    return bot.edit_message_text(
        plain_text, chat_id, message_id, entities=entities, parse_mode="", **kwargs
    )


def payment_method_custom_emoji_id(method):
    """Return the existing payment-button emoji for payment instructions."""
    key = {"kpay": "kpay", "wave": "wave", "aya": "aya_pay"}.get(str(method).lower())
    return get_setting(f"custom_button_emoji_{key}", "") if key else ""


def _button_key(text, callback_data=None, url=None):
    value = str(text or "").lower()
    callback = str(callback_data or "").lower()
    admin_keys = {
        "apanel_products": "admin_products", "apanel_orders": "admin_orders",
        "apanel_users": "admin_users", "apanel_shop": "admin_shop",
        "apanel_promotion": "admin_promotion", "apanel_referral": "admin_referral",
        "apanel_customemoji": "admin_custom_emoji",
        "apanel_help_addproduct": "admin_add_product",
        "apanel_help_editproduct": "admin_edit_product",
        "apanel_help_addstock": "admin_add_stock",
        "apanel_help_setstock": "admin_set_stock",
        "apanel_help_setdiscount": "admin_discount",
        "apanel_discounts": "admin_discount",
        "apanel_removeproduct": "admin_remove_product",
        "apanel_renewproducts": "admin_renew",
        "apanel_adminorders_recent": "admin_recent_orders",
        "apanel_adminorders_userask": "admin_search_orders",
        "apanel_monthlyreport": "admin_monthly_report",
        "apanel_yearlyreport": "admin_yearly_report",
        "apanel_checkrenewals": "admin_check_renewals",
        "apanel_help_send": "admin_manual_send",
        "apanel_userlist": "admin_user_list", "apanel_activeusers": "admin_active_users",
        "apanel_help_announcement": "admin_announcement", "apanel_adminlist": "admin_list",
        "apanel_help_addadmin": "admin_add_admin", "apanel_help_removeadmin": "admin_remove_admin",
        "apanel_shop_open": "admin_open", "apanel_shop_close": "admin_close",
        "apanel_shop_maintenance": "admin_maintenance", "apanel_referral_open": "admin_start",
        "apanel_referral_paused": "admin_pause", "apanel_referral_stats": "admin_stats",
        "apanel_referral_claims": "admin_claims", "apanel_referral_guide": "admin_guide",
        "apanel_promo_addgift": "admin_add_gift", "apanel_promo_addstock": "admin_add_gift_stock",
        "apanel_promo_gifts": "admin_gift_list", "apanel_promo_pending": "admin_pending_manual",
        "apanel_promo_setup": "admin_promotion_setup", "apanel_emoji_buttons": "admin_button_setup",
        "apanel_emoji_messages": "admin_message_setup", "apanel_emoji_products": "admin_product_setup",
        "apanel_emoji_toggle": "admin_toggle",
    }
    if callback in admin_keys:
        return admin_keys[callback]
    if str(text or "").lstrip().startswith("❌"):
        return "out_of_stock"
    if "kpay" in value or "pay_kpay" in callback or "renewpay_kpay" in callback:
        return "kpay"
    if "wave" in value or "pay_wave" in callback or "renewpay_wave" in callback:
        return "wave"
    if "aya" in value or "pay_aya" in callback or "renewpay_aya" in callback:
        return "aya_pay"
    if "erc20" in value:
        return "usdt_erc20"
    if "bep20" in value:
        return "usdt_bep20"
    if "binance" in value:
        return "binance_pay"
    if "approve" in value or "approve" in callback:
        return "approve"
    if "reject" in value or "reject" in callback:
        return "reject"
    if "cancel" in value or "မပေးတော့" in value or "မယူတော့" in value:
        return "cancel"
    if "confirm" in value:
        return "confirm"
    if "review" in value or "feedback" in value:
        return "review"
    if "support" in value:
        return "support"
    if "giveaway" in value:
        return "giveaway"
    if "referral" in value or callback.startswith("ref_"):
        return "referral"
    if callback == "set_lang_my":
        return "language_my"
    if callback == "set_lang_en":
        return "language_en"
    if "language" in value or "lang" in callback:
        return "language"
    if "refresh" in value or "refresh" in callback:
        return "refresh"
    if callback == "shop":
        return "shop"
    if "back" in value or "home" in value or callback in ("home", "shop"):
        return "home" if "home" in value or callback == "home" else "back"
    if "shop" in value or callback.startswith("shop"):
        return "shop"
    if "my orders" in value or callback == "my_orders":
        return "my_orders"
    if "products" in value:
        return "products"
    if "orders" in value:
        return "orders"
    if "users" in value:
        return "users"
    if "promotion" in value or "promo_" in callback:
        return "promotion"
    if "stock" in value:
        return "stock"
    if "discount" in value:
        return "discount"
    if "admin" in value:
        return "admin"
    if "channel" in value:
        return "channel"
    if "verify" in value:
        return "verify"
    return None


def _remove_leading_emoji(text):
    # Custom emoji occupies the icon slot; remove only the old leading emoji.
    return re.sub(r"^\s*[^\w\s]+\s*", "", str(text)).strip()


def _resolve_button_style(text, callback_data="", explicit_style=None):
    """Assign Telegram colored button styles (primary=Blue/Teal, success=Green, danger=Red)."""
    if explicit_style is not None:
        return explicit_style if explicit_style in ("primary", "success", "danger") else None
    global_style = str(get_setting("button_style", "primary") or "primary").lower()
    if global_style == "off":
        return None
    cb = str(callback_data or "").lower()
    val = str(text or "").lower()
    if val.lstrip().startswith("❌") or "reject" in cb or "cancel" in cb or "delete" in cb or "remove" in cb or "close" in cb:
        return "danger"
    if "approve" in cb or "confirm" in cb or cb.startswith("walletbuy_") or cb == "daily_checkin":
        return "success"
    if global_style in ("primary", "success", "danger"):
        return global_style
    return "primary"


def custom_inline_button(text, *args, **kwargs):
    # Some URL buttons have localized labels, so their intended emoji key is
    # passed explicitly instead of trying to infer it from translated text.
    explicit_key = kwargs.pop("_emoji_key", None)
    explicit_product_id = kwargs.pop("_product_id", None)
    explicit_style = kwargs.pop("_style", kwargs.pop("style", None))
    callback_data = str(kwargs.get("callback_data") or "")
    resolved_style = _resolve_button_style(text, callback_data, explicit_style)
    if resolved_style:
        kwargs["style"] = resolved_style
    if get_setting("custom_emoji_enabled", "off") != "on":
        return _ORIGINAL_BUTTON(text, *args, **kwargs)
    callback_data = str(kwargs.get("callback_data") or "")
    key = explicit_key or _button_key(text, callback_data, kwargs.get("url"))
    # Every unavailable product uses one common custom stock-out icon.
    if key == "out_of_stock":
        emoji_id = get_setting("custom_button_emoji_out_of_stock", "")
        if emoji_id:
            kwargs["icon_custom_emoji_id"] = emoji_id
            return _ORIGINAL_BUTTON(_remove_leading_emoji(text), *args, **kwargs)
    # Product icons belong in the catalog only. Quantity buttons use
    # buy_<product_id>_<quantity> and intentionally keep their plain numbers.
    product_match = re.match(r"^buy_(\d+)$", callback_data)
    product_id = explicit_product_id
    if product_id is None and product_match:
        product_id = int(product_match.group(1))
    if product_id is not None:
        product_emoji_id = get_product_custom_emoji(int(product_id))
        if product_emoji_id:
            kwargs["icon_custom_emoji_id"] = product_emoji_id
            return _ORIGINAL_BUTTON(_remove_leading_emoji(text), *args, **kwargs)
    emoji_id = get_setting(f"custom_button_emoji_{key}", "") if key else ""
    if not emoji_id:
        return _ORIGINAL_BUTTON(text, *args, **kwargs)
    kwargs["icon_custom_emoji_id"] = emoji_id
    return _ORIGINAL_BUTTON(_remove_leading_emoji(text), *args, **kwargs)


def enable_custom_emoji_buttons():
    """Patch pyTelegramBotAPI once before handlers create their buttons."""
    if types.InlineKeyboardButton is not custom_inline_button:
        types.InlineKeyboardButton = custom_inline_button
