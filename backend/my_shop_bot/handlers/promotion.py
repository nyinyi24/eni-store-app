import html

from telebot import types
from handlers.custom_emoji import custom_inline_button
from config import DATABASE_NAME

from database import (
    get_all_admin_ids, get_promotion_claim, get_promotion_gifts,
    get_user_language, is_admin_user, is_order_promotion_eligible,
    create_promotion_claim, claim_promotion_gift_stock,
    complete_promotion_manual_claim, get_db_connection,
)


def send_promotion_gift_choice(bot, order_id, user_id):
    """Offer one gift after a completed qualifying order, only once."""
    if int(user_id) >= 9000000000:  # app-only account, no Telegram chat
        return False
    if not is_order_promotion_eligible(order_id) or get_promotion_claim(order_id):
        return False

    gifts = get_promotion_gifts(active_only=True)
    if not gifts:
        return False

    # Store the entitlement now.  The customer can still choose later even
    # when the advertised promotion period has ended.
    if not create_promotion_claim(order_id, user_id, status="offered"):
        return False

    language = get_user_language(user_id) or "my"
    markup = types.InlineKeyboardMarkup(row_width=1)
    for gift_id, name, details, _ in gifts:
        label = f"🎁 {name}" + (f" — {details}" if details else "")
        markup.add(custom_inline_button(label[:64], callback_data=f"promo_choose_{order_id}_{gift_id}"))
    markup.add(custom_inline_button(
        "🚫 No thanks" if language == "en" else "🚫 လက်ဆောင်မယူတော့ပါ",
        callback_data=f"promo_decline_{order_id}",
    ))
    text = (
        "🎉 <b>You are eligible for a free promotion gift!</b>\n\n"
        "Please choose one gift below."
        if language == "en" else
        "🎉 <b>Promotion လက်ဆောင်တစ်မျိုး ရယူခွင့်ရရှိပါပြီ!</b>\n\n"
        "အောက်မှ ကြိုက်နှစ်သက်ရာ လက်ဆောင်တစ်မျိုးကို ရွေးချယ်ပါ။"
    )
    bot.send_message(user_id, text, reply_markup=markup, parse_mode="HTML")
    return True


def _notify_manual_pending(bot, claim_id, order_id, user_id, gift_name, details):
    text = (
        "🎁 <b>Manual Gift Pending</b>\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🆔 Claim: <code>{claim_id}</code>\n"
        f"🧾 Order: <code>{order_id}</code>\n"
        f"👤 User ID: <code>{user_id}</code>\n"
        f"🎁 Selected: <b>{html.escape(str(gift_name))}</b>\n"
        f"ℹ️ Details: {html.escape(str(details or '-'))}\n\n"
        "Auto-delivery stock မရှိပါ။ Gift info ကို အောက်ပါ command ဖြင့် manually ပို့ပါ။\n"
        f"<code>/sendgift {claim_id} gift_info</code>"
    )
    for admin_id in get_all_admin_ids():
        try:
            bot.send_message(admin_id, text, parse_mode="HTML")
        except Exception as error:
            print(f"Promotion manual notification failed for {admin_id}: {error}")


