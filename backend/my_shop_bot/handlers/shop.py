import telebot
from config import DATABASE_NAME, MMK_PER_USD
from telebot import types
from handlers.custom_emoji import custom_inline_button
from database import (
    get_all_items, get_item_by_id, get_user_language, get_active_discounts,
    get_available_stock, get_available_stock_map, get_mmk_per_usd,
    get_shop_status, is_admin_user
)
from datetime import datetime
import pytz
import re


def format_price_for_user(price_mmk, language):
    price_mmk = float(str(price_mmk).replace(',', ''))
    if language == "en":
        price_usd = price_mmk / (get_mmk_per_usd() or MMK_PER_USD or 4500)
        return f"${price_usd:.2f}"
    return f"{int(price_mmk):,} MMK"


def is_shop_open():
    tz = pytz.timezone('Asia/Yangon')
    now = datetime.now(tz)
    current_hour = now.hour
    if 8 <= current_hour < 22:
        return True
    return False


def _detect_product_group(item_name):
    """Detect whether an item belongs to a grouped plan sub-menu."""
    text = str(item_name or "").lower()
    if ("telegram" in text or "tg " in text) and "premium" in text:
        return "tg_premium"
    if ("telegram" in text or "tg " in text) and "star" in text:
        return "tg_stars"
    if ("apple" in text or "itunes" in text) and ("gift" in text or "card" in text or "$" in text):
        return "apple_gc"
    return None


PRODUCT_ICON_MAP = (
    ("adobe", "🎨", "Adobe CC"),
    ("alight motion", "🎬", "Alight Motion"),
    ("apple music", "🎵", "Apple Music"),
    ("canva", "🎨", "Canva"),
    ("capcut", "✂️", "CapCut Pro"),
    ("chat gpt", "🤖", "ChatGPT"),
    ("chatgpt", "🤖", "ChatGPT"),
    ("claude", "✴️", "Claude Ai"),
    ("coursera", "🎓", "Coursera"),
    ("disney", "🏰", "Disney Plus"),
    ("duolingo", "🦉", "Duolingo"),
    ("express", "🛡", "Express"),
    ("gemini", "✨", "Gemini Pro"),
    ("hbo", "🎬", "HBO MAX"),
    ("hiddify", "🚀", "Hiddify"),
    ("iqiyi", "📺", "IQIYI"),
    ("jump jump", "⚡", "Jump Jump Vpn"),
    ("mail", "✉️", "Mail"),
    ("meitu", "🌸", "Meitu"),
    ("microsoft 365", "💼", "Microsoft 365"),
    ("netflix", "🎬", "Netflix Premium"),
    ("outline", "🟢", None),
    ("picsart", "🎨", "Picsart"),
    ("prime video", "📺", "Prime Video"),
    ("spotify", "🎧", "Spotify"),
    ("grok", "🏴", "Super Grok"),
    ("surfshark", "🦈", "Surfshark"),
    ("telegram account", "✈️", "Telegram Account"),
    ("telegram channel", "🌟", "TELEGRAM CHANNEL / GR..."),
    ("telegram sms", "📲", "Telegram SMS Fees"),
    ("tiktok", "🎵", "TikTok Promote"),
    ("crunchyroll", "🍥", "Crunchyroll"),
    ("cursor", "💻", "Cursor Pro"),
    ("freepik", "🖼", "Freepik"),
    ("grammarly", "✍️", "Grammarly"),
    ("linkedin", "💼", "LinkedIn"),
    ("nordvpn", "🛡", "NordVPN"),
    ("notion", "📓", "Notion Plus"),
    ("perplexity", "🔍", "Perplexity AI"),
    ("tradingview", "📈", "TradingView"),
    ("wink", "😉", "Wink"),
    ("youtube", "▶️", "YouTube Premium"),
    ("zoom", "📹", "Zoom"),
)


