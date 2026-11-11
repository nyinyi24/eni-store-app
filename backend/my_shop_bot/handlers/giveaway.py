import telebot
from telebot import types
from handlers.custom_emoji import custom_inline_button
import datetime
from database import get_shop_status, get_user_language, is_admin_user
from database import (
    get_all_gw_item_types, get_user_last_gw_claim,
    add_gw_claim, get_available_gw_items_by_type, reduce_gw_stock
)

def init_giveaway_handlers(bot):

    def show_giveaway_options(user_id, bot):
        """Giveaway ပစ္စည်းစာရင်းကို ပြသခြင်း"""
        gw_types = get_all_gw_item_types()
        language = get_user_language(user_id) or "my"

        markup = types.InlineKeyboardMarkup()
        back_btn = custom_inline_button("🏠 Back to Home", callback_data='home')

        if not gw_types:
            markup.add(back_btn)
            if language == "en":
                bot.send_message(user_id, "🎁 No giveaway is available right now.", reply_markup=markup)
                return
            bot.send_message(user_id, "🎁 လက်ရှိတွင် Giveaway အစီအစဉ်မရှိသေးပါ။", reply_markup=markup)
            return

        for gt in gw_types:
            markup.add(custom_inline_button(f"🎁 {gt}", callback_data=f"claim_gw_{gt}"))

        markup.add(back_btn)
        if language == "en":
            bot.send_message(
                user_id,
                "🎁 *Available Giveaways:*\n\nPlease choose the giveaway type you want to claim:",
                reply_markup=markup,
                parse_mode='Markdown'
            )
            return
        bot.send_message(
            user_id,
            "🎁 *Available Giveaways:*\n\nကံစမ်းလိုသည့် အမျိုးအစားကို ရွေးချယ်ပါ-",
            reply_markup=markup,
            parse_mode='Markdown'
        )

    @bot.callback_query_handler(func=lambda call: call.data == 'giveaway')
    def giveaway_callback(call):
        language = get_user_language(call.from_user.id) or "my"
        # Maintenance စစ်ဆေးခြင်း
        if get_shop_status() == 'maintenance' and not is_admin_user(call.from_user.id):
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

        user_id = call.from_user.id
        from handlers.start import check_subscription
        is_joined = check_subscription(user_id, bot)

        if not is_joined:
            if language == "en":
                bot.answer_callback_query(call.id, "Please join our channel first.", show_alert=True)

                markup = types.InlineKeyboardMarkup()
                markup.add(custom_inline_button("Join Our Channel", url="https://t.me/ENIpremiumstore"))
                markup.add(custom_inline_button("Verify & Continue", callback_data='giveaway'))
                markup.add(custom_inline_button("Back to Home", callback_data='home'))

                try:
                    bot.edit_message_text(
                        chat_id=call.message.chat.id,
                        message_id=call.message.message_id,
                        text="🎁 To claim giveaways, please join our channel first.",
                        reply_markup=markup
                    )
                except Exception:
                    pass
                return
            bot.answer_callback_query(call.id, "❌ Verify fail! Channel ကို မ join ရသေးပါ၊၊", show_alert=True)

            markup = types.InlineKeyboardMarkup()
            markup.add(custom_inline_button("📢 Join Our Channel", url="https://t.me/ENIpremiumstore"))
            markup.add(custom_inline_button("✅ Verify & Continue", callback_data='giveaway'))
            markup.add(custom_inline_button("🏠 Back to Home", callback_data='home'))

            try:
                bot.edit_message_text(
                    chat_id=call.message.chat.id,
                    message_id=call.message.message_id,
                    text="🎁 Giveaway ရယူရန် ကျွန်ုပ်တို့၏ Channel ကို အရင် Join ပေးပါ၊၊",
                    reply_markup=markup
                )
            except Exception:
                pass
            return

        bot.answer_callback_query(call.id, "✅ အတည်ပြုပြီးပါပြီ၊၊")
        bot.delete_message(call.message.chat.id, call.message.message_id)
        show_giveaway_options(user_id, bot)

    @bot.callback_query_handler(func=lambda call: call.data.startswith('claim_gw_'))
    def claim_giveaway(call):  # ← indent ပြင်ထားပါပြီ (မူရင်းတွင် function body က handler ပြင်ပ ထွက်နေခဲ့သည်)
        user_id   = call.from_user.id
        language = get_user_language(user_id) or "my"
        item_type = call.data.split('claim_gw_')[1]
        now       = datetime.datetime.now()

        # ၁။ နောက်ဆုံးယူခဲ့သည့်အချိန် စစ်ဆေးခြင်း (၇ ရက် cooldown)
        last_claim_time = get_user_last_gw_claim(user_id)

        if last_claim_time:
            last_date = datetime.datetime.strptime(last_claim_time, "%Y-%m-%d %H:%M:%S")

            if now < last_date + datetime.timedelta(days=7):
                next_available = last_date + datetime.timedelta(days=7)
                wait_time      = next_available - now
                days           = wait_time.days
                hours          = wait_time.seconds // 3600
                if language == "en":
                    bot.answer_callback_query(
                        call.id,
                        f"You have already claimed this week's giveaway.\n\nPlease wait {days} days {hours} hours.",
                        show_alert=True
                    )
                    return

                bot.answer_callback_query(
                    call.id,
                    f"❌ သင်သည် ဤအပတ်အတွက် Giveaway ယူပြီးပါပြီ၊၊\n\n"
                    f"နောက်ထပ် {days} ရက် {hours} နာရီ စောင့်ပေးပါဦးဗျာ၊၊",
                    show_alert=True
                )
                return

        # ၂။ ပစ္စည်းရှိမရှိ စစ်ဆေးခြင်း
        item = get_available_gw_items_by_type(item_type)
        if item:
            # item columns: gw_item_id(0), name(1), content(2), stock(3), is_used(4), rules(5)
            item_id      = item[0]
            item_content = item[2]
            item_rules   = item[5] if len(item) > 5 and item[5] else (item[4] if len(item) > 4 and isinstance(item[4], str) else "မည်သူ့ကိုမျှ မမျှဝေပါနှင့်၊၊")

            delivery_text = (
                "🎉 <b>Congratulations!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"🎁 <b>{item_type}</b> ရရှိပါပြီ:\n\n"
                f"🔑 <b>Content:</b> <code>{item_content}</code>\n\n"
                f"⚠️ <b>စည်းကမ်းချက်များ:</b>\n"
                f"<i>{item_rules}</i>\n\n"
                "━━━━━━━━━━━━━━━━━━\n"
                "⚠️ ဤအချက်အလက်ကို သေချာစွာ သိမ်းဆည်းထားပါ၊၊ ၁ ပတ်လျှင် တစ်ကြိမ်သာ ယူခွင့်ရှိပါသည်၊၊"
            )

            if language == "en":
                delivery_text = (
                    "<b>Congratulations!</b>\n"
                    "━━━━━━━━━━━━━━━━━━\n\n"
                    f"🎁 You received <b>{item_type}</b>:\n\n"
                    f"🔑 <b>Content:</b> <code>{item_content}</code>\n\n"
                    f"⚠️ <b>Rules:</b>\n<i>{item_rules}</i>\n\n"
                    "━━━━━━━━━━━━━━━━━━\n"
                    "Please store this information safely. You can claim a giveaway once per week."
                )
            bot.send_message(user_id, delivery_text, parse_mode='HTML')

            # Stock လျှော့ပြီး claim မှတ်သားမည်
            try:
                reduce_gw_stock(item_id)
                add_gw_claim(user_id, now.strftime("%Y-%m-%d %H:%M:%S"))
                print(f"✅ GW claimed: user={user_id}, item_id={item_id}")
            except Exception as e:
                print(f"❌ GW DB Error: {e}")

            bot.answer_callback_query(call.id, "✅ အောင်မြင်စွာ ရယူပြီးပါပြီ၊၊")
        else:
            bot.answer_callback_query(call.id, "😔 စိတ်မကောင်းပါဘူး၊ ပစ္စည်းကုန်သွားပါပြီ၊၊", show_alert=True)