def init_promotion_handlers(bot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith("promo_choose_"))
    def choose_promotion_gift(call):
        try:
            _, _, order_id_text, gift_id_text = call.data.split("_", 3)
            order_id, gift_id = int(order_id_text), int(gift_id_text)
        except (TypeError, ValueError):
            bot.answer_callback_query(call.id, "Invalid gift request.", show_alert=True)
            return
        offer = get_promotion_claim(order_id)
        if not offer or int(offer[2]) != call.from_user.id or offer[4] != "offered":
            bot.answer_callback_query(call.id, "This gift request is unavailable.", show_alert=True)
            return
        gifts = {gift[0]: gift for gift in get_promotion_gifts(active_only=True)}
        gift = gifts.get(gift_id)
        if not gift:
            bot.answer_callback_query(call.id, "This gift is unavailable.", show_alert=True)
            return
        claim_id = create_promotion_claim(order_id, call.from_user.id, gift_id)
        if not claim_id:
            bot.answer_callback_query(call.id, "You have already chosen for this order.", show_alert=True)
            return
        content = claim_promotion_gift_stock(claim_id, gift_id)
        language = get_user_language(call.from_user.id) or "my"
        if content:
            text = (
                f"🎉 <b>Your promotion gift has arrived!</b>\n\n🎁 <b>{html.escape(str(gift[1]))}</b>\n"
                f"<code>{html.escape(str(content))}</code>"
            )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML")
            bot.answer_callback_query(call.id, "Gift delivered!")
            return
        text = (
            "✅ <b>Your gift selection has been recorded.</b>\n\n"
            f"🎁 {html.escape(str(gift[1]))}\n\nOur admin will send it to you shortly."
            if language == "en" else
            "✅ <b>သင်ရွေးချယ်ထားသော လက်ဆောင်ကို မှတ်တမ်းတင်ပြီးပါပြီ။</b>\n\n"
            f"🎁 {html.escape(str(gift[1]))}\n\nAdmin မှ အမြန်ဆုံး manually ပို့ဆောင်ပေးပါမည်။"
        )
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, parse_mode="HTML")
        bot.answer_callback_query(call.id, "ရွေးချယ်မှု အောင်မြင်ပါသည်")
        _notify_manual_pending(bot, claim_id, order_id, call.from_user.id, gift[1], gift[2])

    @bot.callback_query_handler(func=lambda call: call.data.startswith("promo_decline_"))
    def confirm_promotion_decline(call):
        order_id = call.data.rsplit("_", 1)[-1]
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            custom_inline_button("✅ Confirm", callback_data=f"promo_declineyes_{order_id}"),
            custom_inline_button("⬅️ Back", callback_data=f"promo_back_{order_id}"),
        )
        bot.edit_message_text(
            "လက်ဆောင်ကို မယူတော့မှာ သေချာပါသလား?\n\nဒီ order အတွက် နောက်တစ်ကြိမ် ပြန်ရွေး၍မရပါ။",
            call.message.chat.id, call.message.message_id, reply_markup=markup,
        )
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("promo_declineyes_"))
    def decline_promotion_gift(call):
        try:
            order_id = int(call.data.rsplit("_", 1)[-1])
        except ValueError:
            return
        offer = get_promotion_claim(order_id)
        if not offer or int(offer[2]) != call.from_user.id or offer[4] != "offered":
            bot.answer_callback_query(call.id, "This gift request is unavailable.", show_alert=True)
            return
        claim_id = create_promotion_claim(order_id, call.from_user.id, status="declined")
        if not claim_id:
            bot.answer_callback_query(call.id, "This order has already been decided.", show_alert=True)
            return
        bot.edit_message_text("✅ ဒီ order အတွက် promotion လက်ဆောင်ကို မယူတော့ပါ။", call.message.chat.id, call.message.message_id)
        bot.answer_callback_query(call.id, "Confirmed")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("promo_back_"))
    def back_to_promotion_gifts(call):
        try:
            order_id = int(call.data.rsplit("_", 1)[-1])
        except ValueError:
            return
        gifts = get_promotion_gifts(active_only=True)
        markup = types.InlineKeyboardMarkup(row_width=1)
        for gift_id, name, details, _ in gifts:
            markup.add(custom_inline_button(
                (f"🎁 {name}" + (f" — {details}" if details else ""))[:64],
                callback_data=f"promo_choose_{order_id}_{gift_id}",
            ))
        markup.add(custom_inline_button("🚫 လက်ဆောင်မယူတော့ပါ", callback_data=f"promo_decline_{order_id}"))
        bot.edit_message_text("🎉 <b>Promotion လက်ဆောင်တစ်မျိုး ရယူခွင့်ရရှိပါပြီ!</b>\n\nအောက်မှ ရွေးချယ်ပါ။", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
        bot.answer_callback_query(call.id)

    @bot.message_handler(commands=["sendgift"])
    def send_manual_promotion_gift(message):
        if not is_admin_user(message.from_user.id):
            return
        parts = message.text.split(maxsplit=2)
        if len(parts) < 3 or not parts[1].isdigit():
            bot.reply_to(message, "Usage: <code>/sendgift claim_id gift_info</code>", parse_mode="HTML")
            return
        claim_id, gift_data = int(parts[1]), parts[2]
        # Claim ID lookup is intentionally local: only pending claims can be completed.
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT c.user_id, g.name FROM promotion_claims c JOIN promotion_gifts g ON g.gift_id = c.gift_id "
                "WHERE c.claim_id = ? AND c.status = 'manual_pending'", (claim_id,)
            ).fetchone()
        if not row:
            bot.reply_to(message, "❌ Pending gift claim မတွေ့ပါ။")
            return
        user_id, gift_name = row
        if not complete_promotion_manual_claim(claim_id, message.from_user.id, gift_data):
            bot.reply_to(message, "❌ Gift claim ကို update မလုပ်နိုင်ပါ။")
            return
        bot.send_message(
            user_id,
            f"🎉 <b>သင်ရွေးချယ်ထားသော Promotion Gift ရောက်ရှိပါပြီ!</b>\n\n🎁 <b>{html.escape(str(gift_name))}</b>\n<code>{html.escape(gift_data)}</code>",
            parse_mode="HTML",
        )
        bot.reply_to(message, f"✅ Gift ကို User <code>{user_id}</code> ထံ ပို့ပြီးပါပြီ။", parse_mode="HTML")