import telebot
from telebot import types
from handlers.custom_emoji import (
    custom_inline_button, custom_message_entities, send_custom_emoji_message,
)
import datetime
import html
from config import YOUR_CHANNEL_ID, CHANNEL_URL, SELL_PROOF_CHANNEL_URL
from database import (
    add_user, get_user, get_shop_status, get_user_language, set_user_language,
    create_pending_referral, get_pending_referral_for_user, verify_pending_referral,
    get_valid_referral_count, get_referral_required_count, get_referral_reward_text,
    get_referral_status, create_referral_reward_claim, get_referral_reward_status,
    is_admin_user, get_all_admin_ids
)

def check_subscription(user_id, bot):
    """User က Channel ကို Join ထားခြင်း ရှိ/မရှိ စစ်ဆေးခြင်း"""
    try:
        status = bot.get_chat_member(YOUR_CHANNEL_ID, user_id).status
        return status in ["member", "administrator", "creator"]
    except Exception as e:
        print(f"Error checking subscription: {e}")
        return False

def show_home_menu(user_id, first_name, bot):
    """ပင်မ Menu နှင့် Welcome Message ကို ပြသခြင်း"""
    language = get_user_language(user_id) or "my"
    welcome_text = (
        f"👋 မင်္ဂလာပါ *{first_name}* ရေ...\n\n"
        f"🏰 *ENI Premium Store* မှ နွေးထွေးစွာ ကြိုဆိုပါတယ်ဗျာ။\n\n"
        f"🤖 *ကျွန်ုပ်တို့၏ Bot သည်:*\n"
        f"🔹 Premium Account များကို သက်သာသော ဈေးနှုန်းဖြင့် ဝယ်ယူနိုင်ခြင်း\n"
        f"🔹 လစဉ် Giveaway အစီအစဉ်များတွင် ပါဝင်ကံစမ်းနိုင်ခြင်း\n"
        f"🔹 လုံခြုံစိတ်ချရသော ငွေလွှဲစနစ်များဖြင့် ဝန်ဆောင်မှုပေးနေပါသည်၊၊\n\n"
    )

    if language == "en":
        welcome_text = (
            f"👋 Hello *{first_name}*...\n\n"
            "🏰 Welcome to *ENI Premium Store*.\n\n"
            "🤖 *What you can do with this bot:*\n"
            "🔹 Buy premium accounts at affordable prices\n"
            "🔹 Join giveaway events\n"
            "🔹 Pay securely with crypto payment options\n\n"
        )

    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        custom_inline_button("🛍️ Shop",      callback_data='shop', _style='primary'),
        custom_inline_button("🎁 Giveaway",  callback_data='giveaway', _style='primary'),
        custom_inline_button("🛒 My Orders", callback_data='my_orders', _style='primary'),
        custom_inline_button("👤 My Profile / Wallet", callback_data='my_profile', _style='primary'),
    )
    markup.add(
        custom_inline_button("📅 Daily Check-in", callback_data='daily_checkin', _style='success'),
        custom_inline_button("🔐 2FA Code", callback_data='tool_2fa', _style='primary'),
    )
    markup.add(
        custom_inline_button("❓ FAQ / လမ်းညွှန်", callback_data='faq_home', _style='primary'),
        custom_inline_button("🎧 Support",   url="https://t.me/independence_N", _style='primary'),
    )
    proof_label = "🧾 Purchase Proofs" if language == "en" else "🧾 ဝယ်ယူမှုမှတ်တမ်း"
    markup.add(
        custom_inline_button("📢 Join Channel", url=CHANNEL_URL, _style='primary'),
        custom_inline_button(proof_label, url=SELL_PROOF_CHANNEL_URL, _emoji_key="sell_proof", _style='primary'),
    )
    markup.add(
        custom_inline_button("🎁 Referral", callback_data="referral_home", _style='primary'),
        custom_inline_button("🌐 Language", callback_data="change_language", _style='primary'),
    )

    # Text custom emoji are configured separately from buttons.  When no
    # custom IDs are set, these remain normal Unicode emoji.
    clean_text = welcome_text.replace('*', '')
    message_entities = custom_message_entities(clean_text, (
        ('👋', 'welcome_greeting'), ('🏰', 'welcome_store'),
        ('🤖', 'welcome_bot'), ('🔹', 'welcome_bullet'),
    ))
    try:
        if message_entities:
            # An explicit empty parse mode prevents TeleBot's global HTML mode
            # from being sent together with custom-emoji entities.
            bot.send_message(
                user_id, clean_text, reply_markup=markup,
                entities=message_entities, parse_mode=''
            )
        else:
            bot.send_message(user_id, welcome_text, reply_markup=markup, parse_mode='Markdown')
    except Exception as error:
        print(f"Welcome custom emoji send failed: {error}")
        bot.send_message(user_id, welcome_text, reply_markup=markup, parse_mode='Markdown')

