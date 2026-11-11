import base64
import hashlib
import hmac
import html
import struct
import time
from telebot import types
from handlers.custom_emoji import custom_inline_button
from database import (
    get_user_language, is_admin_user, get_all_admin_ids,
    add_stock_waitlist, pop_stock_waitlist_users, get_item_by_id,
    get_order_details, get_public_order_id, create_support_ticket,
    close_support_ticket, get_user_profile_stats, get_valid_referral_count,
    claim_daily_checkin, redeem_points_to_wallet, get_user_wallet,
    create_wallet_topup_request, process_wallet_topup_request,
    adjust_user_wallet_balance, OUTLINE_GUIDE_POST_URL,
    find_bot_user_by_identifier, transfer_wallet_balance_between_users
)

pending_2fa_users = set()
pending_ticket_orders = {}    # user_id -> order_id
pending_admin_replies = {}    # admin_id -> (ticket_id, target_user_id)
pending_gift_notes = {}       # user_id -> order_id
pending_topup_Basic = {}      # user_id -> (amount, method)
pending_wallet_transfer_user = set()
pending_wallet_transfer_amt = {}   # sender_id -> recipient_dict


def generate_totp_code(secret_key):
    cleaned = "".join(str(secret_key or "").split()).upper().replace("-", "")
    if not cleaned:
        raise ValueError("Empty secret key")
    missing_padding = len(cleaned) % 8
    if missing_padding:
        cleaned += "=" * (8 - missing_padding)
    key_bytes = base64.b32decode(cleaned, casefold=True)
    now_sec = int(time.time())
    counter = now_sec // 30
    remaining_sec = 30 - (now_sec % 30)
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key_bytes, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code_int = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000
    return f"{code_int:06d}", remaining_sec


def notify_waitlist_users(bot, item_id):
    item = get_item_by_id(item_id)
    if not item or int(item[4] or 0) <= 0:
        return 0
    waiting_users = pop_stock_waitlist_users(item_id)
    if not waiting_users:
        return 0
    item_name = html.escape(str(item[1]))
    price_mmk = f"{int(float(item[3] or 0)):,} MMK"
    sent = 0
    for uid in waiting_users:
        lang = get_user_language(uid) or "my"
        markup = types.InlineKeyboardMarkup()
        btn_label = "🛒 Buy Now" if lang == "en" else "🛒 အခုပဲဝယ်ယူမည်"
        markup.add(custom_inline_button(btn_label, callback_data=f"buy_{item_id}"))
        text = (
            f"🔔 <b>Restock Alert!</b>\n\n📦 <b>{item_name}</b> is back in stock ({price_mmk})!"
            if lang == "en" else
            f"🔔 <b>Stock ပြန်ဝင်ပါပြီ! (Restock Alert)</b>\n\n"
            f"သင်စောင့်ဆိုင်းနေသော 📦 <b>{item_name}</b> ပစ္စည်း Stock ပြန်ဖြည့်ပြီးပါပြီ!\n"
            f"💰 <b>ဈေးနှုန်း:</b> {price_mmk}"
        )
        try:
            bot.send_message(uid, text, reply_markup=markup, parse_mode="HTML")
            sent += 1
        except Exception:
            pass
    return sent