def _compact_grid_label(item_name):
    """Return a clean, compact 2-column button label like the reference screenshot."""
    raw = str(item_name or "").strip().lstrip("\u200e").strip()
    lower = raw.lower()
    if "outline" in lower:
        if "unlimited" in lower:
            return "🟢 Outline - Unlimited Data"
        return "🟢 Outline"
    if "gemini" in lower:
        m = re.search(r"(\d+\s*(?:months?|m|year|yr))", lower)
        suffix = f" ({m.group(1).title()})" if m and "18" not in m.group(1) else ""
        return f"✨ Gemini Pro{suffix}"
    if "chat gpt" in lower or "chatgpt" in lower:
        if "25d" in lower:
            return "🤖 ChatGPT (25D)"
        if "1d" in lower:
            return "🤖 ChatGPT (1D)"
        return "🤖 ChatGPT"
    for keyword, emoji, short_title in PRODUCT_ICON_MAP:
        if keyword in lower and short_title:
            return f"{emoji} {short_title}"
    # Fallback: strip duration/warranty suffixes for a clean 2-col button
    cleaned = re.sub(r"\s*\([^)]*\)", "", raw).strip()
    cleaned = re.sub(r"\s+1\s*(?:Year|Month|M|Y)\b.*", "", cleaned, flags=re.I).strip()
    return f"📦 {cleaned[:22]}"


def _short_plan_label(item_name, group_key):
    """Make plan button labels clean inside the sub-menu."""
    name = str(item_name or "").strip()
    if group_key == "tg_premium":
        for prefix in ("Telegram Premium", "TG Premium"):
            if name.lower().startswith(prefix.lower()):
                sub = name[len(prefix):].strip(" -—()[]")
                if sub:
                    return f"🎁 {sub}"
        return f"🎁 {name}"
    if group_key == "tg_stars":
        for prefix in ("Telegram Stars", "TG Stars"):
            if name.lower().startswith(prefix.lower()):
                sub = name[len(prefix):].strip(" -—()[]")
                if sub:
                    return f"🌟 {sub}"
        return f"🌟 {name}"
    if group_key == "apple_gc":
        return f"🍎 {name}"
    return f"📦 {name}"


GROUP_CONFIG = {
    "tg_premium": {
        "btn_my": "🎁 Telegram Premium",
        "btn_en": "🎁 Telegram Premium",
        "title_my": "🎁 *Telegram Premium Plans*\n\nဝယ်ယူလိုသည့် သက်တမ်း (Plan) ကို ရွေးချယ်ပါ -",
        "title_en": "🎁 *Telegram Premium Plans*\n\nPlease select the subscription duration:",
        "hide_stock": True,
    },
    "tg_stars": {
        "btn_my": "🌟 Telegram Star",
        "btn_en": "🌟 Telegram Star",
        "title_my": "🌟 *Telegram Stars Packages*\n\nဝယ်ယူလိုသည့် Stars ပမာဏကို ရွေးချယ်ပါ -",
        "title_en": "🌟 *Telegram Stars Packages*\n\nPlease select the Stars package you want to buy:",
        "hide_stock": True,
    },
    "apple_gc": {
        "btn_my": "🍎 Apple Gift Card (US)",
        "btn_en": "🍎 Apple Gift Card (US)",
        "title_my": "🍎 *Apple Gift Card (US Region)*\n\nဝယ်ယူလိုသည့် Gift Card တန်ဖိုးကို ရွေးချယ်ပါ -",
        "title_en": "🍎 *Apple Gift Card (US Region)*\n\nPlease select the Gift Card denomination:",
        "hide_stock": False,
    },
}