def ask_language(user_id, bot):
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        custom_inline_button("🇲🇲 Myanmar", callback_data="set_lang_my"),
        custom_inline_button("🇬🇧 English", callback_data="set_lang_en")
    )
    send_custom_emoji_message(
        bot,
        user_id,
        "🌐 Please choose your language.\n\nကျေးဇူးပြု၍ အသုံးပြုမည့် ဘာသာစကားကို ရွေးချယ်ပါ။",
        (("🌐", "language_title"),),
        reply_markup=markup,
    )

def send_help(message, bot):
    language = get_user_language(message.from_user.id) or "my"
    """Help စာသားကို ပြသခြင်း"""
    help_text = (
        "❓ *အကူအညီလိုအပ်ပါသလား?*\n\n"
        "• ပစ္စည်းများကြည့်ရှုရန် /start သို့မဟုတ် *Shop* ကိုနှိပ်ပါ။\n"
        "• ပင်မစာမျက်နှာသို့ပြန်သွားရန် /home ကိုနှိပ်ပါ။\n"
        "• ဝယ်ယူထားသည်များကိုကြည့်ရန် *My Orders* ကိုနှိပ်ပါ။\n\n"
        "🎧 အခက်အခဲရှိပါက Admin @independence\\_N သို့ တိုက်ရိုက်ဆက်သွယ်နိုင်ပါသည်၊၊"
    )
    if language == "en":
        help_text = (
            "❓ *Need help?*\n\n"
            "• Use /start or tap *Shop* to view products.\n"
            "• Use /home to return to the main menu.\n"
            "• Tap *My Orders* to view your previous orders.\n"
            "• Use /language to change your language anytime.\n\n"
            "🎧 If you need support, contact Admin @independence_N."
        )
    markup = types.InlineKeyboardMarkup()
    markup.add(custom_inline_button("💬 Chat with Admin", url="https://t.me/independence_N"))

    try:
        bot.send_message(message.chat.id, help_text, reply_markup=markup, parse_mode='Markdown')
    except Exception:
        bot.send_message(message.chat.id, help_text, reply_markup=markup)

def get_referral_link(user_id, bot):
    try:
        bot_username = bot.get_me().username
    except Exception:
        bot_username = ""
    if not bot_username:
        return f"Open this bot with start code: ref_{user_id}"
    return f"https://t.me/{bot_username}?start=ref_{user_id}"

