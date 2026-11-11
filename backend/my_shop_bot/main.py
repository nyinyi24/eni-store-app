import telebot
from telebot import apihelper
import sqlite3
import html
import threading
import time
import re
import os
import tempfile
from config import DATABASE_NAME, API_TOKEN, ADMIN_ID, MMK_PER_USD, YOUR_CHANNEL_ID
from database import (
    init_db, set_shop_status, get_shop_status, get_user_count, get_users_for_admin,
    get_orders_needing_renewal_notice, mark_renewal_notice_sent,
    get_recently_expired_orders_missing_user_notice,
    get_orders_needing_admin_expiry_notice, mark_admin_expiry_notice_sent,
    get_monthly_sales_report, get_yearly_sales_report,
    add_product, add_item_stock_accounts,
    update_product, set_product_stock, get_item_by_id, get_item_by_name, get_all_items,
    get_product_removal_preview, remove_product,
    set_product_renewable,
    get_all_user_ids, get_referral_status, set_referral_status, get_referral_stats,
    get_pending_referral_rewards, update_referral_reward_status,
    get_valid_referral_count, get_referral_required_count, get_referral_reward_text,
    get_recent_orders_for_admin, get_orders_by_user_for_admin, get_pending_orders_for_admin, get_user_language,
    get_order_renewal_option,
    record_user_activity, get_active_users_for_admin, get_user_activity_summary,
    is_admin_user as db_is_admin_user, is_master_admin, add_admin_user,
    remove_admin_user, get_admin_users, get_all_admin_ids,
    set_product_discount, get_active_discounts, cancel_product_discount,
    expire_product_discounts, expire_stock_reservations,
    is_outline_renewable_product,
    get_setting, set_setting,
    get_promotion_config, set_promotion_config, add_promotion_gift,
    get_promotion_gifts, set_promotion_gift_active, add_promotion_gift_stock,
    get_promotion_gift_stock_count, get_pending_promotion_claims,
    set_product_custom_emoji, get_product_custom_emoji, get_db_connection,
    mark_user_inactive, generate_coupons, get_active_coupons, assign_coupon_to_user, get_coupon_details,
    get_order_details, update_order_delivery, update_order_status,
    claim_stock_reservation_for_processing, complete_stock_reservation, mark_payment_submission_status,
    get_unsold_stock_rows, delete_unsold_stock_row, get_mmk_per_usd, set_mmk_per_usd, add_gw_item,
    get_outline_orders_map, get_expiring_and_expired_orders_for_admin, yangon_now
)
from outline_api import suspend_access_key, delete_access_key, get_server_status, get_all_keys_with_usage
from handlers.start import init_start_handlers, show_home_menu
from handlers.shop import init_shop_handlers
from handlers.giveaway import init_giveaway_handlers
from handlers.promotion import init_promotion_handlers, send_promotion_gift_choice
from handlers.custom_emoji import (
    BUTTON_EMOJI_KEYS, MESSAGE_EMOJI_KEYS, custom_inline_button,
    send_custom_emoji_message, edit_custom_emoji_message,
)

# 🚨 ပြင်ဆင်ချက်: payment.py ထဲက init_all_handlers ကို လှမ်းယူပါတယ်
from handlers.payment import init_all_handlers, send_delivery_message, publish_sell_proof
from handlers.tools import init_extra_tool_handlers, notify_waitlist_users

ACTIVITY_WRITE_INTERVAL_SECONDS = 60
_activity_cache = {}
_activity_cache_lock = threading.Lock()


def should_record_activity(user_id):
    """Avoid a database write for every button tap from the same user."""
    now = time.monotonic()
    with _activity_cache_lock:
        previous = _activity_cache.get(user_id, 0)
        if now - previous < ACTIVITY_WRITE_INTERVAL_SECONDS:
            return False
        _activity_cache[user_id] = now
        # Keep the in-memory cache bounded during very long bot runtimes.
        if len(_activity_cache) > 10_000:
            cutoff = now - (ACTIVITY_WRITE_INTERVAL_SECONDS * 2)
            for cached_user, seen_at in list(_activity_cache.items()):
                if seen_at < cutoff:
                    _activity_cache.pop(cached_user, None)
        return True


def is_bot_unreachable_error(error):
    error_text = str(error).lower()
    return getattr(error, "error_code", None) == 403 or any(message in error_text for message in (
        "bot was blocked by the user", "user is deactivated", "chat not found",
    ))


def announcement_custom_emoji_entities(message, announcement_text):
    """Carry custom emoji IDs from the admin's command into the broadcast.

    The emoji is selected by the admin in Telegram; no fixed emoji ID or
    message template is stored in the bot.
    """
    command_prefix = message.text[:message.text.find(announcement_text)]
    prefix_units = len(command_prefix.encode("utf-16-le")) // 2
    announcement_units = len(announcement_text.encode("utf-16-le")) // 2
    entities = []
    for entity in (getattr(message, "entities", None) or []):
        if getattr(entity, "type", "") != "custom_emoji":
            continue
        start = int(entity.offset) - prefix_units
        end = start + int(entity.length)
        if start < 0 or end > announcement_units:
            continue
        entities.append(telebot.types.MessageEntity(
            type="custom_emoji", offset=start, length=int(entity.length),
            custom_emoji_id=entity.custom_emoji_id,
        ))
    return entities


def send_announcement_message(chat_id, text, custom_emoji_entities):
    if custom_emoji_entities:
        return bot.send_message(chat_id, text, entities=custom_emoji_entities, parse_mode="")
    return bot.send_message(chat_id, text, parse_mode="HTML")

def track_user_activity(bot_instance, update):
    try:
        user = getattr(update, "from_user", None)
        if not user or getattr(user, "is_bot", False):
            return
        if not should_record_activity(user.id):
            return

        callback_data = getattr(update, "data", None)
        if callback_data is not None:
            action = f"button:{str(callback_data)[:100]}"
        else:
            text = (getattr(update, "text", None) or "").strip()
            if text.startswith("/"):
                action = f"command:{text.split()[0][:100]}"
            else:
                content_type = getattr(update, "content_type", None) or "unknown"
                action = f"message:{content_type}"

        record_user_activity(
            user.id,
            action,
            username=getattr(user, "username", None),
            first_name=getattr(user, "first_name", None),
            last_name=getattr(user, "last_name", None),
        )
    except Exception as error:
        print(f"User activity middleware error: {error}")

# ၁။ Bot Initialize လုပ်ခြင်း
apihelper.ENABLE_MIDDLEWARE = True
bot = telebot.TeleBot(
    API_TOKEN,
    parse_mode='HTML',
    suppress_middleware_excepions=True,
)
pending_stock_broadcasts = {}
pending_discount_broadcasts = {}
pending_coupon_actions = {}

# ၂။ Database Initialize လုပ်ခြင်း
init_db()
bot.register_middleware_handler(
    track_user_activity,
    update_types=['message', 'callback_query']
)

# ၃။ Handler များ Register လုပ်ခြင်း
init_start_handlers(bot)
init_shop_handlers(bot)
init_giveaway_handlers(bot)
init_promotion_handlers(bot)

# 🌟 ပြင်ဆင်ချက်: Payment, Review, Admin Buttons အားလုံး တစ်ခါတည်း အလုပ်လုပ်စေရန် နှိုးလိုက်ခြင်း
init_all_handlers(bot)
init_extra_tool_handlers(bot)

def format_mmk(amount):
    return f"{int(float(amount)):,} MMK"

def parse_discount_duration(value):
    match = re.fullmatch(r"\s*(\d+)\s*([dhm]?)\s*", value.lower())
    if not match:
        return None
    amount = int(match.group(1))
    if amount <= 0:
        return None
    unit = match.group(2) or "d"
    return amount * {"d": 86400, "h": 3600, "m": 60}[unit]

def format_discount_duration(seconds, language="my"):
    if seconds % 86400 == 0:
        value, unit_en, unit_my = seconds // 86400, "day(s)", "ရက်"
    elif seconds % 3600 == 0:
        value, unit_en, unit_my = seconds // 3600, "hour(s)", "နာရီ"
    else:
        value, unit_en, unit_my = seconds // 60, "minute(s)", "မိနစ်"
    return f"{value} {unit_en}" if language == "en" else f"{value} {unit_my}"

def build_discount_announcement(discount, duration_seconds, language):
    name = html.escape(str(discount["name"]))
    percent = f'{discount["discount_percent"]:g}'
    old_price = discount["original_price"]
    new_price = discount["discounted_price"]
    end_time = html.escape(discount["ends_at"])
    if language == "en":
        old_usd = old_price / MMK_PER_USD if MMK_PER_USD else 0
        new_usd = new_price / MMK_PER_USD if MMK_PER_USD else 0
        return (
            "🔥 <b>LIMITED-TIME DISCOUNT!</b> 🔥\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>{name}</b>\n"
            f"🏷 <b>{percent}% OFF</b>\n"
            f"💵 Regular price: <s>${old_usd:.2f}</s>\n"
            f"✨ Sale price: <b>${new_usd:.2f}</b>\n\n"
            f"⏳ Offer duration: <b>{format_discount_duration(duration_seconds, 'en')}</b>\n"
            f"📅 Ends at: <b>{end_time}</b> (Myanmar Time)\n\n"
            "🛒 Open the Shop menu and grab the offer before it ends!"
        )
    return (
        "🔥 <b>အချိန်ကန့်သတ် DISCOUNT အစီအစဉ်!</b> 🔥\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>{name}</b>\n"
        f"🏷 <b>{percent}% လျှော့ဈေး</b>\n"
        f"💰 မူလဈေး: <s>{format_mmk(old_price)}</s>\n"
        f"✨ Discount ဈေး: <b>{format_mmk(new_price)}</b>\n\n"
        f"⏳ သက်တမ်း: <b>{format_discount_duration(duration_seconds)}</b>\n"
        f"📅 ကုန်ဆုံးချိန်: <b>{end_time}</b> (မြန်မာစံတော်ချိန်)\n\n"
        "🛒 အချိန်မကုန်မီ Bot ရဲ့ Shop Menu မှာ ဝယ်ယူနိုင်ပါပြီခင်ဗျာ။"
    )

def broadcast_discount_announcement(discount, duration_seconds):
    product_emoji_id = get_product_custom_emoji(discount["item_id"])
    product_slot = ("📦", "discount_product")
    if product_emoji_id:
        product_slot = (*product_slot, 0, product_emoji_id)

    def worker():
        sent_count = 0
        failed_count = 0
        texts = {
            "my": build_discount_announcement(discount, duration_seconds, "my"),
            "en": build_discount_announcement(discount, duration_seconds, "en"),
        }
        for user_id in get_all_user_ids():
            try:
                language = get_user_language(user_id) or "my"
                discount_text = texts["en" if language == "en" else "my"]
                send_custom_emoji_message(
                    bot, user_id, discount_text,
                    (
                        ("🔥", "discount_title"),
                        product_slot,
                        ("🏷", "discount_percent"),
                        ("💰", "discount_regular_price"),
                        ("✨", "discount_sale_price"),
                        ("⏳", "discount_duration"),
                        ("📅", "discount_end"),
                        ("🛒", "discount_shop"),
                    )
                )
                sent_count += 1
                time.sleep(0.04)
            except Exception as err:
                failed_count += 1
                if is_bot_unreachable_error(err):
                    mark_user_inactive(user_id)
        for admin_id in get_all_admin_ids():
            try:
                bot.send_message(
                    admin_id,
                    f"✅ <b>Discount announcement finished.</b>\n\nSent: <b>{sent_count}</b>\nFailed: <b>{failed_count}</b>",
                    parse_mode="HTML"
                )
            except Exception:
                pass
    threading.Thread(target=worker, daemon=True).start()

def ask_discount_broadcast_confirmation(message, discount, duration_seconds):
    broadcast_id = f"{message.message_id}_{int(time.time())}"
    pending_discount_broadcasts[broadcast_id] = (discount, duration_seconds)
    my_preview = build_discount_announcement(discount, duration_seconds, "my")
    en_preview = build_discount_announcement(discount, duration_seconds, "en")
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        custom_inline_button(
            "✅ Announcement ပို့မယ်",
            callback_data=f"discountcast_send_{broadcast_id}"
        ),
        custom_inline_button(
            "❌ မပို့တော့ပါ",
            callback_data=f"discountcast_skip_{broadcast_id}"
        )
    )
    bot.send_message(
        message.chat.id,
        "✅ <b>Discount စတင်ပြီးပါပြီ။</b>\n"
        "အောက်က Announcement Text ကို user တွေဆီ ပို့မလား စစ်ဆေးအတည်ပြုပါ။\n\n"
        "🇲🇲 <b>Myanmar Preview</b>\n"
        f"{my_preview}\n\n"
        "🇬🇧 <b>English Preview</b>\n"
        f"{en_preview}",
        reply_markup=markup,
        parse_mode="HTML"
    )

def build_stock_notification_text(product_name, price=None, stock=None, is_new=False):
    title = "✨ <b>Product အသစ်ရောက်ပါပြီ!</b>" if is_new else "📦 <b>Stock ပြန်ရပါပြီ!</b>"
    lines = [
        title,
        "",
        f"📦 <b>{html.escape(str(product_name))}</b>"
    ]
    if price is not None:
        lines.append(f"💰 <b>စျေးနှုန်း:</b> {format_mmk(price)}")
    if stock is not None:
        lines.append(f"📊 <b>Stock:</b> {int(stock)} ခု")
    lines.extend([
        "",
        "🛒 Bot ထဲက Shop Menu မှာ ဝင်ကြည့်ပြီး ဝယ်ယူနိုင်ပါပြီခင်ဗျာ။"
    ])
    return "\n".join(lines)


def stock_notification_emojis(is_new, product_emoji_id=""):
    """Use the catalog icon for this product; fall back to stock_product."""
    product_occurrence = 0 if is_new else 1
    product_slot = ("📦", "stock_product", product_occurrence)
    if product_emoji_id:
        product_slot = (*product_slot, product_emoji_id)
    return (
        ("✨", "stock_title") if is_new else ("📦", "stock_title", 0),
        product_slot,
        ("💰", "stock_price"),
        ("📊", "stock_count"),
        ("🛒", "stock_shop"),
    )

def ask_stock_broadcast_confirmation(message, product_name, price=None, stock=None, is_new=False):
    broadcast_id = f"{message.message_id}_{int(time.time())}"
    product = get_item_by_name(product_name)
    product_emoji_id = get_product_custom_emoji(product[0]) if product else ""
    notification_text = build_stock_notification_text(
        product_name,
        price=price,
        stock=stock,
        is_new=is_new
    )
    pending_stock_broadcasts[broadcast_id] = (
        notification_text,
        stock_notification_emojis(is_new, product_emoji_id),
        product[0] if product else None,
    )
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(
        custom_inline_button("✅ Users ဆီ Noti ပို့မယ်", callback_data=f"stockcast_send_{broadcast_id}"),
        custom_inline_button("❌ မပို့တော့ပါ", callback_data=f"stockcast_skip_{broadcast_id}")
    )
    bot.send_message(
        message.chat.id,
        (
            "📣 <b>Users အားလုံးဆီ notification ပို့မလား?</b>\n\n"
            f"Product: <b>{html.escape(str(product_name))}</b>"
        ),
        reply_markup=markup,
        parse_mode='HTML'
    )