def build_group_plan_catalog(user_id, group_key):
    items = get_all_items()
    active_discounts = {row[0]: row for row in get_active_discounts()}
    available_stock_map = get_available_stock_map()
    language = get_user_language(user_id) or "my"
    cfg = GROUP_CONFIG.get(group_key, GROUP_CONFIG["tg_premium"])

    group_items = [item for item in items if _detect_product_group(item[1]) == group_key]
    group_items.sort(key=lambda x: float(x[3] or 0))

    markup = types.InlineKeyboardMarkup(row_width=2)
    plan_buttons = []
    for item in group_items:
        item_id = item[0]
        item_name = item[1]
        price = item[3]
        stock = available_stock_map.get(item_id, item[4] if len(item) > 4 else 0)
        formatted_price = format_price_for_user(price, language)
        discount = active_discounts.get(item_id)
        discount_label = f" 🔥-{discount[4]:g}%" if discount else ""
        plan_label = _short_plan_label(item_name, group_key)

        if stock > 0:
            btn_text = f"{plan_label}{discount_label} • {formatted_price}"
            btn_style = "primary"
        else:
            out_label = "Out" if language == "en" else "ကုန်"
            btn_text = f"❌ {plan_label} ({out_label})"
            btn_style = "danger"

        plan_buttons.append(
            custom_inline_button(
                btn_text,
                callback_data=f"buy_{item_id}",
                _product_id=item_id,
                _style=btn_style,
            )
        )

    for idx in range(0, len(plan_buttons), 2):
        markup.row(*plan_buttons[idx:idx + 2])

    back_label = "⬅️ Back to Shop" if language == "en" else "⬅️ Shop သို့ပြန်မည်"
    markup.add(custom_inline_button(back_label, callback_data="shop_back", _style="primary"))
    text = cfg["title_en"] if language == "en" else cfg["title_my"]
    return text, markup


def build_shop_catalog(user_id):
    items = get_all_items()
    active_discounts = {row[0]: row for row in get_active_discounts()}
    available_stock_map = get_available_stock_map()
    markup = types.InlineKeyboardMarkup(row_width=2)
    language = get_user_language(user_id) or "my"

    if not items:
        text = (
            "🛍️ No products are available right now."
            if language == "en"
            else "🛍️ လက်ရှိတွင် ရောင်းချရန် ပစ္စည်းမရှိသေးပါ။"
        )
        refresh_label = "🔄 Refresh" if language == "en" else "🔄 ပြန်စစ်မည်"
        markup.row(
            custom_inline_button(refresh_label, callback_data='shop_refresh'),
            custom_inline_button("🏠 Back to Home", callback_data='home')
        )
        return text, markup

    present_groups = set()
    standalone_entries = []

    for item in items:
        try:
            item_id = item[0]
            item_name = item[1]
            g = _detect_product_group(item_name)
            if g is not None:
                present_groups.add(g)
                continue
            stock = available_stock_map.get(item_id, item[4] if len(item) > 4 else 0)
            discount = active_discounts.get(item_id)
            discount_badge = f" 🔥-{discount[4]:g}%" if discount else ""
            label = _compact_grid_label(item_name) + discount_badge
            if stock <= 0:
                label = "❌ " + _compact_grid_label(item_name)
            sort_key = re.sub(r"^[^A-Za-z0-9]+", "", label).lower()
            standalone_entries.append((
                sort_key,
                custom_inline_button(
                    label,
                    callback_data=f"buy_{item_id}",
                    _product_id=item_id,
                    _style="primary" if stock > 0 else "danger",
                ),
            ))
        except Exception as e:
            print(f"Error rendering item: {e}")
            continue

    # Add grouped category buttons into the same alphabetical 2-column grid
    for group_key in ("tg_premium", "tg_stars", "apple_gc"):
        if group_key in present_groups:
            cfg = GROUP_CONFIG[group_key]
            btn_label = cfg["btn_en"] if language == "en" else cfg["btn_my"]
            sort_key = re.sub(r"^[^A-Za-z0-9]+", "", btn_label).lower()
            standalone_entries.append((
                sort_key,
                custom_inline_button(
                    btn_label,
                    callback_data=f"shopgroup_{group_key}",
                    _style="primary",
                ),
            ))

    standalone_entries.sort(key=lambda x: x[0])
    grid_buttons = [entry[1] for entry in standalone_entries]
    for idx in range(0, len(grid_buttons), 2):
        markup.row(*grid_buttons[idx:idx + 2])

    refresh_label = "🔄 Refresh" if language == "en" else "🔄 ပြန်စစ်မည်"
    markup.row(
        custom_inline_button(refresh_label, callback_data='shop_refresh', _style="primary"),
        custom_inline_button("🏠 Back to Home", callback_data='home', _style="primary")
    )
    text = (
        "🛍️ *ENI Premium Store — Product Catalog*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Please tap any product below to view plans, details, and prices:"
        if language == "en"
        else "🛍️ *ENI Premium Store — Product Catalog*\n"
             "━━━━━━━━━━━━━━━━━━━━━━\n"
             "ဝယ်ယူလိုသည့် ပစ္စည်းကို နှိပ်၍ ဈေးနှုန်းနှင့် အသေးစိတ်အချက်အလက်များကို ကြည့်ရှုနိုင်ပါသည် -"
    )
    return text, markup