def build_referral_text(user_id, bot):
    language = get_user_language(user_id) or "my"
    status = get_referral_status()
    valid_count = get_valid_referral_count(user_id)
    required_count = get_referral_required_count()
    reward_text = get_referral_reward_text()
    ref_link = get_referral_link(user_id, bot)
    reward_status = get_referral_reward_status(user_id)

    if status != "open":
        if language == "en":
            return (
                "🎁 <b>Referral Program</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "⏸ <b>The referral program is temporarily paused.</b>\n\n"
                "Please check again later."
            )
        return (
            "🎁 <b>Referral Program</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "⏸ <b>Referral program ကို ခေတ္တရပ်ထားပါတယ်။</b>\n\n"
            "နောက်မှပြန်လည်စစ်ဆေးပေးပါခင်ဗျာ။"
        )

    if language == "en":
        status_text = "Open" if status == "open" else "Paused"
        claim_text = ""
        if reward_status:
            claim_text = f"\n🎁 <b>Reward claim:</b> <code>{html.escape(str(reward_status[1]))}</code>"
        return (
            "🎁 <b>Referral Program</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 <b>Status:</b> <code>{status_text}</code>\n"
            f"👥 <b>Your valid referrals:</b> <code>{valid_count}/{required_count}</code>\n"
            f"🎁 <b>Reward:</b> {html.escape(str(reward_text))}{claim_text}\n\n"
            "🔗 <b>Your referral link:</b>\n"
            f"<code>{html.escape(ref_link)}</code>\n\n"
            "📖 <b>How to use</b>\n"
            "1. Share your referral link with new users.\n"
            "2. The new user must open the bot using your link.\n"
            "3. They must join our channel and tap Verify.\n"
            "4. Only real new users count. Old users, duplicate joins, and your own link do not count.\n"
            f"5. One user can receive up to {required_count} valid referrals."
        )

    status_text = "ဖွင့်ထားသည်" if status == "open" else "ခေတ္တရပ်ထားသည်"
    claim_text = ""
    if reward_status:
        claim_text = f"\n🎁 <b>Reward Claim:</b> <code>{html.escape(str(reward_status[1]))}</code>"
    return (
        "🎁 <b>Referral Program</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📌 <b>Status:</b> <code>{status_text}</code>\n"
        f"👥 <b>ခေါ်ထားပြီးသော လူသစ်:</b> <code>{valid_count}/{required_count}</code>\n"
        f"🎁 <b>ရရှိမည့်ဆု:</b> {html.escape(str(reward_text))}{claim_text}\n\n"
        "🔗 <b>သင့် Referral Link:</b>\n"
        f"<code>{html.escape(ref_link)}</code>\n\n"
        "📖 <b>အသုံးပြုပုံ</b>\n"
        "1. ဒီ link ကို လူသစ်တွေကိုပို့ပါ။\n"
        "2. လူသစ်က link ကနေ bot ထဲဝင်ရပါမယ်။\n"
        "3. Channel join ပြီး Verify နှိပ်ရပါမယ်။\n"
        "4. လူဟောင်း၊ duplicate၊ ကိုယ့် link ကိုယ်နှိပ်တာတွေ count မတိုးပါ။\n"
        f"5. User တစ်ယောက်အတွက် အများဆုံး {required_count} ယောက်အထိသာ count တိုးပါမယ်။"
    )

def build_referral_markup(user_id):
    language = get_user_language(user_id) or "my"
    status = get_referral_status()
    pending_ref = get_pending_referral_for_user(user_id)
    valid_count = get_valid_referral_count(user_id)
    required_count = get_referral_required_count()
    markup = types.InlineKeyboardMarkup(row_width=2)

    if status != "open":
        markup.add(
            custom_inline_button("🔄 Refresh", callback_data="ref_refresh"),
            custom_inline_button("🏠 Home", callback_data="home")
        )
        return markup

    if pending_ref:
        verify_label = "✅ Verify Channel" if language == "en" else "✅ Channel Verify"
        markup.add(
            custom_inline_button("📢 Join Channel", url=CHANNEL_URL),
            custom_inline_button(verify_label, callback_data="ref_verify")
        )

    if valid_count >= required_count:
        claim_label = "🎁 Claim Reward" if language == "en" else "🎁 ဆု Claim လုပ်မယ်"
        markup.add(custom_inline_button(claim_label, callback_data="ref_claim"))

    markup.add(
        custom_inline_button("🔄 Refresh", callback_data="ref_refresh"),
        custom_inline_button("🏠 Home", callback_data="home")
    )
    return markup

