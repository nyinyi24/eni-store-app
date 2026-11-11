import sqlite3
from config import DATABASE_NAME

def setup_all_plans():
    conn = sqlite3.connect(DATABASE_NAME)
    cursor = conn.cursor()

    plans = [
        # ==========================================================
        # 💎 1. Telegram Premium Plans (3, 6, 12 Months)
        # ==========================================================
        (
            "Telegram Premium (3 Months)",
            "3 Months Official Telegram Premium (Direct to @username)",
            38000.0, 999,
            "✨ Telegram Premium (3 Months)\n\n"
            "• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Premium ၃ လစာ Plan ဖြစ်ပါသည်။\n"
            "• Account Password ပေးရန် လုံးဝမလိုအပ်ပါ။\n"
            "• သက်တမ်းအပြည့် အာမခံ (Full Warranty) ပါဝင်ပါသည်။",
            "3 Months Official Telegram Premium",
            "✨ Telegram Premium (3 Months)\n\n"
            "• Official 3-Month subscription delivered directly to your @username.\n"
            "• No password or login required.\n"
            "• Full duration warranty included."
        ),
        (
            "Telegram Premium (6 Months)",
            "6 Months Official Telegram Premium (Direct to @username)",
            68000.0, 999,
            "✨ Telegram Premium (6 Months)\n\n"
            "• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Premium ၆ လစာ Plan ဖြစ်ပါသည်။\n"
            "• Account Password ပေးရန် လုံးဝမလိုအပ်ပါ။\n"
            "• သက်တမ်းအပြည့် အာမခံ (Full Warranty) ပါဝင်ပါသည်။",
            "6 Months Official Telegram Premium",
            "✨ Telegram Premium (6 Months)\n\n"
            "• Official 6-Month subscription delivered directly to your @username.\n"
            "• No password or login required.\n"
            "• Full duration warranty included."
        ),
        (
            "Telegram Premium (12 Months)",
            "12 Months / 1 Year Official Telegram Premium (Direct to @username)",
            125000.0, 999,
            "✨ Telegram Premium (12 Months / 1 Year)\n\n"
            "• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Premium ၁ နှစ်စာ Plan ဖြစ်ပါသည်။\n"
            "• Account Password ပေးရန် လုံးဝမလိုအပ်ပါ။\n"
            "• သက်တမ်းအပြည့် အာမခံ (Full Warranty) ပါဝင်ပါသည်။",
            "12 Months Official Telegram Premium",
            "✨ Telegram Premium (12 Months / 1 Year)\n\n"
            "• Official 1-Year subscription delivered directly to your @username.\n"
            "• No password or login required.\n"
            "• Full duration warranty included."
        ),

        # ==========================================================
        # ⭐ 2. Telegram Stars Packages (50 to 10,000 Stars)
        # ==========================================================
        (
            "Telegram Stars (50 Stars)",
            "50 Telegram Stars (Direct to @username)",
            4800.0, 999,
            "⭐ Telegram Stars (50 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 50 ခု ဖြစ်ပါသည်။",
            "50 Telegram Stars",
            "⭐ 50 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (100 Stars)",
            "100 Telegram Stars (Direct to @username)",
            9500.0, 999,
            "⭐ Telegram Stars (100 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 100 ခု ဖြစ်ပါသည်။",
            "100 Telegram Stars",
            "⭐ 100 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (150 Stars)",
            "150 Telegram Stars (Direct to @username)",
            14200.0, 999,
            "⭐ Telegram Stars (150 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 150 ခု ဖြစ်ပါသည်။",
            "150 Telegram Stars",
            "⭐ 150 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (250 Stars)",
            "250 Telegram Stars (Direct to @username)",
            23500.0, 999,
            "⭐ Telegram Stars (250 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 250 ခု ဖြစ်ပါသည်။",
            "250 Telegram Stars",
            "⭐ 250 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (350 Stars)",
            "350 Telegram Stars (Direct to @username)",
            32800.0, 999,
            "⭐ Telegram Stars (350 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 350 ခု ဖြစ်ပါသည်။",
            "350 Telegram Stars",
            "⭐ 350 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (500 Stars)",
            "500 Telegram Stars (Direct to @username)",
            46500.0, 999,
            "⭐ Telegram Stars (500 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 500 ခု ဖြစ်ပါသည်။",
            "500 Telegram Stars",
            "⭐ 500 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (750 Stars)",
            "750 Telegram Stars (Direct to @username)",
            69500.0, 999,
            "⭐ Telegram Stars (750 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 750 ခု ဖြစ်ပါသည်။",
            "750 Telegram Stars",
            "⭐ 750 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (1000 Stars)",
            "1000 Telegram Stars (Direct to @username)",
            92000.0, 999,
            "⭐ Telegram Stars (1,000 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 1,000 ခု ဖြစ်ပါသည်။",
            "1000 Telegram Stars",
            "⭐ 1,000 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (2500 Stars)",
            "2500 Telegram Stars (Direct to @username)",
            228000.0, 999,
            "⭐ Telegram Stars (2,500 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 2,500 ခု ဖြစ်ပါသည်။",
            "2500 Telegram Stars",
            "⭐ 2,500 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (5000 Stars)",
            "5000 Telegram Stars (Direct to @username)",
            450000.0, 999,
            "⭐ Telegram Stars (5,000 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 5,000 ခု ဖြစ်ပါသည်။",
            "5000 Telegram Stars",
            "⭐ 5,000 Official Telegram Stars delivered directly to your @username."
        ),
        (
            "Telegram Stars (10000 Stars)",
            "10000 Telegram Stars (Direct to @username)",
            895000.0, 999,
            "⭐ Telegram Stars (10,000 Stars)\n• သင့် @username သို့ တိုက်ရိုက်ပို့ဆောင်ပေးမည့် Official Telegram Stars 10,000 ခု ဖြစ်ပါသည်။",
            "10000 Telegram Stars",
            "⭐ 10,000 Official Telegram Stars delivered directly to your @username."
        ),

        # ==========================================================
        # 🍎 3. Apple Gift Card Plans ($2 to $200 — US Region)
        # ==========================================================
        (
            "Apple Gift Card $2 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            11500.0, 5,
            "🍎 Apple Gift Card $2 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($2)",
            "🍎 Apple Gift Card $2 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $5 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            26500.0, 5,
            "🍎 Apple Gift Card $5 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($5)",
            "🍎 Apple Gift Card $5 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $10 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            49900.0, 5,
            "🍎 Apple Gift Card $10 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($10)",
            "🍎 Apple Gift Card $10 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $15 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            74500.0, 5,
            "🍎 Apple Gift Card $15 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($15)",
            "🍎 Apple Gift Card $15 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $20 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            98500.0, 5,
            "🍎 Apple Gift Card $20 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($20)",
            "🍎 Apple Gift Card $20 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $25 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            122500.0, 5,
            "🍎 Apple Gift Card $25 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($25)",
            "🍎 Apple Gift Card $25 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $30 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            146500.0, 5,
            "🍎 Apple Gift Card $30 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($30)",
            "🍎 Apple Gift Card $30 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $50 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            242000.0, 5,
            "🍎 Apple Gift Card $50 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($50)",
            "🍎 Apple Gift Card $50 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $100 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            480000.0, 5,
            "🍎 Apple Gift Card $100 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($100)",
            "🍎 Apple Gift Card $100 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
        (
            "Apple Gift Card $200 (US Region)",
            "US Apple ID Only (Instant Redeem Code)",
            955000.0, 3,
            "🍎 Apple Gift Card $200 (United States)\n• US Region Apple ID များတွင်သာ အသုံးပြုနိုင်ပါသည်။\n• ကုဒ်ထုတ်ပေးပြီးပါက Refund / Exchange လုံးဝမရပါ။",
            "US Apple ID Only ($200)",
            "🍎 Apple Gift Card $200 (US Region). Valid only for US Apple ID accounts. Non-refundable."
        ),
    ]

    added_items = 0
    for item in plans:
        exists = cursor.execute(
            "SELECT item_id FROM items WHERE TRIM(name) = TRIM(?) COLLATE NOCASE",
            (item[0],)
        ).fetchone()
        if not exists:
            cursor.execute(
                """
                INSERT INTO items (name, details, price, stock, type, details_en, type_en, renewable)
                VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                """,
                item
            )
            added_items += 1
            print(f"✅ Added Plan: {item[0]} — {int(item[2]):,} MMK")
        else:
            print(f"ℹ️ Already exists: {item[0]}")

    # Apple Gift Card အားလုံးအတွက် စမ်းသပ်ရန် Dummy Redeem Code (၁၆ လုံးတွဲ) များ ထည့်ပေးခြင်း
    apple_denominations = [2, 5, 10, 15, 20, 25, 30, 50, 100, 200]
    for denom in apple_denominations:
        item_name = f"Apple Gift Card ${denom} (US Region)"
        for idx in range(1, 6):
            # 16-character alphanumeric test code so One-Tap App Store Redeem button appears automatically
            raw_code = f"XAPPLEUS{denom:03d}TEST{idx:02d}"[:16].ljust(16, "9")
            exists_stock = cursor.execute(
                "SELECT 1 FROM item_stocks WHERE TRIM(item_name) = TRIM(?) AND TRIM(account_info) = TRIM(?)",
                (item_name, raw_code)
            ).fetchone()
            if not exists_stock:
                cursor.execute(
                    "INSERT INTO item_stocks (item_name, account_info, is_sold) VALUES (?, ?, 0)",
                    (item_name, raw_code)
                )

    conn.commit()
    conn.close()
    print(f"\n🎉 Done! Added {added_items} new plans + dummy test codes into shop.db!")

if __name__ == "__main__":
    setup_all_plans()