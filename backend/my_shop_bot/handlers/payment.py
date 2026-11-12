import telebot
from telebot import types
from handlers.custom_emoji import (
    custom_inline_button, edit_custom_emoji_message, send_custom_emoji_message,
    payment_method_custom_emoji_id,
)
import re
import html
from datetime import datetime
from config import (
    SUPPORT_URL, MMK_PER_USD, USDT_ERC20_ADDRESS, USDT_BEP20_ADDRESS,
    BINANCE_PAY_ID, STOCK_RESERVATION_MINUTES, SELL_PROOF_CHANNEL_ID
)
from database import get_shop_status, get_user_language, is_admin_user, get_all_admin_ids
from database import (
    get_item_by_id, get_item_by_name, update_order_status,
    get_order_details, update_order_delivery, 
    pull_accounts_from_stock_by_name,
    reduce_item_stock_manual, get_user_orders, get_public_order_id,
    create_reserved_order, get_available_stock, submit_payment_proof,
    get_active_reserved_order_for_user, claim_stock_reservation_for_processing,
    set_stock_reservation_remainder, complete_stock_reservation,
    reject_stock_reservation, cancel_user_stock_reservation,
    mark_payment_submission_status, claim_order_for_sell_proof,
    complete_order_sell_proof, get_order_renewal_option,
    create_existing_key_renewal_order, get_order_type,
    complete_existing_key_renewal_order, yangon_now,
    is_outline_renewable_product, get_product_custom_emoji,
    get_pending_renewal_outline_data, get_coupon_for_user,
    is_gift_card_product, is_apple_gift_card, is_telegram_direct_product,
    update_order_target_username, get_order_target_username, get_mmk_per_usd,
    get_user_vip_discount_percent, get_user_wallet, adjust_user_wallet_balance,
    create_order, OUTLINE_GUIDE_POST_URL, find_bot_user_by_identifier,
    set_order_gift_metadata, get_order_gift_metadata
)
from handlers.promotion import send_promotion_gift_choice
from outline_api import (
    renew_access_key, create_access_key, get_key_data_usage,
    is_configured as is_outline_api_configured
)
from crypto_api import (
    is_binance_api_configured, is_onchain_api_configured, is_cryptopay_configured,
    verify_evm_usdt_transaction, verify_binance_pay_transaction,
    create_cryptopay_invoice, check_cryptopay_invoice
)
# ယာယီ အော်ဒါမှတ်တမ်းများကို သိမ်းရန်
pending_orders = {}
pending_coupons = {}
applied_coupons = {}
pending_tg_usernames = {}
confirmed_tg_usernames = {}
confirmed_gift_regions = set()
pending_gift_recipient_step = {}   # user_id -> (item_id, qty)
pending_gift_note_step = {}        # user_id -> (item_id, qty, recipient_dict)
confirmed_gift_orders = {}         # user_id -> {"item_id": int, "qty": int, "recipient_id": int, "recipient_label": str, "message": str, "sender_name": str}
pending_crypto_tx_input = {}       # user_id -> (order_id, method)
cryptopay_invoices = {}            # order_id -> invoice_id

def format_payment_amount(amount_mmk, language):
    amount_mmk = float(amount_mmk)
    if language == "en":
        rate = get_mmk_per_usd() or MMK_PER_USD or 4500
        amount_usd = amount_mmk / rate
        return f"${amount_usd:.2f}"
    return f"{int(amount_mmk):,} MMK"


def quantity_stepper_markup(item_id, quantity):
    """A compact selector which stays safe even when stock is very large."""
    markup = types.InlineKeyboardMarkup(row_width=3)
    markup.row(
        custom_inline_button("➖", callback_data=f"qty_{item_id}_{quantity}_minus"),
        custom_inline_button(f"{quantity} ခု", callback_data="qty_noop"),
        custom_inline_button("➕", callback_data=f"qty_{item_id}_{quantity}_plus"),
    )
    markup.add(custom_inline_button("✅ မိမိအတွက် ဝယ်ယူမည် (Continue)", callback_data=f"buy_{item_id}_{quantity}", _style="success"))
    markup.add(custom_inline_button("🎁 သူငယ်ချင်းထံ တိုက်ရိုက် Gift ဝယ်ပို့မည်", callback_data=f"buygift_{item_id}_{quantity}", _style="primary"))
    markup.add(custom_inline_button("⬅️ Back to Shop", callback_data="shop", _style="primary"))
    return markup


def quantity_selection_text(item_name, raw_price, item_stock, language, short_detail="", product_info=""):
    unit_price = format_payment_amount(float(raw_price), language)
    if language == "en":
        detail_block = f"\n📝 <b>Product Details:</b>\n{html.escape(str(product_info))}\n" if product_info else ""
        type_line = f"ℹ️ <b>Plan / Type:</b> {html.escape(str(short_detail))}\n" if short_detail else ""
        return (
            f"📦 <b>{html.escape(str(item_name))}</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"{type_line}"
            f"💵 <b>Unit Price:</b> <code>{unit_price}</code>\n"
            f"📊 <b>Available Stock:</b> <b>{item_stock} pcs</b>\n"
            f"{detail_block}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            "👇 Use ➖ / ➕ to choose quantity, then tap <b>Continue</b>:"
        )
    detail_block = f"\n📝 <b>Product Details:</b>\n{html.escape(str(product_info))}\n" if product_info else ""
    type_line = f"ℹ️ <b>အမျိုးအစား:</b> {html.escape(str(short_detail))}\n" if short_detail else ""
    return (
        f"📦 <b>{html.escape(str(item_name))}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{type_line}"
        f"💵 <b>တစ်ခုဈေး:</b> <code>{unit_price}</code>\n"
        f"📊 <b>လက်ကျန် Stock:</b> <b>{item_stock} ခု</b>\n"
        f"{detail_block}\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "👇 ➖ / ➕ ကိုသုံးပြီး အရေအတွက်ရွေးကာ <b>Continue</b> ကိုနှိပ်ပါ -"
    )


def payment_instruction_emoji_slots(method):
    """Message icons for payment instructions; method uses its button emoji."""
    payment_icon = payment_method_custom_emoji_id(method)
    method_slot = ("✅", "payment_method", 0, payment_icon) if payment_icon else ("✅", "payment_method")
    pay_id_slot = ("📍", "payment_pay_id", 0, payment_icon) if payment_icon else ("📍", "payment_pay_id")
    return (
        method_slot,
        ("💰", "payment_amount"),
        ("🆔", "payment_order_id"),
        pay_id_slot,
        ("📝", "payment_note"),
        ("📸", "payment_screenshot"),
        ("⏳", "payment_reservation"),
    )


def delivery_emoji_slots(item_name):
    item = get_item_by_name(item_name)
    product_emoji_id = get_product_custom_emoji(item[0]) if item else ""
    product_slot = ("📦", "delivery_product")
    if product_emoji_id:
        product_slot = (*product_slot, 0, product_emoji_id)
    return (
        ("🎉", "delivery_title"), product_slot, ("📧", "delivery_account"),
        ("🙏", "delivery_thanks"), ("✨", "delivery_service"),
        ("🛠", "delivery_support"),
    )

def get_localized_item_text(item, language):
    short_detail = item[2]
    product_info = item[5] if len(item) > 5 and item[5] else "Product details မရှိသေးပါ။"
    if language == "en":
        short_detail = item[6] if len(item) > 6 and item[6] else item[2]
        product_info = item[7] if len(item) > 7 and item[7] else "English product details are not available yet."
    return short_detail, product_info

def get_wallet_info(method):
    wallet_map = {
        "erc20": ("USDT ERC20", USDT_ERC20_ADDRESS),
        "bep20": ("USDT BEP20", USDT_BEP20_ADDRESS),
        "binance": ("Binance Pay", BINANCE_PAY_ID),
        "cryptobot": ("Telegram @CryptoBot (USDT)", "CRYPTOPAY_INVOICE"),
    }
    return wallet_map.get(method, (method.upper(), ""))

def get_expiry_label(expiry_date, language):
    if not expiry_date:
        return "Expiry Date" if language == "en" else "သက်တမ်းရက်စွဲ"
    try:
        expiry_dt = datetime.strptime(str(expiry_date), "%Y-%m-%d %H:%M:%S")
        is_expired = expiry_dt < yangon_now()
    except ValueError:
        is_expired = False
    if language == "en":
        return "Expired At" if is_expired else "Current Expiry"
    return "သက်တမ်းကုန်ပြီးသောရက်" if is_expired else "လက်ရှိသက်တမ်းကုန်မည့်ရက်"

def send_renewed_key_message(bot, target_user_id, renewal):
    if is_app_only_user(target_user_id):
        return
    language = get_user_language(target_user_id) or "my"
    safe_item_name = html.escape(str(renewal["item_name"]))
    safe_expiry = html.escape(str(renewal["expiry_date"]))
    access_data = renewal.get("outline_access_url") or renewal.get("delivered_data") or ""
    safe_access_data = html.escape(str(access_data))

    if language == "en":
        text = (
            "✅ <b>Your existing Outline key has been renewed.</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Item:</b> {safe_item_name}\n"
            f"📅 <b>New Expiry Date:</b> <code>{safe_expiry}</code>\n\n"
            "🔑 <b>Use the same key/link:</b>\n"
            f"<code>{safe_access_data}</code>\n\n"
            "No need to import a new key. You can continue using your current VPN profile."
        )
    else:
        text = (
            "✅ <b>လက်ရှိအသုံးပြုနေသော Outline Key ကို Renew လုပ်ပြီးပါပြီ။</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Item:</b> {safe_item_name}\n"
            f"📅 <b>သက်တမ်းကုန်မည့်ရက်အသစ်:</b> <code>{safe_expiry}</code>\n\n"
            "🔑 <b>Key/Link အဟောင်းကိုပဲ ဆက်သုံးနိုင်ပါတယ်:</b>\n"
            f"<code>{safe_access_data}</code>\n\n"
            "Key အသစ်ပြောင်းထည့်ရန် မလိုပါ။ လက်ရှိ VPN profile ကိုပဲ ဆက်အသုံးပြုနိုင်ပါတယ်ခင်ဗျာ။"
        )
    bot.send_message(target_user_id, text, parse_mode="HTML")

def _extract_apple_redeem_code(account_data):
    for line in str(account_data or "").splitlines():
        cleaned = line.strip()
        if cleaned.lower().startswith("account ") and ":" in cleaned:
            cleaned = cleaned.split(":", 1)[1].strip()
        if re.fullmatch(r"[A-Z0-9]{12,19}", cleaned):
            return cleaned
    match = re.search(r"\b([A-Z0-9]{16})\b", str(account_data or ""))
    return match.group(1) if match else None

def check_and_send_low_stock_alert(bot, item_name):
    try:
        if is_telegram_direct_product(item_name):
            return
        item = get_item_by_name(item_name)
        if not item:
            return
        avail = get_available_stock(item[0])
        if avail <= 2:
            alert_msg = (
                "⚠️ <b>Low Stock Alert!</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>Product:</b> {html.escape(str(item[1]))} (ID: <code>{item[0]}</code>)\n"
                f"📊 <b>လက်ကျန် Stock:</b> <b>{avail}</b> ခုသာ ကျန်ပါတော့သည်။\n\n"
                "Stock ထပ်ဖြည့်ရန် <code>/addstock</code> သို့မဟုတ် <code>/setstock</code> ကို အသုံးပြုပါ။"
            )
            for admin_id in get_all_admin_ids():
                try:
                    bot.send_message(admin_id, alert_msg, parse_mode="HTML")
                except Exception:
                    pass
    except Exception as e:
        print(f"Low stock alert error: {e}")

def is_app_only_user(user_id):
    """Mobile-app accounts without a linked Telegram chat use synthetic IDs >= 9,000,000,000."""
    try:
        return int(user_id) >= 9000000000
    except Exception:
        return False


def send_delivery_message(bot, target_user_id, item_name, account_data):
    if is_app_only_user(target_user_id):
        # No Telegram chat exists; the app reads delivered_data from the order itself.
        return
    language = get_user_language(target_user_id) or "my"
    review_markup = types.InlineKeyboardMarkup()
    if is_apple_gift_card(item_name):
        redeem_code = _extract_apple_redeem_code(account_data)
        if redeem_code:
            review_markup.add(
                types.InlineKeyboardButton(
                    "🍎 Redeem Now on App Store",
                    url=f"https://apps.apple.com/redeem?ctx=offercodes&id=&code={redeem_code}"
                )
            )
    if "outline" in str(item_name or "").lower():
        review_markup.add(
            types.InlineKeyboardButton(
                "📖 Outline အသုံးပြုနည်း လမ်းညွှန်",
                url=OUTLINE_GUIDE_POST_URL
            )
        )
    review_markup.add(custom_inline_button("✍️ Review / Feedback ပေးရန်", callback_data="give_review"))

    safe_item_name = html.escape(str(item_name))
    safe_account_data = html.escape(str(account_data))
    delivery_msg = (
        "🎉 <b>သင်ဝယ်ယူထားသော ပစ္စည်းရောက်ရှိပါပြီ!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>Item:</b> {safe_item_name}\n"
        f"📧 <b>Account Info:</b>\n<code>{safe_account_data}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🙏 <b>ENI Premium Store ကို အားပေးမှုအတွက် အထူးပင် ကျေးဇူးတင်ရှိပါတယ်ဗျာ၊၊</b>\n"
        "✨ <i>လူကြီးမင်းတို့၏ စိတ်တိုင်းကျ ဝန်ဆောင်မှုပေးနိုင်ရန် အမြဲ ကြိုးစားနေပါမည်၊၊</i>\n\n"
        "🛠 အဆင်မပြေမှုတစ်စုံတစ်ရာရှိပါက Admin @independence_N ကို ချက်ချင်း ဆက်သွယ်နိုင်ပါသည်၊၊"
    )

    if language == "en":
        review_markup = types.InlineKeyboardMarkup()
        if is_apple_gift_card(item_name):
            redeem_code = _extract_apple_redeem_code(account_data)
            if redeem_code:
                review_markup.add(
                    types.InlineKeyboardButton(
                        "🍎 Redeem Now on App Store",
                        url=f"https://apps.apple.com/redeem?ctx=offercodes&id=&code={redeem_code}"
                    )
                )
        if "outline" in str(item_name or "").lower():
            review_markup.add(
                types.InlineKeyboardButton(
                    "📖 Outline Setup Guide",
                    url=OUTLINE_GUIDE_POST_URL
                )
            )
        review_markup.add(custom_inline_button("Review / Feedback", callback_data="give_review"))
        delivery_msg = (
        "🎉 <b>Your purchased product has been delivered!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📦 <b>Item:</b> {safe_item_name}\n"
        f"📧 <b>Account Info:</b>\n<code>{safe_account_data}</code>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🙏 <b>Thank you for supporting ENI Premium Store.</b>\n"
        "✨ <i>We will always do our best to provide a service that meets your needs.</i>\n\n"
        "🛠 If you experience any issue, please contact Admin @independence_N immediately."
    )

    send_custom_emoji_message(
        bot, target_user_id, delivery_msg, delivery_emoji_slots(item_name),
        reply_markup=review_markup,
    )