def send_referral_page(user_id, bot, chat_id=None, message_id=None, allow_send=True):
    chat_id = chat_id or user_id
    text = build_referral_text(user_id, bot)
    markup = build_referral_markup(user_id)
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return True
        except Exception as e:
            print(f"Referral page edit failed: {e}")
            if not allow_send:
                return False
    if allow_send:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        return True
    return False

def build_referral_join_required_text(user_id):
    language = get_user_language(user_id) or "my"
    if language == "en":
        return (
            "📢 <b>Channel Join Required</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "To join the referral program, please join our official channel first.\n\n"
            "After joining, tap <b>Verify</b>."
        )
    return (
        "📢 <b>Channel Join လိုအပ်ပါသည်</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Referral program မှာ ပါဝင်ရန် official channel ကို အရင် join ပေးပါခင်ဗျာ။\n\n"
        "Join ပြီးပါက <b>Verify</b> ကိုနှိပ်ပေးပါ။"
    )

def build_referral_join_required_markup(user_id):
    language = get_user_language(user_id) or "my"
    verify_label = "✅ Verify" if language == "en" else "✅ Verify လုပ်မယ်"
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        custom_inline_button("📢 Join Channel", url=CHANNEL_URL),
        custom_inline_button(verify_label, callback_data="ref_gate_verify")
    )
    markup.add(custom_inline_button("🏠 Home", callback_data="home"))
    return markup

def send_referral_join_required(user_id, bot, chat_id=None, message_id=None, allow_send=True):
    chat_id = chat_id or user_id
    text = build_referral_join_required_text(user_id)
    markup = build_referral_join_required_markup(user_id)
    if message_id:
        try:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=markup, parse_mode="HTML")
            return True
        except Exception as e:
            print(f"Referral join gate edit failed: {e}")
            if not allow_send:
                return False
    if allow_send:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
        return True
    return False