def send_user_renewal_notice(bot, order, already_expired=False):
    order_id, user_id, item_name, timestamp, order_code, expiry_date, item_id, outline_key_id = order
    safe_item_name = html.escape(str(item_name))
    safe_expiry_date = html.escape(str(expiry_date or "-"))
    language = get_user_language(user_id) or "my"
    markup = telebot.types.InlineKeyboardMarkup()
    renew_option = get_order_renewal_option(order_id, user_id)
    can_renew_existing = bool(
        renew_option and is_outline_renewable_product(renew_option.get("item_name"))
    )

    if already_expired and language == "en":
        text = (
            "⏰ <b>Your Premium Account Has Expired</b>\n\n"
            f"The 📦 <b>{safe_item_name}</b> account you purchased from "
            f"ENI Premium Store expired on 📅 <b>{safe_expiry_date}</b>.\n\n"
            "You can renew it now to continue using the service. 🙏✨"
        )
        existing_renew_label = "🔄 Renew Existing Key"
        new_key_label = "🆕 Buy New Key"
    elif already_expired:
        text = (
            "⏰ <b>Premium Account သက်တမ်းကုန်ဆုံးသွားပါပြီ</b>\n\n"
            f"လူကြီးမင်း ENI Premium Store မှ ဝယ်ယူထားသော 📦 <b>{safe_item_name}</b> အကောင့်သည် "
            f"📅 <b>{safe_expiry_date}</b> တွင် သက်တမ်းကုန်ဆုံးသွားပါပြီ။\n\n"
            "ဆက်လက်အသုံးပြုလိုပါက အောက်ပါ Renew Button မှတစ်ဆင့် ပြန်လည်ဝယ်ယူနိုင်ပါသည်ခင်ဗျာ။ 🙏✨"
        )
        existing_renew_label = "🔄 လက်ရှိ Key ကို Renew မယ်"
        new_key_label = "🆕 Key အသစ်ဝယ်မယ်"
    elif language == "en":
        text = (
            "⏰ <b>Your Premium Account Is Expiring Soon</b>\n\n"
            f"The 📦 <b>{safe_item_name}</b> account you purchased from "
            f"ENI Premium Store will expire within <b>3 days</b> "
            f"(📅 {safe_expiry_date}).\n\n"
            "Renew now to continue using it without interruption. 🙏✨"
        )
        existing_renew_label = "🔄 Renew Existing Key"
        new_key_label = "🆕 Buy New Key"
    else:
        text = (
            "⏰ <b>Premium Account သက်တမ်းကုန်တော့မည်ဖြစ်ပါသည်</b>\n\n"
            f"လူကြီးမင်း ENI Premium Store မှ ဝယ်ယူအားပေးထားသော 📦 <b>{safe_item_name}</b> အကောင့်သည် "
            f"<b>၃ ရက်အတွင်း</b> (📅 {safe_expiry_date}) သက်တမ်းကုန်ဆုံးတော့မည် ဖြစ်ပါသည်ဗျာ။\n\n"
            "သက်တမ်းမပြတ် ဆက်လက်အသုံးပြုနိုင်ရန် အောက်ပါ Renew Button မှတစ်ဆင့် "
            "ပြန်လည်ဝယ်ယူနိုင်ပါသည်ခင်ဗျာ။ 🙏✨"
        )
        existing_renew_label = "🔄 လက်ရှိ Key ကို Renew မယ်"
        new_key_label = "🆕 Key အသစ်ဝယ်မယ်"

    if can_renew_existing:
        markup.add(
            custom_inline_button(
                existing_renew_label,
                callback_data=f"renew_existing_{order_id}",
            )
        )
    if item_id is not None:
        markup.add(custom_inline_button(new_key_label, callback_data=f"buy_{item_id}"))
    bot.send_message(
        user_id,
        text,
        parse_mode='HTML',
        reply_markup=markup if can_renew_existing or item_id is not None else None,
    )
    mark_renewal_notice_sent(order_id)

def check_renewal_notifications(bot):
    upcoming_orders = get_orders_needing_renewal_notice(days_before=3)
    missed_orders = get_recently_expired_orders_missing_user_notice(grace_days=7)
    sent_count = 0
    failed_count = 0
    for order, already_expired in (
        [(order, False) for order in upcoming_orders]
        + [(order, True) for order in missed_orders]
    ):
        order_id = order[0]
        try:
            send_user_renewal_notice(bot, order, already_expired)
            sent_count += 1
        except Exception as e:
            failed_count += 1
            print(f"Renewal notification failed for order {order_id}: {e}")
    return sent_count, failed_count

def start_renewal_notifier(bot):
    def worker():
        while True:
            try:
                check_renewal_notifications(bot)
            except Exception as e:
                print(f"Renewal notifier error: {e}")
            time.sleep(30 * 60)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()

def check_admin_expiry_notifications(bot):
    orders = get_orders_needing_admin_expiry_notice()
    sent_orders = 0
    failed_orders = 0
    for order_id, user_id, username, first_name, last_name, item_name, quantity, order_code, expiry_date, outline_key_id in orders:
        safe_username = html.escape(f"@{username}" if username else "မရှိပါ")
        full_name = " ".join(part for part in (first_name, last_name) if part).strip() or "မရှိပါ"
        safe_name = html.escape(full_name)
        safe_item = html.escape(str(item_name or "-"))
        safe_order_code = html.escape(str(order_code or order_id))
        safe_expiry = html.escape(str(expiry_date or "-"))
        outline_text = ""
        if outline_key_id:
            outline_text = (
                f"🔐 <b>Outline Key:</b> <code>{html.escape(str(outline_key_id))}</code>\n"
                "ℹ️ Outline Manager ထဲမှာ key သက်တမ်း/data ကို admin ဘက်က manually စစ်ပေးပါ။\n\n"
            )
        text = (
            "⏰ <b>Customer Product သက်တမ်းကုန်ဆုံးပါပြီ</b>\n"
            "━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>အမည်:</b> {safe_name}\n"
            f"🆔 <b>User ID:</b> <code>{user_id}</code>\n"
            f"🔗 <b>Username:</b> {safe_username}\n\n"
            f"📦 <b>Product:</b> {safe_item}\n"
            f"🔢 <b>Quantity:</b> {int(quantity or 1)}\n"
            f"🧾 <b>Order ID:</b> <code>{safe_order_code}</code>\n"
            f"📅 <b>Expired At:</b> <code>{safe_expiry}</code>\n\n"
            "ℹ️ အထက်ပါ customer ဝယ်ယူထားသော product သည် ယခု သက်တမ်းကုန်ဆုံးသွားပါပြီ။ "
            "လိုအပ်ပါက customer ကို Renew ပြုလုပ်နိုင်ကြောင်း ဆက်သွယ်အသိပေးနိုင်ပါသည်။"
        )
        if outline_text:
            text += f"\n\n{outline_text}"
        admin_expiry_markup = None
        if outline_key_id:
            admin_expiry_markup = telebot.types.InlineKeyboardMarkup(row_width=2)
            admin_expiry_markup.add(
                custom_inline_button("⏸ Suspend Key (0MB)", callback_data=f"outline_suspend_{outline_key_id}"),
                custom_inline_button("🗑 Delete Key", callback_data=f"outline_delete_{outline_key_id}"),
            )
        delivered_to_admin = False
        for admin_id in get_all_admin_ids():
            try:
                bot.send_message(admin_id, text, parse_mode="HTML", reply_markup=admin_expiry_markup)
                delivered_to_admin = True
            except Exception as e:
                print(f"Admin expiry notice failed for order {order_id}, admin {admin_id}: {e}")
        if delivered_to_admin:
            mark_admin_expiry_notice_sent(order_id)
            sent_orders += 1
        else:
            failed_orders += 1
    return sent_orders, failed_orders

def start_admin_expiry_notifier(bot):
    def worker():
        while True:
            try:
                check_admin_expiry_notifications(bot)
            except Exception as e:
                print(f"Admin expiry notifier error: {e}")
            time.sleep(5 * 60)
    threading.Thread(target=worker, daemon=True).start()

def start_discount_expiry_checker(bot):
    def worker():
        while True:
            try:
                expired = expire_product_discounts()
                for item_id, product_name, original_price in expired:
                    safe_name = html.escape(str(product_name))
                    for admin_id in get_all_admin_ids():
                        try:
                            bot.send_message(
                                admin_id,
                                "⏰ <b>Discount expired.</b>\n\n"
                                f"Product: <b>{safe_name}</b> (ID: <code>{item_id}</code>)\n"
                                f"Price restored to: <b>{format_mmk(original_price)}</b>",
                                parse_mode="HTML"
                            )
                        except Exception:
                            pass
            except Exception as e:
                print(f"Discount expiry checker error: {e}")
            time.sleep(60)
    threading.Thread(target=worker, daemon=True).start()

def start_stock_reservation_expiry_checker(bot):
    def worker():
        while True:
            try:
                expired = expire_stock_reservations()
                for _, user_id, item_name, quantity, order_code in expired:
                    language = get_user_language(user_id) or "my"
                    safe_item = html.escape(str(item_name))
                    safe_order = html.escape(str(order_code))
                    if language == "en":
                        text = (
                            "⏰ <b>Your stock reservation has expired.</b>\n\n"
                            f"📦 Product: <b>{safe_item}</b>\n"
                            f"🔢 Quantity: <b>{int(quantity)}</b>\n"
                            f"🧾 Order ID: <code>{safe_order}</code>\n\n"
                            "The held stock is available again. Please place a new order if you still want to buy it."
                        )
                    else:
                        text = (
                            "⏰ <b>Stock သိမ်းထားသည့်အချိန် ကုန်ဆုံးသွားပါပြီ</b>\n\n"
                            f"📦 Product: <b>{safe_item}</b>\n"
                            f"🔢 အရေအတွက်: <b>{int(quantity)}</b>\n"
                            f"🧾 Order ID: <code>{safe_order}</code>\n\n"
                            "သိမ်းထားသော stock ကို ပြန်လွှတ်ပေးလိုက်ပါပြီ။ ဝယ်ယူလိုပါက Shop မှ Order အသစ်ပြန်တင်ပေးပါ။"
                        )
                    try:
                        bot.send_message(user_id, text, parse_mode="HTML")
                    except Exception as error:
                        print(f"Reservation expiry notice failed for order {order_code}: {error}")
            except Exception as e:
                print(f"Stock reservation expiry checker error: {e}")
            time.sleep(60)
    threading.Thread(target=worker, daemon=True).start()

def is_admin_user(user_id):
    return db_is_admin_user(user_id)

def build_admin_panel_markup(section="home"):
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    if section == "home":
        markup.add(
            custom_inline_button("📦 Products", callback_data="apanel_products"),
            custom_inline_button("🧾 Orders", callback_data="apanel_orders"),
            custom_inline_button("👥 Users", callback_data="apanel_users"),
            custom_inline_button("⚙️ Shop", callback_data="apanel_shop"),
        )
        markup.add(
            custom_inline_button("🎁 Promotion", callback_data="apanel_promotion"),
            custom_inline_button("🎁 Referral", callback_data="apanel_referral"),
        )
        markup.add(custom_inline_button("🎟 Coupons", callback_data="apanel_coupons"))
        markup.add(custom_inline_button("🎨 Custom Emoji", callback_data="apanel_customemoji"))
        markup.add(custom_inline_button("🔄 Refresh", callback_data="apanel_home"))
        return markup

    if section == "products":
        markup.add(
            custom_inline_button("➕ Add Product", callback_data="apanel_help_addproduct"),
            custom_inline_button("✏️ Edit Product", callback_data="apanel_help_editproduct"),
            custom_inline_button("📥 Add Stock", callback_data="apanel_help_addstock"),
            custom_inline_button("📊 Set Stock", callback_data="apanel_help_setstock"),
        )
        markup.add(
            custom_inline_button("🔥 Set Discount", callback_data="apanel_help_setdiscount"),
            custom_inline_button("🏷 Active Discounts", callback_data="apanel_discounts"),
        )
        markup.add(
            custom_inline_button("🗑 Remove Product", callback_data="apanel_removeproduct")
        )
        markup.add(
            custom_inline_button("🔄 Renew ON/OFF", callback_data="apanel_renewproducts"),
            custom_inline_button("🔐 View Stock", callback_data="apanel_help_viewstock"),
        )
    elif section == "orders":
        markup.add(
            custom_inline_button("🧾 Recent Orders", callback_data="apanel_adminorders_recent"),
            custom_inline_button("⏳ Pending Payments", callback_data="apanel_adminorders_pending"),
            custom_inline_button("📅 သက်တမ်းကုန်မည့်စာရင်း", callback_data="apanel_expiring_list", _style="primary"),
            custom_inline_button("📊 Outline Keys Usage", callback_data="apanel_outlinekeys_0", _style="primary"),
            custom_inline_button("🔎 Search User Orders", callback_data="apanel_adminorders_userask"),
            custom_inline_button("📊 Monthly Report", callback_data="apanel_monthlyreport"),
            custom_inline_button("📈 Yearly Report", callback_data="apanel_yearlyreport"),
            custom_inline_button("⏰ Check Renewals", callback_data="apanel_checkrenewals"),
            custom_inline_button("📤 Manual Send", callback_data="apanel_help_send"),
        )
    elif section == "users":
        markup.add(
            custom_inline_button("👥 User List", callback_data="apanel_userlist"),
            custom_inline_button("🟢 Active Users", callback_data="apanel_activeusers"),
            custom_inline_button("📢 Announcement", callback_data="apanel_help_announcement"),
            custom_inline_button("🛡 Admin List", callback_data="apanel_adminlist"),
            custom_inline_button("➕ Add Admin", callback_data="apanel_help_addadmin"),
            custom_inline_button("➖ Remove Admin", callback_data="apanel_help_removeadmin"),
        )
    elif section == "shop":
        markup.add(
            custom_inline_button("✅ Open", callback_data="apanel_shop_open"),
            custom_inline_button("🛑 Close", callback_data="apanel_shop_close"),
            custom_inline_button("🛠 Maintenance", callback_data="apanel_shop_maintenance"),
            custom_inline_button("🖥 Outline Status", callback_data="apanel_outlinestatus"),
            custom_inline_button("📊 Outline Keys Usage", callback_data="apanel_outlinekeys_0", _style="primary"),
            custom_inline_button("📅 သက်တမ်းကုန်မည့်စာရင်း", callback_data="apanel_expiring_list", _style="primary"),
        )
    elif section == "referral":
        markup.add(
            custom_inline_button("✅ Start", callback_data="apanel_referral_open"),
            custom_inline_button("⏸ Pause", callback_data="apanel_referral_paused"),
            custom_inline_button("📊 Stats", callback_data="apanel_referral_stats"),
            custom_inline_button("🎁 Claims", callback_data="apanel_referral_claims"),
        )
        markup.add(custom_inline_button("📖 Guide", callback_data="apanel_referral_guide"))
    elif section == "promotion":
        markup.add(
            custom_inline_button("➕ Add Gift", callback_data="apanel_promo_addgift"),
            custom_inline_button("📦 Add Gift Stock", callback_data="apanel_promo_addstock"),
            custom_inline_button("🎁 Gift List", callback_data="apanel_promo_gifts"),
            custom_inline_button("⏳ Pending Manual", callback_data="apanel_promo_pending"),
            custom_inline_button("⚙️ Promotion Setup", callback_data="apanel_promo_setup"),
        )
    elif section == "coupons":
        markup.add(
            custom_inline_button("➕ Generate", callback_data="apanel_coupon_generate"),
            custom_inline_button("📋 Active Codes", callback_data="apanel_coupon_list"),
            custom_inline_button("👤 Send to User", callback_data="apanel_coupon_send"),
            custom_inline_button("📣 FCFS Broadcast", callback_data="apanel_coupon_fcfs"),
        )
    elif section == "customemoji":
        markup.add(
            custom_inline_button("🧩 Button Emoji Setup", callback_data="apanel_emoji_buttons"),
            custom_inline_button("💬 Message Emoji Setup", callback_data="apanel_emoji_messages"),
            custom_inline_button("📦 Product Emoji Setup", callback_data="apanel_emoji_products"),
            custom_inline_button("🔁 Toggle Emoji ON/OFF", callback_data="apanel_emoji_toggle"),
        )
        markup.add(
            custom_inline_button("🟦 Color: Blue/Teal", callback_data="apanel_btnstyle_primary", _style="primary"),
            custom_inline_button("🟩 Color: Green", callback_data="apanel_btnstyle_success", _style="success"),
            custom_inline_button("🟥 Color: Red", callback_data="apanel_btnstyle_danger", _style="danger"),
            custom_inline_button("⬜ Color: Default", callback_data="apanel_btnstyle_off", _style=""),
        )
    markup.add(custom_inline_button("⬅️ Back", callback_data="apanel_home"))
    return markup

def get_admin_panel_text():
    shop_status = html.escape(str(get_shop_status()))
    referral_status = html.escape(str(get_referral_status()))
    total_users = get_user_count()
    return (
        "🛠 <b>Admin Panel</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏪 <b>Shop Status:</b> <code>{shop_status}</code>\n"
        f"🎁 <b>Referral:</b> <code>{referral_status}</code>\n"
        f"👥 <b>Total Users:</b> <code>{total_users}</code>\n\n"
        "အောက်က category ကိုရွေးပါ။"
    )

def edit_or_send_admin_panel(chat_id, message_id=None, section="home"):
    text = get_admin_panel_text() if section == "home" else f"🛠 <b>Admin Panel</b>\n\n<b>{section.title()}</b> menu ကိုရွေးထားပါတယ်။"
    markup = build_admin_panel_markup(section)
    emoji_slots = (
        ("🛠", "admin_title"),
        ("🏪", "admin_shop_status"),
        ("🎁", "admin_referral_status"),
        ("👥", "admin_total_users"),
    )
    if message_id:
        edit_custom_emoji_message(
            bot, chat_id, message_id, text, emoji_slots,
            reply_markup=markup, fallback_parse_mode="HTML"
        )
    else:
        send_custom_emoji_message(bot, chat_id, text, emoji_slots, reply_markup=markup)

def send_admin_help(chat_id, title, usage, example=None):
    text = f"ℹ️ <b>{title}</b>\n\n<b>Usage:</b>\n<code>{html.escape(usage)}</code>"
    if example:
        text += f"\n\n<b>Example:</b>\n<code>{html.escape(example)}</code>"
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(custom_inline_button("⬅️ Back to Admin", callback_data="apanel_home"))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