def deliver_direct_gift_if_needed(bot, order_id, item_name, account_data):
    """If an order was purchased as a Direct Gift for another Bot user, deliver the Gift Card directly to them!"""
    gift_meta = get_order_gift_metadata(order_id)
    if not gift_meta:
        return False
    order = get_order_details(order_id)
    buyer_id = int(order[1]) if order else 0
    expiry_str = str(order[9] or "") if order and len(order) > 9 else ""
    recipient_id = gift_meta["recipient_id"]
    recipient_label = gift_meta["recipient_label"]
    sender_name = gift_meta["sender_name"]
    gift_note = gift_meta["gift_message"]

    gift_card_msg = (
        "🎁✨ <b>SPECIAL DIGITAL GIFT FOR YOU!</b> ✨🎁\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"💌 <b>From:</b> <b>{html.escape(sender_name)}</b>\n"
        f"💬 <b>Message:</b> <i>\"{html.escape(gift_note)}\"</i>\n\n"
        f"📦 <b>Gift Item:</b> <b>{html.escape(str(item_name))}</b>\n"
        f"🔑 <b>Account / Redeem Data:</b>\n<code>{html.escape(str(account_data))}</code>\n"
        + (f"\n📅 <b>Valid Until:</b> <code>{html.escape(expiry_str)}</code>\n" if expiry_str else "\n")
        + "━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏰 <i>Powered by ENI Premium Store</i>"
    )
    gift_markup = types.InlineKeyboardMarkup(row_width=1)
    if is_apple_gift_card(item_name):
        redeem_code = _extract_apple_redeem_code(account_data)
        if redeem_code:
            gift_markup.add(
                types.InlineKeyboardButton(
                    "🍎 Redeem Now on App Store",
                    url=f"https://apps.apple.com/redeem?ctx=offercodes&id=&code={redeem_code}"
                )
            )
    if "outline" in str(item_name or "").lower():
        gift_markup.add(types.InlineKeyboardButton("📖 Outline အသုံးပြုနည်း လမ်းညွှန်", url=OUTLINE_GUIDE_POST_URL))
    gift_markup.add(custom_inline_button("🛒 My Orders တွင်ကြည့်ရန်", callback_data="my_orders", _style="primary"))
    gift_markup.add(custom_inline_button("✍️ Review / Feedback ပေးရန်", callback_data="give_review", _style="primary"))

    delivered_directly = False
    try:
        bot.send_message(recipient_id, gift_card_msg, reply_markup=gift_markup, parse_mode="HTML")
        delivered_directly = True
    except Exception as e:
        print(f"Direct gift send to {recipient_id} failed: {e}")

    if buyer_id:
        if delivered_directly:
            buyer_confirm = (
                "🎉🎁 <b>Direct Gift ပို့ဆောင်မှု အောင်မြင်ပါပြီ!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"🎯 <b>လက်ခံသူ:</b> <b>{html.escape(recipient_label)}</b>\n"
                f"📦 <b>လက်ဆောင်ပစ္စည်း:</b> <b>{html.escape(str(item_name))}</b>\n"
                f"💬 <b>ဆုတောင်းစာ:</b> <i>\"{html.escape(gift_note)}\"</i>\n\n"
                "✅ <b>Bot မှ လက်ခံသူထံသို့ အကောင့်နှင့် လက်ဆောင်ကတ်ကို တိုက်ရိုက် ပို့ဆောင်ပေးပြီးပါပြီ!</b>\n"
                "<i>(လုံခြုံရေးအရ အကောင့်အချက်အလက်ကို လက်ခံသူထံသို့သာ သီးသန့်ပို့ပေးထားပါသည်)</i>"
            )
            buyer_markup = types.InlineKeyboardMarkup()
            buyer_markup.add(custom_inline_button("✍️ Review / Feedback ပေးရန်", callback_data="give_review"))
            bot.send_message(buyer_id, buyer_confirm, reply_markup=buyer_markup, parse_mode="HTML")
        else:
            bot.send_message(
                buyer_id,
                "⚠️ လက်ခံသူသည် Bot ကို Block ထားသဖြင့် တိုက်ရိုက်ပို့မရပါ။ အောက်ပါ Gift Card ကို သူငယ်ချင်းထံ Forward ပို့ပေးနိုင်ပါသည် 👇",
                parse_mode="HTML",
            )
            bot.send_message(buyer_id, gift_card_msg, reply_markup=gift_markup, parse_mode="HTML")
    return True



def complete_auto_verified_crypto_order(bot, user_id, order_id, unique_tx_id, paid_label, chat_id, message_id=None):
    """Atomically record the verified TxID/Transaction, prevent replay, and auto-deliver the order!"""
    order = get_order_details(order_id)
    if not order:
        bot.send_message(chat_id, "❌ Order not found.")
        return False

    submit_res = submit_payment_proof(order_id, user_id, unique_tx_id, unique_tx_id)
    if submit_res == "duplicate_proof":
        bot.send_message(
            chat_id,
            "❌ <b>This Transaction ID / Hash has already been used for another order!</b>",
            parse_mode="HTML",
        )
        return False
    if submit_res not in ("submitted", "already_submitted"):
        bot.send_message(
            chat_id,
            f"⚠️ Order reservation is no longer active (<code>{html.escape(str(submit_res))}</code>). Please contact Support.",
            parse_mode="HTML",
        )
        return False

    claim_status = claim_stock_reservation_for_processing(order_id, admin_id=0)
    if claim_status not in ("claimed", "legacy"):
        bot.send_message(chat_id, "ℹ️ This order is already being processed.")
        return False

    mark_payment_submission_status(order_id, "approved", admin_id=0)
    pending_orders.pop(user_id, None)

    item_name = str(order[2])
    requested_quantity = max(1, int(order[3] or 1))
    pub_code = get_public_order_id(order)

    # Case 1: Existing Outline Key Renewal
    if get_order_type(order_id) == "renewal":
        pending_renewal = get_pending_renewal_outline_data(order_id)
        if pending_renewal:
            renew_access_key(
                pending_renewal["outline_key_id"],
                pending_renewal["item_name"],
                pending_renewal["order_code"],
                pending_renewal["expiry_date"],
            )
        renewal = complete_existing_key_renewal_order(order_id)
        if renewal:
            send_renewed_key_message(bot, user_id, renewal)
            publish_sell_proof(bot, order_id)
            send_promotion_gift_choice(bot, order_id, user_id)
            return True

    # Case 2: Standard Product or Direct Gift
    account_list = pull_accounts_from_stock_by_name(item_name, requested_quantity)
    if not account_list and "outline" in item_name.lower() and is_outline_api_configured():
        for _ in range(requested_quantity):
            res = create_access_key(item_name, pub_code, order[9] or "")
            if res.get("ok"):
                account_list.append(res["formatted"])
        if account_list:
            reduce_item_stock_manual(item_name, len(account_list))

    check_and_send_low_stock_alert(bot, item_name)

    if account_list and len(account_list) >= requested_quantity:
        acc_data = "\n\n".join(f"Account {i}:\n{a}" for i, a in enumerate(account_list, 1))
        update_order_delivery(order_id, acc_data)
        update_order_status(order_id, "Success", reduce_stock=False)
        complete_stock_reservation(order_id)
        if not deliver_direct_gift_if_needed(bot, order_id, item_name, acc_data):
            send_delivery_message(bot, user_id, item_name, acc_data)
        publish_sell_proof(bot, order_id)
        send_promotion_gift_choice(bot, order_id, user_id)

        done_text = (
            "⚡✅ <b>Crypto Payment Verified Automatically!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>Item:</b> {html.escape(item_name)} (x{requested_quantity})\n"
            f"💵 <b>Verified Payment:</b> <b>{html.escape(paid_label)}</b>\n"
            f"🧾 <b>Order ID:</b> <code>{html.escape(str(pub_code))}</code>\n"
            f"🔗 <b>Ref:</b> <code>{html.escape(str(unique_tx_id))}</code>\n\n"
            "🎉 Your product has been delivered instantly!"
        )
        if message_id:
            try:
                bot.edit_message_text(done_text, chat_id, message_id, parse_mode="HTML")
            except Exception:
                bot.send_message(chat_id, done_text, parse_mode="HTML")
        else:
            bot.send_message(chat_id, done_text, parse_mode="HTML")
        return True

    # Case 3: Paid & Verified, but requires manual delivery (e.g. Telegram @username direct or stock empty)
    target_uname = get_order_target_username(order_id)
    adm_markup = types.InlineKeyboardMarkup(row_width=2)
    adm_markup.add(
        custom_inline_button("✅ Deliver / Complete", callback_data=f"admin_approve_{order_id}"),
    )
    for admin_id in get_all_admin_ids():
        try:
            bot.send_message(
                admin_id,
                "⚡💵 <b>Auto-Verified Crypto Order (Ready to Deliver)!</b>\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"📦 Item: <b>{html.escape(item_name)}</b> (x{requested_quantity})\n"
                + (f"🎯 Target Username: <code>{html.escape(str(target_uname))}</code>\n" if target_uname else "")
                + f"💰 Paid: <b>{html.escape(paid_label)}</b>\n"
                f"🔗 Verified Ref: <code>{html.escape(str(unique_tx_id))}</code>\n"
                f"🆔 Order ID: <code>{html.escape(str(pub_code))}</code>",
                reply_markup=adm_markup,
                parse_mode="HTML",
            )
        except Exception:
            pass

    bot.send_message(
        chat_id,
        f"✅ <b>Payment of {html.escape(paid_label)} Verified Automatically!</b>\n"
        f"🧾 Order ID: <code>{html.escape(str(pub_code))}</code>\n\n"
        "⏳ Our admin has been notified and will complete your delivery shortly.",
        parse_mode="HTML",
    )
    return True


def mask_customer_name(first_name, username):
    display_name = str(first_name or username or "").strip().lstrip("@")
    if not display_name:
        return "Anonymous Customer"
    return f"{display_name[0]}***"

def publish_sell_proof(bot, order_id, admin_chat_id=None):
    if not SELL_PROOF_CHANNEL_ID:
        return False

    order = claim_order_for_sell_proof(order_id)
    if not order:
        return False

    (
        _, order_code, item_name, quantity, payment_method, timestamp,
        first_name, username
    ) = order
    public_code = str(order_code or f"ORD-{order_id:010d}")
    masked_code = f"ORD-••••{public_code[-4:]}"
    masked_customer = mask_customer_name(first_name, username)
    proof_text = (
        "🛍️ <b>New Purchase Completed</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"👤 <b>Customer:</b> {html.escape(masked_customer)}\n"
        f"📦 <b>Product:</b> {html.escape(str(item_name))}\n"
        f"🔢 <b>Quantity:</b> {int(quantity or 1)}\n"
        f"💳 <b>Payment:</b> {html.escape(str(payment_method or '-'))}\n"
        f"🆔 <b>Order:</b> <code>{html.escape(masked_code)}</code>\n"
        f"📅 <b>Order Date:</b> {html.escape(str(timestamp or '-'))}\n\n"
        "✅ <b>Successfully delivered to our customer.</b>\n"
        "🙏 Thank you for choosing ENI Premium Store."
    )

    try:
        bot.send_message(SELL_PROOF_CHANNEL_ID, proof_text, parse_mode="HTML")
        complete_order_sell_proof(order_id, True)
        return True
    except Exception as error:
        complete_order_sell_proof(order_id, False)
        print(f"Sell proof channel post failed for order {order_id}: {error}")
        if admin_chat_id:
            try:
                bot.send_message(
                    admin_chat_id,
                    (
                        "⚠️ <b>Sell Proof Channel ထဲ post မတင်နိုင်ပါ။</b>\n\n"
                        f"Order: <code>{html.escape(public_code)}</code>\n"
                        f"Error: <code>{html.escape(str(error))}</code>\n\n"
                        "Bot ကို channel admin ခန့်ထားခြင်းနဲ့ "
                        "<code>SELL_PROOF_CHANNEL_ID</code> ကို စစ်ဆေးပါ။"
                    ),
                    parse_mode="HTML"
                )
            except Exception:
                pass
        return False


# =====================================================================
# 🌟 (၁) MANUAL DELIVERY FUNCTION (🚨 အပြင်ဘက်သို့ လုံးဝ ဆွဲထုတ်လိုက်ပါပြီ)
# =====================================================================
def process_manual_delivery(message, bot, target_user_id, item_name, order_id, original_caption, admin_msg_id, manual_quantity=None):
    if not is_admin_user(message.from_user.id): return
    
    account_data = message.text.strip()
    
    # Database အား အောင်မြင်ကြောင်း အခြေအနေပြောင်းလဲခြင်း
    existing_order = get_order_details(order_id)
    existing_delivery = existing_order[7] if existing_order and len(existing_order) > 7 and existing_order[7] else ""
    if manual_quantity is None and existing_order:
        manual_quantity = int(existing_order[3] or 1) if not existing_delivery else 0
    if manual_quantity and int(manual_quantity) > 0:
        reduce_item_stock_manual(item_name, int(manual_quantity))
    update_order_status(order_id, "Success", reduce_stock=False)
    complete_stock_reservation(order_id)
    mark_payment_submission_status(order_id, "approved", message.from_user.id)
    combined_account_data = f"{existing_delivery}\n\n{account_data}".strip() if existing_delivery else account_data
    update_order_delivery(order_id, combined_account_data)
    
    # Admin Chat ရှိ Message အား အခြေအနေ ပြောင်းလဲခြင်း
    try:
        bot.edit_message_caption(original_caption + "\n\n✅ *Status: Manual-Delivered*", 
                                 message.chat.id, admin_msg_id, parse_mode='Markdown')
    except Exception as e:
        print(f"Error editing admin caption: {e}")

    if not deliver_direct_gift_if_needed(bot, order_id, item_name, account_data):
        send_delivery_message(bot, target_user_id, item_name, account_data)
    send_promotion_gift_choice(bot, order_id, target_user_id)
    publish_sell_proof(bot, order_id, message.chat.id)
    bot.send_message(message.chat.id, f"✅ User <code>{target_user_id}</code> ထံ ပစ္စည်းကို Manual စနစ်ဖြင့် ပို့ဆောင်ပြီးပါပြီဗျာ၊၊", parse_mode='HTML')