def init_extra_tool_handlers(bot):

    # =========================================================
    # 1. Profile, VIP Status & Wallet Overview
    # =========================================================
    def send_user_profile(chat_id, user, message_id=None):
        lang = get_user_language(user.id) or "my"
        stats = get_user_profile_stats(user.id)
        refs = get_valid_referral_count(user.id)
        full_name = html.escape(user.first_name or "User")
        uname = f"@{html.escape(user.username)}" if user.username else "-"
        role_badge = stats.get("role", "user").upper()

        if lang == "en":
            text = (
                "👤 <b>My Profile & Wallet</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🏷 <b>Name:</b> {full_name} ({uname})\n"
                f"🆔 <b>User ID:</b> <code>{stats['user_id']}</code>\n"
                f"🔰 <b>Role:</b> <code>{role_badge}</code>\n"
                f"🏅 <b>Tier:</b> <b>{stats['tier']}</b>\n\n"
                f"💳 <b>Wallet Balance:</b> <b>{int(stats['balance']):,} MMK</b>\n"
                f"🎰 <b>Reward Points:</b> <b>{stats['points']} pts</b> (🔥 {stats['streak']}d streak)\n\n"
                f"🛒 <b>Completed Orders:</b> <b>{stats['total_orders']}</b>\n"
                f"💰 <b>Total Spent:</b> <b>{int(stats['total_spent']):,} MMK</b>\n"
                f"🎁 <b>Valid Referrals:</b> <b>{refs}</b>\n"
                f"📅 <b>Joined:</b> <code>{html.escape(str(stats['join_date']))}</code>"
            )
        else:
            text = (
                "👤 <b>ကျွန်ုပ်၏ Profile နှင့် Wallet</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🏷 <b>အမည်:</b> {full_name} ({uname})\n"
                f"🆔 <b>User ID:</b> <code>{stats['user_id']}</code>\n"
                f"🔰 <b>Role:</b> <code>{role_badge}</code>\n"
                f"🏅 <b>အဆင့် (Tier):</b> <b>{stats['tier']}</b>\n\n"
                f"💳 <b>Wallet လက်ကျန်ငွေ:</b> <b>{int(stats['balance']):,} MMK</b>\n"
                f"🎰 <b>စုဆောင်းထားသော Points:</b> <b>{stats['points']} pts</b> (🔥 {stats['streak']} ရက်ဆက်တိုက်)\n\n"
                f"🛒 <b>ဝယ်ယူပြီးသော အော်ဒါ:</b> <b>{stats['total_orders']} ခု</b>\n"
                f"💰 <b>စုစုပေါင်း အားပေးမှု:</b> <b>{int(stats['total_spent']):,} MMK</b>\n"
                f"🎁 <b>ဖိတ်ခေါ်ထားသူ (Referral):</b> <b>{refs} ဦး</b>\n"
                f"📅 <b>စတင်သုံးစွဲသည့်ရက်:</b> <code>{html.escape(str(stats['join_date']))}</code>"
            )

        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            custom_inline_button("💳 Wallet ငွေဖြည့်မည်", callback_data="wallet_topup_menu", _style="primary"),
            custom_inline_button("💸 သူငယ်ချင်းထံ Wallet လွှဲမည်", callback_data="wallet_transfer_start", _style="primary"),
        )
        markup.add(
            custom_inline_button("📅 Daily Check-in", callback_data="daily_checkin", _style="success"),
            custom_inline_button("🎁 Points လဲလှယ်မည်", callback_data="points_redeem_menu", _style="primary"),
        )
        markup.add(custom_inline_button("🔐 2FA Code ထုတ်ရန်", callback_data="tool_2fa", _style="primary"))
        markup.add(
            custom_inline_button("❓ FAQ / အသုံးပြုနည်း", callback_data="faq_home"),
            custom_inline_button("🛒 My Orders", callback_data="my_orders"),
        )
        if is_admin_user(user.id):
            markup.add(custom_inline_button("🛠 Admin Panel", callback_data="apanel_home"))
        markup.add(custom_inline_button("🏠 Back to Home", callback_data="home"))

        if message_id:
            try:
                bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
                return
            except Exception:
                pass
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")

    @bot.message_handler(commands=["profile", "wallet"])
    def handle_profile_cmd(message):
        send_user_profile(message.chat.id, message.from_user)

    @bot.callback_query_handler(func=lambda call: call.data == "my_profile")
    def handle_profile_callback(call):
        bot.answer_callback_query(call.id)
        send_user_profile(call.message.chat.id, call.from_user, call.message.message_id)

    # =========================================================
    # 2. Daily Check-in & Points Exchange
    # =========================================================
    @bot.callback_query_handler(func=lambda call: call.data == "daily_checkin")
    def handle_daily_checkin(call):
        res = claim_daily_checkin(call.from_user.id)
        if not res["ok"]:
            bot.answer_callback_query(
                call.id,
                f"✅ ယနေ့အတွက် Check-in နှိပ်ပြီးသားဖြစ်ပါသည်!\nလက်ရှိ Points: {res['points']} pts (🔥 {res['streak']} ရက်ဆက်တိုက်)",
                show_alert=True,
            )
            return
        bonus_txt = f"\n🎉 7-Day Streak Bonus: +{res['bonus']} pts!" if res.get("bonus") else ""
        bot.answer_callback_query(
            call.id,
            f"🎰 Daily Check-in အောင်မြင်ပါသည်!\n"
            f"➕ ရရှိသော Points: +{res['earned']} pts{bonus_txt}\n"
            f"🔥 ဆက်တိုက်ရက်: {res['streak']} ရက်\n"
            f"💰 စုစုပေါင်း: {res['points']} pts",
            show_alert=True,
        )
        send_user_profile(call.message.chat.id, call.from_user, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == "points_redeem_menu")
    def handle_points_redeem_menu(call):
        wallet = get_user_wallet(call.from_user.id)
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            custom_inline_button("💵 500 Points ➔ 1,000 MMK (Wallet)", callback_data="redeem_pts_500"),
            custom_inline_button("💵 1,000 Points ➔ 2,500 MMK (Wallet)", callback_data="redeem_pts_1000"),
            custom_inline_button("⬅️ Back to Profile", callback_data="my_profile"),
        )
        text = (
            "🎁 <b>Reward Points လဲလှယ်ရန်</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎰 <b>သင့်လက်ရှိ Points:</b> <b>{wallet['points']} pts</b>\n"
            f"💳 <b>သင့်လက်ရှိ Wallet:</b> <b>{int(wallet['balance']):,} MMK</b>\n\n"
            "နေ့စဉ် Check-in နှိပ်၍ စုဆောင်းထားသော Points များကို Wallet လက်ကျန်ငွေအဖြစ် တိုက်ရိုက်လဲလှယ်ပြီး ဆိုင်ရှိ မည်သည့်ပစ္စည်းမဆို ဝယ်ယူနိုင်ပါသည်။"
        )
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data in ("redeem_pts_500", "redeem_pts_1000"))
    def handle_points_redeem_action(call):
        pts_cost, mmk_val = (500, 1000) if call.data == "redeem_pts_500" else (1000, 2500)
        res = redeem_points_to_wallet(call.from_user.id, pts_cost, mmk_val)
        if not res["ok"]:
            bot.answer_callback_query(
                call.id,
                f"❌ Points မလုံလောက်သေးပါ။ (လိုအပ်ချက်: {pts_cost} pts / လက်ရှိ: {res['points']} pts)",
                show_alert=True,
            )
            return
        bot.answer_callback_query(
            call.id,
            f"🎉 လဲလှယ်မှု အောင်မြင်ပါသည်! +{mmk_val:,} MMK ကို သင့် Wallet ထဲသို့ ထည့်သွင်းပေးလိုက်ပါပြီ။",
            show_alert=True,
        )
        send_user_profile(call.message.chat.id, call.from_user, call.message.message_id)

    # =========================================================
    # 3. Wallet Top-up Flow + Admin Approval
    # =========================================================
    @bot.callback_query_handler(func=lambda call: call.data == "wallet_topup_menu")
    def handle_wallet_topup_menu(call):
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        for amt in (5000, 10000, 20000, 30000, 50000, 100000):
            markup.add(custom_inline_button(f"➕ {amt:,} MMK", callback_data=f"topup_amt_{amt}"))
        markup.add(custom_inline_button("⬅️ Back to Profile", callback_data="my_profile"))
        text = (
            "💳 <b>Wallet ငွေဖြည့်သွင်းရန် (Top-up)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Wallet ထဲသို့ ကြိုတင်ငွေဖြည့်ထားခြင်းဖြင့် ဆိုင်ပိတ်ချိန် (ညဘက်) များတွင်ပါ Admin စောင့်စရာမလိုဘဲ <b>၁ စက္ကန့်အတွင်း (Instant Auto-Delivery)</b> ဝယ်ယူနိုင်ပါသည်။\n\n"
            "👇 ဖြည့်သွင်းလိုသော ပမာဏကို ရွေးချယ်ပါ -"
        )
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("topup_amt_"))
    def handle_wallet_topup_amount(call):
        amt = int(call.data.rsplit("_", 1)[1])
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            custom_inline_button("KPay", callback_data=f"topup_pay_KPAY_{amt}"),
            custom_inline_button("Wave", callback_data=f"topup_pay_WAVE_{amt}"),
            custom_inline_button("AYA Pay", callback_data=f"topup_pay_AYA_{amt}"),
        )
        markup.add(custom_inline_button("⬅️ Back", callback_data="wallet_topup_menu"))
        bot.edit_message_text(
            f"💳 <b>Wallet Top-up: {amt:,} MMK</b>\n\nငွေလွှဲမည့် နည်းလမ်းကို ရွေးချယ်ပါ -",
            call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("topup_pay_"))
    def handle_wallet_topup_method(call):
        _, _, method, amt_str = call.data.split("_")
        amt = int(amt_str)
        pending_topup_Basic[call.from_user.id] = (amt, method)
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button("❌ Cancel", callback_data="my_profile"))
        msg = bot.edit_message_text(
            f"✅ <b>Wallet Top-up ({method})</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💰 <b>ဖြည့်သွင်းမည့်ပမာဏ:</b> <code>{amt:,} MMK</code>\n"
            "📍 <b>ငွေလွှဲရန်:</b> <code>09975374020</code> (NNML)\n"
            "📝 <b>Note:</b> <code>Payment</code>\n\n"
            "📸 <b>ငွေလွှဲပြီးပါက ပြေစာ Screenshot ပုံကို ယခုပို့ပေးပါ။</b>",
            call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML"
        )
        bot.register_next_step_handler(msg, _process_topup_screenshot)

    def _process_topup_screenshot(message):
        state = pending_topup_Basic.pop(message.from_user.id, None)
        if not state:
            return
        if message.content_type != "photo":
            bot.reply_to(message, "❌ Screenshot ပုံ ပေးပို့ရန် လိုအပ်ပါသည်။ Profile မှ ပြန်လည်ရွေးချယ်ပေးပါ။")
            return
        amt, method = state
        photo = message.photo[-1]
        topup_id, err = create_wallet_topup_request(
            message.from_user.id, amt, method, photo.file_unique_id or photo.file_id
        )
        if not topup_id:
            bot.reply_to(message, "❌ ဤပြေစာပုံကို အသုံးပြုပြီးသား ဖြစ်နေပါသည်။")
            return

        uname = f"@{message.from_user.username}" if message.from_user.username else "မရှိပါ"
        admin_caption = (
            "💳 <b>New Wallet Top-up Request!</b>\n\n"
            f"🆔 Top-up ID: <code>#{topup_id}</code>\n"
            f"👤 User ID: <code>{message.from_user.id}</code> ({html.escape(uname)})\n"
            f"💰 Amount: <b>{amt:,} MMK</b>\n"
            f"💳 Method: <b>{html.escape(method)}</b>"
        )
        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        admin_markup.add(
            custom_inline_button("✅ Approve Top-up", callback_data=f"topup_adm_approve_{topup_id}"),
            custom_inline_button("❌ Reject", callback_data=f"topup_adm_reject_{topup_id}"),
        )
        for admin_id in get_all_admin_ids():
            try:
                bot.send_photo(admin_id, photo.file_id, caption=admin_caption, reply_markup=admin_markup, parse_mode="HTML")
            except Exception:
                pass
        bot.reply_to(
            message,
            f"✅ <b>Wallet Top-up ({amt:,} MMK) ပြေစာ လက်ခံရရှိပါပြီ။</b>\nAdmin စစ်ဆေးပြီးသည်နှင့် သင့် Wallet ထဲသို့ အလိုအလျောက် ပေါင်းထည့်ပေးပါမည်။",
            parse_mode="HTML"
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("topup_adm_"))
    def handle_admin_topup_decision(call):
        if not is_admin_user(call.from_user.id):
            return
        _, _, action, topup_id_str = call.data.split("_")
        approve = action == "approve"
        res, err = process_wallet_topup_request(int(topup_id_str), call.from_user.id, approve=approve)
        if not res:
            bot.answer_callback_query(call.id, f"Already processed ({err})", show_alert=True)
            return
        bot.answer_callback_query(call.id, f"Top-up {res['status']}!")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
        if approve:
            bot.send_message(
                res["user_id"],
                f"🎉 <b>Wallet ငွေဖြည့်သွင်းမှု အောင်မြင်ပါပြီ!</b>\n\n"
                f"➕ ဖြည့်သွင်းငွေ: <b>+{int(res['amount']):,} MMK</b>\n"
                f"💳 လက်ရှိ Wallet Balance: <b>{int(res['new_balance']):,} MMK</b>",
                parse_mode="HTML",
            )
        else:
            bot.send_message(
                res["user_id"],
                f"❌ သင့် Wallet Top-up (#{topup_id_str}) ပြေစာကို ငြင်းပယ်လိုက်ပါသည်။",
            )

    @bot.message_handler(commands=["addbalance"])
    def handle_admin_add_balance_cmd(message):
        if not is_admin_user(message.from_user.id):
            return
        parts = (message.text or "").split()
        if len(parts) != 3 or not parts[1].isdigit():
            bot.reply_to(message, "Usage: <code>/addbalance [user_id] [amount_mmk]</code>", parse_mode="HTML")
            return
        uid = int(parts[1])
        amt = float(parts[2].replace(",", ""))
        ok, new_bal = adjust_user_wallet_balance(uid, amt)
        if not ok:
            bot.reply_to(message, "❌ လက်ကျန်ငွေ အနုတ်ပြနေပါသည်။")
            return
        bot.reply_to(message, f"✅ User <code>{uid}</code> ၏ Wallet Balance: <b>{int(new_bal):,} MMK</b>", parse_mode="HTML")


    @bot.callback_query_handler(func=lambda call: call.data == "wallet_transfer_start")
    def handle_wallet_transfer_start(call):
        wallet = get_user_wallet(call.from_user.id)
        if wallet["balance"] < 1000:
            bot.answer_callback_query(
                call.id,
                f"❌ Wallet ငွေလွှဲရန် အနည်းဆုံး 1,000 MMK ရှိရပါမည်။ (လက်ရှိ: {int(wallet['balance']):,} MMK)",
                show_alert=True,
            )
            return
        pending_wallet_transfer_user.add(call.from_user.id)
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button("❌ Cancel", callback_data="my_profile", _style="danger"))
        msg = bot.edit_message_text(
            "💸 <b>သူငယ်ချင်းထံ Wallet လက်ကျန်ငွေ လွှဲပြောင်းပေးရန် (Step 1/2)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💳 <b>သင့်လက်ရှိ Wallet Balance:</b> <b>{int(wallet['balance']):,} MMK</b>\n\n"
            "👤 <b>ငွေလက်ခံမည့် သူငယ်ချင်း၏ Telegram <code>@username</code> သို့မဟုတ် <code>User ID</code> ကို ရိုက်ပို့ပေးပါ -</b>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_wallet_transfer_recipient)

    def _process_wallet_transfer_recipient(message):
        if message.from_user.id not in pending_wallet_transfer_user:
            return
        pending_wallet_transfer_user.discard(message.from_user.id)
        raw = (message.text or "").strip()
        if not raw or raw.startswith("/"):
            bot.reply_to(message, "❌ Cancelled.")
            return
        recipient = find_bot_user_by_identifier(raw)
        if not recipient:
            bot.reply_to(
                message,
                f"❌ <b>{html.escape(raw)}</b> ကို Bot အသုံးပြုသူစာရင်းထဲတွင် မတွေ့ပါ။ သူငယ်ချင်းကို Bot တွင် <code>/start</code> အရင်နှိပ်ခိုင်းပါ။",
                parse_mode="HTML",
            )
            return
        if int(recipient["user_id"]) == int(message.from_user.id):
            bot.reply_to(message, "❌ မိမိအကောင့်သို့ ပြန်လွှဲ၍မရပါ။")
            return
        pending_wallet_transfer_amt[message.from_user.id] = recipient
        wallet = get_user_wallet(message.from_user.id)
        msg = bot.reply_to(
            message,
            "💸 <b>Wallet ငွေလွှဲပြောင်းရန် (Step 2/2)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 <b>လက်ခံမည့်သူ:</b> <b>{html.escape(recipient['display'])}</b>\n"
            f"💳 <b>သင့်လက်ကျန်ငွေ:</b> <b>{int(wallet['balance']):,} MMK</b>\n\n"
            "💰 <b>လွှဲပြောင်းလိုသော ငွေပမာဏ (MMK) ကို ဂဏန်းဖြင့် ရိုက်ပို့ပေးပါ (ဥပမာ - <code>5000</code>):</b>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_wallet_transfer_amount)

    def _process_wallet_transfer_amount(message):
        recipient = pending_wallet_transfer_amt.pop(message.from_user.id, None)
        if not recipient:
            return
        raw_amt = (message.text or "").strip().replace(",", "")
        if not raw_amt.isdigit() or int(raw_amt) < 500:
            bot.reply_to(message, "❌ အနည်းဆုံး 500 MMK မှစ၍ ဂဏန်းဖြင့်သာ ရိုက်ထည့်ပေးပါ။")
            return
        amt = int(raw_amt)
        res = transfer_wallet_balance_between_users(message.from_user.id, recipient["user_id"], amt)
        if not res.get("ok"):
            bot.reply_to(message, "❌ လက်ကျန်ငွေ မလုံလောက်ပါ သို့မဟုတ် လွှဲပြောင်းမှု မအောင်မြင်ပါ။")
            return

        sender_name = message.from_user.first_name or (f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}")
        try:
            bot.send_message(
                recipient["user_id"],
                "🎁💸 <b>WALLET GIFT RECEIVED!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💌 <b>From:</b> <b>{html.escape(sender_name)}</b>\n"
                f"➕ <b>ရရှိသောငွေပမာဏ:</b> <b>+{amt:,} MMK</b>\n"
                f"💳 <b>သင့်လက်ရှိ Wallet Balance:</b> <b>{int(res['recipient_balance']):,} MMK</b>\n\n"
                "🛍️ ဆိုင်ရှိ မည်သည့်ပစ္စည်းကိုမဆို Wallet ဖြင့် တိုက်ရိုက် ဝယ်ယူနိုင်ပါပြီ!",
                parse_mode="HTML",
            )
        except Exception:
            pass

        bot.reply_to(
            message,
            "✅ <b>Wallet ငွေလွှဲပြောင်းမှု အောင်မြင်ပါပြီ!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 <b>လက်ခံသူ:</b> <b>{html.escape(recipient['display'])}</b>\n"
            f"💸 <b>လွှဲပြောင်းငွေ:</b> <b>{amt:,} MMK</b>\n"
            f"💳 <b>သင့်လက်ကျန် Wallet:</b> <b>{int(res['sender_balance']):,} MMK</b>",
            parse_mode="HTML",
        )

    # =========================================================
    # 4. Digital Receipt & Gift to a Friend (My Orders Extras)
    # =========================================================
    @bot.callback_query_handler(func=lambda call: call.data.startswith("receipt_order_"))
    def handle_digital_receipt(call):
        order_id = int(call.data.rsplit("_", 1)[1])
        order = get_order_details(order_id)
        if not order or int(order[1]) != call.from_user.id:
            bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
            return
        bot.answer_callback_query(call.id)
        pub_code = get_public_order_id(order)
        item_name = html.escape(str(order[2]))
        qty = int(order[3] or 1)
        method = html.escape(str(order[4] or "-"))
        bought_at = html.escape(str(order[6] or "-"))
        expiry_at = html.escape(str(order[9] or "Lifetime / Non-expiring"))
        total_amt = f"{int(float(order[11] or 0)):,} MMK"

        receipt_text = (
            "🧾 <b>OFFICIAL DIGITAL RECEIPT</b>\n"
            "🏪 <b>ENI Premium Store</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Receipt No:</b> <code>{html.escape(pub_code)}</code>\n"
            f"👤 <b>Buyer ID:</b> <code>{call.from_user.id}</code>\n"
            f"📅 <b>Date:</b> <code>{bought_at}</code>\n"
            "──────────────────────\n"
            f"📦 <b>Product:</b> {item_name}\n"
            f"🔢 <b>Quantity:</b> {qty}\n"
            f"💳 <b>Paid Via:</b> {method}\n"
            f"💰 <b>Total Paid:</b> <b>{total_amt}</b>\n"
            f"⏳ <b>Valid Until:</b> <code>{expiry_at}</code>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "✅ <i>Status: Paid & Verified by ENI Store</i>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button("⬅️ Back to Order", callback_data=f"view_order_{order_id}"))
        bot.send_message(call.message.chat.id, receipt_text, reply_markup=markup, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("giftcard_order_"))
    def handle_gift_to_friend_start(call):
        order_id = int(call.data.rsplit("_", 1)[1])
        order = get_order_details(order_id)
        if not order or int(order[1]) != call.from_user.id:
            bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
            return
        pending_gift_notes[call.from_user.id] = order_id
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            call.message.chat.id,
            "🎁 <b>သူငယ်ချင်းထံ လက်ဆောင်ကတ် ပေးပို့ရန်</b>\n\n"
            "လက်ဆောင်ကတ်ပေါ်တွင် ထည့်သွင်းလိုသော ဆုတောင်းစာသား သို့မဟုတ် Message တိုလေး တစ်ကြောင်း ရိုက်ပို့ပေးပါ -\n"
            "<i>(ဥပမာ - Happy Birthday ပါ သူငယ်ချင်း! 🎉)</i>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_gift_note)

    def _process_gift_note(message):
        order_id = pending_gift_notes.pop(message.from_user.id, None)
        if not order_id:
            return
        note = (message.text or "").strip()
        if not note or note.startswith("/"):
            bot.reply_to(message, "❌ Cancelled.")
            return
        order = get_order_details(order_id)
        if not order:
            return
        sender_name = html.escape(message.from_user.first_name or "Your Friend")
        gift_card_msg = (
            "🎁✨ <b>SPECIAL DIGITAL GIFT FOR YOU!</b> ✨🎁\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"💌 <b>From:</b> <b>{sender_name}</b>\n"
            f"💬 <b>Message:</b> <i>\"{html.escape(note[:200])}\"</i>\n\n"
            f"📦 <b>Gift Item:</b> <b>{html.escape(str(order[2]))}</b>\n"
            f"🔑 <b>Account / Redeem Data:</b>\n<code>{html.escape(str(order[7] or '-'))}</code>\n"
            + (f"\n📅 <b>Valid Until:</b> <code>{html.escape(str(order[9]))}</code>\n" if order[9] else "\n")
            + "━━━━━━━━━━━━━━━━━━━━━━\n"
            "🏰 <i>Powered by ENI Premium Store</i>"
        )
        bot.reply_to(
            message,
            "✅ <b>အောက်ပါ Gift Card Message ကို သင့်သူငယ်ချင်းထံသို့ တိုက်ရိုက် Forward ပို့ပေးနိုင်ပါပြီ 👇</b>",
            parse_mode="HTML",
        )
        bot.send_message(message.chat.id, gift_card_msg, parse_mode="HTML")

    # =========================================================
    # 5. Interactive FAQ Center
    # =========================================================
    FAQ_DATA = {
        "2fa": (
            "🔐 <b>ChatGPT / Account 2FA ကုဒ် ဘယ်လိုထုတ်ရမလဲ?</b>\n\n"
            "၁။ သင်ရရှိထားသော အကောင့် Format <code>mail:pass:2FA_KEY</code> မှ နောက်ဆုံးက 2FA Key ကို Copy ကူးပါ။\n"
            "၂။ ဤ Bot ၏ Home Menu ရှိ <b>🔐 2FA Code</b> ခလုတ်ကို နှိပ်ပြီး Key ပို့လိုက်ရုံဖြင့် ဂဏန်း ၆ လုံး OTP ကုဒ် ချက်ချင်း ရရှိပါမည်။"
        ),
        "outline": (
            "🛡 <b>Outline VPN ဘယ်လိုချိတ်ဆက်သုံးရမလဲ?</b>\n\n"
            "Outline App ဒေါင်းလုဒ်ဆွဲနည်းနှင့် Key ထည့်သွင်းအသုံးပြုနည်း အသေးစိတ်ကို အောက်ပါ Official Channel လမ်းညွှန်ပို့စ်တွင် ကြည့်ရှုနိုင်ပါသည် -\n\n"
            f"👉 <a href='{OUTLINE_GUIDE_POST_URL}'>Outline အသုံးပြုနည်း လမ်းညွှန် ဖတ်ရှုရန်</a>"
        ),
        "apple": (
            "🍎 <b>Apple Gift Card (US) ထည့်သွင်းနည်းနှင့် သတိပြုရန်</b>\n\n"
            "• သင့် Apple ID သည် <b>United States (US) Region</b> ဖြစ်ရပါမည်။\n"
            "• ကုဒ်ရရှိချိန်တွင် ပါလာသော <b>🍎 Redeem Now on App Store</b> ခလုတ်ကို နှိပ်၍ တိုက်ရိုက်ဖြည့်သွင်းနိုင်ပါသည်။"
        ),
        "wallet": (
            "💳 <b>Wallet နဲ့ ဝယ်ရင် ဘာထူးခြားသလဲ?</b>\n\n"
            "• Profile မှတစ်ဆင့် Wallet ထဲ ကြိုတင်ငွေဖြည့်ထားပါက ပစ္စည်းဝယ်ချိန်တွင် Screenshot ပို့စရာမလို၊ Admin စောင့်စရာမလိုဘဲ ၂၄ နာရီပတ်လုံး စက္ကန့်ပိုင်းအတွင်း အကောင့်တန်းထုတ်ယူနိုင်ပါသည်။"
        ),
    }

    @bot.callback_query_handler(func=lambda call: call.data == "faq_home" or call.data.startswith("faq_topic_"))
    def handle_faq_center(call):
        bot.answer_callback_query(call.id)
        topic = call.data.replace("faq_topic_", "", 1) if call.data.startswith("faq_topic_") else None
        body = FAQ_DATA.get(topic, "❓ <b>အမေးများသော မေးခွန်းများ (FAQ & Help Center)</b>\n\nသိရှိလိုသော အကြောင်းအရာကို အောက်ပါခလုတ်များမှ ရွေးချယ်ဖတ်ရှုပါ -")

        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            custom_inline_button("🛡 Outline VPN အသုံးပြုနည်း လမ်းညွှန်", url=OUTLINE_GUIDE_POST_URL),
            custom_inline_button("🔐 2FA OTP ကုဒ်ထုတ်ယူနည်း", callback_data="faq_topic_2fa"),
            custom_inline_button("🍎 Apple Gift Card ထည့်သွင်းနည်း", callback_data="faq_topic_apple"),
            custom_inline_button("💳 Wallet Instant Buy အကြောင်း", callback_data="faq_topic_wallet"),
            custom_inline_button("🏠 Back to Home", callback_data="home"),
        )
        bot.edit_message_text(body, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML", disable_web_page_preview=True)

    # =========================================================
    # 6. 2FA Tool, Waitlist & Warranty Ticket (Existing)
    # =========================================================
    @bot.message_handler(commands=["2fa"])
    def handle_2fa_cmd(message):
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].strip():
            _reply_with_2fa_code(message, parts[1].strip())
            return
        pending_2fa_users.add(message.from_user.id)
        msg = bot.reply_to(
            message,
            "🔐 <b>2FA Code Generator</b>\n\nသင့်အကောင့်တွင် ပါဝင်သော <b>2FA Secret Key</b> ကို ရိုက်ပို့ပေးပါ။",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_2fa_input)

    @bot.callback_query_handler(func=lambda call: call.data == "tool_2fa")
    def handle_2fa_callback(call):
        bot.answer_callback_query(call.id)
        pending_2fa_users.add(call.from_user.id)
        msg = bot.send_message(
            call.message.chat.id,
            "🔐 <b>2FA Code Generator</b>\n\nသင့်အကောင့်တွင် ပါဝင်သော <b>2FA Secret Key</b> ကို ရိုက်ပို့ပေးပါ။",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_2fa_input)

    def _process_2fa_input(message):
        if message.from_user.id not in pending_2fa_users:
            return
        pending_2fa_users.discard(message.from_user.id)
        raw = (message.text or "").strip()
        if not raw.startswith("/"):
            _reply_with_2fa_code(message, raw)

    def _reply_with_2fa_code(message, secret_text):
        try:
            code, rem = generate_totp_code(secret_text)
            markup = types.InlineKeyboardMarkup()
            markup.add(
                custom_inline_button("🔄 ကုဒ်အသစ်ထပ်ထုတ်မည်", callback_data="tool_2fa"),
                custom_inline_button("🏠 Home", callback_data="home"),
            )
            bot.reply_to(
                message,
                f"🔐 <b>2FA Verification Code</b>\n\n🔢 <b>OTP Code:</b> <code>{code}</code>\n⏳ <b>Valid for:</b> <b>{rem}s</b>",
                reply_markup=markup, parse_mode="HTML",
            )
        except Exception:
            bot.reply_to(message, "❌ 2FA Secret Key ပုံစံ မမှန်ကန်ပါ။")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("waitlist_"))
    def handle_waitlist_subscribe(call):
        item_id = int(call.data.split("_", 1)[1])
        added = add_stock_waitlist(call.from_user.id, item_id)
        bot.answer_callback_query(
            call.id,
            "🔔 မှတ်သားပြီးပါပြီ! Stock ပြန်ဝင်တာနဲ့ Bot က ချက်ချင်း အကြောင်းကြားပေးပါမယ်။" if added else "ℹ️ Notify စာရင်းထဲ ထည့်သွင်းပြီးသား ဖြစ်ပါတယ်။",
            show_alert=True,
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("report_order_"))
    def handle_report_order_start(call):
        order_id = int(call.data.rsplit("_", 1)[1])
        order = get_order_details(order_id)
        if not order or int(order[1]) != call.from_user.id:
            bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
            return
        pending_ticket_orders[call.from_user.id] = order_id
        bot.answer_callback_query(call.id)
        msg = bot.send_message(
            call.message.chat.id,
            f"🛠 <b>Warranty Claim / ပြဿနာတင်ပြရန်</b>\n\n🧾 Order: <code>{html.escape(get_public_order_id(order))}</code>\nကြုံတွေ့နေရသော အခက်အခဲကို ရေးပို့ပေးပါ -",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_ticket_submission)

    def _process_ticket_submission(message):
        order_id = pending_ticket_orders.pop(message.from_user.id, None)
        if not order_id:
            return
        text = (message.text or "").strip()
        if not text or text.startswith("/"):
            return
        order = get_order_details(order_id)
        if not order:
            return
        ticket_id = create_support_ticket(order_id, message.from_user.id, text)
        pub_code = get_public_order_id(order)
        uname = f"@{message.from_user.username}" if message.from_user.username else "မရှိပါ"
        admin_alert = (
            f"🚨 <b>Warranty Ticket #{ticket_id}</b>\n\n"
            f"👤 User: <code>{message.from_user.id}</code> ({html.escape(uname)})\n"
            f"🧾 Order: <code>{html.escape(pub_code)}</code>\n"
            f"📦 Item: {html.escape(str(order[2]))}\n"
            f"📝 Issue: <i>{html.escape(text)}</i>"
        )
        admin_markup = types.InlineKeyboardMarkup(row_width=2)
        admin_markup.add(
            custom_inline_button("💬 Reply ပြန်မည်", callback_data=f"ticket_reply_{ticket_id}_{message.from_user.id}"),
            custom_inline_button("✅ Close", callback_data=f"ticket_close_{ticket_id}_{message.from_user.id}"),
        )
        for admin_id in get_all_admin_ids():
            try:
                bot.send_message(admin_id, admin_alert, reply_markup=admin_markup, parse_mode="HTML")
            except Exception:
                pass
        bot.reply_to(message, f"✅ သင့်တင်ပြချက် (Ticket <code>#{ticket_id}</code>) ကို Admin ထံ ပေးပို့ပြီးပါပြီ။", parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ticket_reply_"))
    def handle_admin_ticket_reply_btn(call):
        if not is_admin_user(call.from_user.id):
            return
        _, _, ticket_id, target_uid = call.data.split("_")
        pending_admin_replies[call.from_user.id] = (int(ticket_id), int(target_uid))
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, f"✍️ Ticket #{ticket_id} သို့ ပြန်ကြားမည့်စာ ရိုက်ပို့ပါ -")
        bot.register_next_step_handler(msg, _process_admin_ticket_reply)

    def _process_admin_ticket_reply(message):
        state = pending_admin_replies.pop(message.from_user.id, None)
        if not state:
            return
        ticket_id, target_uid = state
        reply_text = (message.text or "").strip()
        if not reply_text or reply_text.startswith("/"):
            return
        bot.send_message(target_uid, f"💬 <b>Admin Reply (Ticket #{ticket_id}):</b>\n\n{html.escape(reply_text)}", parse_mode="HTML")
        close_support_ticket(ticket_id, message.from_user.id)
        bot.reply_to(message, f"✅ Ticket #{ticket_id} replied & closed.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("ticket_close_"))
    def handle_admin_ticket_close_btn(call):
        if not is_admin_user(call.from_user.id):
            return
        _, _, ticket_id, _ = call.data.split("_")
        close_support_ticket(int(ticket_id), call.from_user.id)
        bot.answer_callback_query(call.id, f"Ticket #{ticket_id} closed.")
        try:
            bot.edit_message_reply_markup(call.message.chat.id, call.message.message_id, reply_markup=None)
        except Exception:
            pass