def show_shop_catalog(user_id, bot):
    text, markup = build_shop_catalog(user_id)
    bot.send_message(
        user_id,
        text,
        reply_markup=markup,
        parse_mode='Markdown'
    )


def init_shop_handlers(bot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith('shopgroup_'))
    def shop_group_callback(call):
        group_key = call.data.replace('shopgroup_', '', 1)
        if group_key not in GROUP_CONFIG:
            bot.answer_callback_query(call.id, "Invalid category.")
            return
        bot.answer_callback_query(call.id)
        text, markup = build_group_plan_catalog(call.from_user.id, group_key)
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )

    @bot.callback_query_handler(func=lambda call: call.data == 'shop_back')
    def shop_back_callback(call):
        bot.answer_callback_query(call.id)
        text, markup = build_shop_catalog(call.from_user.id)
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode='Markdown'
        )

    @bot.callback_query_handler(func=lambda call: call.data == 'shop')
    def shop_callback(call):
        status = get_shop_status()
        language = get_user_language(call.from_user.id) or "my"

        if status == 'maintenance' and not is_admin_user(call.from_user.id):
            if language == "en":
                bot.answer_callback_query(call.id, "Bot is under maintenance.", show_alert=True)
                bot.edit_message_text(
                    "<b>Bot is Under Maintenance</b>\n\nPlease try again later.",
                    call.message.chat.id, call.message.message_id, parse_mode='HTML'
                )
                return
            bot.answer_callback_query(call.id, "🛠 Bot ကို ပြုပြင်နေပါသည်၊၊", show_alert=True)
            bot.edit_message_text(
                "🛠 <b>Bot is Under Maintenance</b>\n\nခေတ္တပြုပြင်နေပါသဖြင့် မည်သည့် Feature ကိုမျှ အသုံးပြု၍ မရနိုင်သေးပါ၊၊",
                call.message.chat.id, call.message.message_id, parse_mode='HTML'
            )
            return

        if status == 'close':
            if language == "en":
                bot.answer_callback_query(call.id, "Shop is closed today.", show_alert=True)
                bot.edit_message_text(
                    "<b>Shop is Closed Today</b>\n\nPlease come back later. Thank you for your support.",
                    call.message.chat.id, call.message.message_id, parse_mode='HTML'
                )
                return
            admin_closed_text = (
                "🛑 <b>Shop is Closed Today</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "ယနေ့ ဆိုင်ပိတ်ထားပါတယ်ခင်ဗျာ၊၊\n\n"
                "နောက်ရက်မှ ပြန်လည် အားပေးပါရန် ဖိတ်ခေါ်အပ်ပါတယ်၊၊ ကျေးဇူးတင်ပါတယ်ဗျ၊၊ 🙏"
            )
            bot.answer_callback_query(call.id, "ယနေ့ ဆိုင်ပိတ်ပါသည်", show_alert=True)
            bot.edit_message_text(admin_closed_text, call.message.chat.id, call.message.message_id, parse_mode='HTML')
            return

        if not is_shop_open():
            if language == "en":
                markup = types.InlineKeyboardMarkup()
                markup.add(custom_inline_button("Continue to Pre-Order", callback_data="force_open_catalog", _style="success"))
                markup.add(custom_inline_button("Back to Home", callback_data='home', _style="primary"))
                bot.answer_callback_query(call.id, "Shop is closed, but pre-order is available.", show_alert=True)
                bot.edit_message_text(
                    "<b>Shop is Currently Closed (Pre-Order Available)</b>\n\n"
                    "Normal auto-delivery is paused during admin rest time.\n\n"
                    "<b>Shop hours:</b> 08:00 AM - 10:00 PM\n\n"
                    "You can still place a pre-order now. Admin will review and deliver your product when the shop opens.",
                    call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML'
                )
                return
            time_closed_text = (
                "🌙 <b>Shop is Currently Closed (Pre-Order Available)</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "ယခုအချိန်သည် Admin အနားယူချိန် ဖြစ်ပါသဖြင့် ပုံမှန် Auto-Delivery စနစ်ကို ခေတ္တပိတ်ထားပါသည်၊၊\n\n"
                "🕒 <b>ဆိုင်ဖွင့်ချိန်:</b> 08:00 AM - 10:00 PM\n\n"
                "💡 <b>ဒါပေမဲ့ စိတ်မပူပါနဲ့ခင်ဗျာ!</b>\n"
                "သင်အခုပဲ <b>Pre-Order (ကြိုတင်မှာယူခြင်း)</b> စနစ်ဖြင့် ငွေပေးချေပြီး အော်ဒါတင်ထားနိုင်ပါတယ်၊၊ "
                "မနက်ဖြန် ဆိုင်ဖွင့်တာနဲ့ Admin ဘက်က အကောင့်များကို ဦးစားပေးစနစ်ဖြင့် ချက်ချင်း ပို့ဆောင်ပေးသွားမှာ ဖြစ်ပါသည်ဗျာ၊၊ 🙏\n\n"
                "👇 ကြိုတင်မှာယူလိုပါက အောက်ကခလုတ်ကို နှိပ်ပြီး ဆက်သွားနိုင်ပါတယ်-"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(custom_inline_button("📝 Pre-Order တင်ရန် ဆက်သွားမည်", callback_data="force_open_catalog", _style="success"))
            markup.add(custom_inline_button("🏠 Back to Home", callback_data='home', _style="primary"))
            bot.answer_callback_query(call.id, "ဆိုင်ပိတ်ချိန်ဖြစ်သော်လည်း Pre-Order တင်နိုင်ပါသည်", show_alert=True)
            bot.edit_message_text(time_closed_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
            return

        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        show_shop_catalog(call.from_user.id, bot)

    @bot.callback_query_handler(func=lambda call: call.data == 'force_open_catalog')
    def force_catalog_callback(call):
        bot.answer_callback_query(call.id)
        bot.delete_message(chat_id=call.message.chat.id, message_id=call.message.message_id)
        show_shop_catalog(call.from_user.id, bot)

    @bot.callback_query_handler(func=lambda call: call.data == 'shop_refresh')
    def refresh_catalog_callback(call):
        language = get_user_language(call.from_user.id) or "my"
        text, markup = build_shop_catalog(call.from_user.id)
        try:
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            notice = "Product list updated." if language == "en" else "Product list ကို refresh လုပ်ပြီးပါပြီ။"
            bot.answer_callback_query(call.id, notice)
        except Exception as error:
            if "message is not modified" in str(error).lower():
                notice = "Already up to date." if language == "en" else "နောက်ဆုံးအခြေအနေဖြစ်ပြီးသားပါ။"
                bot.answer_callback_query(call.id, notice)
                return
            print(f"Shop catalog refresh failed: {error}")
            notice = "Refresh failed. Please try again." if language == "en" else "Refresh မအောင်မြင်ပါ။ ပြန်စမ်းကြည့်ပါ။"
            bot.answer_callback_query(call.id, notice, show_alert=True)