def show_product_removal_list(chat_id, message_id):
    items = get_all_items()
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    if not items:
        markup.add(
            custom_inline_button("⬅️ Back to Products", callback_data="apanel_products")
        )
        bot.edit_message_text(
            "🗑 <b>Remove Product</b>\n\nဖျက်ရန် product မရှိသေးပါ။",
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
        return

    for item in items:
        item_id, item_name = item[0], item[1]
        stock = int(item[4] or 0) if len(item) > 4 else 0
        label = f"🗑 ID {item_id} | {item_name} | Stock {stock}"
        markup.add(
            custom_inline_button(
                label[:60],
                callback_data=f"apanel_removeproduct_select_{item_id}"
            )
        )
    markup.add(
        custom_inline_button("⬅️ Back to Products", callback_data="apanel_products")
    )
    bot.edit_message_text(
        "🗑 <b>Remove Product</b>\n\nဖျက်လိုသည့် product ကိုရွေးပါ။",
        chat_id,
        message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def show_product_removal_confirmation(chat_id, message_id, item_id):
    preview = get_product_removal_preview(item_id)
    if not preview:
        edit_or_send_admin_panel(chat_id, message_id, "products")
        return

    safe_name = html.escape(str(preview["name"]))
    blocked_text = ""
    if preview["active_orders"]:
        blocked_text = (
            "\n\n⚠️ <b>ယခုဖျက်၍မရသေးပါ။</b>\n"
            f"Active order/reservation <b>{preview['active_orders']}</b> ခုကို အရင်ပြီးအောင်လုပ်ပါ။"
        )
    elif preview["same_name_products"] > 1:
        blocked_text = (
            "\n\n⚠️ <b>နာမည်တူ product ရှိနေသောကြောင့် မဖျက်နိုင်ပါ။</b>\n"
            "Stock မှားဖျက်ခြင်းမဖြစ်စေရန် product တစ်ခုကို အရင် rename လုပ်ပါ။"
        )

    text = (
        "🗑 <b>Remove Product Confirmation</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 <b>Item ID:</b> <code>{preview['item_id']}</code>\n"
        f"📦 <b>Product:</b> {safe_name}\n"
        f"💰 <b>Price:</b> {preview['price']:,.0f} MMK\n"
        f"📊 <b>Displayed Stock:</b> {preview['stock']}\n"
        f"🔐 <b>Unsold Account Rows:</b> {preview['unsold_accounts']}\n"
        f"🧾 <b>Completed Orders Kept:</b> {preview['completed_orders']}"
        f"{blocked_text}\n\n"
        "Product နဲ့ stock rows တွေဖျက်မယ်။ Customer order history ကို မဖျက်ပါ။"
    )
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    if not blocked_text:
        markup.add(
            custom_inline_button(
                "✅ Confirm Delete",
                callback_data=f"apanel_removeproduct_confirm_{item_id}"
            ),
            custom_inline_button(
                "❌ Cancel",
                callback_data="apanel_removeproduct"
            )
        )
    else:
        markup.add(
            custom_inline_button("⬅️ Back", callback_data="apanel_removeproduct")
        )
    bot.edit_message_text(
        text,
        chat_id,
        message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def show_product_renewable_list(chat_id, message_id):
    items = get_all_items()
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    if not items:
        markup.add(custom_inline_button("⬅️ Back to Products", callback_data="apanel_products"))
        bot.edit_message_text(
            "🔄 <b>Renew Settings</b>\n\nProduct မရှိသေးပါ။",
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
        return

    for item in items:
        item_id = item[0]
        item_name = item[1]
        stock = int(item[4] or 0) if len(item) > 4 else 0
        renewable = bool(len(item) > 8 and int(item[8] or 0))
        status = "ON" if renewable else "OFF"
        icon = "✅" if renewable else "⛔"
        label = f"{icon} ID {item_id} | {item_name} | Renew {status} | Stock {stock}"
        markup.add(
            custom_inline_button(
                label[:60],
                callback_data=f"apanel_togglerenew_{item_id}_{0 if renewable else 1}"
            )
        )

    markup.add(custom_inline_button("⬅️ Back to Products", callback_data="apanel_products"))
    bot.edit_message_text(
        (
            "🔄 <b>Renew Settings</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Renew လုပ်ခွင့် ON/OFF ပြောင်းချင်တဲ့ product ကိုနှိပ်ပါ။"
        ),
        chat_id,
        message_id,
        reply_markup=markup,
        parse_mode="HTML"
    )

def send_user_list_report(chat_id):
    total_users = get_user_count()
    users = get_users_for_admin(limit=50)
    if not users:
        bot.send_message(chat_id, "👥 <b>User မရှိသေးပါ။</b>", parse_mode='HTML')
        return

    lines = ["👥 <b>User List</b>", f"Total users: <b>{total_users}</b>", "Showing latest 50 users", ""]
    for index, user in enumerate(users, start=1):
        user_id, join_date, role, username, first_name, last_name, order_count, success_count = user
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        username_text = f"@{username}" if username else "-"
        lines.extend([
            f"{index}. <code>{user_id}</code>",
            f"Name: {html.escape(full_name) if full_name else '-'}",
            f"Username: {html.escape(username_text)}",
            f"Joined: {html.escape(str(join_date or '-'))}",
            f"Role: {html.escape(str(role or 'user'))}",
            f"Orders: {order_count or 0} | Success: {success_count or 0}",
            ""
        ])

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        bot.send_message(chat_id, text[start:start + 3900], parse_mode='HTML')

def show_active_users_report(chat_id, message_id):
    active_24h, active_7d, active_30d, tracked_total = get_user_activity_summary()
    users = get_active_users_for_admin(limit=15)
    lines = [
        "🟢 <b>User Activity</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"Last 24 hours: <b>{active_24h}</b>",
        f"Last 7 days: <b>{active_7d}</b>",
        f"Last 30 days: <b>{active_30d}</b>",
        f"Tracked users: <b>{tracked_total}</b>",
        "",
        "<b>Latest 15 users</b>",
    ]
    if not users:
        lines.extend(["", "<i>Activity record မရှိသေးပါ။ Bot restart ပြီးနောက် စတင်မှတ်တမ်းတင်ပါမယ်။</i>"])
    else:
        for index, user in enumerate(users, start=1):
            user_id, username, first_name, last_name, last_active, last_action = user
            full_name = " ".join(
                part for part in (first_name, last_name) if part
            ).strip()[:40] or "-"
            username_text = f"@{username[:32]}" if username else "-"
            lines.extend([
                "",
                f"{index}. <b>{html.escape(full_name)}</b> ({html.escape(username_text)})",
                f"   ID: <code>{user_id}</code>",
                f"   Last active: <code>{html.escape(str(last_active))}</code>",
                f"   Action: <code>{html.escape(str(last_action)[:80])}</code>",
            ])

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        custom_inline_button("🔄 Refresh", callback_data="apanel_activeusers"),
        custom_inline_button("⬅️ Back", callback_data="apanel_users")
    )
    text = "\n".join(lines)
    try:
        bot.edit_message_text(
            text,
            chat_id,
            message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
    except Exception as error:
        if "message is not modified" not in str(error).lower():
            raise

def send_admin_list_report(chat_id):
    admins = get_admin_users()
    lines = [
        "🛡 <b>Admin List</b>",
        "━━━━━━━━━━━━━━━━━━",
        "",
        f"👑 <b>Master Admin:</b> <code>{ADMIN_ID}</code>",
        "",
    ]

    if not admins:
        lines.append("<i>Extra admin မရှိသေးပါ။</i>")
    else:
        lines.append("👮 <b>Extra Admins:</b>")
        for index, (user_id, added_at, added_by) in enumerate(admins, start=1):
            lines.extend([
                f"{index}. <code>{user_id}</code>",
                f"   Added: <code>{html.escape(str(added_at or '-'))}</code>",
                f"   By: <code>{html.escape(str(added_by or '-'))}</code>",
            ])

    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

def send_referral_stats_report(chat_id):
    stats = get_referral_stats()
    text = (
        "🎁 <b>Referral Stats</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"Status: <code>{html.escape(str(stats['status']))}</code>\n"
        f"Required: <b>{stats['required_count']}</b>\n"
        f"Reward: <b>{html.escape(str(stats['reward_text']))}</b>\n\n"
        f"Pending referrals: <b>{stats['pending_refs']}</b>\n"
        f"Valid referrals: <b>{stats['valid_refs']}</b>\n"
        f"Active referrers: <b>{stats['active_referrers']}</b>\n"
        f"Pending claims: <b>{stats['pending_claims']}</b>"
    )
    bot.send_message(chat_id, text, parse_mode="HTML")

def send_referral_claims_report(chat_id):
    claims = get_pending_referral_rewards(limit=20)
    if not claims:
        bot.send_message(chat_id, "🎁 <b>Pending referral claim မရှိသေးပါ။</b>", parse_mode="HTML")
        return

    for reward_id, user_id, created_at in claims:
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            custom_inline_button("✅ Approve", callback_data=f"refclaim_approve_{reward_id}"),
            custom_inline_button("❌ Reject", callback_data=f"refclaim_reject_{reward_id}")
        )
        bot.send_message(
            chat_id,
            (
                "🎁 <b>Referral Reward Claim</b>\n\n"
                f"Reward ID: <code>{reward_id}</code>\n"
                f"User ID: <code>{user_id}</code>\n"
                f"Created: <code>{html.escape(str(created_at or '-'))}</code>\n"
                f"Valid Referrals: <b>{get_valid_referral_count(user_id)}/{get_referral_required_count()}</b>\n"
                f"Reward: <b>{html.escape(str(get_referral_reward_text()))}</b>"
            ),
            reply_markup=markup,
            parse_mode="HTML"
        )

def send_referral_admin_guide(chat_id):
    bot.send_message(
        chat_id,
        (
            "📖 <b>Referral Admin Guide</b>\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            "✅ <b>Start</b> - user တွေ referral link သုံးပြီး count တိုးနိုင်မယ်။\n"
            "⏸ <b>Pause</b> - link ဝင်လာရင်လည်း count မတိုးတော့ဘူး။\n"
            "📊 <b>Stats</b> - referral count နဲ့ pending claim တွေကြည့်မယ်။\n"
            "🎁 <b>Claims</b> - 10 ယောက်ပြည့်တဲ့ user တွေ claim တင်ထားတာ approve/reject လုပ်မယ်။\n\n"
            "User ဘက်မှာ Home Menu > Referral ကနေ link copy လုပ်ပြီး share လုပ်နိုင်ပါတယ်။"
        ),
        parse_mode="HTML"
    )


def build_outline_status_markup():
    markup = telebot.types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        custom_inline_button("📊 Key တစ်ခုချင်းစီ၏ Usage နှင့် User စာရင်းကြည့်ရန်", callback_data="apanel_outlinekeys_0", _style="primary"),
        custom_inline_button("📅 သက်တမ်းကုန်တော့မည့် User များ စာရင်းကြည့်ရန်", callback_data="apanel_expiring_list", _style="primary"),
        custom_inline_button("⬅️ Back to Admin Panel", callback_data="apanel_home", _style="primary"),
    )
    return markup


def send_outline_keys_usage_report(chat_id, page=0, message_id=None):
    data = get_all_keys_with_usage()
    if not data.get("ok"):
        bot.send_message(chat_id, f"⚠️ Outline API Error:\n<code>{html.escape(str(data.get('reason')))}</code>", parse_mode="HTML")
        return

    keys = data["keys"]
    orders_map = get_outline_orders_map()
    by_key_id = orders_map["by_key_id"]
    by_order_code = orders_map["by_order_code"]

    per_page = 10
    total_keys = len(keys)
    total_pages = max(1, (total_keys + per_page - 1) // per_page)
    page = max(0, min(int(page), total_pages - 1))
    slice_keys = keys[page * per_page : (page + 1) * per_page]

    lines = [
        f"📊 <b>Outline Keys & User Usage Report</b>",
        f"🖥 <b>Server:</b> {html.escape(str(data['server_name']))}",
        f"🔑 <b>Total Keys:</b> <b>{total_keys}</b> ခု | 📦 <b>Total Traffic:</b> <b>{data['total_gb']} GB</b>",
        f"📄 <b>Page:</b> {page + 1} / {total_pages} <i>(အများဆုံးသုံးထားသူများမှ စီထားသည်)</i>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    if not slice_keys:
        lines.append("\n<i>Key မရှိသေးပါ။</i>")
    else:
        for idx, k in enumerate(slice_keys, start=page * per_page + 1):
            kid = k["key_id"]
            kname = k["name"]
            matched = by_key_id.get(kid)
            if not matched:
                m_ord = re.search(r"(ORD-[A-Z0-9]+)", kname.upper())
                if m_ord:
                    matched = by_order_code.get(m_ord.group(1))

            if k["is_suspended"]:
                usage_str = f"⏸ <b>SUSPENDED (0 MB)</b> | Used: {k['used_gb']} GB"
            elif k["limit_gb"]:
                filled = min(8, max(0, k["percent"] // 12))
                bar = "█" * filled + "░" * (8 - filled)
                usage_str = f"<b>{k['used_gb']} GB</b> / {k['limit_gb']} GB ({k['percent']}%) [{bar}]"
            else:
                usage_str = f"<b>{k['used_gb']} GB</b> (Unlimited)"

            lines.append(f"\n<b>{idx}. Key ID: <code>{html.escape(kid)}</code></b> — {html.escape(kname)}")
            lines.append(f"   📈 Usage: {usage_str}")
            if matched:
                lines.append(f"   👤 Buyer: <b>{html.escape(matched['buyer_display'])}</b> (<code>{matched['user_id']}</code>)")
                lines.append(f"   📅 Expiry: <code>{html.escape(str(matched['expiry_date']))}</code> | 🧾 <code>{html.escape(matched['order_code'])}</code>")
            else:
                lines.append("   ℹ️ <i>(Outline Manager မှ တိုက်ရိုက်ဆောက်ထားသော Key)</i>")

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    nav_btns = []
    if page > 0:
        nav_btns.append(custom_inline_button("⬅️ Prev Page", callback_data=f"apanel_outlinekeys_{page - 1}", _style="primary"))
    if page + 1 < total_pages:
        nav_btns.append(custom_inline_button("Next Page ➡️", callback_data=f"apanel_outlinekeys_{page + 1}", _style="primary"))
    if nav_btns:
        markup.row(*nav_btns)
    markup.add(
        custom_inline_button("🔄 Refresh Usage", callback_data=f"apanel_outlinekeys_{page}", _style="success"),
        custom_inline_button("📅 သက်တမ်းကုန်မည့်စာရင်း", callback_data="apanel_expiring_list", _style="primary"),
    )
    markup.add(custom_inline_button("⬅️ Back to Admin", callback_data="apanel_home", _style="primary"))

    text = "\n".join(lines)
    if message_id:
        try:
            bot.edit_message_text(text[:3950], chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    bot.send_message(chat_id, text[:3950], reply_markup=markup, parse_mode="HTML")


def send_expiring_orders_dashboard(chat_id, message_id=None):
    report = get_expiring_and_expired_orders_for_admin(days_ahead=7, expired_days_back=14)
    now = report["now"]
    expiring_soon = report["expiring_soon"]
    recently_expired = report["recently_expired"]
    all_upcoming = report["all_active_upcoming"]

    lines = [
        "📅 <b>User သက်တမ်းကုန်မည့်စာရင်း (Expiry Tracker)</b>",
        f"🕒 <b>လက်ရှိအချိန်:</b> <code>{now.strftime('%Y-%m-%d %H:%M')}</code>",
        "━━━━━━━━━━━━━━━━━━━━━━",
    ]

    # Section 1: Expiring within 7 days
    lines.append(f"\n⚠️ <b>၇ ရက်အတွင်း သက်တမ်းကုန်တော့မည့်သူများ ({len(expiring_soon)} ခု):</b>")
    if not expiring_soon:
        lines.append("<i>၇ ရက်အတွင်း သက်တမ်းကုန်မည့် အော်ဒါ မရှိသေးပါ။</i>")
    else:
        for idx, row in enumerate(expiring_soon[:12], 1):
            order_id, order_code, uid, uname, fname, lname, item_name, qty, exp_str, key_id = row
            full_name = " ".join(p for p in (fname, lname) if p).strip() or f"User {uid}"
            uname_txt = f"@{uname}" if uname else f"ID:{uid}"
            try:
                from datetime import datetime as _dt
                exp_dt = _dt.strptime(str(exp_str), "%Y-%m-%d %H:%M:%S")
                diff = exp_dt - now
                rem_days = max(0, diff.days)
                rem_hrs = max(0, diff.seconds // 3600)
                left_badge = f"⏳ {rem_days} ရက် {rem_hrs} နာရီ ကျန်"
            except Exception:
                left_badge = f"📅 {exp_str}"
            key_badge = f" | 🔑 Key <code>{html.escape(str(key_id))}</code>" if key_id else ""
            lines.append(
                f"{idx}. 👤 <b>{html.escape(full_name)}</b> ({html.escape(uname_txt)} | <code>{uid}</code>)\n"
                f"   📦 {html.escape(str(item_name))}{key_badge}\n"
                f"   📅 ကုန်မည့်ရက်: <code>{html.escape(str(exp_str))}</code> (<b>{left_badge}</b>)"
            )

    # Section 2: Recently Expired (last 14 days)
    lines.append(f"\n🔴 <b>လတ်တလော သက်တမ်းကုန်သွားသူများ ({len(recently_expired)} ခု):</b>")
    if not recently_expired:
        lines.append("<i>လတ်တလော သက်တမ်းကုန်သွားသော အော်ဒါ မရှိပါ။</i>")
    else:
        for idx, row in enumerate(recently_expired[:10], 1):
            order_id, order_code, uid, uname, fname, lname, item_name, qty, exp_str, key_id = row
            full_name = " ".join(p for p in (fname, lname) if p).strip() or f"User {uid}"
            uname_txt = f"@{uname}" if uname else f"ID:{uid}"
            key_badge = f" | 🔑 Key <code>{html.escape(str(key_id))}</code>" if key_id else ""
            lines.append(
                f"{idx}. 👤 <b>{html.escape(full_name)}</b> ({html.escape(uname_txt)} | <code>{uid}</code>)\n"
                f"   📦 {html.escape(str(item_name))}{key_badge}\n"
                f"   ❌ ကုန်ဆုံးခဲ့သည့်ရက်: <code>{html.escape(str(exp_str))}</code>"
            )

    # Section 3: Next upcoming active subscriptions (if nothing expiring within 7 days)
    if not expiring_soon and all_upcoming:
        lines.append(f"\n🟢 <b>လက်ရှိသုံးနေဆဲ အော်ဒါများ (အနီးဆုံးကုန်မည့်ရက်အလိုက်):</b>")
        for idx, row in enumerate(all_upcoming[:10], 1):
            order_id, order_code, uid, uname, fname, lname, item_name, qty, exp_str, key_id = row
            full_name = " ".join(p for p in (fname, lname) if p).strip() or f"User {uid}"
            uname_txt = f"@{uname}" if uname else f"ID:{uid}"
            try:
                from datetime import datetime as _dt
                exp_dt = _dt.strptime(str(exp_str), "%Y-%m-%d %H:%M:%S")
                rem_days = max(0, (exp_dt - now).days)
                left_badge = f"{rem_days} ရက်ကျန်"
            except Exception:
                left_badge = exp_str
            lines.append(
                f"{idx}. 👤 <b>{html.escape(full_name)}</b> ({html.escape(uname_txt)}) — {html.escape(str(item_name))}\n"
                f"   📅 Expiry: <code>{html.escape(str(exp_str))}</code> (<b>{left_badge}</b>)"
            )

    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        custom_inline_button("⏰ သက်တမ်းကုန်ခါနီးသူများထံ သတိပေးစာပို့မည်", callback_data="apanel_checkrenewals", _style="success"),
    )
    markup.add(
        custom_inline_button("📊 Outline Keys Usage", callback_data="apanel_outlinekeys_0", _style="primary"),
        custom_inline_button("🔄 Refresh", callback_data="apanel_expiring_list", _style="primary"),
    )
    markup.add(custom_inline_button("⬅️ Back to Admin", callback_data="apanel_home", _style="primary"))

    text = "\n".join(lines)
    if message_id:
        try:
            bot.edit_message_text(text[:3950], chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return
        except Exception:
            pass
    bot.send_message(chat_id, text[:3950], reply_markup=markup, parse_mode="HTML")

def send_monthly_sales_report(chat_id, year_month=None):
    report = get_monthly_sales_report(year_month)
    rows = report["items"]
    total_mmk = int(report["total_amount"] or 0)
    total_usd = total_mmk / MMK_PER_USD if MMK_PER_USD else 0

    lines = [
        "📊 <b>ENI Premium Store - လစဉ် အရောင်းစာရင်းချုပ်</b>",
        f"🗓 <b>သတ်မှတ်လ:</b> {html.escape(report['year_month'])}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 <b>စုစုပေါင်း အော်ဒါအရေအတွက်:</b> {report['total_order_count']} ခု",
        f"📦 <b>စုစုပေါင်း ရောင်းရသောပမာဏ:</b> {report['total_quantity']} ခု",
        f"💰 <b>စုစုပေါင်း ဝင်ငွေ (MMK):</b> {total_mmk:,} MMK",
        f"💵 <b>စုစုပေါင်း ဝင်ငွေ (USD/USDT):</b> {total_usd:.2f} USD",
        "",
        "📋 <b>ဝယ်ယူထားသော ပစ္စည်းများနှင့် အရေအတွက်စာရင်း:</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if not rows:
        lines.append("<i>ယခုလအတွင်း ရောင်းချမှု မရှိသေးပါ။</i>")
    else:
        for index, (item_name, qty, amount, order_count) in enumerate(rows, start=1):
            lines.extend([
                f"{index}. 📦 <b>{html.escape(str(item_name))}</b>",
                f"   ├ အရေအတွက်: <b>{int(qty or 0)} ခု</b>",
                f"   ├ အော်ဒါ: <b>{int(order_count or 0)} ခု</b>",
                f"   └ စုစုပေါင်း: <b>{int(amount or 0):,} MMK</b>",
                ""
            ])
    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        bot.send_message(chat_id, text[start:start + 3900], parse_mode='HTML')

def send_yearly_sales_report(chat_id, year=None):
    report = get_yearly_sales_report(year)
    total_mmk = int(report["total_amount"] or 0)
    total_usd = total_mmk / MMK_PER_USD if MMK_PER_USD else 0

    lines = [
        "📈 <b>ENI Premium Store - နှစ်ချုပ် အရောင်းစာရင်း</b>",
        f"🗓 <b>သတ်မှတ်နှစ်:</b> {html.escape(report['year'])}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📊 <b>စုစုပေါင်း အော်ဒါအရေအတွက်:</b> {report['total_order_count']} ခု",
        f"📦 <b>စုစုပေါင်း ရောင်းရသောပမာဏ:</b> {report['total_quantity']} ခု",
        f"💰 <b>စုစုပေါင်း ဝင်ငွေ (MMK):</b> {total_mmk:,} MMK",
        f"💵 <b>စုစုပေါင်း ဝင်ငွေ (USD/USDT):</b> {total_usd:.2f} USD",
        "",
        "🗓 <b>လအလိုက် စာရင်းချုပ်:</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not report["months"]:
        lines.append("<i>ဒီနှစ်အတွင်း ရောင်းချမှု မရှိသေးပါ။</i>")
    else:
        for year_month, order_count, qty, amount in report["months"]:
            lines.append(
                f"• <b>{html.escape(str(year_month))}</b> - "
                f"Order <b>{int(order_count or 0)}</b> ခု | "
                f"Qty <b>{int(qty or 0)}</b> ခု | "
                f"<b>{int(amount or 0):,} MMK</b>"
            )

    lines.extend([
        "",
        "📋 <b>ပစ္စည်းအလိုက် နှစ်ချုပ်စာရင်း:</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ])

    if report["items"]:
        for index, (item_name, qty, amount, order_count) in enumerate(report["items"], start=1):
            lines.extend([
                f"{index}. 📦 <b>{html.escape(str(item_name))}</b>",
                f"   ├ အရေအတွက်: <b>{int(qty or 0)} ခု</b>",
                f"   ├ အော်ဒါ: <b>{int(order_count or 0)} ခု</b>",
                f"   └ စုစုပေါင်း: <b>{int(amount or 0):,} MMK</b>",
                ""
            ])

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        bot.send_message(chat_id, text[start:start + 3900], parse_mode='HTML')

def format_admin_order_row(index, order):
    (
        order_id, order_code, user_id, username, first_name, last_name, item_name,
        quantity, payment_method, status, timestamp, expiry_date, total_amount,
        has_delivery
    ) = order
    full_name = " ".join(part for part in [first_name, last_name] if part).strip()
    username_text = f"@{username}" if username else "-"
    amount_text = f"{int(float(total_amount)):,} MMK" if total_amount is not None else "-"
    delivery_text = "Yes" if has_delivery else "No"
    return (
        f"{index}. <b>{html.escape(str(order_code or order_id))}</b>\n"
        f"   👤 User: <code>{user_id}</code> | {html.escape(full_name or '-')}\n"
        f"   🔗 Username: {html.escape(username_text)}\n"
        f"   📦 Item: {html.escape(str(item_name or '-'))}\n"
        f"   🔢 Qty: <b>{int(quantity or 0)}</b> | 💳 {html.escape(str(payment_method or '-'))}\n"
        f"   💰 Amount: <b>{amount_text}</b>\n"
        f"   📌 Status: <code>{html.escape(str(status or '-'))}</code> | Data: <code>{delivery_text}</code>\n"
        f"   📅 Bought: <code>{html.escape(str(timestamp or '-'))}</code>\n"
        f"   ⏳ Expiry: <code>{html.escape(str(expiry_date or '-'))}</code>"
    )

def send_admin_order_report(chat_id, title, orders):
    if not orders:
        bot.send_message(chat_id, f"🧾 <b>{html.escape(title)}</b>\n\nOrder မတွေ့ပါ။", parse_mode="HTML")
        return

    header_lines = [
        f"🧾 <b>{html.escape(title)}</b>",
        "━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    chunks = []
    current_lines = header_lines[:]
    for index, order in enumerate(orders, start=1):
        row_text = format_admin_order_row(index, order)
        candidate = "\n".join(current_lines + [row_text, ""])
        if len(candidate) > 3400 and len(current_lines) > len(header_lines):
            chunks.append("\n".join(current_lines))
            current_lines = header_lines[:] + [row_text, ""]
        else:
            current_lines.extend([row_text, ""])

    if current_lines:
        chunks.append("\n".join(current_lines))

    for chunk in chunks:
        try:
            bot.send_message(chat_id, chunk, parse_mode="HTML")
        except Exception as e:
            print(f"Admin order report send failed: {e}")
            plain_chunk = re.sub(r"</?[^>]+>", "", chunk)
            bot.send_message(chat_id, plain_chunk)

def ask_admin_order_user_id(chat_id):
    msg = bot.send_message(
        chat_id,
        (
            "🔎 <b>User Orders Search</b>\n\n"
            "Order history ကြည့်ချင်တဲ့ <b>User ID</b> ကိုရိုက်ပေးပါ။\n\n"
            "Example:\n<code>7640253919</code>"
        ),
        parse_mode="HTML"
    )
    bot.register_next_step_handler(msg, process_admin_order_user_search)

def process_admin_order_user_search(message):
    if not is_admin_user(message.from_user.id):
        return
    text = (message.text or "").strip()
    if not re.match(r"^-?\d+$", text):
        bot.reply_to(message, "User ID ကို number အနေနဲ့ရိုက်ပေးပါ။", parse_mode="HTML")
        return
    user_id = int(text)
    orders = get_orders_by_user_for_admin(user_id, limit=30)
    send_admin_order_report(message.chat.id, f"Orders for User {user_id}", orders)

# ---------------------------------------------------------
# Universal Callback Handlers
# (start.py ထဲမှ home handler ကို ဖယ်ရှားပြီး ဒီနေရာတွင်တစ်ခုတည်းသာ ထားရမည်)
# ---------------------------------------------------------

@bot.callback_query_handler(func=lambda call: call.data == 'home')
def universal_back_home(call):
    try:
        bot.answer_callback_query(call.id)
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_home_menu(call.from_user.id, call.from_user.first_name, bot)
    except Exception:
        show_home_menu(call.from_user.id, call.from_user.first_name, bot)


@bot.message_handler(commands=['admin'])
def handle_admin_panel(message):
    if not is_admin_user(message.from_user.id):
        return
    edit_or_send_admin_panel(message.chat.id)


def process_coupon_generate(message):
    if not is_admin_user(message.from_user.id):
        return
    try:
        quantity, discount_type, value = [part.strip() for part in message.text.split('|')]
        result = generate_coupons(int(quantity), discount_type.lower(), float(value), valid_days=7)
        codes = '\n'.join(f'<code>{code}</code>' for code in result['codes'])
        bot.send_message(message.chat.id, f"✅ <b>{len(result['codes'])} Coupons Generated</b>\nExpiry: <code>{result['expires_at']}</code>\n\n{codes}", parse_mode='HTML')
    except Exception as error:
        bot.send_message(message.chat.id, f"❌ Invalid format: {html.escape(str(error))}\nUse: <code>10 | percent | 20</code>", parse_mode='HTML')


def process_coupon_send(message):
    try:
        code, user_id = [part.strip() for part in message.text.split('|')]
        user_id = int(user_id)
        if not assign_coupon_to_user(code, user_id):
            raise ValueError('Coupon is unavailable, expired, or already assigned')
        coupon = get_coupon_details(code)
        _, discount_type, discount_value, expires_at, _ = coupon
        discount = f"{discount_value:g}% OFF" if discount_type == "percent" else f"{discount_value:,.0f} MMK OFF"
        bot.send_message(
            user_id,
            "🎁 <b>သင့်အတွက် ENI Premium Store Coupon ရရှိထားပါသည်။</b>\n\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"🏷 <b>Coupon Code:</b> <code>{html.escape(code.upper())}</code>\n"
            f"💸 <b>Discount:</b> {discount}\n"
            f"📅 <b>သက်တမ်းကုန်ဆုံးချိန်:</b> <code>{html.escape(str(expires_at))}</code>\n\n"
            "🛒 Bot ရဲ့ Shop မှာ Product ရွေးပြီး <b>Coupon Code ထည့်မယ်</b> မှာ အထက်ပါ code ကိုထည့်အသုံးပြုပါ။\n\n"
            "⚠️ <b>ဒီ Coupon Code ကို သင့် Account အတွက်သာ သတ်မှတ်ထားပါသည်။</b>\n"
            "အခြားသူများ အသုံးပြု၍မရပါ။",
            parse_mode='HTML',
        )
        bot.send_message(message.chat.id, '✅ Coupon sent and locked to that User ID.')
    except Exception as error:
        bot.send_message(message.chat.id, f'❌ {html.escape(str(error))}', parse_mode='HTML')


def process_coupon_fcfs(message):
    try:
        codes = [part.strip().upper() for part in message.text.replace('\n', ' ').split() if part.strip()]
        active = {row[0] for row in get_active_coupons(500)}
        codes = [code for code in codes if code in active]
        if not codes:
            raise ValueError('No active codes found')
        text = "🎉 <b>ENI FCFS Coupon Event</b>\n\nFirst come, first served. Each code can be used once.\n\n" + '\n'.join(f'<code>{code}</code>' for code in codes)
        def worker():
            for user_id in get_all_user_ids():
                try: bot.send_message(user_id, text, parse_mode='HTML')
                except Exception: pass
                time.sleep(0.04)
        threading.Thread(target=worker, daemon=True).start()
        bot.send_message(message.chat.id, f'✅ FCFS broadcast started for {len(codes)} codes.')
    except Exception as error:
        bot.send_message(message.chat.id, f'❌ {html.escape(str(error))}', parse_mode='HTML')


@bot.callback_query_handler(func=lambda call: call.data.startswith('apanel_'))
def handle_admin_panel_callback(call):
    if not is_admin_user(call.from_user.id):
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True)
        return

    action = call.data.replace('apanel_', '', 1)
    bot.answer_callback_query(call.id)

    if action in ("home", "products", "orders", "users", "shop", "referral", "promotion", "customemoji", "coupons"):
        edit_or_send_admin_panel(call.message.chat.id, call.message.message_id, action)
        return

    if action == "coupon_list":
        rows = get_active_coupons()
        text = "🎟 <b>Active Coupons</b>\n\n" + ("\n".join(f"<code>{c}</code> — {v:g}{'%' if t == 'percent' else ' MMK'} | {e}" for c, t, v, e, _ in rows) if rows else "No active coupons.")
        bot.send_message(call.message.chat.id, text[:3900], parse_mode="HTML")
        return
    if action == "coupon_generate":
        msg = bot.send_message(call.message.chat.id, "Send: <code>quantity | percent/fixed | amount</code>\nExample: <code>10 | percent | 20</code>", parse_mode="HTML")
        bot.register_next_step_handler(msg, process_coupon_generate)
        return
    if action == "coupon_send":
        msg = bot.send_message(call.message.chat.id, 'Send: <code>ENI-CODE | user_id</code>', parse_mode='HTML')
        bot.register_next_step_handler(msg, process_coupon_send)
        return
    if action == "coupon_fcfs":
        msg = bot.send_message(call.message.chat.id, 'Send active codes separated by spaces or new lines.', parse_mode='HTML')
        bot.register_next_step_handler(msg, process_coupon_fcfs)
        return

    if action.startswith("btnstyle_"):
        style_val = action.replace("btnstyle_", "", 1)
        set_setting("button_style", style_val)
        bot.send_message(
            call.message.chat.id,
            f"🎨 Button Color Style ကို <b>{html.escape(style_val.upper())}</b> သို့ ပြောင်းလဲပြီးပါပြီ။",
            parse_mode="HTML",
        )
        edit_or_send_admin_panel(call.message.chat.id, call.message.message_id, "customemoji")
        return

    if action == "emoji_toggle":
        current = get_setting('custom_emoji_enabled', 'off')
        next_state = 'off' if current == 'on' else 'on'
        set_setting('custom_emoji_enabled', next_state)
        bot.send_message(call.message.chat.id, f"✅ Custom emoji: <b>{next_state.upper()}</b>", parse_mode='HTML')
        return

    if action in ('emoji_buttons', 'emoji_messages', 'emoji_products'):
        if action == 'emoji_buttons':
            keys = BUTTON_EMOJI_KEYS
            command = '/setbuttonemoji button_key'
            title = '🧩 <b>Button Custom Emoji</b>'
            prefix = 'custom_button_emoji_'
        elif action == 'emoji_messages':
            keys = MESSAGE_EMOJI_KEYS
            command = '/setmessageemoji message_key'
            title = '💬 <b>Message Custom Emoji</b>'
            prefix = 'custom_message_emoji_'
        else:
            bot.send_message(
                call.message.chat.id,
                "📦 <b>Product Custom Emoji</b>\n\n"
                "Product logo custom emoji ပါတဲ့ message ကို Reply ပြီး\n"
                "<code>/setproductemoji product_id</code> ပို့ပါ။\n\n"
                "ဥပမာ: <code>/setproductemoji 1</code>",
                parse_mode='HTML'
            )
            return
        rows = [title, "", "Custom emoji ကို Reply ပြီး အောက်က command သုံးပါ:", f"<code>{command}</code>", ""]
        for key in keys:
            rows.append(f"• <code>{key}</code>: {'✅' if get_setting(prefix + key, '') else '—'}")
        bot.send_message(call.message.chat.id, '\n'.join(rows), parse_mode='HTML')
        return

    if action == "promo_setup":
        config = get_promotion_config()
        bot.send_message(
            call.message.chat.id,
            "🎁 <b>Promotion Setup</b>\n\n"
            f"Status: <code>{html.escape(str(config['status']))}</code>\n"
            f"Period: <code>{html.escape(str(config['start_at'] or '-'))}</code> to <code>{html.escape(str(config['end_at'] or '-'))}</code>\n"
            f"Minimum: <code>{int(config['minimum_amount']):,} MMK</code>\n\n"
            "<code>/setpromotion on|off</code>\n"
            "<code>/setpromotion YYYY-MM-DD | YYYY-MM-DD | minimum_amount</code>\n\n"
            "Example:\n<code>/setpromotion 2026-10-20 | 2026-10-30 | 10000</code>",
            parse_mode="HTML",
        )
        return

    if action == "promo_addgift":
        bot.send_message(
            call.message.chat.id,
            "➕ <b>Add Promotion Gift</b>\n\n<code>/addgift Gift name | duration/details</code>\n\nExample:\n<code>/addgift Gemini Pro | 18 Months</code>",
            parse_mode="HTML",
        )
        return

    if action == "promo_addstock":
        bot.send_message(
            call.message.chat.id,
            "📦 <b>Add auto-delivery Gift Stock</b>\n\n<code>/addgiftstock gift_id | key1\nkey2\nkey3</code>\n\nStock မရှိလည်း customer က gift ကိုရွေးနိုင်ပြီး admin ထံ manual pending အဖြစ်ရောက်ပါမည်။",
            parse_mode="HTML",
        )
        return

    if action == "promo_gifts":
        gifts = get_promotion_gifts()
        if not gifts:
            bot.send_message(call.message.chat.id, "🎁 Gift မထည့်ရသေးပါ။")
            return
        lines = ["🎁 <b>Promotion Gifts</b>\n"]
        markup = telebot.types.InlineKeyboardMarkup(row_width=1)
        for gift_id, name, details, active in gifts:
            stock = get_promotion_gift_stock_count(gift_id)
            state = "ON" if active else "OFF"
            lines.append(f"<b>{gift_id}.</b> {html.escape(str(name))} — {html.escape(str(details or '-'))}\n   Status: <code>{state}</code> | Auto stock: <b>{stock}</b>")
            markup.add(custom_inline_button(
                f"{'⏸ Disable' if active else '▶️ Enable'}: {name}"[:64],
                callback_data=f"apanel_promo_toggle_{gift_id}_{0 if active else 1}",
            ))
        markup.add(custom_inline_button("⬅️ Back", callback_data="apanel_promotion"))
        bot.send_message(call.message.chat.id, "\n\n".join(lines), reply_markup=markup, parse_mode="HTML")
        return

    if action.startswith("promo_toggle_"):
        try:
            _, gift_id_text, enabled_text = action.rsplit("_", 2)
            updated = set_promotion_gift_active(int(gift_id_text), bool(int(enabled_text)))
        except (TypeError, ValueError):
            updated = False
        bot.send_message(call.message.chat.id, "✅ Gift status updated." if updated else "❌ Gift not found.")
        return

    if action == "promo_pending":
        claims = get_pending_promotion_claims()
        if not claims:
            bot.send_message(call.message.chat.id, "✅ Manual ပို့ရန် Gift မရှိပါ။")
            return
        lines = ["🎁 <b>Pending Manual Gifts</b>"]
        for claim_id, order_id, user_id, gift_name, details, selected_at in claims:
            lines.append(
                f"\n<b>Claim {claim_id}</b> | Order {order_id}\n"
                f"User: <code>{user_id}</code>\nGift: <b>{html.escape(str(gift_name))}</b> ({html.escape(str(details or '-'))})\n"
                f"<code>/sendgift {claim_id} gift_info</code>"
            )
        bot.send_message(call.message.chat.id, "\n".join(lines), parse_mode="HTML")
        return

    if action == "outlinestatus":
        st = get_server_status()
        if not st.get("ok"):
            bot.send_message(call.message.chat.id, f"⚠️ Outline API Error:\n<code>{html.escape(str(st.get('reason')))}</code>", parse_mode="HTML")
        else:
            bot.send_message(
                call.message.chat.id,
                "🖥 <b>Outline Server Status</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"🏷 <b>Server:</b> {html.escape(str(st['name']))}\n"
                f"🔢 <b>Version:</b> <code>{html.escape(str(st['version']))}</code>\n"
                f"🔌 <b>Port:</b> <code>{st['port']}</code>\n"
                f"🔑 <b>Active Keys:</b> <b>{st['total_keys']}</b> ခု\n"
                f"📊 <b>Total Traffic (30d):</b> <b>{st['total_gb']} GB</b>\n\n"
                "👇 <b>Key တစ်ခုချင်းစီ၏ Usage နှင့် သက်တမ်းကုန်မည့်ရက်များကို အောက်ပါခလုတ်များဖြင့် ကြည့်ရှုနိုင်ပါသည် -</b>",
                reply_markup=build_outline_status_markup(),
                parse_mode="HTML",
            )
        return

    if action.startswith("outlinekeys_"):
        page_num = int(action.replace("outlinekeys_", "", 1) or 0)
        send_outline_keys_usage_report(call.message.chat.id, page=page_num, message_id=call.message.message_id)
        return

    if action == "expiring_list":
        send_expiring_orders_dashboard(call.message.chat.id, message_id=call.message.message_id)
        return

    if action == "monthlyreport":
        send_monthly_sales_report(call.message.chat.id)
        return

    if action == "yearlyreport":
        send_yearly_sales_report(call.message.chat.id)
        return

    if action == "checkrenewals":
        sent_count, failed_count = check_renewal_notifications(bot)
        bot.send_message(
            call.message.chat.id,
            (
                "⏰ <b>Renewal notice check finished.</b>\n\n"
                f"Sent: <b>{sent_count}</b>\n"
                f"Failed: <b>{failed_count}</b>"
            ),
            parse_mode='HTML'
        )
        return

    if action == "userlist":
        send_user_list_report(call.message.chat.id)
        return

    if action == "activeusers":
        show_active_users_report(call.message.chat.id, call.message.message_id)
        return

    if action == "adminlist":
        send_admin_list_report(call.message.chat.id)
        return

    if action == "discounts":
        send_active_discounts_report(call.message.chat.id)
        return

    if action == "removeproduct":
        show_product_removal_list(call.message.chat.id, call.message.message_id)
        return

    if action == "renewproducts":
        show_product_renewable_list(call.message.chat.id, call.message.message_id)
        return

    if action.startswith("togglerenew_"):
        try:
            _, item_id_text, enabled_text = action.split("_", 2)
            item_id = int(item_id_text)
            enabled = bool(int(enabled_text))
        except (TypeError, ValueError):
            bot.send_message(call.message.chat.id, "❌ Invalid renew setting.")
            return
        updated = set_product_renewable(item_id, enabled)
        if not updated:
            bot.send_message(call.message.chat.id, "❌ Product not found.")
            return
        show_product_renewable_list(call.message.chat.id, call.message.message_id)
        return

    if action.startswith("removeproduct_select_"):
        try:
            item_id = int(action.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            bot.send_message(call.message.chat.id, "❌ Invalid product ID.")
            return
        show_product_removal_confirmation(
            call.message.chat.id,
            call.message.message_id,
            item_id
        )
        return

    if action.startswith("removeproduct_confirm_"):
        try:
            item_id = int(action.rsplit("_", 1)[1])
        except (TypeError, ValueError):
            bot.send_message(call.message.chat.id, "❌ Invalid product ID.")
            return
        result = remove_product(item_id)
        if result.get("ok"):
            text = (
                "✅ <b>Product Removed</b>\n\n"
                f"📦 {html.escape(str(result['name']))}\n"
                f"🗑 Removed stock rows: <b>{result['removed_stock_rows']}</b>\n\n"
                "Customer order history ကို မဖျက်ထားပါ။"
            )
            markup = telebot.types.InlineKeyboardMarkup()
            markup.add(
                custom_inline_button(
                    "🗑 Remove Another Product",
                    callback_data="apanel_removeproduct"
                )
            )
            markup.add(
                custom_inline_button(
                    "⬅️ Back to Products",
                    callback_data="apanel_products"
                )
            )
            bot.edit_message_text(
                text,
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode="HTML"
            )
            return

        reason = result.get("reason")
        if reason == "active_orders":
            error_text = (
                "⚠️ Product မှာ active order/reservation "
                f"<b>{int(result.get('active_orders', 0))}</b> ခုရှိနေသောကြောင့် မဖျက်နိုင်ပါ။"
            )
        elif reason == "duplicate_name":
            error_text = "⚠️ နာမည်တူ product ရှိနေသောကြောင့် stock safety အတွက် မဖျက်နိုင်ပါ။"
        else:
            error_text = "❌ Product ရှာမတွေ့ပါ။ ဖျက်ပြီးသားဖြစ်နိုင်ပါတယ်။"
        markup = telebot.types.InlineKeyboardMarkup()
        markup.add(
            custom_inline_button("⬅️ Back", callback_data="apanel_removeproduct")
        )
        bot.edit_message_text(
            error_text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML"
        )
        return

    if action.startswith("adminorders_"):
        order_action = action.replace("adminorders_", "", 1)
        if order_action == "pending":
            orders = get_pending_orders_for_admin(limit=50)
            if not orders:
                bot.send_message(call.message.chat.id, "✅ Pending order မရှိပါ။")
                return
            for row in orders:
                order_id, order_code, user_id, item_name, quantity, method, amount, timestamp = row[:8]
                target_uname = row[8] if len(row) > 8 and row[8] else ""
                buyer_uname = f"@{row[9]}" if len(row) > 9 and row[9] else "မရှိပါ"
                markup = telebot.types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    custom_inline_button("✅ Approve", callback_data=f"admin_approve_{order_id}"),
                    custom_inline_button("❌ Reject", callback_data=f"admin_reject_{order_id}"),
                )
                bot.send_message(
                    call.message.chat.id,
                    f"🔔 <b>Pending Order</b>\n\n"
                    f"👤 User ID: <code>{user_id}</code> ({html.escape(buyer_uname)})\n"
                    f"📦 Item: {html.escape(str(item_name))}\n"
                    f"🔢 Quantity: {int(quantity or 1)}\n"
                    + (f"🎯 <b>Target Username:</b> {html.escape(str(target_uname))}\n" if target_uname else "")
                    + f"💳 Method: {html.escape(str(method or '-'))}\n"
                    f"💰 Amount: {float(amount or 0):,.0f} MMK\n"
                    f"🆔 Order ID: <code>{html.escape(str(order_code))}</code>\n"
                    f"📅 Created: <code>{html.escape(str(timestamp))}</code>",
                    reply_markup=markup, parse_mode="HTML",
                )
            return
        if order_action == "recent":
            orders = get_recent_orders_for_admin(limit=20)
            send_admin_order_report(call.message.chat.id, "Recent Orders", orders)
            return
        if order_action == "userask":
            ask_admin_order_user_id(call.message.chat.id)
            return

    if action.startswith("shop_"):
        status = action.replace("shop_", "", 1)
        set_shop_status(status)
        bot.send_message(call.message.chat.id, f"✅ Shop status set to <b>{html.escape(status)}</b>.", parse_mode="HTML")
        edit_or_send_admin_panel(call.message.chat.id, call.message.message_id, "home")
        return

    if action.startswith("referral_"):
        ref_action = action.replace("referral_", "", 1)
        if ref_action in ("open", "paused"):
            set_referral_status(ref_action)
            bot.send_message(call.message.chat.id, f"✅ Referral status set to <b>{html.escape(ref_action)}</b>.", parse_mode="HTML")
            edit_or_send_admin_panel(call.message.chat.id, call.message.message_id, "home")
            return
        if ref_action == "stats":
            send_referral_stats_report(call.message.chat.id)
            return
        if ref_action == "claims":
            send_referral_claims_report(call.message.chat.id)
            return
        if ref_action == "guide":
            send_referral_admin_guide(call.message.chat.id)
            return

    help_map = {
        "help_addproduct": (
            "Add Product",
            "/addproduct name | details | price | stock | product details | details_en | product details_en",
            "/addproduct Netflix 1M | 1 Month account | 10000 | 5 | Myanmar details | 1 Month account | English details",
        ),
        "help_editproduct": (
            "Edit Product",
            "/editproduct item_id | name | details | price | stock | product details | details_en | product details_en",
            "/editproduct 3 | - | - | 12000 | 7 | - | - | -",
        ),
        "help_addstock": (
            "Add Stock",
            "/addstock item name | account1\naccount2\naccount3",
            "/addstock Netflix 1M | email1:pass1\nemail2:pass2",
        ),
        "help_setstock": (
            "Set Stock",
            "/setstock item_id stock",
            "/setstock 3 7",
        ),
        "help_viewstock": (
            "View & Delete Unsold Stock",
            "/viewstock item_id  AND  /delstock stock_id",
            "/viewstock 2",
        ),
        "help_setrenew": (
            "Set Renew",
            "/setrenew item_id on/off",
            "/setrenew 3 on",
        ),
        "help_setdiscount": (
            "Set Product Discount",
            "/setdiscount item_id sale_price duration OR /setdiscount item_id percent% duration",
            "/setdiscount 3 8000 2d OR /setdiscount 3 20% 2d",
        ),
        "help_send": (
            "Manual Delivery",
            "/deliver order_id account_info",
            "/deliver 123 email@example.com:password",
        ),
        "help_announcement": (
            "Announcement",
            "/announcement message",
            "/announcement ဒီနေ့ discount ရှိပါတယ်",
        ),
        "help_addadmin": (
            "Add Admin",
            "/addadmin user_id",
            "/addadmin 123456789",
        ),
        "help_removeadmin": (
            "Remove Admin",
            "/removeadmin user_id",
            "/removeadmin 123456789",
        ),
    }
    if action in help_map:
        send_admin_help(call.message.chat.id, *help_map[action])


@bot.callback_query_handler(func=lambda call: call.data.startswith('refclaim_'))
def handle_referral_claim_callback(call):
    if not is_admin_user(call.from_user.id):
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True)
        return

    parts = call.data.split("_")
    if len(parts) != 3:
        bot.answer_callback_query(call.id, "Invalid claim action.", show_alert=True)
        return

    action = parts[1]
    try:
        reward_id = int(parts[2])
    except ValueError:
        bot.answer_callback_query(call.id, "Invalid reward ID.", show_alert=True)
        return

    status = "approved" if action == "approve" else "rejected"
    user_id = update_referral_reward_status(reward_id, status)
    if not user_id:
        bot.answer_callback_query(call.id, "Claim not found.", show_alert=True)
        return

    bot.answer_callback_query(call.id, f"Claim {status}.")
    try:
        bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
    except Exception:
        pass

    if status == "approved":
        user_text = (
            "🎉 <b>Referral Reward Approved!</b>\n\n"
            "သင့် referral reward ကို Admin မှ approve လုပ်ပြီးပါပြီ။\n"
            "ဆုထုတ်ယူရန် Admin @independence_N ကို ဆက်သွယ်နိုင်ပါသည်။"
        )
    else:
        user_text = (
            "❌ <b>Referral Reward Rejected</b>\n\n"
            "သင့် referral reward claim ကို Admin မှ reject လုပ်ထားပါသည်။\n"
            "မေးမြန်းလိုပါက Admin @independence_N ကို ဆက်သွယ်ပါ။"
        )

    try:
        bot.send_message(user_id, user_text, parse_mode="HTML")
    except Exception as e:
        print(f"Failed to notify referral reward user {user_id}: {e}")

    bot.send_message(
        call.message.chat.id,
        f"🎁 Reward ID <code>{reward_id}</code> has been <b>{status}</b> for user <code>{user_id}</code>.",
        parse_mode="HTML"
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('discountcast_'))
def handle_discount_broadcast_confirmation(call):
    if not is_admin_user(call.from_user.id):
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True)
        return

    if call.data.startswith('discountcast_skip_'):
        broadcast_id = call.data.replace('discountcast_skip_', '', 1)
        pending_discount_broadcasts.pop(broadcast_id, None)
        bot.answer_callback_query(call.id, "Skipped.")
        bot.edit_message_text(
            "❌ Announcement မပို့တော့ပါ။\n\nDiscount ဈေးနှုန်းနဲ့ expiry timer ကတော့ ဆက်ပြီး active ဖြစ်နေပါမယ်။",
            call.message.chat.id,
            call.message.message_id
        )
        return

    broadcast_id = call.data.replace('discountcast_send_', '', 1)
    pending = pending_discount_broadcasts.pop(broadcast_id, None)
    if not pending:
        bot.answer_callback_query(call.id, "This announcement request expired.", show_alert=True)
        return

    discount, duration_seconds = pending
    bot.answer_callback_query(call.id, "Sending...")
    bot.edit_message_text(
        "📢 <b>Discount announcement ကို user တွေဆီ background မှာ စပို့နေပါပြီ။</b>",
        call.message.chat.id,
        call.message.message_id,
        parse_mode="HTML"
    )
    broadcast_discount_announcement(discount, duration_seconds)


@bot.callback_query_handler(func=lambda call: call.data.startswith('stockcast_'))
def handle_stock_broadcast_confirmation(call):
    if not is_admin_user(call.from_user.id):
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True)
        return

    if call.data.startswith('stockcast_skip_'):
        broadcast_id = call.data.replace('stockcast_skip_', '', 1)
        pending_stock_broadcasts.pop(broadcast_id, None)
        bot.answer_callback_query(call.id, "Skipped.")
        bot.edit_message_text(
            "❌ Stock notification မပို့တော့ပါ။",
            call.message.chat.id,
            call.message.message_id
        )
        return

    broadcast_id = call.data.replace('stockcast_send_', '', 1)
    pending = pending_stock_broadcasts.pop(broadcast_id, None)
    if not pending:
        bot.answer_callback_query(call.id, "This notification request expired.", show_alert=True)
        return
    text, emoji_slots, product_id = pending

    bot.answer_callback_query(call.id, "Sending...")
    sent_count = 0
    failed_count = 0
    for user_id in get_all_user_ids():
        try:
            language = get_user_language(user_id) or "my"
            markup = None
            if product_id:
                markup = telebot.types.InlineKeyboardMarkup()
                label = "🛒 Buy Now" if language == "en" else "🛒 အခုပဲဝယ်မယ်"
                markup.add(custom_inline_button(
                    label, callback_data=f"buy_{product_id}", _emoji_key="buy_now"
                ))
            send_custom_emoji_message(
                bot, user_id, text, emoji_slots, reply_markup=markup
            )
            sent_count += 1
            time.sleep(0.04)
        except Exception:
            failed_count += 1

    bot.edit_message_text(
        (
            "✅ <b>Stock notification sent.</b>\n\n"
            f"Sent: <b>{sent_count}</b>\n"
            f"Failed: <b>{failed_count}</b>"
        ),
        call.message.chat.id,
        call.message.message_id,
        parse_mode='HTML'
    )

# ---------------------------------------------------------
# Admin Commands
# ---------------------------------------------------------

@bot.message_handler(commands=['deliver'])
def handle_deliver_command(message):
    """Deliver one recorded order and keep delivery data/status in sync."""
    if not is_admin_user(message.from_user.id):
        return

    parts = (message.text or '').split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit() or not parts[2].strip():
        bot.reply_to(message, "⚠️ <b>အသုံးပြုပုံ:</b>\n<code>/deliver [order_id] [account_info]</code>\n\nဥပမာ: <code>/deliver 123 email@example.com:password</code>", parse_mode='HTML')
        return

    order_id = int(parts[1])
    account_info = parts[2].strip()
    order = get_order_details(order_id)
    if not order:
        bot.reply_to(message, f"❌ Order ID <code>{order_id}</code> မတွေ့ပါ။", parse_mode='HTML')
        return

    target_user_id = int(order[1])
    item_name = str(order[2])
    quantity = max(1, int(order[3] or 1))
    current_status = str(order[5] or '')
    existing_delivery = str(order[7] or '').strip()
    if current_status.lower() == 'success' or existing_delivery:
        bot.reply_to(message, f"⚠️ Order <code>{order_id}</code> ကို deliver လုပ်ပြီးသားဖြစ်ပါတယ်။ My Orders data မထပ်ရေးရန် command ကိုရပ်ထားပါတယ်။", parse_mode='HTML')
        return

    try:
        reservation_state = claim_stock_reservation_for_processing(order_id, message.from_user.id)
        # Reserved orders already have stock held. Legacy orders need one deduction.
        reduce_stock = reservation_state == 'legacy'
        if reservation_state not in ('claimed', 'legacy', 'active', 'awaiting_review'):
            bot.reply_to(message, f"⚠️ Order <code>{order_id}</code> ကို ဆက်လုပ်လို့မရပါ။ Reservation status: <code>{html.escape(reservation_state)}</code>", parse_mode='HTML')
            return

        update_order_delivery(order_id, account_info)
        update_order_status(order_id, 'Success', reduce_stock=reduce_stock)
        complete_stock_reservation(order_id)
        mark_payment_submission_status(order_id, 'approved', message.from_user.id)

        try:
            send_delivery_message(bot, target_user_id, item_name, account_info)
            send_promotion_gift_choice(bot, order_id, target_user_id)
        except Exception as send_error:
            print(f"Manual delivery customer notification failed for order {order_id}: {send_error}")
        try:
            publish_sell_proof(bot, order_id, message.chat.id)
        except Exception as proof_error:
            print(f"Manual delivery sell proof failed for order {order_id}: {proof_error}")

        bot.reply_to(message, f"✅ Order <code>{order_id}</code> ကို delivered အဖြစ်မှတ်တမ်းတင်ပြီးပါပြီ။\nUser: <code>{target_user_id}</code>\nItem: <b>{html.escape(item_name)}</b>\nQuantity: <b>{quantity}</b>", parse_mode='HTML')
    except Exception as error:
        print(f"Manual delivery failed for order {order_id}: {error}")
        bot.reply_to(message, "❌ Delivery မအောင်မြင်ပါ။ Server log ကိုစစ်ပြီး ထပ်လုပ်ပါ။")


@bot.message_handler(commands=['send'])
def handle_send_command(message):
    """Prevent untracked manual sends from the retired command."""
    if not is_admin_user(message.from_user.id):
        return
    bot.reply_to(message, "ℹ️ <code>/send</code> ကို မသုံးတော့ပါ။ Order history, My Orders နှင့် expiry ကို မှန်စေရန်\n<code>/deliver [order_id] [account_info]</code> ကိုသုံးပါ။\n\nဥပမာ: <code>/deliver 123 email@example.com:password</code>", parse_mode='HTML')


def _message_custom_emoji_ids(message):
    source = message.reply_to_message if message.reply_to_message else message
    return [
        getattr(entity, 'custom_emoji_id', None)
        for entity in (getattr(source, 'entities', None) or [])
        if getattr(entity, 'type', None) == 'custom_emoji' and getattr(entity, 'custom_emoji_id', None)
    ]


@bot.message_handler(commands=['emojiid'])
def handle_custom_emoji_id(message):
    if not is_admin_user(message.from_user.id):
        return
    emoji_ids = _message_custom_emoji_ids(message)
    if not emoji_ids:
        bot.reply_to(
            message,
            "Custom emoji ပါတဲ့ message ကို <b>Reply</b> ပြီး <code>/emojiid</code> ပို့ပါ။\n\n"
            "ဥပမာ: Custom emoji ကိုအရင်ပို့ → အဲဒီစာကို Reply → <code>/emojiid</code>",
            parse_mode='HTML'
        )
        return
    bot.reply_to(message, "Custom Emoji ID:\n<code>" + "\n".join(emoji_ids) + "</code>", parse_mode='HTML')


@bot.message_handler(commands=['setbuttonemoji'])
def handle_set_button_emoji(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip() not in BUTTON_EMOJI_KEYS:
        bot.reply_to(
            message,
            "Usage: Custom emoji ပါတဲ့ message ကို Reply ပြီး\n"
            "<code>/setbuttonemoji button_key</code>\n\n"
            "Keys: <code>" + ", ".join(BUTTON_EMOJI_KEYS) + "</code>",
            parse_mode='HTML'
        )
        return
    emoji_ids = _message_custom_emoji_ids(message)
    if not emoji_ids:
        bot.reply_to(message, "❌ Custom emoji ပါတဲ့ message ကို Reply ပြီး command ပို့ပေးပါ။")
        return
    key = parts[1].strip()
    set_setting(f"custom_button_emoji_{key}", emoji_ids[0])
    bot.reply_to(message, f"✅ <b>{html.escape(key)}</b> button emoji ကို save လုပ်ပြီးပါပြီ။\nID: <code>{emoji_ids[0]}</code>", parse_mode='HTML')


@bot.message_handler(commands=['setmessageemoji'])
def handle_set_message_emoji(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip() not in MESSAGE_EMOJI_KEYS:
        bot.reply_to(
            message,
            "Usage: Custom emoji ပါတဲ့ message ကို Reply ပြီး\n"
            "<code>/setmessageemoji message_key</code>\n\n"
            "Keys: <code>" + ', '.join(MESSAGE_EMOJI_KEYS) + "</code>",
            parse_mode='HTML'
        )
        return
    emoji_ids = _message_custom_emoji_ids(message)
    if not emoji_ids:
        bot.reply_to(message, "❌ Custom emoji ပါတဲ့ message ကို Reply ပြီး command ပို့ပေးပါ။")
        return
    key = parts[1].strip()
    set_setting(f"custom_message_emoji_{key}", emoji_ids[0])
    bot.reply_to(message, f"✅ <b>{html.escape(key)}</b> message emoji ကို save လုပ်ပြီးပါပြီ။", parse_mode='HTML')



@bot.message_handler(commands=['buttoncolor'])
def handle_button_color_command(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = (message.text or "").split()
    if len(parts) < 2 or parts[1].lower() not in ("primary", "success", "danger", "off"):
        current = get_setting("button_style", "primary")
        bot.reply_to(
            message,
            f"🎨 Current Button Color Style: <code>{html.escape(str(current))}</code>\n\n"
            "Usage:\n"
            "• <code>/buttoncolor primary</code> (🟦 Blue/Teal)\n"
            "• <code>/buttoncolor success</code> (🟩 Green)\n"
            "• <code>/buttoncolor danger</code> (🟥 Red)\n"
            "• <code>/buttoncolor off</code> (Default)",
            parse_mode="HTML",
        )
        return
    val = parts[1].lower()
    set_setting("button_style", val)
    bot.reply_to(message, f"✅ Button color style set to <b>{val.upper()}</b>.", parse_mode="HTML")


@bot.message_handler(commands=['customemoji'])
def handle_custom_emoji_toggle(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in ('on', 'off'):
        current = get_setting('custom_emoji_enabled', 'off')
        bot.reply_to(message, f"Current: <code>{current}</code>\nUsage: <code>/customemoji on</code> or <code>/customemoji off</code>", parse_mode='HTML')
        return
    state = parts[1].strip().lower()
    set_setting('custom_emoji_enabled', state)
    bot.reply_to(message, f"✅ Custom emoji buttons: <b>{state.upper()}</b>", parse_mode='HTML')


@bot.message_handler(commands=['setproductemoji'])
def handle_set_product_emoji(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(
            message,
            "Custom emoji ပါတဲ့ message ကို <b>Reply</b> ပြီး\n"
            "<code>/setproductemoji product_id</code> ပို့ပါ။\n\n"
            "ဥပမာ: <code>/setproductemoji 1</code>",
            parse_mode='HTML'
        )
        return
    emoji_ids = _message_custom_emoji_ids(message)
    if not emoji_ids:
        bot.reply_to(message, "❌ Product logo custom emoji ပါတဲ့ message ကို Reply ပြီး command ပို့ပေးပါ။")
        return
    item_id = int(parts[1].strip())
    if not set_product_custom_emoji(item_id, emoji_ids[0]):
        bot.reply_to(message, "❌ Product ID မတွေ့ပါ။ /admin → Products မှာ ID ကိုစစ်ပါ။")
        return
    bot.reply_to(
        message,
        f"✅ Product <code>{item_id}</code> custom emoji ကို save လုပ်ပြီးပါပြီ။\n"
        "Shop page အသစ်ပြန်ဖွင့်လျှင် ပေါ်ပါမည်။",
        parse_mode='HTML'
    )


@bot.message_handler(commands=['removeproductemoji'])
def handle_remove_product_emoji(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        bot.reply_to(message, "Usage: <code>/removeproductemoji product_id</code>", parse_mode='HTML')
        return
    if set_product_custom_emoji(int(parts[1].strip()), None):
        bot.reply_to(message, "✅ Product custom emoji ကိုဖယ်ပြီး Unicode emoji ပြန်သုံးပါမည်။")
    else:
        bot.reply_to(message, "❌ Product ID မတွေ့ပါ။")


@bot.message_handler(commands=['buttonemojis'])
def handle_button_emoji_list(message):
    if not is_admin_user(message.from_user.id):
        return
    rows = ["🎨 <b>Custom Button Emoji Setup</b>"]
    for key in BUTTON_EMOJI_KEYS:
        value = get_setting(f"custom_button_emoji_{key}", '')
        rows.append(f"• <code>{key}</code>: {'✅' if value else '—'}")
    rows.append("\nReply custom emoji → <code>/setbuttonemoji button_key</code>")
    bot.reply_to(message, "\n".join(rows), parse_mode='HTML')


@bot.message_handler(commands=['setpromotion'])
def handle_set_promotion(message):
    if not is_admin_user(message.from_user.id):
        return
    value = message.text.replace('/setpromotion', '', 1).strip()
    if value.lower() in ('on', 'off'):
        set_promotion_config(status=value.lower())
        bot.reply_to(message, f"✅ Promotion is <b>{value.lower()}</b>.", parse_mode='HTML')
        return
    parts = [part.strip() for part in value.split('|')]
    if len(parts) != 3:
        bot.reply_to(message, "Usage:\n<code>/setpromotion on|off</code>\n<code>/setpromotion YYYY-MM-DD | YYYY-MM-DD | minimum_amount</code>", parse_mode='HTML')
        return
    try:
        from datetime import datetime
        start = datetime.strptime(parts[0], '%Y-%m-%d').strftime('%Y-%m-%d 00:00:00')
        end = datetime.strptime(parts[1], '%Y-%m-%d').strftime('%Y-%m-%d 23:59:59')
        minimum = float(parts[2].replace(',', ''))
        if minimum < 0 or start > end:
            raise ValueError
    except ValueError:
        bot.reply_to(message, "❌ Date ကို YYYY-MM-DD format နဲ့၊ minimum amount ကို number ဖြင့်ထည့်ပေးပါ။")
        return
    set_promotion_config(start_at=start, end_at=end, minimum_amount=minimum)
    bot.reply_to(message, f"✅ Promotion period set: <code>{start}</code> to <code>{end}</code>\nMinimum: <b>{int(minimum):,} MMK</b>", parse_mode='HTML')


@bot.message_handler(commands=['addgift'])
def handle_add_gift(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = [part.strip() for part in message.text.replace('/addgift', '', 1).strip().split('|', 1)]
    if not parts or not parts[0]:
        bot.reply_to(message, "Usage: <code>/addgift Gift name | duration/details</code>", parse_mode='HTML')
        return
    gift_id = add_promotion_gift(parts[0], parts[1] if len(parts) > 1 else '')
    bot.reply_to(message, f"✅ Gift added. ID: <code>{gift_id}</code>", parse_mode='HTML')


@bot.message_handler(commands=['addgiftstock'])
def handle_add_gift_stock(message):
    if not is_admin_user(message.from_user.id):
        return
    raw = message.text.replace('/addgiftstock', '', 1).strip()
    if '|' not in raw:
        bot.reply_to(message, "Usage: <code>/addgiftstock gift_id | key1\\nkey2</code>", parse_mode='HTML')
        return
    gift_id_text, content_text = raw.split('|', 1)
    try:
        gift_id = int(gift_id_text.strip())
    except ValueError:
        bot.reply_to(message, "❌ Gift ID must be a number.")
        return
    if not any(gift[0] == gift_id for gift in get_promotion_gifts()):
        bot.reply_to(message, "❌ Gift ID မတွေ့ပါ။")
        return
    added = add_promotion_gift_stock(gift_id, content_text.splitlines())
    bot.reply_to(message, f"✅ Auto-delivery gift stock <b>{added}</b> ခု ထည့်ပြီးပါပြီ။", parse_mode='HTML')


STATUS_NOTIFICATIONS = {
    'open': "✅ <b>ဆိုင်ပြန်ဖွင့်ပါပြီ</b>\n\nလိုအပ်သော Product များကို Bot တွင် ဝယ်ယူနိုင်ပါပြီ။",
    'close': "🛑 <b>ဆိုင်ခေတ္တပိတ်ထားပါသည်</b>\n\nမကြာမီ ပြန်လည်ဖွင့်ပေးပါမည်။",
    'maintenance': "🛠 <b>Bot ကို ခေတ္တပြုပြင်နေပါသည်</b>\n\nအနည်းငယ်ကြာလျှင် ပြန်လည်အသုံးပြုနိုင်ပါမည်။",
}

def broadcast_shop_status(bot_instance, admin_chat_id, status):
    text = STATUS_NOTIFICATIONS.get(status)
    if not text:
        return
    def worker():
        sent = failed = 0
        status_slot = {
            "open": ("✅", "shop_open"),
            "close": ("🛑", "shop_close"),
            "maintenance": ("🛠", "shop_maintenance"),
        }.get(status, ("ℹ️", "info"))
        for user_id in get_all_user_ids():
            try:
                send_custom_emoji_message(bot_instance, user_id, text, (status_slot,))
                sent += 1
            except Exception as error:
                failed += 1
                print(f"Shop status notification failed for {user_id}: {error}")
            time.sleep(0.04)
        if YOUR_CHANNEL_ID:
            try:
                send_custom_emoji_message(bot_instance, YOUR_CHANNEL_ID, text, (status_slot,))
            except Exception as error:
                print(f"Shop status channel notification failed: {error}")
        try:
            bot_instance.send_message(admin_chat_id, f"📢 Status notification finished. Sent: <b>{sent}</b> | Failed: <b>{failed}</b>", parse_mode='HTML')
        except Exception as error:
            print(f"Status broadcast report failed: {error}")
    threading.Thread(target=worker, daemon=True).start()

@bot.message_handler(commands=['open', 'close', 'maintenance'])
def change_status(message):
    if not is_admin_user(message.from_user.id):
        return

    status = message.text[1:]  # /open → open
    # database.py ၏ set_shop_status() ကို သုံးခြင်းဖြင့်
    # row မရှိသော်လည်း INSERT OR REPLACE ဖြင့် အမြဲ အလုပ်လုပ်မည်
    set_shop_status(status)

    status_msg = {
        'open':        "✅ ဆိုင်ကို ပြန်ဖွင့်လိုက်ပါပြီ၊၊",
        'close':       "🛑 ဆိုင်ကို ပိတ်လိုက်ပါပြီ၊၊",
        'maintenance': "🛠 Bot ကို Maintenance Mode ပြောင်းလိုက်ပါပြီ၊၊"
    }
    bot.reply_to(message, status_msg.get(status, "Status updated!"))
    broadcast_shop_status(bot, message.chat.id, status)
    bot.send_message(message.chat.id, "📢 User အားလုံးထံ status notification ပို့နေပါသည်...", parse_mode='HTML')


@bot.message_handler(commands=['addproduct'])
def handle_addproduct(message):
    if not is_admin_user(message.from_user.id):
        return

    raw_text = message.text.replace('/addproduct', '', 1).strip()
    parts = [part.strip() for part in raw_text.split('|')]
    if len(parts) < 5:
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/addproduct name | details | price | stock | product details | details_en | product details_en</code>\n\n"
            "Example:\n"
            "<code>/addproduct Netflix 1M | 1 Month account | 10000 | 5 | Myanmar details | 1 Month account | English details</code>",
            parse_mode='HTML'
        )
        return

    name, details, price_text, stock_text, product_info = parts[:5]
    details_en = parts[5] if len(parts) > 5 and parts[5] else None
    product_info_en = parts[6] if len(parts) > 6 and parts[6] else None

    try:
        price = float(price_text.replace(',', ''))
        stock = int(stock_text)
    except ValueError:
        bot.reply_to(message, "Price must be a number and stock must be an integer.")
        return

    item_id = add_product(name, details, price, stock, product_info, details_en, product_info_en)
    bot.reply_to(
        message,
        (
            "✅ <b>Product added successfully.</b>\n\n"
            f"ID: <code>{item_id}</code>\n"
            f"Name: <b>{html.escape(name)}</b>\n"
            f"Price: <b>{int(price):,} MMK</b>\n"
            f"Stock: <b>{stock}</b>"
        ),
        parse_mode='HTML'
    )


    if stock > 0:
        ask_stock_broadcast_confirmation(message, name, price=price, stock=stock, is_new=True)


@bot.message_handler(commands=['addstock'])
def handle_addstock(message):
    if not is_admin_user(message.from_user.id):
        return

    raw_text = message.text.replace('/addstock', '', 1).strip()
    if '|' not in raw_text:
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/addstock item name | account1\naccount2\naccount3</code>\n\n"
            "Each line after | will be added as one stock account.",
            parse_mode='HTML'
        )
        return

    item_name, accounts_text = [part.strip() for part in raw_text.split('|', 1)]
    accounts = accounts_text.splitlines()
    added_count = add_item_stock_accounts(item_name, accounts)
    if added_count <= 0:
        bot.reply_to(message, "No stock account was added.")
        return

    bot.reply_to(
        message,
        (
            "✅ <b>Stock added successfully.</b>\n\n"
            f"Item: <b>{html.escape(item_name)}</b>\n"
            f"Added: <b>{added_count}</b> accounts"
        ),
        parse_mode='HTML'
    )


    item = get_item_by_name(item_name)
    if item:
        notify_waitlist_users(bot, item[0])
    price = item[3] if item else None
    current_stock = item[4] if item else added_count
    ask_stock_broadcast_confirmation(message, item_name, price=price, stock=current_stock, is_new=False)


@bot.message_handler(commands=['editproduct'])
def handle_editproduct(message):
    if not is_admin_user(message.from_user.id):
        return

    raw_text = message.text.replace('/editproduct', '', 1).strip()
    parts = [part.strip() for part in raw_text.split('|')]
    if len(parts) < 2:
        bot.reply_to(
            message,
            "Usage:\n"
            "<code>/editproduct item_id | name | details | price | stock | product details | details_en | product details_en</code>\n\n"
            "Use <code>-</code> for fields you do not want to change.\n"
            "Example:\n"
            "<code>/editproduct 3 | - | - | 12000 | 7 | - | - | -</code>",
            parse_mode='HTML'
        )
        return

    try:
        item_id = int(parts[0])
    except ValueError:
        bot.reply_to(message, "item_id must be a number.")
        return

    if not get_item_by_id(item_id):
        bot.reply_to(message, f"Product ID {item_id} not found.")
        return

    fields = parts[1:] + ["-"] * (7 - len(parts[1:]))
    name, details, price_text, stock_text, product_info, details_en, product_info_en = fields[:7]

    def clean(value):
        return None if value == "-" or value == "" else value

    price = clean(price_text)
    stock = clean(stock_text)
    try:
        if price is not None:
            price = float(price.replace(',', ''))
        if stock is not None:
            stock = int(stock)
    except ValueError:
        bot.reply_to(message, "Price must be a number and stock must be an integer.")
        return

    updated = update_product(
        item_id,
        name=clean(name),
        details=clean(details),
        price=price,
        stock=stock,
        product_info=clean(product_info),
        details_en=clean(details_en),
        product_info_en=clean(product_info_en),
    )
    if not updated:
        bot.reply_to(message, "No product field was updated.")
        return

    bot.reply_to(message, f"✅ Product <code>{item_id}</code> updated successfully.", parse_mode='HTML')


@bot.message_handler(commands=['setstock'])
def handle_setstock(message):
    if not is_admin_user(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(message, "Usage:\n<code>/setstock item_id stock</code>\nExample: <code>/setstock 3 7</code>", parse_mode='HTML')
        return

    try:
        item_id = int(parts[1])
        stock = int(parts[2])
    except ValueError:
        bot.reply_to(message, "item_id and stock must be numbers.")
        return

    if stock < 0:
        bot.reply_to(message, "Stock cannot be negative.")
        return

    updated = set_product_stock(item_id, stock)
    if not updated:
        bot.reply_to(message, f"Product ID {item_id} not found.")
        return

    bot.reply_to(message, f"✅ Product <code>{item_id}</code> stock set to <b>{stock}</b>.", parse_mode='HTML')


    if stock > 0:
        item = get_item_by_id(item_id)
        if item:
            notify_waitlist_users(bot, item[0])
            ask_stock_broadcast_confirmation(message, item[1], price=item[3], stock=stock, is_new=False)


@bot.message_handler(commands=['setrenew'])
def handle_setrenew(message):
    if not is_admin_user(message.from_user.id):
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        bot.reply_to(
            message,
            "Usage:\n<code>/setrenew item_id on/off</code>\nExample: <code>/setrenew 3 on</code>",
            parse_mode='HTML'
        )
        return

    try:
        item_id = int(parts[1])
    except ValueError:
        bot.reply_to(message, "item_id must be a number.")
        return

    value = parts[2].strip().lower()
    if value not in ("on", "off", "1", "0", "yes", "no", "true", "false"):
        bot.reply_to(message, "Renew value must be on or off.")
        return

    enabled = value in ("on", "1", "yes", "true")
    updated = set_product_renewable(item_id, enabled)
    if not updated:
        bot.reply_to(message, f"Product ID {item_id} not found.")
        return

    status = "ON" if enabled else "OFF"
    bot.reply_to(
        message,
        f"✅ Product <code>{item_id}</code> renew setting is now <b>{status}</b>.",
        parse_mode='HTML'
    )


def send_active_discounts_report(chat_id):
    discounts = get_active_discounts()
    if not discounts:
        bot.send_message(chat_id, "🏷 Active discount မရှိသေးပါ။")
        return
    lines = ["🏷 <b>Active Discounts</b>", ""]
    for item_id, name, original, discounted, percent, _, ends_at in discounts:
        lines.extend([
            f"🔥 <b>{html.escape(str(name))}</b> (ID: <code>{item_id}</code>)",
            f"Discount: <b>{percent:g}%</b>",
            f"Price: <s>{format_mmk(original)}</s> → <b>{format_mmk(discounted)}</b>",
            f"Ends: <b>{html.escape(str(ends_at))}</b>",
            f"Cancel: <code>/canceldiscount {item_id}</code>",
            "",
        ])
    bot.send_message(chat_id, "\n".join(lines), parse_mode="HTML")

@bot.message_handler(commands=['setdiscount'])
def handle_set_discount(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 4:
        bot.reply_to(
            message,
            "Usage: <code>/setdiscount item_id sale_price duration</code>\n"
            "Example: <code>/setdiscount 3 8000 2d</code>\n\n"
            "Percent နဲ့ဆို: <code>/setdiscount 3 20% 2d</code>\n"
            "Duration: <code>2d</code>, <code>12h</code>, or <code>30m</code>",
            parse_mode="HTML"
        )
        return
    try:
        item_id = int(parts[1])
        discount_value_text = parts[2].replace(",", "")
        discount_value = float(discount_value_text.replace("%", ""))
    except ValueError:
        bot.reply_to(message, "item_id နဲ့ discount value က number ဖြစ်ရပါမယ်။")
        return
    duration_seconds = parse_discount_duration(parts[3])
    if duration_seconds is None:
        bot.reply_to(message, "Duration မှားနေပါတယ်။ ဥပမာ: <code>2d</code>, <code>12h</code>, <code>30m</code>", parse_mode="HTML")
        return

    use_percent = discount_value_text.endswith("%") or discount_value <= 100
    try:
        discount = set_product_discount(
            item_id,
            discount_value if use_percent else None,
            duration_seconds,
            message.from_user.id,
            sale_price=None if use_percent else discount_value,
        )
    except ValueError as error:
        bot.reply_to(message, f"❌ {html.escape(str(error))}", parse_mode="HTML")
        return
    if not discount:
        bot.reply_to(message, f"Product ID {item_id} မတွေ့ပါ။")
        return
    ask_discount_broadcast_confirmation(message, discount, duration_seconds)

@bot.message_handler(commands=['canceldiscount'])
def handle_cancel_discount(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) != 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: <code>/canceldiscount item_id</code>", parse_mode="HTML")
        return
    item_id = int(parts[1])
    if cancel_product_discount(item_id):
        bot.reply_to(message, f"✅ Product <code>{item_id}</code> discount ပိတ်ပြီး မူလဈေးပြန်ထားပါပြီ။", parse_mode="HTML")
    else:
        bot.reply_to(message, "Active discount မတွေ့ပါ။")

@bot.message_handler(commands=['discounts'])
def handle_active_discounts(message):
    if not is_admin_user(message.from_user.id):
        return
    send_active_discounts_report(message.chat.id)

@bot.message_handler(commands=['announcement'])
def broadcast(message):
    if not is_admin_user(message.from_user.id):
        return

    command_parts = message.text.split(maxsplit=1)
    if len(command_parts) < 2 or not command_parts[1].strip():
        bot.reply_to(message, "💡 သုံးနည်း: /announcement [စာသား]")
        return
    text_to_send = command_parts[1].strip()
    custom_emoji_entities = announcement_custom_emoji_entities(message, text_to_send)

    admin_chat_id = message.chat.id
    bot.reply_to(message, "📢 Announcement ကို background မှာ စပို့နေပါပြီ။", parse_mode='HTML')

    def worker():
        count = failed_count = blocked_count = 0
        for user_id in get_all_user_ids():
            try:
                send_announcement_message(user_id, text_to_send, custom_emoji_entities)
                count += 1
            except Exception as error:
                failed_count += 1
                if is_bot_unreachable_error(error):
                    mark_user_inactive(user_id)
                    blocked_count += 1
            time.sleep(0.04)

        channel_sent = False
        if YOUR_CHANNEL_ID:
            try:
                send_announcement_message(YOUR_CHANNEL_ID, text_to_send, custom_emoji_entities)
                channel_sent = True
            except Exception as error:
                print(f"Announcement channel send failed: {error}")

        result_text = (
            "✅ <b>Announcement ပို့ဆောင်ပြီးပါပြီ။</b>\n\n"
            f"👥 Users: <b>{count}</b> ပို့ပြီး / <b>{failed_count}</b> မအောင်မြင်\n"
            f"🚫 Blocked/Inactivated: <b>{blocked_count}</b>\n"
            f"📢 Channel: <b>{'ပို့ပြီး' if channel_sent else 'မအောင်မြင်'}</b>"
        )
        try:
            bot.send_message(admin_chat_id, result_text, parse_mode='HTML')
        except Exception as error:
            print(f"Announcement report failed: {error}")

    threading.Thread(target=worker, daemon=True).start()


@bot.message_handler(commands=['userlist'])
def handle_userlist(message):
    if not is_admin_user(message.from_user.id):
        return

    total_users = get_user_count()
    users = get_users_for_admin(limit=50)
    if not users:
        bot.reply_to(message, "👥 <b>User မရှိသေးပါ။</b>", parse_mode='HTML')
        return

    lines = [
        "👥 <b>User List</b>",
        f"Total users: <b>{total_users}</b>",
        "Showing latest 50 users",
        ""
    ]

    for index, user in enumerate(users, start=1):
        user_id, join_date, role, username, first_name, last_name, order_count, success_count = user
        full_name = " ".join(part for part in [first_name, last_name] if part).strip()
        username_text = f"@{username}" if username else "-"
        name_text = html.escape(full_name) if full_name else "-"
        lines.extend([
            f"{index}. <code>{user_id}</code>",
            f"Name: {name_text}",
            f"Username: {html.escape(username_text)}",
            f"Joined: {html.escape(str(join_date or '-'))}",
            f"Role: {html.escape(str(role or 'user'))}",
            f"Orders: {order_count or 0} | Success: {success_count or 0}",
            ""
        ])

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        bot.send_message(message.chat.id, text[start:start + 3900], parse_mode='HTML')


@bot.message_handler(commands=['monthlyreport'])
def handle_monthly_report(message):
    if not is_admin_user(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    year_month = parts[1].strip() if len(parts) > 1 else None
    if year_month and not re.match(r"^\d{4}-\d{2}$", year_month):
        bot.reply_to(message, "Usage: <code>/monthlyreport</code> or <code>/monthlyreport 2026-06</code>", parse_mode='HTML')
        return

    report = get_monthly_sales_report(year_month)
    rows = report["items"]
    total_mmk = int(report["total_amount"] or 0)
    total_usd = total_mmk / MMK_PER_USD if MMK_PER_USD else 0

    lines = [
        "📊 <b>ENI Premium Store - လစဉ် အရောင်းစာရင်းချုပ်</b>",
        f"🗓 <b>သတ်မှတ်လ:</b> {html.escape(report['year_month'])}",
        "━━━━━━━━━━━━━━━━━━━━",
        "",
        f"📈 <b>စုစုပေါင်း အော်ဒါအရေအတွက်:</b> {report['total_order_count']} ခု",
        f"📦 <b>စုစုပေါင်း ရောင်းရသောပမာဏ:</b> {report['total_quantity']} ခု",
        f"💰 <b>စုစုပေါင်း ဝင်ငွေ (MMK):</b> {total_mmk:,} MMK",
        f"💵 <b>စုစုပေါင်း ဝင်ငွေ (USD/USDT):</b> {total_usd:.2f} USD",
        "",
        "📋 <b>ဝယ်ယူထားသော ပစ္စည်းများနှင့် အရေအတွက်စာရင်း:</b>",
        "━━━━━━━━━━━━━━━━━━━━",
    ]

    if not rows:
        lines.append("<i>ယခုလအတွင်း ရောင်းချမှု မရှိသေးပါ။</i>")
    else:
        for index, (item_name, qty, amount, order_count) in enumerate(rows, start=1):
            lines.extend([
                f"{index}. 📦 <b>{html.escape(str(item_name))}</b>",
                f"   ├ အရေအတွက်: <b>{int(qty or 0)} ခု</b>",
                f"   ├ အော်ဒါ: <b>{int(order_count or 0)} ခု</b>",
                f"   └ စုစုပေါင်း: <b>{int(amount or 0):,} MMK</b>",
                ""
            ])

    lines.extend([
        "━━━━━━━━━━━━━━━━━━━━",
        "⚡ <i>စာရင်းအင်းများကို ကုမ္ပဏီ စနစ်မှ ထုတ်ပေးထားပါသည်။</i>"
    ])

    text = "\n".join(lines)
    for start in range(0, len(text), 3900):
        bot.send_message(message.chat.id, text[start:start + 3900], parse_mode='HTML')
    return

@bot.message_handler(commands=['yearlyreport'])
def handle_yearly_report(message):
    if not is_admin_user(message.from_user.id):
        return

    parts = message.text.split(maxsplit=1)
    year = parts[1].strip() if len(parts) > 1 else None
    if year and not re.match(r"^\d{4}$", year):
        bot.reply_to(message, "Usage: <code>/yearlyreport</code> or <code>/yearlyreport 2026</code>", parse_mode='HTML')
        return

    send_yearly_sales_report(message.chat.id, year)
    return


@bot.message_handler(commands=['backupdb'])
def handle_backup_db(message):
    if not is_admin_user(message.from_user.id):
        return

    if not os.path.exists(DATABASE_NAME):
        bot.reply_to(message, "❌ Database file မတွေ့ပါ။", parse_mode='HTML')
        return

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_filename = f"shop_backup_{timestamp}.db"
    backup_path = os.path.join(tempfile.gettempdir(), backup_filename)

    try:
        with get_db_connection() as source_conn:
            with sqlite3.connect(backup_path) as backup_conn:
                source_conn.backup(backup_conn)

        with open(backup_path, "rb") as backup_file:
            bot.send_document(
                message.chat.id,
                backup_file,
                visible_file_name=backup_filename,
                caption=(
                    "💾 <b>Database Backup</b>\n\n"
                    f"File: <code>{html.escape(backup_filename)}</code>\n"
                    f"Time: <code>{html.escape(time.strftime('%Y-%m-%d %H:%M:%S'))}</code>"
                ),
                parse_mode='HTML'
            )
    except Exception as e:
        bot.reply_to(message, f"❌ Backup မအောင်မြင်ပါ။\n<code>{html.escape(str(e))}</code>", parse_mode='HTML')
    finally:
        try:
            if os.path.exists(backup_path):
                os.remove(backup_path)
        except Exception as cleanup_err:
            print(f"Backup cleanup failed: {cleanup_err}")


@bot.message_handler(commands=['addadmin'])
def handle_add_admin(message):
    if not is_master_admin(message.from_user.id):
        bot.reply_to(message, "❌ Master admin only.", parse_mode='HTML')
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not re.match(r"^-?\d+$", parts[1].strip()):
        bot.reply_to(message, "Usage:\n<code>/addadmin user_id</code>", parse_mode='HTML')
        return

    new_admin_id = int(parts[1].strip())
    added, reason = add_admin_user(new_admin_id, added_by=message.from_user.id)
    if added:
        bot.reply_to(message, f"✅ Admin အသစ်ခန့်ပြီးပါပြီ။\nUser ID: <code>{new_admin_id}</code>", parse_mode='HTML')
        set_bot_commands(bot)
        try:
            bot.send_message(new_admin_id, "🛡 သင့်ကို ENI Premium Store admin အဖြစ်ခန့်ထားပါသည်။\n/admin ကိုနှိပ်ပြီး panel ဝင်နိုင်ပါသည်။")
        except Exception as e:
            print(f"Failed to notify new admin {new_admin_id}: {e}")
        return

    if reason == "master":
        bot.reply_to(message, "👑 ဒီ user က master admin ဖြစ်ပြီးသားပါ။", parse_mode='HTML')
    else:
        bot.reply_to(message, "ℹ️ ဒီ user က admin ဖြစ်ပြီးသားပါ။", parse_mode='HTML')


@bot.message_handler(commands=['removeadmin'])
def handle_remove_admin(message):
    if not is_master_admin(message.from_user.id):
        bot.reply_to(message, "❌ Master admin only.", parse_mode='HTML')
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or not re.match(r"^-?\d+$", parts[1].strip()):
        bot.reply_to(message, "Usage:\n<code>/removeadmin user_id</code>", parse_mode='HTML')
        return

    target_admin_id = int(parts[1].strip())
    removed, reason = remove_admin_user(target_admin_id)
    if removed:
        clear_admin_command_scope(target_admin_id)
        bot.reply_to(message, f"✅ Admin permission ပြန်သိမ်းပြီးပါပြီ။\nUser ID: <code>{target_admin_id}</code>", parse_mode='HTML')
        set_bot_commands(bot)
        try:
            bot.send_message(target_admin_id, "ℹ️ သင့် admin permission ကို ပြန်သိမ်းထားပါသည်။")
        except Exception as e:
            print(f"Failed to notify removed admin {target_admin_id}: {e}")
        return

    if reason == "master":
        bot.reply_to(message, "👑 Master admin ကို remove လုပ်လို့မရပါ။", parse_mode='HTML')
    else:
        cleared = clear_admin_command_scope(target_admin_id)
        bot.reply_to(
            message,
            ("✅ ဒီ user က admin မဟုတ်တော့ပါ။ ကျန်နေတဲ့ admin command menu ကို ရှင်းပြီးပါပြီ။"
             if cleared else "ℹ️ ဒီ user ကို admin list ထဲမှာမတွေ့ပါ။"),
        )


@bot.message_handler(commands=['adminlist'])
def handle_admin_list(message):
    if not is_admin_user(message.from_user.id):
        return
    send_admin_list_report(message.chat.id)


@bot.message_handler(commands=['checkrenewals'])
def handle_check_renewals(message):
    if not is_admin_user(message.from_user.id):
        return

    sent_count, failed_count = check_renewal_notifications(bot)
    bot.reply_to(
        message,
        (
            "⏰ <b>Renewal notice check finished.</b>\n\n"
            f"Sent: <b>{sent_count}</b>\n"
            f"Failed: <b>{failed_count}</b>"
        ),
        parse_mode='HTML'
    )




@bot.callback_query_handler(func=lambda call: call.data.startswith(("outline_suspend_", "outline_delete_")))
def handle_admin_outline_key_action(call):
    if not is_admin_user(call.from_user.id):
        bot.answer_callback_query(call.id, "Admin only.", show_alert=True)
        return
    parts = call.data.split("_", 2)
    action, key_id = parts[1], parts[2]
    if action == "suspend":
        res = suspend_access_key(key_id)
        msg = f"✅ Key {key_id} ကို 0MB limit ဖြင့် ခေတ္တပိတ်ထားလိုက်ပါပြီ။" if res.get("ok") else f"❌ Error: {res.get('reason')}"
    else:
        res = delete_access_key(key_id)
        msg = f"🗑 Key {key_id} ကို Outline Server ပေါ်မှ အပြီးဖျက်ပြီးပါပြီ။" if res.get("ok") else f"❌ Error: {res.get('reason')}"
    bot.answer_callback_query(call.id, msg[:190], show_alert=True)
    if res.get("ok"):
        bot.send_message(call.message.chat.id, f"🔐 <b>Outline Key Action:</b>\n{html.escape(msg)}", parse_mode="HTML")


@bot.message_handler(commands=['outlinestatus'])
def handle_outline_status(message):
    if not is_admin_user(message.from_user.id):
        return
    st = get_server_status()
    if not st.get("ok"):
        bot.reply_to(message, f"⚠️ Outline API Error:\n<code>{html.escape(str(st.get('reason')))}</code>", parse_mode="HTML")
        return
    bot.reply_to(
        message,
        "🖥 <b>Outline Server Status</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🏷 <b>Server:</b> {html.escape(str(st['name']))}\n"
        f"🔢 <b>Version:</b> <code>{html.escape(str(st['version']))}</code>\n"
        f"🔌 <b>Port:</b> <code>{st['port']}</code>\n"
        f"🔑 <b>Active Keys:</b> <b>{st['total_keys']}</b> ခု\n"
        f"📊 <b>Total Traffic (30d):</b> <b>{st['total_gb']} GB</b>\n\n"
        "👇 <b>Key တစ်ခုချင်းစီ၏ Usage နှင့် သက်တမ်းကုန်မည့်ရက်များကို အောက်ပါခလုတ်များဖြင့် ကြည့်ရှုနိုင်ပါသည် -</b>",
        reply_markup=build_outline_status_markup(),
        parse_mode="HTML",
    )


@bot.message_handler(commands=['outlinekeys'])
def handle_outline_keys_cmd(message):
    if not is_admin_user(message.from_user.id):
        return
    send_outline_keys_usage_report(message.chat.id, page=0)


@bot.message_handler(commands=['expiring'])
def handle_expiring_orders_cmd(message):
    if not is_admin_user(message.from_user.id):
        return
    send_expiring_orders_dashboard(message.chat.id)


@bot.message_handler(commands=['viewstock'])
def handle_view_stock(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: <code>/viewstock [item_id]</code>", parse_mode="HTML")
        return
    item_name, rows = get_unsold_stock_rows(int(parts[1]), limit=30)
    if item_name is None:
        bot.reply_to(message, "❌ Product ID မတွေ့ပါ။")
        return
    if not rows:
        bot.reply_to(message, f"📦 <b>{html.escape(item_name)}</b> အတွက် Unsold stock မရှိပါ။", parse_mode="HTML")
        return
    lines = [f"📦 <b>{html.escape(item_name)} — Unsold Stock (Top 30)</b>", ""]
    for stock_id, info in rows:
        lines.append(f"• ID <code>{stock_id}</code>: <code>{html.escape(str(info)[:80])}</code>")
    lines.append("\nဖျက်လိုပါက: <code>/delstock [stock_id]</code>")
    bot.reply_to(message, "\n".join(lines)[:3900], parse_mode="HTML")


@bot.message_handler(commands=['delstock'])
def handle_delete_stock(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: <code>/delstock [stock_id]</code>", parse_mode="HTML")
        return
    res = delete_unsold_stock_row(int(parts[1]))
    if res.get("ok"):
        bot.reply_to(message, f"✅ Stock ID <code>{parts[1]}</code> ({html.escape(res['item_name'])}) ကို ဖျက်ပြီးပါပြီ။", parse_mode="HTML")
    else:
        bot.reply_to(message, f"❌ မအောင်မြင်ပါ: <code>{html.escape(str(res.get('reason')))}</code>", parse_mode="HTML")


@bot.message_handler(commands=['setrate'])
def handle_set_usd_rate(message):
    if not is_admin_user(message.from_user.id):
        return
    parts = message.text.split()
    if len(parts) < 2:
        current_rate = get_mmk_per_usd()
        bot.reply_to(message, f"Current Rate: <b>1 USD = {current_rate:,.0f} MMK</b>\nUsage: <code>/setrate 4800</code>", parse_mode="HTML")
        return
    try:
        new_rate = set_mmk_per_usd(float(parts[1].replace(",", "")))
        bot.reply_to(message, f"✅ USD Exchange Rate ကို <b>1 USD = {new_rate:,.0f} MMK</b> သို့ ပြောင်းလဲပြီးပါပြီ။", parse_mode="HTML")
    except ValueError:
        bot.reply_to(message, "❌ Rate ကို ဂဏန်းဖြင့်သာ ထည့်သွင်းပါ။")


@bot.message_handler(commands=['addgw'])
def handle_add_giveaway_item(message):
    if not is_admin_user(message.from_user.id):
        return
    raw = message.text.replace('/addgw', '', 1).strip()
    parts = [p.strip() for p in raw.split('|')]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        bot.reply_to(
            message,
            "Usage: <code>/addgw Name | Content | Stock | Rules</code>\n"
            "Example: <code>/addgw Netflix 1M | mail:pass | 1 | Password မချိန်းရပါ</code>",
            parse_mode="HTML",
        )
        return
    name, content = parts[0], parts[1]
    stock = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 1
    rules = parts[3] if len(parts) > 3 and parts[3] else "မည်သူ့ကိုမျှ မမျှဝေပါနှင့်၊၊"
    gw_id = add_gw_item(name, content, stock=stock, rules=rules)
    bot.reply_to(
        message,
        f"✅ Giveaway item added (ID: <code>{gw_id}</code>)\nName: <b>{html.escape(name)}</b>\nStock: <b>{stock}</b>",
        parse_mode="HTML",
    )


def set_bot_commands(bot):
    user_commands = [
        telebot.types.BotCommand("start", "Bot ကိုစတင်ရန်"),
        telebot.types.BotCommand("home",  "ပင်မစာမျက်နှာသို့သွားရန်"),
        telebot.types.BotCommand("profile", "Profile နှင့် Wallet ကြည့်ရန်"),
        telebot.types.BotCommand("2fa", "2FA OTP ကုဒ်ထုတ်ရန်"),
        telebot.types.BotCommand("language", "Change language"),
        telebot.types.BotCommand("help",  "အကူအညီရယူရန်"),
    ]
    bot.set_my_commands(user_commands, scope=telebot.types.BotCommandScopeAllPrivateChats())

    admin_commands = user_commands + [
        telebot.types.BotCommand("admin", "Admin panel"),
        telebot.types.BotCommand("backupdb", "Backup shop database"),
        telebot.types.BotCommand("adminlist", "Show admin list"),
        telebot.types.BotCommand("addadmin", "Master only: add admin"),
        telebot.types.BotCommand("removeadmin", "Master only: remove admin"),
        telebot.types.BotCommand("monthlyreport", "Show monthly sales report"),
        telebot.types.BotCommand("yearlyreport", "Show yearly sales report"),
        telebot.types.BotCommand("setrenew", "Set product renew on/off"),
        telebot.types.BotCommand("setdiscount", "Set product discount"),
        telebot.types.BotCommand("discounts", "Show active discounts"),
        telebot.types.BotCommand("canceldiscount", "Cancel product discount"),
        telebot.types.BotCommand("setpromotion", "Set promotion status and period"),
        telebot.types.BotCommand("addgift", "Add a promotion gift"),
        telebot.types.BotCommand("addgiftstock", "Add auto-delivery gift stock"),
        telebot.types.BotCommand("sendgift", "Manually deliver a promotion gift"),
        telebot.types.BotCommand("deliver", "Deliver a recorded order"),
        telebot.types.BotCommand("viewstock", "View unsold stock by item ID"),
        telebot.types.BotCommand("delstock", "Delete an unsold stock row"),
        telebot.types.BotCommand("setrate", "Set MMK per USD exchange rate"),
        telebot.types.BotCommand("outlinestatus", "Show Outline server status"),
        telebot.types.BotCommand("outlinekeys", "Show per-key Outline data usage"),
        telebot.types.BotCommand("expiring", "Show expiring & expired customer orders"),
        telebot.types.BotCommand("addgw", "Add a giveaway item"),
    ]
    for admin_id in get_all_admin_ids():
        try:
            bot.set_my_commands(
                admin_commands,
                scope=telebot.types.BotCommandScopeChat(chat_id=admin_id)
            )
        except Exception as e:
            print(f"Failed to set admin commands for {admin_id}: {e}")


def clear_admin_command_scope(user_id):
    """Delete a former admin's per-chat command list."""
    try:
        bot.delete_my_commands(
            scope=telebot.types.BotCommandScopeChat(chat_id=int(user_id))
        )
        return True
    except Exception as error:
        print(f"Failed to clear admin commands for {user_id}: {error}")
        return False


set_bot_commands(bot)
start_renewal_notifier(bot)
start_admin_expiry_notifier(bot)
start_discount_expiry_checker(bot)
start_stock_reservation_expiry_checker(bot)

# ၄။ Bot စတင်ခြင်း
if __name__ == "__main__":
    print("🤖 Bot is running...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