def init_start_handlers(bot):

    def remember_user(user):
        return add_user(
            user.id,
            username=user.username,
            first_name=user.first_name,
            last_name=user.last_name
        )

    @bot.message_handler(commands=["start"])
    def start_handler(message):
        user_id    = message.from_user.id
        first_name = message.from_user.first_name
        referrer_id = None
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) == 2 and parts[1].startswith("ref_"):
            try:
                referrer_id = int(parts[1].replace("ref_", "", 1))
            except ValueError:
                referrer_id = None

        # Maintenance Mode စစ်ဆေးခြင်း (Admin မဟုတ်သူများကိုသာ ပိတ်မည်)
        is_new_user = False
        try:
            is_new_user = remember_user(message.from_user)
            if is_new_user:
                print(f"Registered new user: {user_id}")
        except Exception as db_err:
            print(f"[DATABASE ERROR IN START]: {db_err}")

        if referrer_id and is_new_user:
            created, reason = create_pending_referral(referrer_id, user_id)
            print(f"Referral pending create for {user_id} by {referrer_id}: {created} ({reason})")

        status = get_shop_status()
        if status == 'maintenance' and not is_admin_user(user_id):
            maintenance_text = (
                "🛠 <b>Bot is Under Maintenance</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "ပိုမိုကောင်းမွန်သော ဝန်ဆောင်မှုများ ပေးနိုင်ရန် Bot ကို ခေတ္တပြုပြင်နေပါသည်၊၊\n\n"
                "Admin ဘက်မှ ပြန်လည်ဖွင့်လှစ်ပေးသည်အထိ ခေတ္တစောင့်ဆိုင်းပေးပါရန် မေတ္တာရပ်ခံအပ်ပါတယ်ဗျာ၊၊ 🙏\n\n"
                "👨‍💻 <b>Support:</b> @independence_N"
            )
            if get_user_language(user_id) == "en":
                maintenance_text = (
                    "<b>Bot is Under Maintenance</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    "We are improving the bot to provide better service.\n\n"
                    "Please wait until admin reopens it.\n\n"
                    "<b>Support:</b> @independence_N"
                )
            bot.send_message(message.chat.id, maintenance_text, parse_mode='HTML')
            return

        if not get_user_language(user_id):
            ask_language(user_id, bot)
            return

        # 🌟 [FIXED] User အသစ် မှတ်ပုံတင်ခြင်းအပိုင်းကို Error တက်ရင်ကျော်သွားနိုင်အောင် try...except ခံထားသည်
        try:
            user_info = get_user(user_id)
            if not user_info:
                join_date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                remember_user(message.from_user)
                print(f"📦 [SUCCESS] Registered new user: {user_id}")
        except Exception as db_err:
            print(f"⚠️ [DATABASE ERROR IN START]: {db_err}")

        show_home_menu(user_id, first_name, bot)

    @bot.message_handler(commands=["home"])
    def home_handler(message):
        remember_user(message.from_user)
        if not get_user_language(message.from_user.id):
            ask_language(message.from_user.id, bot)
            return
        show_home_menu(message.from_user.id, message.from_user.first_name, bot)

    @bot.message_handler(commands=["language"])
    def language_handler(message):
        remember_user(message.from_user)
        ask_language(message.from_user.id, bot)

    @bot.callback_query_handler(func=lambda call: call.data == "change_language")
    def change_language_callback(call):
        remember_user(call.from_user)
        bot.answer_callback_query(call.id)
        ask_language(call.from_user.id, bot)

    @bot.message_handler(commands=["help"])
    def help_handler(message):
        send_help(message, bot)

    @bot.callback_query_handler(func=lambda call: call.data in ("set_lang_my", "set_lang_en"))
    def language_callback(call):
        language = "my" if call.data == "set_lang_my" else "en"
        remember_user(call.from_user)
        set_user_language(call.from_user.id, language)
        bot.answer_callback_query(call.id, "Language saved.")
        try:
            bot.delete_message(call.message.chat.id, call.message.message_id)
        except Exception:
            pass
        show_home_menu(call.from_user.id, call.from_user.first_name, bot)

    @bot.callback_query_handler(func=lambda call: call.data in ("referral_home", "ref_refresh"))
    def referral_home_callback(call):
        remember_user(call.from_user)
        bot.answer_callback_query(call.id)
        if not check_subscription(call.from_user.id, bot):
            send_referral_join_required(
                call.from_user.id,
                bot,
                call.message.chat.id,
                call.message.message_id,
                allow_send=(call.data == "referral_home")
            )
            return
        send_referral_page(
            call.from_user.id,
            bot,
            call.message.chat.id,
            call.message.message_id,
            allow_send=(call.data == "referral_home")
        )

    @bot.callback_query_handler(func=lambda call: call.data == "ref_gate_verify")
    def referral_gate_verify_callback(call):
        remember_user(call.from_user)
        language = get_user_language(call.from_user.id) or "my"
        if not check_subscription(call.from_user.id, bot):
            msg = "Please join the channel first." if language == "en" else "Channel ကို အရင် join ပေးပါ။"
            bot.answer_callback_query(call.id, msg, show_alert=True)
            return
        bot.answer_callback_query(call.id, "Verified." if language == "en" else "Verify အောင်မြင်ပါသည်။")
        send_referral_page(call.from_user.id, bot, call.message.chat.id, call.message.message_id, allow_send=False)

    @bot.callback_query_handler(func=lambda call: call.data == "ref_verify")
    def referral_verify_callback(call):
        user_id = call.from_user.id
        language = get_user_language(user_id) or "my"
        if not check_subscription(user_id, bot):
            msg = "Please join the channel first." if language == "en" else "Channel ကို အရင် join ပေးပါ။"
            bot.answer_callback_query(call.id, msg, show_alert=True)
            return

        ok, reason, referrer_id, new_count = verify_pending_referral(user_id)
        required_count = get_referral_required_count()
        if not ok:
            messages = {
                "en": {
                    "paused": "Referral program is paused.",
                    "missing": "No pending referral found.",
                    "limit": "Referral limit has already been reached.",
                },
                "my": {
                    "paused": "Referral program ခေတ္တရပ်ထားပါတယ်။",
                    "missing": "Verify လုပ်ရန် pending referral မတွေ့ပါ။",
                    "limit": "Referral limit ပြည့်ပြီးပါပြီ။",
                }
            }
            bot.answer_callback_query(call.id, messages.get(language, messages["my"]).get(reason, "Failed."), show_alert=True)
            return

        bot.answer_callback_query(call.id, "Verified." if language == "en" else "Verify အောင်မြင်ပါသည်။")
        send_referral_page(user_id, bot, call.message.chat.id, call.message.message_id)
        try:
            bot.send_message(
                referrer_id,
                (
                    f"🎉 <b>Referral အသစ်တစ်ယောက် count တိုးပါပြီ!</b>\n\n"
                    f"👥 Count: <b>{new_count}/{required_count}</b>"
                ),
                parse_mode="HTML"
            )
        except Exception as e:
            print(f"Failed to notify referrer {referrer_id}: {e}")

    @bot.callback_query_handler(func=lambda call: call.data == "ref_claim")
    def referral_claim_callback(call):
        user_id = call.from_user.id
        language = get_user_language(user_id) or "my"
        created, status, reward_id = create_referral_reward_claim(user_id)
        if not created:
            if status == "not_enough":
                msg = "You do not have enough referrals yet." if language == "en" else "Referral count မပြည့်သေးပါ။"
            elif status == "pending":
                msg = "Your reward claim is already pending." if language == "en" else "Reward claim pending ဖြစ်နေပါပြီ။"
            elif status == "approved":
                msg = "Your reward has already been approved." if language == "en" else "Reward approve ဖြစ်ပြီးပါပြီ။"
            else:
                msg = "Claim failed." if language == "en" else "Claim မအောင်မြင်ပါ။"
            bot.answer_callback_query(call.id, msg, show_alert=True)
            return

        bot.answer_callback_query(call.id, "Claim submitted." if language == "en" else "Claim တင်ပြီးပါပြီ။", show_alert=True)
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            custom_inline_button("✅ Approve", callback_data=f"refclaim_approve_{reward_id}"),
            custom_inline_button("❌ Reject", callback_data=f"refclaim_reject_{reward_id}")
        )
        for admin_id in get_all_admin_ids():
            try:
                bot.send_message(
                    admin_id,
                    (
                        "🎁 <b>New Referral Reward Claim</b>\n\n"
                        f"User ID: <code>{user_id}</code>\n"
                        f"Reward ID: <code>{reward_id}</code>\n"
                        f"Valid Referrals: <b>{get_valid_referral_count(user_id)}/{get_referral_required_count()}</b>\n"
                        f"Reward: <b>{html.escape(str(get_referral_reward_text()))}</b>"
                    ),
                    reply_markup=markup,
                    parse_mode="HTML"
                )
            except Exception as e:
                print(f"Failed to send referral claim to admin {admin_id}: {e}")
        send_referral_page(user_id, bot, call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data == 'verify_subscription')
    def verify_subscription_callback(call):
        user_id = call.from_user.id
        if get_user_language(user_id) == "en":
            if check_subscription(user_id, bot):
                bot.answer_callback_query(call.id, "Verified.")
                show_home_menu(user_id, call.from_user.first_name, bot)
            else:
                bot.answer_callback_query(call.id, "Verify failed. Please join the channel first.", show_alert=True)
            return
        if check_subscription(user_id, bot):
            bot.answer_callback_query(call.id, "✅ အောင်မြင်ပါသည်၊၊")
            show_home_menu(user_id, call.from_user.first_name, bot)
        else:
            bot.answer_callback_query(call.id, "❌ Verify fail! Channel ကို အရင် Join ပေးပါ၊၊", show_alert=True)