# =====================================================================
# 🌟 (၂) PAYMENT HANDLERS
# =====================================================================
def init_payment_handlers(bot):

    @bot.callback_query_handler(func=lambda call: call.data.startswith("buygift_"))
    def handle_buy_as_gift_start(call):
        try:
            _, item_id_str, qty_str = call.data.split("_")
            item_id, qty = int(item_id_str), int(qty_str)
        except Exception:
            bot.answer_callback_query(call.id, "Invalid gift request.", show_alert=True)
            return

        item = get_item_by_id(item_id)
        if not item or get_available_stock(item_id) < qty:
            bot.answer_callback_query(call.id, "❌ Stock မလုံလောက်ပါ။", show_alert=True)
            return

        pending_gift_recipient_step[call.from_user.id] = (item_id, qty)
        bot.answer_callback_query(call.id)
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button("❌ Cancel", callback_data=f"buy_{item_id}", _style="danger"))
        msg = bot.edit_message_text(
            "🎁 <b>သူငယ်ချင်းထံ တိုက်ရိုက် Gift ဝယ်ပို့ရန် (Step 1/2)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📦 <b>ရွေးချယ်ထားသောပစ္စည်း:</b> <b>{html.escape(str(item[1]))}</b> (x{qty})\n\n"
            "👤 <b>လက်ဆောင်ပေးပို့လိုသော သူငယ်ချင်း၏ Telegram <code>@username</code> သို့မဟုတ် <code>User ID</code> ကို ရိုက်ပို့ပေးပါ -</b>\n"
            "<i>(မှတ်ချက် - လက်ခံမည့်သူသည် ဤ Bot ကို <code>/start</code> နှိပ်ထားပြီးသူ ဖြစ်ရပါမည်)</i>",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup,
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_buygift_recipient)

    def _process_buygift_recipient(message):
        state = pending_gift_recipient_step.pop(message.from_user.id, None)
        if not state:
            return
        item_id, qty = state
        raw_input = (message.text or "").strip()
        if not raw_input or raw_input.startswith("/"):
            bot.reply_to(message, "❌ Gift ဝယ်ယူမှုကို ပယ်ဖျက်လိုက်ပါသည်။")
            return

        recipient = find_bot_user_by_identifier(raw_input)
        if not recipient:
            retry_markup = types.InlineKeyboardMarkup()
            retry_markup.add(
                custom_inline_button("🔄 ပြန်လည်ရိုက်ထည့်မည်", callback_data=f"buygift_{item_id}_{qty}", _style="primary"),
                custom_inline_button("⬅️ Back", callback_data=f"buy_{item_id}", _style="danger"),
            )
            bot.reply_to(
                message,
                f"❌ <b>{html.escape(raw_input)}</b> ကို Bot အသုံးပြုသူစာရင်းထဲတွင် ရှာမတွေ့ပါ။\n\n"
                "💡 <i>သင့်သူငယ်ချင်းကို ဤ Bot (@ENIpremiumstore_bot) ထဲသို့ အရင်ဝင်ပြီး <code>/start</code> နှိပ်ခိုင်းပါ သို့မဟုတ် သူ၏ Profile ထဲမှ <b>User ID</b> ဂဏန်းကို တောင်းယူပြီး ပြန်ထည့်ပေးပါ။</i>",
                reply_markup=retry_markup,
                parse_mode="HTML",
            )
            return

        if int(recipient["user_id"]) == int(message.from_user.id):
            retry_markup = types.InlineKeyboardMarkup()
            retry_markup.add(
                custom_inline_button("🔄 အခြားသူရွေးမည်", callback_data=f"buygift_{item_id}_{qty}", _style="primary"),
                custom_inline_button("✅ မိမိအတွက်ပဲဝယ်မည်", callback_data=f"buy_{item_id}_{qty}", _style="success"),
            )
            bot.reply_to(
                message,
                "ℹ️ မိမိအကောင့်သို့ ပြန်ပို့ရန်မလိုပါ။ သူငယ်ချင်း၏ @username / User ID ကို ရွေးချယ်ပါ သို့မဟုတ် မိမိအတွက် တိုက်ရိုက်ဝယ်ယူနိုင်ပါသည်။",
                reply_markup=retry_markup,
            )
            return

        pending_gift_note_step[message.from_user.id] = (item_id, qty, recipient)
        msg = bot.reply_to(
            message,
            "🎁 <b>သူငယ်ချင်းထံ တိုက်ရိုက် Gift ဝယ်ပို့ရန် (Step 2/2)</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✅ <b>လက်ခံမည့်သူ:</b> <b>{html.escape(recipient['display'])}</b>\n\n"
            "💌 <b>လက်ဆောင်ကတ်ပေါ်တွင် ရေးသားလိုသော ဆုတောင်းစာသား / Message တိုလေး တစ်ကြောင်း ရိုက်ပို့ပေးပါ -</b>\n"
            "<i>(ဥပမာ - Happy Birthday ပါ သူငယ်ချင်း! 🎉 / ချစ်တယ်နော် ❤️)</i>",
            parse_mode="HTML",
        )
        bot.register_next_step_handler(msg, _process_buygift_note)

    def _process_buygift_note(message):
        state = pending_gift_note_step.pop(message.from_user.id, None)
        if not state:
            return
        item_id, qty, recipient = state
        note = (message.text or "").strip()
        if not note or note.startswith("/"):
            bot.reply_to(message, "❌ Cancelled.")
            return

        sender_name = message.from_user.first_name or (f"@{message.from_user.username}" if message.from_user.username else "Your Friend")
        confirmed_gift_orders[message.from_user.id] = {
            "item_id": item_id,
            "qty": qty,
            "recipient_id": int(recipient["user_id"]),
            "recipient_label": recipient["display"],
            "message": note[:200],
            "sender_name": sender_name,
        }
        if recipient.get("username"):
            confirmed_tg_usernames[message.from_user.id] = f"@{recipient['username'].lstrip('@')}"

        pay_markup = types.InlineKeyboardMarkup()
        pay_markup.add(
            custom_inline_button("💳 ငွေပေးချေမှု ရွေးချယ်ရန် (Continue to Payment)", callback_data=f"buy_{item_id}_{qty}", _style="success")
        )
        bot.reply_to(
            message,
            "🎁✨ <b>Direct Gift Order အသင့်ဖြစ်ပါပြီ!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🎯 <b>ပေးပို့မည့်သူ:</b> <b>{html.escape(recipient['display'])}</b>\n"
            f"💬 <b>Message:</b> <i>\"{html.escape(note[:200])}\"</i>\n\n"
            "👇 ငွေပေးချေပြီးသည်နှင့် Bot က သင့်သူငယ်ချင်းထံသို့ လက်ဆောင်ကတ်နှင့် အကောင့်ကို တိုက်ရိုက် ပို့ဆောင်ပေးပါမည် -",
            reply_markup=pay_markup,
            parse_mode="HTML",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("gc_confirm_"))
    def handle_gift_card_confirm(call):
        try:
            _, _, item_id, qty = call.data.split("_")
            confirmed_gift_regions.add((call.from_user.id, int(item_id)))
            bot.answer_callback_query(call.id, "Confirmed.")
            call.data = f"buy_{item_id}_{qty}"
            handle_buy_button(call)
        except Exception as e:
            print(f"Gift card confirm error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("tguser_self_"))
    def handle_tg_username_self(call):
        try:
            _, _, item_id, qty = call.data.split("_")
            if not call.from_user.username:
                bot.answer_callback_query(call.id, "သင့်အကောင့်တွင် @username မရှိသေးပါ။", show_alert=True)
                return
            confirmed_tg_usernames[call.from_user.id] = f"@{call.from_user.username}"
            bot.answer_callback_query(call.id, f"Selected @{call.from_user.username}")
            call.data = f"buy_{item_id}_{qty}"
            handle_buy_button(call)
        except Exception as e:
            print(f"TG username self error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("tguser_ask_"))
    def handle_tg_username_ask(call):
        try:
            _, _, item_id, qty = call.data.split("_")
            pending_tg_usernames[call.from_user.id] = (int(item_id), int(qty))
            language = get_user_language(call.from_user.id) or "my"
            prompt_text = (
                "✍️ Please send the recipient Telegram <code>@username</code> (e.g. <code>@john_doe</code>):"
                if language == "en"
                else "✍️ လက်ခံမည့် Telegram Username ကို <code>@username</code> ပုံစံဖြင့် ရိုက်ပို့ပေးပါ (ဥပမာ - <code>@my_username</code>):"
            )
            msg = bot.send_message(call.message.chat.id, prompt_text, parse_mode="HTML")
            bot.register_next_step_handler(msg, process_tg_username_input)
            bot.answer_callback_query(call.id)
        except Exception as e:
            print(f"TG username ask error: {e}")

    def process_tg_username_input(message):
        state = pending_tg_usernames.pop(message.from_user.id, None)
        if not state:
            return
        item_id, qty = state
        language = get_user_language(message.from_user.id) or "my"
        raw_username = (message.text or "").strip()
        if raw_username.startswith("/"):
            bot.reply_to(message, "❌ Cancelled.")
            return
        if not raw_username.startswith("@"):
            raw_username = "@" + raw_username
        if not re.fullmatch(r"^@[a-zA-Z0-9_]{5,32}$", raw_username):
            err_msg = (
                "❌ Invalid Telegram username format. Please tap the product in Shop and try again."
                if language == "en"
                else "❌ Username ပုံစံ မမှန်ကန်ပါ (အနည်းဆုံး စာလုံး ၅ လုံး ရှိရပါမည်)။ Shop မှ ပြန်ရွေးပေးပါ။"
            )
            bot.reply_to(message, err_msg, parse_mode="HTML")
            return
        confirmed_tg_usernames[message.from_user.id] = raw_username
        markup = types.InlineKeyboardMarkup()
        btn_label = "💳 Continue to Payment" if language == "en" else "💳 ငွေပေးချေမှု ဆက်လုပ်ရန်"
        markup.add(custom_inline_button(btn_label, callback_data=f"buy_{item_id}_{qty}"))
        ok_msg = (
            f"✅ Recipient account <b>{html.escape(raw_username)}</b> saved. Tap below to choose payment method:"
            if language == "en"
            else f"✅ လက်ခံမည့်အကောင့် <b>{html.escape(raw_username)}</b> ကို မှတ်သားပြီးပါပြီ။ ငွေပေးချေရန် အောက်ပါခလုတ်ကို နှိပ်ပါ -"
        )
        bot.reply_to(message, ok_msg, reply_markup=markup, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('coupon_'))
    def coupon_entry(call):
        try:
            _, item_id, qty = call.data.split('_')
            item_obj = get_item_by_id(int(item_id))
            if item_obj and is_gift_card_product(item_obj[1]):
                bot.answer_callback_query(call.id, "Gift Card ပစ္စည်းများတွင် Coupon အသုံးပြု၍မရပါ။", show_alert=True)
                return
            pending_coupons[call.from_user.id] = (int(item_id), int(qty), call.message.chat.id, call.message.message_id)
            msg = bot.send_message(call.message.chat.id, '🎟 Coupon Code ကိုပို့ပါ။')
            bot.register_next_step_handler(msg, coupon_code_received)
            bot.answer_callback_query(call.id)
        except Exception:
            bot.answer_callback_query(call.id, 'Invalid coupon request.', show_alert=True)

    def coupon_code_received(message):
        state = pending_coupons.pop(message.from_user.id, None)
        if not state:
            return
        item_id, qty, chat_id, message_id = state
        item = get_item_by_id(item_id)
        if not item:
            bot.send_message(chat_id, "Product not found.")
            return
        raw_sub = float(item[3]) * qty
        vip_pct = get_user_vip_discount_percent(message.from_user.id, item[1])
        after_vip_sub = max(0.0, raw_sub - round(raw_sub * vip_pct / 100.0))
        coupon, reason = get_coupon_for_user(message.text.strip(), message.from_user.id, after_vip_sub)
        if not coupon:
            coupon_errors = {
                "assigned_to_other_user": "❌ ဒီ Coupon Code ကို အခြား User Account အတွက် သတ်မှတ်ထားပါသည်။\n\nသင့်အတွက်ပို့ထားသော Coupon Code ကိုသာ အသုံးပြုပါ။",
                "already_reserved": "❌ ဒီ Coupon Code ကို အခြား order တစ်ခုတွင် အသုံးပြုပြီးပါပြီ။",
                "invalid_or_expired": "❌ Coupon Code မမှန်ပါ၊ သို့မဟုတ် သက်တမ်းကုန်ဆုံးသွားပါပြီ။",
            }
            bot.send_message(chat_id, coupon_errors.get(reason, "❌ Coupon Code ကို အသုံးပြု၍မရပါ။"))
            return
        applied_coupons[message.from_user.id] = {"item_id": item_id, "quantity": qty, "code": coupon["code"], "discount": coupon["discount"]}
        payable = max(0, after_vip_sub - float(coupon["discount"]))
        payable_text = format_payment_amount(payable, get_user_language(message.from_user.id) or "my")
        markup = types.InlineKeyboardMarkup(row_width=2)
        send_callback = (
            f"pay_coupon_{item_id}_{qty}"
            if payable <= 0 else f"couponconfirm_{item_id}_{qty}"
        )
        markup.add(
            custom_inline_button("✅ Send Order", callback_data=send_callback),
            custom_inline_button("❌ Cancel Order", callback_data=f"couponcancel_{item_id}_{qty}"),
        )
        bot.send_message(
            chat_id,
            f"✅ <b>Coupon Applied</b>\n\n"
            f"📦 Item: <b>{html.escape(str(item[1]))}</b>\n"
            f"🎟 Coupon: <code>{coupon['code']}</code>\n"
            f"💸 Discount: <b>{int(coupon['discount']):,} MMK</b>\n"
            f"💰 Payable: <b>{payable_text}</b>\n\n"
            "Order ကိုအတည်ပြုရန် <b>Send Order</b> ကိုနှိပ်ပါ။",
            reply_markup=markup, parse_mode='HTML',
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith("couponcancel_"))
    def cancel_coupon_order(call):
        applied_coupons.pop(call.from_user.id, None)
        bot.answer_callback_query(call.id, "Coupon order cancelled.")
        bot.edit_message_text("❌ Coupon order ကို cancel လုပ်ပြီးပါပြီ။ Shop မှာပြန်ရွေးနိုင်ပါတယ်။", call.message.chat.id, call.message.message_id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("couponconfirm_"))
    def confirm_coupon_order(call):
        try:
            _, item_id, qty = call.data.split("_")
            item_id, qty = int(item_id), int(qty)
            coupon = applied_coupons.get(call.from_user.id)
            if not coupon or coupon.get("item_id") != item_id or coupon.get("quantity") != qty:
                bot.answer_callback_query(call.id, "Coupon session expired. Please enter the code again.", show_alert=True)
                return
            payable = max(0, float(get_item_by_id(item_id)[3]) * qty - float(coupon["discount"]))
            markup = types.InlineKeyboardMarkup(row_width=2)
            if payable <= 0:
                markup.add(custom_inline_button("✅ Send Free Order", callback_data=f"pay_coupon_{item_id}_{qty}"))
                text = "🎟 <b>100% Coupon Applied</b>\n\nScreenshot မလိုပါ။ Send Free Order ကိုနှိပ်လျှင် Admin approval သို့ပို့ပါမယ်။"
            else:
                markup.add(
                    custom_inline_button("KPay", callback_data=f"pay_kpay_{item_id}_{qty}"),
                    custom_inline_button("Wave", callback_data=f"pay_wave_{item_id}_{qty}"),
                    custom_inline_button("AYA Pay", callback_data=f"pay_aya_{item_id}_{qty}"),
                )
                text = "✅ <b>Coupon Applied</b>\n\nငွေပေးချေရန် method ကိုရွေးပါ။"
            markup.add(custom_inline_button("❌ Cancel Order", callback_data=f"couponcancel_{item_id}_{qty}"))
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")
            bot.answer_callback_query(call.id)
        except Exception as error:
            print(f"Coupon confirmation error: {error}")
            bot.answer_callback_query(call.id, "Please try again.", show_alert=True)

    @bot.callback_query_handler(func=lambda call: call.data == "qty_noop")
    def quantity_noop(call):
        bot.answer_callback_query(call.id)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("qty_"))
    def change_quantity(call):
        try:
            _, item_id, current_quantity, direction = call.data.split("_", 3)
            item_id, current_quantity = int(item_id), int(current_quantity)
            item = get_item_by_id(item_id)
            item_stock = get_available_stock(item_id)
            if not item or item_stock <= 0:
                bot.answer_callback_query(call.id, "This item is out of stock.", show_alert=True)
                return
            quantity = current_quantity + (1 if direction == "plus" else -1)
            quantity = max(1, min(quantity, int(item_stock)))
            language = get_user_language(call.from_user.id) or "my"
            raw_price = str(item[3]).replace(',', '')
            short_detail, product_info = get_localized_item_text(item, language)
            bot.edit_message_text(
                quantity_selection_text(item[1], raw_price, item_stock, language, short_detail, product_info),
                call.message.chat.id, call.message.message_id,
                reply_markup=quantity_stepper_markup(item_id, quantity), parse_mode="HTML",
            )
            bot.answer_callback_query(call.id)
        except Exception as error:
            print(f"Quantity stepper error: {error}")
            bot.answer_callback_query(call.id, "Please try again.", show_alert=True)
    
    @bot.callback_query_handler(func=lambda call: call.data.startswith('buy_'))
    def handle_buy_button(call):
        try:
            parts = call.data.split('_')
            item_id = int(parts[1])
            quantity = int(parts[2]) if len(parts) > 2 else 1
        
            item = get_item_by_id(item_id)
            if not item: 
                bot.answer_callback_query(call.id, "❌ ပစ္စည်း ရှာမတွေ့ပါ၊၊", show_alert=True)
                return

            item_name = item[1]         
            short_detail = item[2]      
            raw_price_str = str(item[3]).replace(',', '') 
            item_stock = get_available_stock(item_id)
            language = get_user_language(call.from_user.id) or "my"
            product_info = item[5] if len(item) > 5 and item[5] else "Product details မရှိသေးပါ။"
            product_info = item[6] if len(item) > 6 and item[6] else "အသေးစိတ် အချက်အလက် မရှိသေးပါ၊၊"

            product_info = item[5] if len(item) > 5 and item[5] else product_info
            short_detail, product_info = get_localized_item_text(item, language)

            if item_stock <= 0:
                if language == "en":
                    bot.answer_callback_query(call.id, "Sorry, this product is out of stock.", show_alert=True)
                    markup = types.InlineKeyboardMarkup()
                    markup.add(custom_inline_button("🔔 Notify Me When Restocked", callback_data=f"waitlist_{item_id}"))
                    markup.add(custom_inline_button("Back to Shop", callback_data="shop"))
                    bot.edit_message_text(
                        f"<b>{html.escape(str(item_name))}</b> is currently out of stock.\nPlease wait until admin restocks this product.",
                        call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML'
                    )
                    return
                bot.answer_callback_query(call.id, "❌ စိတ်မရှိပါနဲ့ဗျာ၊ ဒီပစ္စည်းက Stock ပြတ်သွားပါပြီ၊၊", show_alert=True)
                markup = types.InlineKeyboardMarkup()
                markup.add(custom_inline_button("🔔 Stock ပြန်ဝင်ရင် အကြောင်းကြားပါ", callback_data=f"waitlist_{item_id}"))
                markup.add(custom_inline_button("⬅️ Back to Shop", callback_data="shop"))
                bot.edit_message_text(
                    f"⚠️ <b>{item_name}</b> က လက်ရှိမှာ Stock ပြတ်လပ်နေပါသည်၊၊\nAdmin ဘက်မှ Stock ပြန်ဖြည့်ပေးရန် ခေတ္တစောင့်ဆိုင်းပေးပါဦး၊၊",
                    call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML'
                )
                return

            if len(parts) == 2:
                confirmed_gift_regions.discard((call.from_user.id, item_id))
                confirmed_tg_usernames.pop(call.from_user.id, None)
                confirmed_gift_orders.pop(call.from_user.id, None)
                bot.edit_message_text(
                    quantity_selection_text(item_name, raw_price_str, item_stock, language, short_detail, product_info),
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=quantity_stepper_markup(item_id, 1),
                    parse_mode='HTML'
                )
                return

            if item_stock < quantity:
                if language == "en":
                    bot.answer_callback_query(call.id, f"Only {item_stock} pcs left.", show_alert=True)
                    return
                bot.answer_callback_query(call.id, f"❌ လက်ကျန် {item_stock} ခုပဲ ရှိပါတော့တယ်ဗျာ၊၊", show_alert=True)
                return

            # Gate 1: Gift Card Region & No-Refund Confirmation Gate
            if is_gift_card_product(item_name) and (call.from_user.id, item_id) not in confirmed_gift_regions:
                warn_markup = types.InlineKeyboardMarkup(row_width=1)
                if language == "en":
                    warn_markup.add(
                        custom_inline_button("✅ I confirm my Account Region matches (Continue)", callback_data=f"gc_confirm_{item_id}_{quantity}"),
                        custom_inline_button("⬅️ Back to Shop", callback_data="shop"),
                    )
                    warn_text = (
                        "⚠️ <b>Important Region & Non-Refundable Notice</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📦 <b>Item:</b> {html.escape(str(item_name))}\n\n"
                        "• Your Apple/Store Account Region <b>must match</b> this Gift Card's region.\n"
                        "• Once the redeem code is delivered, <b>no refunds or exchanges</b> can be provided under any circumstances.\n\n"
                        "Do you confirm and wish to proceed?"
                    )
                else:
                    warn_markup.add(
                        custom_inline_button("✅ Region မှန်ကန်ကြောင်း သေချာပါသည် (ဆက်ဝယ်မည်)", callback_data=f"gc_confirm_{item_id}_{quantity}"),
                        custom_inline_button("⬅️ Back to Shop", callback_data="shop"),
                    )
                    warn_text = (
                        "⚠️ <b>အရေးကြီးသတိပေးချက် (Gift Card Region Confirmation)</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📦 <b>ပစ္စည်း:</b> {html.escape(str(item_name))}\n\n"
                        "▪️ သင့် Account (Apple ID) Region နှင့် ယခုဝယ်ယူမည့် Gift Card Region ကိုက်ညီမှသာ ထည့်သွင်း (Redeem) နိုင်ပါမည်။\n"
                        "▪️ ကုဒ်ထုတ်ပေးပြီးပါက <b>လုံးဝ (လုံးဝ) ပြန်လဲပေးခြင်း / ငွေပြန်အမ်းခြင်း မပြုလုပ်ပေးပါ။</b>\n\n"
                        "ဆက်လက်ဝယ်ယူရန် သေချာပါသလား?"
                    )
                bot.edit_message_text(warn_text, call.message.chat.id, call.message.message_id, reply_markup=warn_markup, parse_mode="HTML")
                return

            # Gate 2: Telegram Premium / Stars Recipient @username Gate
            if is_telegram_direct_product(item_name) and call.from_user.id not in confirmed_tg_usernames:
                tg_markup = types.InlineKeyboardMarkup(row_width=1)
                if call.from_user.username:
                    self_label = (
                        f"👤 Use My Account (@{call.from_user.username})"
                        if language == "en"
                        else f"👤 ကျွန်ုပ်၏အကောင့် (@{call.from_user.username}) သို့ထည့်မည်"
                    )
                    tg_markup.add(custom_inline_button(self_label, callback_data=f"tguser_self_{item_id}_{quantity}"))
                other_label = "🎁 Enter Another @username" if language == "en" else "🎁 အခြား @username ရိုက်ထည့်မည်"
                tg_markup.add(
                    custom_inline_button(other_label, callback_data=f"tguser_ask_{item_id}_{quantity}"),
                    custom_inline_button("⬅️ Back to Shop", callback_data="shop"),
                )
                if language == "en":
                    tg_text = (
                        "🌟 <b>Select Recipient Telegram Username</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📦 <b>Item:</b> {html.escape(str(item_name))}\n"
                        f"🔢 <b>Quantity:</b> {quantity}\n\n"
                        "Please select the Telegram <b>@username</b> that will receive this subscription/stars:"
                    )
                else:
                    tg_text = (
                        "🌟 <b>လက်ခံမည့် Telegram Username ရွေးချယ်ပေးပါ</b>\n"
                        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                        f"📦 <b>ပစ္စည်း:</b> {html.escape(str(item_name))}\n"
                        f"🔢 <b>အရေအတွက်:</b> {quantity} ခု\n\n"
                        "Telegram Premium / Stars ပို့ဆောင်ပေးရမည့် <b>@username</b> ကို ရွေးချယ်ပါ -"
                    )
                bot.edit_message_text(tg_text, call.message.chat.id, call.message.message_id, reply_markup=tg_markup, parse_mode="HTML")
                return

            price_per_item = int(float(raw_price_str))
            subtotal_price = price_per_item * quantity
            vip_pct = get_user_vip_discount_percent(call.from_user.id, item_name)
            vip_discount_mmk = int(round(subtotal_price * vip_pct / 100.0)) if vip_pct > 0 else 0
            total_price = max(0, subtotal_price - vip_discount_mmk)
            user_wallet = get_user_wallet(call.from_user.id)
            wallet_bal = int(user_wallet["balance"])
            language = get_user_language(call.from_user.id) or "my"
            formatted_price = format_payment_amount(price_per_item, language)
            formatted_subtotal = format_payment_amount(subtotal_price, language)
            formatted_total = format_payment_amount(total_price, language)
            recipient_tg = confirmed_tg_usernames.get(call.from_user.id)

            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                custom_inline_button(
                    f"⚡ Wallet ဖြင့် တိုက်ရိုက်ဝယ်မည် (Bal: {wallet_bal:,} MMK)",
                    callback_data=f"walletbuy_{item_id}_{quantity}"
                )
            )
            markup.add(
                custom_inline_button("KPay", callback_data=f"pay_kpay_{item_id}_{quantity}"),
                custom_inline_button("Wave", callback_data=f"pay_wave_{item_id}_{quantity}"),
                custom_inline_button("AYA Pay", callback_data=f"pay_aya_{item_id}_{quantity}")
            )
            if not is_gift_card_product(item_name):
                markup.add(custom_inline_button("🎟 Coupon Code ထည့်မယ်", callback_data=f"coupon_{item_id}_{quantity}"))
            markup.add(custom_inline_button("⬅️ Back to Shop", callback_data="shop"))

            if language == "en":
                markup = types.InlineKeyboardMarkup(row_width=2)
                markup.add(
                    custom_inline_button(
                        f"⚡ Pay with Wallet (Bal: {wallet_bal:,} MMK)",
                        callback_data=f"walletbuy_{item_id}_{quantity}"
                    )
                )
                markup.add(
                    custom_inline_button("USDT ERC20", callback_data=f"pay_erc20_{item_id}_{quantity}"),
                    custom_inline_button("USDT BEP20", callback_data=f"pay_bep20_{item_id}_{quantity}"),
                    custom_inline_button("Binance Pay", callback_data=f"pay_binance_{item_id}_{quantity}"),
                )
                if is_cryptopay_configured():
                    markup.add(
                        custom_inline_button("💎 CryptoBot (Instant 1-Click USDT)", callback_data=f"pay_cryptobot_{item_id}_{quantity}", _style="success")
                    )
                if not is_gift_card_product(item_name):
                    markup.add(custom_inline_button("Coupon Code", callback_data=f"coupon_{item_id}_{quantity}"))
                markup.add(custom_inline_button("⬅️ Back to Shop", callback_data="shop"))

            if vip_discount_mmk > 0:
                price_block_my = (
                    f"💵 <b>တစ်ခုဈေး:</b> <code>{formatted_price}</code>\n"
                    f"🧾 <b>မူလကျသင့်ငွေ:</b> <s>{formatted_subtotal}</s>\n"
                    f"🏅 <b>VIP Discount ({vip_pct}% OFF):</b> <code>-{vip_discount_mmk:,} MMK</code>\n"
                    f"💰 <b>ပေးချေရမည့် စုစုပေါင်း:</b> <code>{formatted_total}</code>\n"
                )
                price_block_en = (
                    f"💵 <b>Unit Price:</b> <code>{formatted_price}</code>\n"
                    f"🧾 <b>Subtotal:</b> <s>{formatted_subtotal}</s>\n"
                    f"🏅 <b>VIP Discount ({vip_pct}% OFF):</b> <code>-{format_payment_amount(vip_discount_mmk, 'en')}</code>\n"
                    f"💰 <b>Total Payable:</b> <code>{formatted_total}</code>\n"
                )
            else:
                price_block_my = (
                    f"💵 <b>တစ်ခုဈေး:</b> <code>{formatted_price}</code>\n"
                    f"💰 <b>စုစုပေါင်း:</b> <code>{formatted_total}</code>\n"
                )
                price_block_en = (
                    f"💵 <b>Unit Price:</b> <code>{formatted_price}</code>\n"
                    f"💰 <b>Total:</b> <code>{formatted_total}</code>\n"
                )

            gift_info = confirmed_gift_orders.get(call.from_user.id)
            if gift_info and gift_info.get("item_id") == item_id:
                target_line_my = (
                    f"🎁 <b>Direct Gift လက်ခံသူ:</b> <b>{html.escape(gift_info['recipient_label'])}</b>\n"
                    f"💬 <b>Gift Message:</b> <i>\"{html.escape(gift_info['message'])}\"</i>\n\n"
                )
                target_line_en = (
                    f"🎁 <b>Gift Recipient:</b> <b>{html.escape(gift_info['recipient_label'])}</b>\n"
                    f"💬 <b>Gift Message:</b> <i>\"{html.escape(gift_info['message'])}\"</i>\n\n"
                )
            else:
                target_line_my = f"🎯 <b>လက်ခံမည့်အကောင့်:</b> <code>{html.escape(recipient_tg)}</code>\n\n" if recipient_tg else "\n"
                target_line_en = f"🎯 <b>Recipient:</b> <code>{html.escape(recipient_tg)}</code>\n\n" if recipient_tg else "\n"
            text = (
                f"💳 <b>Payment Confirmation</b>\n"
                f"━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>ပစ္စည်း:</b> {item_name}\n"
                f"ℹ️ <b>အမျိုးအစား:</b> {short_detail}\n"
                f"📊 <b>လက်ကျန်:</b> {item_stock} ခု\n" 
                f"🔢 <b>ဝယ်ယူမည့် အရေအတွက်:</b> {quantity} ခု\n"
                f"{price_block_my}"
                f"{target_line_my}"
                f"📝 <b>Product Details:</b>\n{product_info}\n\n"
                f"━━━━━━━━━━━━━━━━━━\n"
                f"👇 <b>ငွေပေးချေမည့် နည်းလမ်းကို ရွေးချယ်ပါ:</b>"
            )
            if language == "en":
                text = (
                    f"💳 <b>Payment Confirmation</b>\n"
                    f"━━━━━━━━━━━━━━━━━━\n\n"
                    f"📦 <b>Item:</b> {html.escape(str(item_name))}\n"
                    f"ℹ️ <b>Type:</b> {html.escape(str(short_detail))}\n"
                    f"📊 <b>Stock:</b> {item_stock} pcs\n"
                    f"🔢 <b>Quantity:</b> {quantity}\n"
                    f"{price_block_en}"
                    f"{target_line_en}"
                    f"📝 <b>Product Details:</b>\n{html.escape(str(product_info))}\n\n"
                    f"━━━━━━━━━━━━━━━━━━\n"
                    f"👇 <b>Please choose your payment method:</b>"
                )
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except Exception as e:
            print(f"Buy Button Error: {e}")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('renew_existing_'))
    def handle_existing_key_renewal(call):
        try:
            source_order_id = int(call.data.rsplit('_', 1)[1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id, "Invalid renewal request.", show_alert=True)
            return

        user_id = call.from_user.id
        language = get_user_language(user_id) or "my"
        option = get_order_renewal_option(source_order_id, user_id)
        if not option:
            bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
            return
        if not is_outline_renewable_product(option.get("item_name")):
            bot.answer_callback_query(
                call.id,
                (
                    "This product cannot be renewed. Please buy a new key/account."
                    if language == "en"
                    else "ယခု product ကို renew လုပ်လို့မရပါ။ အသစ်ဝယ်ယူပေးပါ။"
                ),
                show_alert=True,
            )
            return

        item = get_item_by_name(option["item_name"])
        renewal_quantity = max(1, int(option.get("quantity") or 1))
        unit_price = float(item[3]) if item and len(item) > 3 and item[3] is not None else float(option.get("current_price") or 0)
        amount = unit_price * renewal_quantity
        formatted_total = format_payment_amount(amount, language)
        expiry_label = get_expiry_label(option.get("expiry_date"), language)
        safe_expiry = html.escape(str(option.get("expiry_date") or "-"))
        markup = types.InlineKeyboardMarkup(row_width=2)
        if language == "en":
            markup.add(
                custom_inline_button("USDT ERC20", callback_data=f"renewpay_erc20_{source_order_id}"),
                custom_inline_button("USDT BEP20", callback_data=f"renewpay_bep20_{source_order_id}"),
            )
            markup.add(custom_inline_button("Binance Pay", callback_data=f"renewpay_binance_{source_order_id}"))
            text = (
                "🔄 <b>Renew Existing Outline Key</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>Item:</b> {html.escape(str(option['item_name']))}\n"
                f"🔢 <b>Quantity:</b> {renewal_quantity}\n"
                f"📅 <b>{expiry_label}:</b> <code>{safe_expiry}</code>\n"
                f"💰 <b>Renewal Amount:</b> <code>{formatted_total}</code>\n\n"
                "Please choose your payment method."
            )
        else:
            markup.add(
                custom_inline_button("KPay", callback_data=f"renewpay_kpay_{source_order_id}"),
                custom_inline_button("Wave", callback_data=f"renewpay_wave_{source_order_id}"),
                custom_inline_button("AYA Pay", callback_data=f"renewpay_aya_{source_order_id}"),
            )
            text = (
                "🔄 <b>လက်ရှိ Outline Key ကို Renew လုပ်မည်</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>Item:</b> {html.escape(str(option['item_name']))}\n"
                f"🔢 <b>အရေအတွက်:</b> {renewal_quantity}\n"
                f"📅 <b>{expiry_label}:</b> <code>{safe_expiry}</code>\n"
                f"💰 <b>Renewal ကျသင့်ငွေ:</b> <code>{formatted_total}</code>\n\n"
                "ငွေပေးချေမည့်နည်းလမ်းကို ရွေးချယ်ပေးပါ။"
            )
        markup.add(custom_inline_button("❌ Cancel", callback_data="my_orders"))
        bot.answer_callback_query(call.id)
        bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode="HTML")

    @bot.callback_query_handler(func=lambda call: call.data.startswith('renewpay_'))
    def handle_renewal_payment_method(call):
        parts = call.data.split('_')
        method, source_order_id = parts[1], int(parts[2])
        user_id = call.from_user.id
        language = get_user_language(user_id) or "my"

        wallet_label = ""
        wallet_address = ""
        if language == "en":
            wallet_label, wallet_address = get_wallet_info(method)
            if not wallet_address:
                bot.answer_callback_query(
                    call.id,
                    "Wallet address is not configured. Please contact support.",
                    show_alert=True
                )
                return

        reservation = create_existing_key_renewal_order(
            source_order_id,
            user_id,
            method.upper(),
            reservation_minutes=STOCK_RESERVATION_MINUTES,
        )
        if not reservation["ok"]:
            reason = reservation.get("reason")
            notice = (
                "Your previous payment is still under review."
                if reason == "existing_order_under_review" and language == "en"
                else "အရင်ပေးပို့ထားသော payment ကို Admin စစ်ဆေးနေဆဲဖြစ်ပါတယ်။"
                if reason == "existing_order_under_review"
                else "This key cannot be renewed. Please buy a new key."
                if language == "en"
                else "ဒီ key ကို renew မလုပ်နိုင်ပါ။ Key အသစ်ဝယ်ပေးပါ။"
            )
            bot.answer_callback_query(call.id, notice, show_alert=True)
            return

        internal_order_id = reservation["order_id"]
        order_code = reservation["order_code"]
        formatted_total = format_payment_amount(reservation["total_amount"], language)
        pending_orders[user_id] = {
            "order_id": internal_order_id,
            "order_code": order_code,
            "item_name": reservation["item_name"],
            "qty": reservation["quantity"],
            "total": reservation["total_amount"],
            "method": method.upper(),
            "expires_at": reservation["expires_at"],
            "order_type": "renewal",
            "source_order_id": source_order_id,
        }

        markup = types.InlineKeyboardMarkup()
        if language == "en":
            text = (
                f"✅ <b>{wallet_label}</b> selected for renewal\n\n"
                f"💰 <b>Amount:</b> <code>{formatted_total}</code>\n"
                f"🆔 <b>Order ID:</b> <code>{order_code}</code>\n\n"
                f"📍 <b>Wallet / Pay ID:</b>\n<code>{html.escape(wallet_address)}</code>\n\n"
                "📝 <b>Note:</b> Please write <b>Payment</b> only.\n\n"
                f"⏳ <b>Payment reservation: {STOCK_RESERVATION_MINUTES} minutes.</b>\n"
                f"Expires at: <code>{reservation['expires_at']}</code>\n\n"
                "📸 After payment, please send the payment screenshot here."
            )
        else:
            text = (
                f"✅ *{method.upper()}* ကို Renew payment အတွက် ရွေးချယ်ထားပါတယ်၊၊\n\n"
                f"💰 ကျသင့်ငွေ: {formatted_total}\n"
                f"🆔 Order ID: `{order_code}`\n\n"
                f"📍 *ငွေလွှဲရန်:* `09975374020` (NNML)\n\n"
                "📝 *မှတ်ချက်:* Note တွင် `Pyament (သိုမဟုတ်) ငွေပေးချေခြင်း` လိုသာရေးပေးပါ။\n\n"
                f"⏳ *Payment reservation ကို {STOCK_RESERVATION_MINUTES} မိနစ် သိမ်းထားပေးပါမယ်။*\n"
                f"ကုန်ဆုံးချိန်: `{reservation['expires_at']}`\n\n"
                "📸 ငွေလွှဲပြီးပါက ပြေစာ Screenshot ကို ပို့ပေးပါ၊၊"
            )
        markup.add(
            custom_inline_button("🎧 Support", url=SUPPORT_URL),
            custom_inline_button(
                "❌ Cancel",
                callback_data=f"cancel_reservation_{internal_order_id}"
            )
        )
        bot.answer_callback_query(call.id, "Renewal order reserved.")
        edit_custom_emoji_message(
            bot, call.message.chat.id, call.message.message_id, text, payment_instruction_emoji_slots(method),
            reply_markup=markup,
            fallback_parse_mode="HTML" if language == "en" else "Markdown",
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith('walletbuy_'))
    def handle_wallet_instant_buy(call):
        try:
            _, item_id_str, qty_str = call.data.split('_')
            item_id, qty = int(item_id_str), int(qty_str)
        except Exception:
            bot.answer_callback_query(call.id, "Invalid request.", show_alert=True)
            return

        user_id = call.from_user.id
        language = get_user_language(user_id) or "my"
        item = get_item_by_id(item_id)
        if not item or get_available_stock(item_id) < qty:
            bot.answer_callback_query(
                call.id,
                "Out of stock." if language == "en" else "❌ Stock မလုံလောက်ပါ။",
                show_alert=True
            )
            return

        if is_telegram_direct_product(item[1]) and user_id not in confirmed_tg_usernames:
            call.data = f"buy_{item_id}_{qty}"
            handle_buy_button(call)
            return

        raw_subtotal = float(item[3]) * qty
        vip_pct = get_user_vip_discount_percent(user_id, item[1])
        vip_disc = round(raw_subtotal * vip_pct / 100.0) if vip_pct > 0 else 0.0
        after_vip = max(0.0, raw_subtotal - vip_disc)

        selected_coupon = applied_coupons.get(user_id)
        coupon_disc = 0.0
        if selected_coupon and selected_coupon.get("item_id") == item_id and selected_coupon.get("quantity") == qty:
            coupon_disc = min(after_vip, float(selected_coupon.get("discount", 0)))
        payable = max(0.0, after_vip - coupon_disc)

        user_wallet = get_user_wallet(user_id)
        if user_wallet["balance"] < payable:
            shortfall = int(payable - user_wallet["balance"])
            topup_markup = types.InlineKeyboardMarkup(row_width=1)
            topup_markup.add(
                custom_inline_button("💳 Wallet ငွေဖြည့်ရန် (Top-up Now)", callback_data="wallet_topup_menu"),
                custom_inline_button("⬅️ Back to Payment Options", callback_data=f"buy_{item_id}_{qty}"),
            )
            bot.answer_callback_query(
                call.id,
                f"❌ Wallet လက်ကျန်ငွေ မလုံလောက်ပါ။ (လိုအပ်ငွေ: {int(payable):,} MMK / လက်ရှိ: {int(user_wallet['balance']):,} MMK)",
                show_alert=True,
            )
            bot.edit_message_text(
                "💳 <b>Wallet လက်ကျန်ငွေ မလုံလောက်ပါ</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>ပစ္စည်း:</b> {html.escape(str(item[1]))} (x{qty})\n"
                f"💰 <b>ကျသင့်ငွေ:</b> <code>{int(payable):,} MMK</code>\n"
                f"💳 <b>လက်ရှိ Wallet Balance:</b> <code>{int(user_wallet['balance']):,} MMK</code>\n"
                f"⚠️ <b>ထပ်မံလိုအပ်ငွေ:</b> <b>{shortfall:,} MMK</b>\n\n"
                "အောက်ပါခလုတ်မှတစ်ဆင့် Wallet ငွေဖြည့်သွင်းနိုင်ပါသည် သို့မဟုတ် KPay / Wave / AYA Pay ဖြင့် တိုက်ရိုက်ဝယ်ယူနိုင်ပါသည်။",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=topup_markup,
                parse_mode="HTML",
            )
            return

        ok, new_bal = adjust_user_wallet_balance(user_id, -payable)
        if not ok:
            bot.answer_callback_query(call.id, "❌ Wallet လက်ကျန်ငွေ မလုံလောက်ပါ။", show_alert=True)
            return

        applied_coupons.pop(user_id, None)
        confirmed_gift_regions.discard((user_id, item_id))
        target_uname = confirmed_tg_usernames.pop(user_id, None)

        now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
        product_text = " ".join(str(p) for p in (item[1], item[2], item[5] if len(item) > 5 else "") if p)
        order_id = create_order(user_id, item[1], qty, "WALLET", "Pending", now_text, product_text=product_text, total_amount=payable)
        if target_uname:
            update_order_target_username(order_id, target_uname)
        gift_info = confirmed_gift_orders.pop(user_id, None)
        if gift_info and gift_info.get("item_id") == item_id:
            set_order_gift_metadata(
                order_id,
                gift_info["recipient_id"],
                gift_info["recipient_label"],
                gift_info["message"],
                gift_info["sender_name"],
            )

        account_list = pull_accounts_from_stock_by_name(item[1], qty)
        if not account_list and "outline" in item[1].lower() and is_outline_api_configured():
            order_obj = get_order_details(order_id)
            pub_code = get_public_order_id(order_obj)
            for _ in range(qty):
                res = create_access_key(item[1], pub_code, order_obj[9] or "")
                if res.get("ok"):
                    account_list.append(res["formatted"])
            if account_list:
                reduce_item_stock_manual(item[1], len(account_list))

        check_and_send_low_stock_alert(bot, item[1])
        bot.answer_callback_query(call.id, "⚡ Wallet Payment Successful!")

        if account_list:
            acc_data = "\n\n".join(f"Account {i}:\n{a}" for i, a in enumerate(account_list, 1))
            update_order_delivery(order_id, acc_data)
            update_order_status(order_id, "Success", reduce_stock=False)
            if not deliver_direct_gift_if_needed(bot, order_id, item[1], acc_data):
                send_delivery_message(bot, user_id, item[1], acc_data)
            publish_sell_proof(bot, order_id)
            send_promotion_gift_choice(bot, order_id, user_id)
            bot.edit_message_text(
                "⚡ <b>Wallet Instant Purchase Completed!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>ပစ္စည်း:</b> {html.escape(str(item[1]))} (x{qty})\n"
                + (f"🏅 <b>VIP Discount ({vip_pct}%):</b> -{int(vip_disc):,} MMK\n" if vip_disc > 0 else "")
                + f"💰 <b>ပေးချေခဲ့သည့်ငွေ:</b> <b>{int(payable):,} MMK</b>\n"
                f"💳 <b>လက်ကျန် Wallet:</b> <b>{int(new_bal):,} MMK</b>\n\n"
                "✅ သင့်ပစ္စည်းအချက်အလက်ကို အောက်ပါ Message တွင် ပို့ဆောင်ပေးထားပါသည်ခင်ဗျာ။",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML",
            )
        else:
            order_obj = get_order_details(order_id)
            pub_code = get_public_order_id(order_obj)
            buyer_uname = f"@{call.from_user.username}" if getattr(call.from_user, "username", None) else "မရှိပါ"
            adm_markup = types.InlineKeyboardMarkup(row_width=2)
            adm_markup.add(
                custom_inline_button("✅ Approve / Deliver", callback_data=f"admin_approve_{order_id}"),
                custom_inline_button("❌ Reject", callback_data=f"admin_reject_{order_id}"),
            )
            for admin_id in get_all_admin_ids():
                try:
                    bot.send_message(
                        admin_id,
                        "⚡ <b>New Wallet-Paid Order!</b>\n\n"
                        f"👤 User ID: <code>{user_id}</code> ({html.escape(buyer_uname)})\n"
                        f"📦 Item: {html.escape(str(item[1]))}\n"
                        f"🔢 Quantity: {qty}\n"
                        + (f"🎯 <b>Target Username:</b> {html.escape(str(target_uname))}\n" if target_uname else "")
                        + f"💰 Paid via Wallet: <b>{int(payable):,} MMK</b>\n"
                        f"🆔 Order ID: <code>{html.escape(str(pub_code))}</code>",
                        reply_markup=adm_markup,
                        parse_mode="HTML",
                    )
                except Exception:
                    pass
            bot.edit_message_text(
                "✅ <b>Wallet ဖြင့် ငွေပေးချေမှု အောင်မြင်ပါပြီ!</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📦 <b>ပစ္စည်း:</b> {html.escape(str(item[1]))} (x{qty})\n"
                f"💰 <b>ပေးချေခဲ့သည့်ငွေ:</b> <b>{int(payable):,} MMK</b>\n"
                f"💳 <b>လက်ကျန် Wallet:</b> <b>{int(new_bal):,} MMK</b>\n\n"
                "⏳ Admin ဘက်မှ သင့်အော်ဒါကို အမြန်ဆုံး ပို့ဆောင်ပေးသွားပါမည်ခင်ဗျာ။",
                call.message.chat.id,
                call.message.message_id,
                parse_mode="HTML",
            )

    @bot.callback_query_handler(func=lambda call: call.data.startswith('pay_'))
    def handle_payment_method(call):
        parts = call.data.split('_')
        method, item_id, qty = parts[1], int(parts[2]), int(parts[3])
        user_id = call.from_user.id
        item = get_item_by_id(item_id)
        if not item: return

        language = get_user_language(user_id) or "my"
        selected_coupon = applied_coupons.get(user_id)
        coupon_matches_order = bool(
            selected_coupon
            and selected_coupon.get("item_id") == item_id
            and selected_coupon.get("quantity") == qty
        )
        coupon_code = selected_coupon.get("code") if coupon_matches_order else None
        coupon_is_free = coupon_matches_order and float(selected_coupon.get("discount", 0)) >= float(item[3]) * qty
        wallet_label = ""
        wallet_address = ""
        if language == "en":
            wallet_label, wallet_address = get_wallet_info(method)
            if not wallet_address and not coupon_is_free:
                bot.answer_callback_query(
                    call.id,
                    "Wallet address is not configured. Please contact support.",
                    show_alert=True
                )
                return

        if is_telegram_direct_product(item[1]) and user_id not in confirmed_tg_usernames:
            call.data = f"buy_{item_id}_{qty}"
            handle_buy_button(call)
            return

        target_username = confirmed_tg_usernames.get(user_id)
        product_text = " ".join(str(part) for part in (item[1], item[2], item[5] if len(item) > 5 else "") if part)
        reservation = create_reserved_order(
            user_id,
            item_id,
            qty,
            method.upper(),
            product_text=product_text,
            reservation_minutes=STOCK_RESERVATION_MINUTES,
            coupon_code=coupon_code,
            target_username=target_username,
        )
        if not reservation["ok"]:
            reason = reservation.get("reason")
            if reason == "coupon_unavailable":
                applied_coupons.pop(user_id, None)
                bot.answer_callback_query(call.id, "Coupon unavailable. Please enter another code.", show_alert=True)
                return
            if reason == "insufficient_stock":
                available = reservation.get("available_stock", 0)
                notice = (
                    f"Only {available} pcs are currently available."
                    if language == "en"
                    else f"လက်ရှိဝယ်ယူနိုင်သော stock {available} ခုပဲ ကျန်ပါတော့တယ်။"
                )
            elif reason == "existing_order_under_review":
                notice = (
                    "Your previous payment is still under review."
                    if language == "en"
                    else "အရင်ပေးပို့ထားသော payment ကို Admin စစ်ဆေးနေဆဲဖြစ်ပါတယ်။"
                )
            else:
                notice = "Unable to reserve this product. Please try again."
            bot.answer_callback_query(call.id, notice, show_alert=True)
            return

        internal_order_id = reservation["order_id"]
        target_username = confirmed_tg_usernames.pop(user_id, None)
        confirmed_gift_regions.discard((user_id, item_id))
        if target_username:
            update_order_target_username(internal_order_id, target_username)
        gift_info = confirmed_gift_orders.pop(user_id, None)
        if gift_info and gift_info.get("item_id") == item_id:
            set_order_gift_metadata(
                internal_order_id,
                gift_info["recipient_id"],
                gift_info["recipient_label"],
                gift_info["message"],
                gift_info["sender_name"],
            )
        # Disable the button panel that created this order.  A second tap must
        # not look like it can create another order while admin is reviewing.
        try:
            bot.edit_message_reply_markup(
                call.message.chat.id, call.message.message_id, reply_markup=None
            )
        except Exception as error:
            print(f"Could not clear completed order buttons: {error}")
        if coupon_code:
            applied_coupons.pop(user_id, None)
        order_code = reservation["order_code"]
        total_amount = reservation["total_amount"]
        formatted_total = format_payment_amount(total_amount, language)
        pending_orders[user_id] = {
            "order_id": internal_order_id,
            "order_code": order_code,
            "item_name": reservation["item_name"],
            "qty": reservation["quantity"],
            "total": total_amount,
            "method": method.upper(),
            "expires_at": reservation["expires_at"],
            "target_username": target_username,
        }
        # A user can tap after Telegram's callback window has expired.  The
        # acknowledgement may then fail, but creating the order must continue.
        try:
            bot.answer_callback_query(call.id, "Stock reserved.")
        except Exception as error:
            print(f"Payment callback acknowledgement failed: {error}")
        order_id = order_code

        if reservation.get("fully_discounted"):
            buyer_uname = f"@{call.from_user.username}" if getattr(call.from_user, "username", None) else "-"
            admin_text = (
                "🎟 100% Coupon Order — Approval Required\n\n"
                f"👤 User ID: {user_id} ({buyer_uname})\n"
                f"📦 Item: {reservation['item_name']}\n"
                f"🔢 Quantity: {reservation['quantity']}\n"
                + (f"🎯 Target Username: {target_username}\n" if target_username else "")
                + f"🎟 Coupon: {coupon_code or ''}\n"
                "💰 Amount: 0 MMK\n"
                f"🆔 Order ID: {order_code}"
            )
            admin_markup = types.InlineKeyboardMarkup()
            admin_markup.add(
                custom_inline_button("✅ Approve", callback_data=f"admin_approve_{internal_order_id}"),
                custom_inline_button("❌ Reject", callback_data=f"admin_reject_{internal_order_id}"),
            )
            delivered_to_admin = 0
            for admin_id in get_all_admin_ids():
                try:
                    bot.send_message(admin_id, admin_text, reply_markup=admin_markup)
                    delivered_to_admin += 1
                except Exception as error:
                    print(f"Failed to send coupon order alert to admin {admin_id}: {error}")
            cancel_markup = types.InlineKeyboardMarkup()
            cancel_markup.add(custom_inline_button("❌ Cancel order", callback_data=f"cancel_reservation_{internal_order_id}"))
            if delivered_to_admin:
                bot.send_message(user_id, "Your 100% coupon order is waiting for admin approval.", reply_markup=cancel_markup)
            else:
                bot.send_message(
                    user_id,
                    "⚠️ Admin ကို order alert ပို့မရသေးပါ။ Support ကိုဆက်သွယ်ပေးပါ။",
                    reply_markup=cancel_markup,
                )
            return

        text = (
            f"✅ *{method.upper()}* ကို ရွေးချယ်ထားပါတယ်၊၊\n\n"
            f"💰 ကျသင့်ငွေ: {formatted_total}\n"
            f"🆔 Order ID: `{order_id}`\n\n"
            f"📍 *ငွေလွှဲရန်:* `09975374020` (NNML)\n\n"
            "📝 *မှတ်ချက်:* Note တွင် `Pyament (သိုမဟုတ်) ငွေပေးချေခြင်း` လိုသာရေးပေးပါ။\n\n"
            "📸 ငွေလွှဲပြီးပါက ပြေစာ Screenshot ကို ပို့ပေးပါ၊၊"
        )
        if language == "en":
            text = (
                f"✅ *{method.upper()}* selected\n\n"
                f"💰 Amount: {formatted_total}\n"
                f"🆔 Order ID: `{order_id}`\n\n"
                "👇 Please choose the wallet/network below.\n"
                "After payment, send the payment screenshot here."
            )
        markup = types.InlineKeyboardMarkup()
        if language == "en":
            rate = get_mmk_per_usd() or MMK_PER_USD or 4500
            usd_amount = round(float(total_amount) / rate, 2)
            if method == "cryptobot":
                inv = create_cryptopay_invoice(usd_amount, order_id, reservation["item_name"])
                if not inv.get("ok"):
                    bot.answer_callback_query(call.id, f"CryptoBot Error: {inv.get('reason')}", show_alert=True)
                    return
                cryptopay_invoices[internal_order_id] = inv["invoice_id"]
                text = (
                    f"💎 <b>Telegram @CryptoBot Instant Payment</b>\n\n"
                    f"💰 <b>Amount:</b> <code>${usd_amount:.2f} USDT</code>\n"
                    f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n"
                    "1️⃣ Tap <b>💳 Pay with @CryptoBot</b> below to complete payment.\n"
                    "2️⃣ Tap <b>⚡ I Have Paid (Auto-Verify)</b> to receive your product instantly!"
                )
                markup.add(types.InlineKeyboardButton("💳 Pay with @CryptoBot", url=inv["pay_url"]))
                markup.add(
                    custom_inline_button(
                        "⚡ I Have Paid (Auto-Verify)",
                        callback_data=f"cryptoverify_cryptobot_{internal_order_id}",
                        _style="success",
                    )
                )
            elif method == "binance":
                note_instruction = (
                    f"📝 <b>IMPORTANT Note:</b> Please write <code>{order_id}</code> in the Binance Pay Note for <b>Instant Auto-Delivery</b>!\n\n"
                    if is_binance_api_configured()
                    else "📝 <b>Note:</b> Please write <b>Payment</b> only.\n\n"
                )
                text = (
                    f"✅ <b>{wallet_label}</b> selected\n\n"
                    f"💰 <b>Amount:</b> <code>{formatted_total} (USDT)</code>\n"
                    f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n"
                    f"📍 <b>Binance Pay ID:</b>\n<code>{html.escape(wallet_address)}</code>\n\n"
                    f"{note_instruction}"
                    f"⏳ <b>Stock reserved for {STOCK_RESERVATION_MINUTES} minutes.</b>\n"
                    f"Expires at: <code>{reservation['expires_at']}</code>\n\n"
                    "⚡ Tap <b>Verify Binance Pay (Instant)</b> after sending, or upload your payment screenshot here."
                )
                markup.add(
                    custom_inline_button(
                        "⚡ Verify Binance Pay (Instant)",
                        callback_data=f"cryptoverify_binance_{internal_order_id}",
                        _style="success",
                    )
                )
            else:
                text = (
                    f"✅ <b>{wallet_label}</b> selected\n\n"
                    f"💰 <b>Amount:</b> <code>{formatted_total} (USDT)</code>\n"
                    f"🆔 <b>Order ID:</b> <code>{order_id}</code>\n\n"
                    f"📍 <b>Wallet Address ({method.upper()}):</b>\n<code>{html.escape(wallet_address)}</code>\n\n"
                    f"⏳ <b>Stock reserved for {STOCK_RESERVATION_MINUTES} minutes.</b>\n"
                    f"Expires at: <code>{reservation['expires_at']}</code>\n\n"
                    "⚡ Tap <b>Verify by TxID (Instant)</b> to verify on-chain automatically, or send your payment screenshot here."
                )
                markup.add(
                    custom_inline_button(
                        f"⚡ Verify {method.upper()} by TxID (Instant)",
                        callback_data=f"cryptoverify_{method}_{internal_order_id}",
                        _style="success",
                    )
                )
            markup.add(
                custom_inline_button("🎧 Support", url=SUPPORT_URL),
                custom_inline_button(
                    "❌ Cancel",
                    callback_data=f"cancel_reservation_{internal_order_id}"
                )
            )
            edit_custom_emoji_message(
                bot, call.message.chat.id, call.message.message_id, text, payment_instruction_emoji_slots(method),
                reply_markup=markup, fallback_parse_mode='HTML'
            )
            return
        text += (
            f"\n\n⏳ *Stock ကို {STOCK_RESERVATION_MINUTES} မိနစ် သိမ်းထားပေးပါမယ်။*\n"
            f"ကုန်ဆုံးချိန်: `{reservation['expires_at']}`"
        )
        markup.add(
            custom_inline_button("🎧 Support", url=SUPPORT_URL),
            custom_inline_button(
                "❌ Cancel",
                callback_data=f"cancel_reservation_{internal_order_id}"
            )
        )
        edit_custom_emoji_message(
            bot, call.message.chat.id, call.message.message_id, text, payment_instruction_emoji_slots(method),
            reply_markup=markup, fallback_parse_mode='Markdown'
        )

    @bot.callback_query_handler(func=lambda call: call.data.startswith('cancel_reservation_'))
    def cancel_reservation_callback(call):
        try:
            order_id = int(call.data.rsplit('_', 1)[1])
        except (ValueError, IndexError):
            bot.answer_callback_query(call.id, "Invalid reservation.", show_alert=True)
            return
        cancelled = cancel_user_stock_reservation(order_id, call.from_user.id)
        pending_orders.pop(call.from_user.id, None)
        language = get_user_language(call.from_user.id) or "my"
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button(
            "Back to Shop" if language == "en" else "⬅️ Shop သို့ပြန်မည်",
            callback_data="shop"
        ))
        if cancelled:
            text = (
                "✅ Reservation cancelled. The held stock is available again."
                if language == "en"
                else "✅ Order ကိုပယ်ဖျက်ပြီး သိမ်းထားသော stock ကို ပြန်လွှတ်ပေးလိုက်ပါပြီ။"
            )
            bot.answer_callback_query(call.id, "Cancelled.")
        else:
            text = (
                "This reservation has already expired or been submitted."
                if language == "en"
                else "ဒီ reservation က သက်တမ်းကုန်ပြီးသား သို့မဟုတ် payment တင်ပြီးသားဖြစ်ပါတယ်။"
            )
            bot.answer_callback_query(call.id, text, show_alert=True)
        bot.edit_message_text(
            text,
            call.message.chat.id,
            call.message.message_id,
            reply_markup=markup
        )


    @bot.callback_query_handler(func=lambda call: call.data.startswith('cryptoverify_'))
    def handle_crypto_auto_verify_button(call):
        try:
            _, method, order_id_str = call.data.split('_', 2)
            order_id = int(order_id_str)
        except Exception:
            bot.answer_callback_query(call.id, "Invalid verification request.", show_alert=True)
            return

        order = get_order_details(order_id)
        if not order or int(order[1]) != call.from_user.id:
            bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
            return
        if str(order[5]).lower() == "success":
            bot.answer_callback_query(call.id, "✅ This order is already completed!", show_alert=True)
            return

        rate = get_mmk_per_usd() or MMK_PER_USD or 4500
        expected_usd = round(float(order[11] or 0) / rate, 2)
        order_code = get_public_order_id(order)

        # 1) Telegram @CryptoBot Instant Check
        if method == "cryptobot":
            inv_id = cryptopay_invoices.get(order_id)
            if not inv_id:
                bot.answer_callback_query(call.id, "Invoice not found.", show_alert=True)
                return
            res = check_cryptopay_invoice(inv_id)
            if not res.get("ok"):
                bot.answer_callback_query(call.id, f"⏳ {res.get('reason')}", show_alert=True)
                return
            bot.answer_callback_query(call.id, "✅ Payment Verified!")
            complete_auto_verified_crypto_order(
                bot,
                call.from_user.id,
                order_id,
                res["tx_id"],
                f"${res['paid_amount']:.2f} USDT (CryptoBot)",
                call.message.chat.id,
                call.message.message_id,
            )
            return

        # 2) Binance Pay: First try automatic check by Order Code in Note!
        if method == "binance" and is_binance_api_configured():
            auto_res = verify_binance_pay_transaction(order_code, expected_usd)
            if auto_res.get("ok"):
                bot.answer_callback_query(call.id, "✅ Binance Pay Verified Automatically!")
                complete_auto_verified_crypto_order(
                    bot,
                    call.from_user.id,
                    order_id,
                    auto_res["tx_id"],
                    f"${auto_res['paid_amount']:.2f} {auto_res['currency']} (Binance Pay)",
                    call.message.chat.id,
                    call.message.message_id,
                )
                return

        # Otherwise prompt the user to paste their TxID (0x...) or Binance Order ID
        pending_crypto_tx_input[call.from_user.id] = (order_id, method)
        bot.answer_callback_query(call.id)
        if method == "binance":
            prompt_msg = (
                "⚡ <b>Binance Pay Auto-Verification</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 <b>Expected Amount:</b> <code>${expected_usd:.2f} USDT</code>\n"
                f"🆔 <b>Order Code:</b> <code>{html.escape(order_code)}</code>\n\n"
                "📩 Please reply with your <b>Binance Pay Order ID / Transaction ID</b> (or send your payment screenshot if you prefer manual review):"
            )
        else:
            prompt_msg = (
                f"⚡ <b>USDT ({method.upper()}) On-Chain Auto-Verification</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"💰 <b>Expected Amount:</b> <code>${expected_usd:.2f} USDT</code>\n\n"
                "📩 Please paste and send your <b>Transaction Hash (TxID)</b> starting with <code>0x...</code>\n"
                "<i>(Or send a payment screenshot if you prefer manual review)</i>:"
            )
        msg = bot.send_message(call.message.chat.id, prompt_msg, parse_mode="HTML")
        bot.register_next_step_handler(msg, _process_crypto_tx_input)

    def _process_crypto_tx_input(message):
        state = pending_crypto_tx_input.pop(message.from_user.id, None)
        if not state:
            return
        # If user sent a photo instead of text, let the screenshot handler process it!
        if getattr(message, "content_type", "") == "photo":
            handle_screenshot(message)
            return

        order_id, method = state
        raw_tx = (message.text or "").strip()
        if not raw_tx or raw_tx.startswith("/"):
            bot.reply_to(message, "❌ Verification cancelled.")
            return

        order = get_order_details(order_id)
        if not order or int(order[1]) != message.from_user.id:
            bot.reply_to(message, "❌ Order not found.")
            return

        rate = get_mmk_per_usd() or MMK_PER_USD or 4500
        expected_usd = round(float(order[11] or 0) / rate, 2)
        order_code = get_public_order_id(order)

        wait_msg = bot.reply_to(message, "🔍 <i>Verifying transaction via API... Please wait...</i>", parse_mode="HTML")
        if method == "binance":
            res = verify_binance_pay_transaction(order_code, expected_usd, user_input_tx_or_note=raw_tx)
            paid_label = f"${res.get('paid_amount', expected_usd):.2f} USDT (Binance Pay)"
        else:
            res = verify_evm_usdt_transaction(raw_tx, expected_usd, network=method)
            paid_label = f"${res.get('paid_amount', expected_usd):.2f} USDT ({method.upper()})"

        if not res.get("ok"):
            retry_markup = types.InlineKeyboardMarkup()
            retry_markup.add(
                custom_inline_button("🔄 Try Again", callback_data=f"cryptoverify_{method}_{order_id}", _style="primary"),
                custom_inline_button("🎧 Support", url=SUPPORT_URL),
            )
            bot.edit_message_text(
                f"❌ <b>Verification Failed:</b>\n{html.escape(str(res.get('reason')))}\n\n"
                "💡 <i>You can tap Try Again after the transaction confirms, or send your payment screenshot directly in this chat for manual admin review.</i>",
                message.chat.id,
                wait_msg.message_id,
                reply_markup=retry_markup,
                parse_mode="HTML",
            )
            return

        complete_auto_verified_crypto_order(
            bot,
            message.from_user.id,
            order_id,
            res["tx_id"],
            paid_label,
            message.chat.id,
            wait_msg.message_id,
        )

    @bot.message_handler(content_types=["photo"])
    def handle_screenshot(message):
        user_id = message.from_user.id
        language = get_user_language(user_id) or "my"
        reserved_order = get_active_reserved_order_for_user(user_id)
        if reserved_order:
            (
                internal_order_id, order_code, item_name, qty,
                total_amount, payment_method, expires_at, db_target_username
            ) = reserved_order
            existing_mem_target = pending_orders.get(user_id, {}).get("target_username")
            pending_orders[user_id] = {
                "order_id": internal_order_id,
                "order_code": order_code,
                "item_name": item_name,
                "qty": qty,
                "total": total_amount,
                "method": payment_method,
                "expires_at": expires_at,
                "target_username": db_target_username or existing_mem_target,
            }
        elif user_id not in pending_orders:
            return

        order_data = pending_orders[user_id]
        photo = message.photo[-1]
        is_renewal_order = get_order_type(order_data["order_id"]) == "renewal"
        reservation_status = submit_payment_proof(
            order_data["order_id"],
            user_id,
            photo.file_unique_id or photo.file_id,
            photo.file_id,
        )
        if reservation_status == "expired":
            pending_orders.pop(user_id, None)
            text = (
                "⏰ Your stock reservation has expired. Please place the order again."
                if language == "en"
                else "⏰ Stock သိမ်းထားသည့်အချိန် ကုန်ဆုံးသွားပါပြီ။ Shop မှ ပြန်လည်မှာယူပေးပါ။"
            )
            bot.send_message(user_id, text)
            return
        if reservation_status == "already_submitted":
            pending_orders.pop(user_id, None)
            bot.send_message(
                user_id,
                "Your payment is already under review."
                if language == "en"
                else "Payment screenshot ကို ပို့ထားပြီး Admin စစ်ဆေးနေဆဲဖြစ်ပါတယ်။"
            )
            return
        if reservation_status == "duplicate_proof":
            duplicate_alert = (
                "🚨 <b>Duplicate Payment Proof Blocked</b>\n\n"
                f"👤 User ID: <code>{user_id}</code>\n"
                f"🧾 Current Order: <code>{html.escape(str(order_data['order_code']))}</code>\n"
                f"📦 Product: <b>{html.escape(str(order_data['item_name']))}</b>\n\n"
                "ဒီ screenshot ကို အခြား order မှာ အသုံးပြုပြီးသားဖြစ်လို့ system က ပိတ်ထားပါတယ်။"
            )
            for admin_id in get_all_admin_ids():
                try:
                    bot.send_photo(
                        admin_id,
                        photo.file_id,
                        caption=duplicate_alert,
                        parse_mode="HTML"
                    )
                except Exception as error:
                    print(f"Duplicate payment alert failed for admin {admin_id}: {error}")
            bot.send_message(
                user_id,
                (
                    "❌ This payment screenshot has already been used for another order. "
                    "Please send the correct payment proof or contact support."
                    if language == "en"
                    else "❌ ဒီ payment screenshot ကို အခြား order တစ်ခုမှာ အသုံးပြုပြီးသားဖြစ်ပါတယ်။ "
                         "မှန်ကန်သောငွေလွှဲပြေစာကို ပို့ပေးပါ သို့မဟုတ် Admin ကိုဆက်သွယ်ပါ။"
                )
            )
            return
        if reservation_status != "submitted":
            pending_orders.pop(user_id, None)
            bot.send_message(
                user_id,
                "This order is no longer available. Please place a new order."
                if language == "en"
                else "ဒီ order ကို ဆက်လုပ်လို့မရတော့ပါ။ Order အသစ်ပြန်တင်ပေးပါ။"
            )
            return

        markup = types.InlineKeyboardMarkup()
        markup.add(
            custom_inline_button("✅ Approve", callback_data=f"admin_approve_{order_data['order_id']}"),
            custom_inline_button("❌ Reject", callback_data=f"admin_reject_{order_data['order_id']}")
        )

        from handlers.shop import is_shop_open
        alert_title = "🔔 <b>New Order Alert!</b>" if is_shop_open() else "🌙 <b>New Pre-Order Alert (ညဘက်မှာယူမှု)!</b>"
        buyer_username = f"@{message.from_user.username}" if getattr(message.from_user, "username", None) else "မရှိပါ"
        target_username = (
            order_data.get("target_username")
            or get_order_target_username(order_data["order_id"])
            or (f"@{message.from_user.username}" if is_telegram_direct_product(order_data["item_name"]) and getattr(message.from_user, "username", None) else None)
        )

        admin_text = (
            f"{alert_title}\n\n"
            f"👤 User ID: <code>{user_id}</code> ({html.escape(buyer_username)})\n"
            f"📦 Item: {html.escape(str(order_data['item_name']))}\n"
            f"🔢 Quantity: {int(order_data.get('qty') or 1)}\n"
            + (f"🎯 <b>Target Username:</b> {html.escape(str(target_username))}\n" if target_username else "")
            + f"💰 Amount: {order_data['total']:,.0f} MMK\n"
            f"💳 Method: {html.escape(str(order_data['method']))}\n"
            f"🆔 Order ID: <code>{html.escape(str(order_data['order_code']))}</code>"
        )
        if is_renewal_order:
            admin_text += "\n🔄 Type: Existing Outline Key Renewal"
        for admin_id in get_all_admin_ids():
            try:
                bot.send_photo(admin_id, message.photo[-1].file_id, caption=admin_text, reply_markup=markup, parse_mode='HTML')
            except Exception as e:
                print(f"Failed to send order alert to admin {admin_id}: {e}")
                try:
                    plain_text = re.sub(r"</?[^>]+>", "", admin_text)
                    bot.send_photo(admin_id, message.photo[-1].file_id, caption=plain_text, reply_markup=markup, parse_mode="")
                except Exception as e2:
                    print(f"Fallback admin photo send failed: {e2}")
        
        if is_shop_open():
            success_text = (
                "✅ <b>Screenshot ပေးပို့မှု အောင်မြင်ပါသည်၊၊</b>\n\n"
                "ကျွန်ုပ်တို့၏ Admin မှ သင်၏ ငွေလွှဲပြေစာကို စစ်ဆေးနေပါပြီ၊၊ "
                "စစ်ဆေးပြီးပါက အကောင့်အချက်အလက်များကို ဤနေရာသို့ အလိုအလျောက် ပို့ဆောင်ပေးသွားမည် ဖြစ်ပါသည်၊၊\n\n"
                "⏳ ခေတ္တစောင့်ဆိုင်းပေးပါရန် မေတ္တာရပ်ခံအပ်ပါသည်၊၊"
            )
        else:
            success_text = (
                "📝 <b>Pre-Order မှာယူမှု အောင်မြင်ပါသည်ဗျာ၊၊</b>\n"
                "━━━━━━━━━━━━━━━━━━\n\n"
                "ငွေလွှဲပြေစာ Screenshot ပေးပို့မှု အောင်မြင်ပါသည်၊၊ ယခုအော်ဒါသည် ဆိုင်ပိတ်ချိန်အတွင်း "
                "မှာယူထားခြင်းဖြစ်သဖြင့် မနက်ဖြန် ဆိုင်ပြန်ဖွင့်ချိန် (မနက် ၈ နာရီ) ကျမှသာ Admin ဘက်က စစ်ဆေးပြီး "
                "<b>ပစ္စည်းကို အမြန်ဆုံး လှမ်းပို့ပေးသွားမှာ ဖြစ်ပါတယ်ပါတယ်ခင်ဗျာ၊၊</b>\n\n"
                "🙏 အနားယူချိန်စနစ်ကြောင့် ခေတ္တစောင့်ဆိုင်းရခြင်းအတွက် အနူးအညွတ် တောင်းပန်အပ်ပါသည်၊၊ "
                "ဝယ်ယူအားပေးမှုကို အထူးပင် ကျေးဇူးတင်ရှိပါသည်ဗျာ၊၊ 😊"
            )
        if language == "en":
            if is_shop_open():
                success_text = (
                    "✅ <b>Screenshot received successfully.</b>\n\n"
                    "Our admin is now reviewing your payment screenshot. "
                    "Once approved, your account information will be delivered here automatically.\n\n"
                    "⏳ Please wait a moment."
                )
            else:
                success_text = (
                    "📝 <b>Pre-order received successfully.</b>\n\n"
                    "Your payment screenshot has been received. Since this order was placed outside shop hours, "
                    "our admin will review it when the shop opens and deliver your product as soon as possible.\n\n"
                    "🙏 Thank you for your patience and support."
                )
        preorder_slots = (
            ("📝", "preorder_title"), ("🙏", "preorder_thanks"),
            ("😊", "preorder_smile"),
        )
        send_custom_emoji_message(bot, user_id, success_text, preorder_slots)
        del pending_orders[user_id]


# =====================================================================
# 🌟 (၃) REVIEW SYSTEM HANDLERS
# =====================================================================
def init_review_handlers(bot):
    @bot.callback_query_handler(func=lambda call: call.data == 'give_review')
    def ask_for_review_callback(call):
        bot.answer_callback_query(call.id)
        language = get_user_language(call.from_user.id) or "my"
        review_text = (
            "✍️ <b>Feedback & Review ပေးရန်</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "ENI Premium Store ကို အားပေးရတာ အဆင်ပြေရဲ့လားခင်ဗျာ၊၊ "
            "ဝန်ဆောင်မှုအပေါ် သဘောကျကျေနပ်မှု ရှိတယ်ဆိုရင် အောက်တွင် Review စာသားလေး (သို့မဟုတ်) "
            "အကြံပြုချက်လေးများကို ရိုက်ပြီး ပို့ပေးပါဦးဗျာ၊၊\n\n"
            "<i>(သင်ပို့လိုက်သော စာသားကို ကျွန်ုပ်တို့၏ Feedback Channel တွင် လူကြီးမင်း၏ နာမည်ကို ဖျောက်၍ အလိုအလျောက် တင်ပေးသွားမည် ဖြစ်ပါသည်)</i>"
        )
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button("❌ မပေးတော့ပါ", callback_data='home'))
        if language == "en":
            review_text = (
                "<b>Feedback & Review</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "How was your experience with ENI Premium Store?\n"
                "Please type your review or suggestion below.\n\n"
                "<i>Your review may be posted to our feedback channel with your name hidden.</i>"
            )
            markup = types.InlineKeyboardMarkup()
            markup.add(custom_inline_button("Cancel", callback_data='home'))
        msg = bot.edit_message_text(review_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        bot.register_next_step_handler(msg, process_user_review, bot)

    def process_user_review(message, bot):
        user_id = message.from_user.id
        language = get_user_language(user_id) or "my"
        user_name = message.from_user.first_name if message.from_user.first_name else "Customer"
        review_content = message.text.strip()
        
        if review_content.startswith('/'):
            if language == "en":
                bot.reply_to(message, "Review cancelled.")
                return
            bot.reply_to(message, "❌ Review ပေးခြင်းကို ဖျက်သိမ်းလိုက်ပါပြီ၊၊")
            return

        FEEDBACK_CHANNEL_ID = -1003923790039  
        channel_msg = (
            "🌟 <b>Review From Customer</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"✍️ <i>\"{review_content}\"</i>\n\n"
            f"👤 <b>Buyer:</b> {user_name[0]}*** (Verified Buyer)\n"
            f"🏪 <b>Shop:</b> @ENIpremiumstore_bot\n"
            "━━━━━━━━━━━━━━━━━━━━━━"
        )
        admin_msg = (
            "🔔 <b>Review အသစ်တစ်ခု ရောက်ရှိပါသည်!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 <b>User:</b> {user_name} (ID: <code>{user_id}</code>)\n"
            f"📝 <b>Review:</b> {review_content}"
        )

        try: bot.send_message(FEEDBACK_CHANNEL_ID, channel_msg, parse_mode='HTML')
        except: pass
        for admin_id in get_all_admin_ids():
            try: bot.send_message(admin_id, admin_msg, parse_mode='HTML')
            except: pass

        thank_you_text = (
                "❤️ <b>ကျေးဇူးအများကြီး တင်ပါတယ်ဗျာ!</b>\n\n"
                "လူကြီးမင်းပေးခဲ့တဲ့ Review ဟာ ENI Premium Store ရဲ့ ဝန်ဆောင်မှုတွေကို "
                "ပိုမိုကောင်းမွန်လာအောင် ပြင်ဆင်ရာမှာ အများကြီး အထောက်အကူပြုပါတယ်ခင်ဗျာ၊၊ 🙏😊\n\n"
                "📣 အခြားသူများ၏ Review & Feedback များကိုလည်း <a href='https://t.me/ENIreviews'>ENI Reviews Channel</a> တွင် ဝင်ရောက်ကြည့်ရှုနိုင်ပါသည်ဗျာ၊၊"
            )
        markup = types.InlineKeyboardMarkup()
        markup.add(custom_inline_button("🏠 Back to Home", callback_data='home'))
        if language == "en":
            thank_you_text = (
                "<b>Thank you for your feedback!</b>\n\n"
                "Your review helps us improve ENI Premium Store services.\n\n"
                "You can also view customer reviews at "
                "<a href='https://t.me/ENIreviews'>ENI Reviews Channel</a>."
            )
        bot.send_message(user_id, thank_you_text, reply_markup=markup, parse_mode='HTML')


# =====================================================================
# 🌟 (၄) ADMIN ACTION HANDLERS
# =====================================================================
def init_admin_handlers(bot):
    @bot.callback_query_handler(func=lambda call: call.data.startswith('admin_'))
    def admin_action(call):
        if not is_admin_user(call.from_user.id):
            bot.answer_callback_query(call.id, "Admin only.", show_alert=True)
            return
        bot.answer_callback_query(call.id, "ခေတ္တစောင့်ဆိုင်းပါ...")
        parts = call.data.split('_')
        action, order_id = parts[1], int(parts[2])
        caption = call.message.caption or call.message.text or ""

        def update_admin_card(text, chat_id, message_id, parse_mode=None):
            clean_text = text.replace("*", "")
            try:
                if call.message.content_type == "text":
                    return bot.edit_message_text(
                        clean_text, chat_id, message_id, reply_markup=None, parse_mode=""
                    )
                return bot.edit_message_caption(
                    clean_text, chat_id, message_id, parse_mode="", reply_markup=None
                )
            except Exception as err:
                print(f"update_admin_card error: {err}")
        
        try:
            target_user_id = int(re.search(r'User ID:.*?(\d+)', caption).group(1))
            _o = get_order_details(order_id)
            item_name = str(_o[2]).strip() if _o and _o[2] else ""
            if not item_name:
                item_name = re.search(r'(?:Item|Product): (.*)', caption).group(1).strip()
        except Exception as e:
            print(f"Data parsing error: {e}")
            return

        if action == "approve":
            order = get_order_details(order_id)
            if not order:
                bot.send_message(call.message.chat.id, "❌ အော်ဒါအချက်အလက် ရှာမတွေ့ပါ၊၊")
                return

            renewal_api_result = None
            if get_order_type(order_id) == "renewal":
                pending_renewal = get_pending_renewal_outline_data(order_id)
                if not pending_renewal:
                    bot.send_message(
                        call.message.chat.id,
                        "❌ Renewal order data မတွေ့ပါ။ Database order status ကို စစ်ပါ။",
                    )
                    return
                renewal_api_result = renew_access_key(
                    pending_renewal["outline_key_id"], pending_renewal["item_name"],
                    pending_renewal["order_code"], pending_renewal["expiry_date"],
                )
                if renewal_api_result["mode"] == "error":
                    bot.send_message(
                        call.message.chat.id,
                        "⚠️ <b>Outline API renewal မအောင်မြင်သေးပါ။</b> Order ကို approve မလုပ်ရသေးပါ။\n\n"
                        f"Order: <code>{html.escape(str(pending_renewal['order_code']))}</code>\n"
                        f"Key: <code>{html.escape(str(pending_renewal.get('outline_key_id') or '-'))}</code>\n"
                        f"Error: <code>{html.escape(renewal_api_result['reason'])}</code>",
                        parse_mode="HTML",
                    )
                    return

            claim_status = claim_stock_reservation_for_processing(order_id, call.from_user.id)
            if claim_status not in ("claimed", "legacy"):
                bot.send_message(
                    call.message.chat.id,
                    (
                        "⚠️ ဒီ order ကို အခြား admin က ကိုင်တွယ်ပြီးသား သို့မဟုတ် "
                        f"ဆက်လုပ်လို့မရသောအခြေအနေဖြစ်ပါတယ်။\nStatus: <code>{html.escape(str(claim_status))}</code>"
                    ),
                    parse_mode="HTML"
                )
                return
            mark_payment_submission_status(order_id, "approved", call.from_user.id)

            if get_order_type(order_id) == "renewal":
                renewal = complete_existing_key_renewal_order(order_id)
                if not renewal:
                    bot.send_message(
                        call.message.chat.id,
                        "❌ Renewal order ကို complete မလုပ်နိုင်ပါ။ Database order status ကို စစ်ပါ။",
                        parse_mode="HTML"
                    )
                    return

                api_result = renewal_api_result or {"mode": "manual"}

                send_renewed_key_message(bot, target_user_id, renewal)
                status_text = (
                    "\n\n✅ *Status: Existing Key Renewal Approved*"
                    f"\nNew Expiry: {renewal['expiry_date']}"
                    + ("\nOutline API: auto-renewed." if api_result["mode"] == "auto"
                       else "\nOutline API is not configured; manual renewal is required.")
                )
                renewal_key = (
                    renewal.get("outline_access_url")
                    or renewal.get("outline_key_id")
                    or renewal.get("delivered_data")
                    or "-"
                )
                admin_notice = (
                    "🔄 <b>Existing Key Renewal Approved</b>\n"
                    "━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 <b>User ID:</b> <code>{target_user_id}</code>\n"
                    f"📦 <b>Item:</b> {html.escape(str(renewal['item_name']))}\n"
                    f"🆔 <b>Order ID:</b> <code>{html.escape(str(renewal['order_code']))}</code>\n"
                    f"📅 <b>New Expiry:</b> <code>{html.escape(str(renewal['expiry_date']))}</code>\n\n"
                    f"🔐 <b>Renew လုပ်ရန် Key / Link:</b>\n<code>{html.escape(str(renewal_key))}</code>\n\n"
                    + ("✅ <b>Outline API:</b> Key quota/name ကို auto update လုပ်ပြီးပါပြီ။"
                     if api_result["mode"] == "auto" else
                     "ℹ️ <b>Outline API မချိတ်ထားသေးပါ။</b> Outline Manager ထဲတွင် manual ပြင်ပေးပါ။")
                )
                bot.send_message(call.message.chat.id, admin_notice, parse_mode="HTML")
                update_admin_card(
                    caption + status_text,
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='Markdown'
                )
                publish_sell_proof(bot, order_id, call.message.chat.id)
                send_promotion_gift_choice(bot, order_id, target_user_id)
                return

            requested_quantity = int(order[3] or 1)
            account_list = pull_accounts_from_stock_by_name(item_name, requested_quantity)

            # A) Telegram Direct Gift (@username via @PremiumBot)
            target_username = get_order_target_username(order_id)
            if not account_list and (target_username or is_telegram_direct_product(item_name)):
                recipient = target_username or "Customer Telegram Account"
                delivered_note = f"Delivered directly to {recipient} (Quantity: {requested_quantity})"
                update_order_delivery(order_id, delivered_note)
                update_order_status(order_id, "Success", reduce_stock=True)
                complete_stock_reservation(order_id)
                if not deliver_direct_gift_if_needed(bot, order_id, item_name, delivered_note):
                    send_delivery_message(bot, target_user_id, item_name, delivered_note)
                update_admin_card(
                    caption + f"\n\n✅ *Status: Direct Gift Sent ({recipient})*",
                    call.message.chat.id,
                    call.message.message_id,
                    parse_mode='Markdown'
                )
                publish_sell_proof(bot, order_id, call.message.chat.id)
                send_promotion_gift_choice(bot, order_id, target_user_id)
                return

            # B) On-Demand Outline Key Generation when DB stock is empty but Outline API is configured
            if not account_list and "outline" in item_name.lower() and is_outline_api_configured():
                generated_keys = []
                order_code_str = get_public_order_id(order)
                expiry_str = order[9] or ""
                for _ in range(requested_quantity):
                    res = create_access_key(item_name, order_code_str, expiry_str)
                    if res.get("ok"):
                        generated_keys.append(res["formatted"])
                if generated_keys:
                    account_list = generated_keys
                    reduce_item_stock_manual(item_name, len(generated_keys))

            delivered_count = len(account_list)
            missing_count = requested_quantity - delivered_count
            set_stock_reservation_remainder(order_id, missing_count)
            check_and_send_low_stock_alert(bot, item_name)

            if account_list:
                account_data = "\n\n".join(
                    f"Account {index}:\n{account_info}"
                    for index, account_info in enumerate(account_list, start=1)
                )
                try:
                    if not deliver_direct_gift_if_needed(bot, order_id, item_name, account_data):
                        send_delivery_message(bot, target_user_id, item_name, account_data)
                    update_order_delivery(order_id, account_data)

                    if missing_count <= 0:
                        update_order_status(order_id, "Success", reduce_stock=False)
                        status_text = f"\n\n✅ *Status: Auto-Delivered ({delivered_count}/{requested_quantity})*"
                    else:
                        update_order_status(order_id, "Partial", reduce_stock=False)
                        status_text = (
                            f"\n\n⚠️ *Status: Partial Auto-Delivered ({delivered_count}/{requested_quantity})*"
                            f"\nManual needed: {missing_count}"
                        )

                    update_admin_card(
                        caption + status_text,
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )

                    if missing_count <= 0:
                        publish_sell_proof(bot, order_id, call.message.chat.id)
                        send_promotion_gift_choice(bot, order_id, target_user_id)

                    if missing_count > 0:
                        msg = bot.send_message(
                            call.message.chat.id,
                            (
                                f"⚠️ <b>{html.escape(str(item_name))}</b> အတွက် user က "
                                f"<b>{requested_quantity}</b> ခု ဝယ်ထားပါတယ်။\n"
                                f"Database ထဲကနေ <b>{delivered_count}</b> ခု auto ပို့ပြီးပါပြီ။\n"
                                f"ကျန် <b>{missing_count}</b> ခုကို manual ပို့ပေးရန်လိုအပ်ပါသည်။\n\n"
                                f"<b>User ID:</b> <code>{target_user_id}</code>\n"
                                f"<b>Order ID:</b> <code>{get_public_order_id(order)}</code>\n\n"
                                "<b>ကျန် account info ကို အောက်မှာ ရိုက်ပြီး ပို့ပေးပါ။</b>"
                            ),
                            parse_mode='HTML'
                        )
                        bot.register_next_step_handler(
                            msg,
                            process_manual_delivery,
                            bot,
                            target_user_id,
                            item_name,
                            order_id,
                            caption,
                            call.message.message_id,
                            missing_count
                        )
                    return
                except Exception as send_err:
                    update_order_delivery(order_id, account_data)
                    update_admin_card(
                        caption + f"\n\n⚠️ *Status: Auto data found ({delivered_count}/{requested_quantity}), but user delivery failed*",
                        call.message.chat.id,
                        call.message.message_id,
                        parse_mode='Markdown'
                    )
                    bot.send_message(
                        call.message.chat.id,
                        (
                            "⚠️ <b>Auto data ရှိပါတယ်။ ဒါပေမယ့် user ဆီ bot က မပို့နိုင်ပါ။</b>\n\n"
                            f"<b>User ID:</b> <code>{target_user_id}</code>\n"
                            f"<b>Item:</b> {html.escape(str(item_name))}\n"
                            f"<b>Error:</b> <code>{html.escape(str(send_err))}</code>\n\n"
                            f"<b>Account Info:</b>\n<code>{html.escape(str(account_data))}</code>"
                        ),
                        parse_mode="HTML"
                    )
                    return

            msg = bot.send_message(
                call.message.chat.id,
                (
                    f"⚠️ <b>{html.escape(str(item_name))}</b> အတွက် database ထဲမှာ account data မလောက်တော့ပါ။\n\n"
                    f"User က <b>{requested_quantity}</b> ခု ဝယ်ထားပါတယ်။\n"
                    f"ကျန် <b>{requested_quantity}</b> ခုလုံးကို manual ပို့ပေးရန်လိုအပ်ပါသည်။\n\n"
                    f"<b>User ID:</b> <code>{target_user_id}</code>\n"
                    f"<b>Order ID:</b> <code>{get_public_order_id(order)}</code>\n\n"
                    "<b>Account info ကို အောက်မှာ ရိုက်ပြီး ပို့ပေးပါ။</b>"
                ),
                parse_mode='HTML'
            )
            bot.register_next_step_handler(
                msg,
                process_manual_delivery,
                bot,
                target_user_id,
                item_name,
                order_id,
                caption,
                call.message.message_id,
                requested_quantity
            )
            return

        elif action == "reject":
            internal_order_id = order_id
            reject_status = reject_stock_reservation(internal_order_id, call.from_user.id)
            if reject_status not in ("rejected", "legacy"):
                bot.send_message(
                    call.message.chat.id,
                    (
                        "⚠️ ဒီ order ကို အခြား admin က ကိုင်တွယ်နေပြီးသားဖြစ်ပါတယ်။\n"
                        f"Status: <code>{html.escape(str(reject_status))}</code>"
                    ),
                    parse_mode="HTML"
                )
                return
            order_id = get_public_order_id(get_order_details(internal_order_id))
            update_order_status(internal_order_id, "Rejected", reduce_stock=False)
            update_admin_card(caption + "\n\n❌ *Status: Rejected*", call.message.chat.id, call.message.message_id, parse_mode='Markdown')
            reject_msg = f"❌ သင်၏ Order ID: {order_id} ကို ငြင်းပယ်လိုက်ပါတယ်၊၊"
            bot.send_message(target_user_id, reject_msg)


# =====================================================================
# 🌟 (၅) USER ORDER HISTORY HANDLERS
# =====================================================================
def init_order_history_handlers(bot):
    @bot.callback_query_handler(func=lambda call: call.data == 'my_orders')
    def my_orders(call):
        if get_shop_status() == 'maintenance' and not is_admin_user(call.from_user.id):
            return
        if (get_user_language(call.from_user.id) or "my") == "en":
            orders = get_user_orders(call.from_user.id)
            markup = types.InlineKeyboardMarkup(row_width=1)
            if not orders:
                markup.add(custom_inline_button("Back to Home", callback_data='home'))
                bot.edit_message_text(
                    "🛒 *You do not have any orders yet.*",
                    call.message.chat.id,
                    call.message.message_id,
                    reply_markup=markup,
                    parse_mode='Markdown'
                )
                return
            for order in orders:
                btn_text = f"📦 {order[2]} ({order[6].split()[0]})"
                item = get_item_by_name(order[2])
                markup.add(custom_inline_button(
                    btn_text, callback_data=f"view_order_{order[0]}",
                    _product_id=item[0] if item else None,
                ))
            markup.add(custom_inline_button("Back to Home", callback_data='home'))
            bot.edit_message_text(
                "🛒 *Your Orders:*",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=markup,
                parse_mode='Markdown'
            )
            return
        orders = get_user_orders(call.from_user.id)
        markup = types.InlineKeyboardMarkup(row_width=1)
        if not orders:
            markup.add(custom_inline_button("🏠 Back to Home", callback_data='home'))
            bot.edit_message_text("🛒 *ဝယ်ယူထားသည့် မှတ်တမ်းမရှိသေးပါ၊၊*", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')
            return
        for o in orders:
            g_meta = get_order_gift_metadata(o[0])
            if g_meta and int(g_meta["recipient_id"]) == int(call.from_user.id):
                prefix = "🎁 [Received Gift] "
            elif g_meta and int(o[1]) == int(call.from_user.id):
                prefix = "📤 [Sent Gift] "
            else:
                prefix = "📦 "
            btn_text = f"{prefix}{o[2]} ({o[6].split()[0]})"
            item = get_item_by_name(o[2])
            markup.add(custom_inline_button(
                btn_text, callback_data=f"view_order_{o[0]}",
                _product_id=item[0] if item else None,
            ))
        markup.add(custom_inline_button("🏠 Back to Home", callback_data='home'))
        bot.edit_message_text("🛒 *သင်ဝယ်ယူထားသည့် အော်ဒါများ:*", call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='Markdown')

    @bot.callback_query_handler(func=lambda call: call.data.startswith('view_order_'))
    def view_order_detail(call):
        try:
            order_id = int(call.data.split('_')[2])
            order = get_order_details(order_id)
            item = get_item_by_name(order[2]) if order else None
            item_id = item[0] if item else None
            if order and (get_user_language(call.from_user.id) or "my") == "en":
                order = list(order)
                order[0] = get_public_order_id(order)
                acc_info = order[7] if len(order) > 7 and order[7] else "No account information yet"
                expiry_date = order[9] if len(order) > 9 and order[9] else "Not available"
                detail_text = (
                    f"📄 <b>Order Detail</b> (ID: <code>{html.escape(str(order[0]))}</code>)\n"
                    f"📦 <b>Item:</b> {html.escape(str(order[2]))}\n"
                    f"📅 <b>Expiry Date:</b> <code>{html.escape(str(expiry_date))}</code>\n"
                    f"📧 <b>Account Info:</b>\n<code>{html.escape(str(acc_info))}</code>"
                )
                markup = types.InlineKeyboardMarkup()
                renew_option = get_order_renewal_option(order_id, call.from_user.id)
                if "outline" in str(order[2]).lower():
                    markup.add(custom_inline_button("📊 Check Data Usage", callback_data=f"check_usage_{order_id}"))
                    markup.add(types.InlineKeyboardButton("📖 Outline Setup Guide", url=OUTLINE_GUIDE_POST_URL))
                if renew_option and is_outline_renewable_product(renew_option.get("item_name")):
                    markup.add(custom_inline_button("🔄 Renew Existing Key", callback_data=f"renew_existing_{order_id}"))
                if item_id is not None:
                    qty_bought = max(1, int(order[3] or 1))
                    markup.add(custom_inline_button("🔁 Buy Again", callback_data=f"buy_{item_id}_{qty_bought}"))
                markup.row(
                    custom_inline_button("🧾 Receipt", callback_data=f"receipt_order_{order_id}"),
                    custom_inline_button("🎁 Send as Gift", callback_data=f"giftcard_order_{order_id}"),
                )
                markup.add(custom_inline_button("🛠 Report Issue / Warranty Claim", callback_data=f"report_order_{order_id}"))
                markup.add(custom_inline_button("Back to List", callback_data='my_orders'))
                bot.edit_message_text(detail_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
                return
            if order:
                order = list(order)
                order[0] = get_public_order_id(order)
                acc_info = order[7] if len(order) > 7 and order[7] else "အချက်အလက်မရှိပါ"
                expiry_date = order[9] if len(order) > 9 and order[9] else "သက်တမ်းရက်စွဲ မရှိသေးပါ"
                detail_text = (
                    f"📄 <b>Order Detail</b> (ID: <code>{html.escape(str(order[0]))}</code>)\n"
                    f"📦 <b>Item:</b> {html.escape(str(order[2]))}\n"
                    f"📅 <b>သက်တမ်းကုန်မည့်ရက်:</b> <code>{html.escape(str(expiry_date))}</code>\n"
                    f"📧 <b>Account Info:</b>\n<code>{html.escape(str(acc_info))}</code>"
                )
                markup = types.InlineKeyboardMarkup()
                renew_option = get_order_renewal_option(order_id, call.from_user.id)
                if "outline" in str(order[2]).lower():
                    markup.add(custom_inline_button("📊 Data လက်ကျန်စစ်ရန် (Check Usage)", callback_data=f"check_usage_{order_id}"))
                    markup.add(types.InlineKeyboardButton("📖 Outline အသုံးပြုနည်း လမ်းညွှန်", url=OUTLINE_GUIDE_POST_URL))
                if renew_option and is_outline_renewable_product(renew_option.get("item_name")):
                    markup.add(custom_inline_button("🔄 လက်ရှိ Key ကို Renew မယ်", callback_data=f"renew_existing_{order_id}"))
                if item_id is not None:
                    qty_bought = max(1, int(order[3] or 1))
                    markup.add(custom_inline_button("🔁 ထပ်မံဝယ်ယူမည် (Buy Again)", callback_data=f"buy_{item_id}_{qty_bought}"))
                markup.row(
                    custom_inline_button("🧾 ဘောင်ချာထုတ်မည်", callback_data=f"receipt_order_{order_id}"),
                    custom_inline_button("🎁 လက်ဆောင်ကတ်ပို့မည်", callback_data=f"giftcard_order_{order_id}"),
                )
                markup.add(custom_inline_button("🛠 ပြဿနာတင်ပြရန် / Warranty Claim", callback_data=f"report_order_{order_id}"))
                markup.add(custom_inline_button("⬅️ Back to List", callback_data='my_orders'))
                bot.edit_message_text(detail_text, call.message.chat.id, call.message.message_id, reply_markup=markup, parse_mode='HTML')
        except Exception as e: print(e)



    @bot.callback_query_handler(func=lambda call: call.data.startswith("check_usage_"))
    def handle_check_outline_usage(call):
        try:
            order_id = int(call.data.rsplit("_", 1)[1])
            order = get_order_details(order_id)
            if not order or int(order[1]) != call.from_user.id:
                bot.answer_callback_query(call.id, "Order not found.", show_alert=True)
                return
            opt = get_order_renewal_option(order_id, call.from_user.id)
            key_id = opt.get("outline_key_id") if opt else None
            usage = get_key_data_usage(key_id, order[2])
            if not usage.get("ok"):
                bot.answer_callback_query(
                    call.id,
                    f"ℹ️ လက်ရှိတွင် Data Usage တိုက်ရိုက်စစ်ဆေး၍မရသေးပါ။ ({usage.get('reason')})",
                    show_alert=True,
                )
                return
            used_gb = usage["used_gb"]
            limit_gb = usage["limit_gb"]
            rem_gb = usage["remaining_gb"]
            pct = usage["percent"]
            filled = min(10, max(0, pct // 10))
            bar = "█" * filled + "░" * (10 - filled)
            if limit_gb:
                text = (
                    f"📊 Outline VPN Data Usage\n\n"
                    f"• သုံးစွဲပြီး: {used_gb} GB\n"
                    f"• လက်ကျန်: {rem_gb} GB / {limit_gb} GB\n"
                    f"• [{bar}] {pct}%"
                )
            else:
                text = f"📊 Outline VPN (Unlimited Plan)\n\n• လက်ရှိသုံးစွဲပြီးပမာဏ: {used_gb} GB"
            bot.answer_callback_query(call.id, text, show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, f"Error: {e}", show_alert=True)


# =====================================================================
# 🚀 ALL HANDLERS INITIALIZER (ပင်မ စုစည်းမှု စနစ်)
# =====================================================================
def init_all_handlers(bot):
    init_payment_handlers(bot)
    init_review_handlers(bot)
    init_admin_handlers(bot)
    init_order_history_handlers(bot)