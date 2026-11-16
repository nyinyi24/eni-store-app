"""FastAPI REST Backend for ENI Premium Store Android Mobile App.
Shares the exact same SQLite database (shop.db), Outline VPN API, and Crypto Verification API as the Telegram Bot.
"""
import hashlib
import html
import os
import secrets
from datetime import datetime, timedelta
from typing import Optional

import jwt
import telebot
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config import (
    API_TOKEN,
    DATABASE_NAME,
    SUPPORT_URL,
    USDT_ERC20_ADDRESS,
    USDT_BEP20_ADDRESS,
    BINANCE_PAY_ID,
)
from database import (
    init_db,
    ensure_app_notifications_table,
    cancel_user_stock_reservation,
    get_db_connection,
    get_all_items,
    get_available_stock_map,
    get_active_discounts,
    create_reserved_order,
    create_existing_key_renewal_order,
    submit_payment_proof,
    get_user_orders,
    get_user_profile_stats,
    add_user,
    get_all_admin_ids,
    get_user_wallet,
    claim_daily_checkin,
    redeem_points_to_wallet,
    create_wallet_topup_request,
    get_coupon_for_user,
    get_mmk_per_usd,
    get_order_details,
    update_order_delivery,
    update_order_status,
    claim_stock_reservation_for_processing,
    complete_stock_reservation,
    mark_payment_submission_status,
    pull_accounts_from_stock_by_name,
    adjust_user_wallet_balance,
    create_support_ticket,
    yangon_now,
)
from outline_api import get_key_data_usage, create_access_key, is_configured as is_outline_configured
from crypto_api import (
    verify_evm_usdt_transaction,
    verify_binance_pay_transaction,
)

init_db()

app = FastAPI(title="ENI Premium Store Mobile API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bot = telebot.TeleBot(API_TOKEN, parse_mode="HTML") if API_TOKEN else None
JWT_SECRET = os.environ.get("APP_JWT_SECRET", "eni_super_secret_jwt_key_change_this_in_production_2026")
JWT_ALGO = "HS256"

KPAY_INFO = os.environ.get("KPAY_NUMBER", "09xxxxxxxxx (Admin KPay)")
WAVEPAY_INFO = os.environ.get("WAVEPAY_NUMBER", "09xxxxxxxxx (Admin WavePay)")


def init_app_auth_tables():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS app_accounts (
                account_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER UNIQUE NOT NULL,
                phone_or_email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL DEFAULT 'App User',
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS telegram_link_codes (
                code TEXT PRIMARY KEY,
                telegram_user_id INTEGER NOT NULL,
                expires_at TEXT NOT NULL
            )
            """
        )
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(telegram_link_codes)").fetchall()]
        if "app_user_id" not in cols:
            cursor.execute("ALTER TABLE telegram_link_codes ADD COLUMN app_user_id INTEGER")
        conn.commit()


init_app_auth_tables()
with get_db_connection(DATABASE_NAME) as _c:
    ensure_app_notifications_table(_c.cursor())
    _c.commit()


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception):
    print(f"Unhandled API error on {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Server ဘက်မှာ ပြဿနာ ဖြစ်နေပါတယ်။ ခဏနေမှ ပြန်ကြိုးစားပါ၊ ဆက်ဖြစ်နေရင် Admin ကို ဆက်သွယ်ပါ။"},
    )


def friendly_order_error(res: dict) -> str:
    reason = str(res.get("reason", ""))
    if reason == "insufficient_stock":
        stock = int(res.get("available_stock", 0))
        if stock <= 0:
            return "ဒီပစ္စည်း လောလောဆယ် Stock ကုန်နေပါတယ်။ တခြားသူက reserve လုပ်ထားတာလည်း ဖြစ်နိုင်လို့ ၁၀ မိနစ်ခန့်နေမှ ပြန်ကြည့်ပါ။"
        return f"Stock မလုံလောက်ပါ။ အခု ဝယ်လို့ရတာ {stock} ခုပဲ ကျန်ပါတယ်။"
    messages = {
        "invalid_quantity": "အရေအတွက်ကို ၁ ခု သို့မဟုတ် အထက် ထည့်ပါ။",
        "item_not_found": "ဒီပစ္စည်းကို ရှာမတွေ့ပါ။ ဖယ်ရှားထားနိုင်ပါတယ်၊ Shop ကို refresh လုပ်ပါ။",
        "coupon_unavailable": "ဒီ Coupon ကို သုံးလို့မရပါ။ (code မှားနေ၊ သက်တမ်းကုန်၊ သုံးပြီးသား သို့မဟုတ် တခြားသူ့ဆီ သီးသန့်ထုတ်ထားတာ ဖြစ်နိုင်ပါတယ်)",
        "existing_order_under_review": "ငွေပေးချေမှု စစ်ဆေးနေဆဲ order တစ်ခု ရှိနေပါတယ်။ Admin အတည်ပြုပြီးမှ order အသစ် ဝယ်ပါ။",
        "source_order_not_found": "မူရင်း order ကို ရှာမတွေ့ပါ။",
        "product_not_renewable": "ဒီပစ္စည်းကို renew လုပ်လို့မရပါ။",
    }
    return messages.get(reason, "Order မလုပ်နိုင်ပါ။ ခဏနေမှ ပြန်ကြိုးစားပါ။")


PROOF_ERRORS = {
    "already_submitted": "ဒီ order အတွက် Receipt ပို့ပြီးသားပါ။ Admin အတည်ပြုပေးဖို့ စောင့်ပါ။",
    "duplicate_proof": "ဒီ Receipt ပုံကို အရင်က အသုံးပြုပြီးသား ဖြစ်နေပါတယ်။ ငွေလွှဲပြီးသား screenshot အသစ်ကို တင်ပါ။",
    "not_found": "Order ကို ရှာမတွေ့ပါ။",
    "expired": "ဒီ order ရဲ့ ၁၀ မိနစ် reserve သက်တမ်း ကုန်သွားပါပြီ။ Order အသစ် ပြန်လုပ်ပါ။",
    "cancelled": "ဒီ order ကို ပယ်ဖျက်ပြီးသားပါ။ Order အသစ် ပြန်လုပ်ပါ။",
    "released": "ဒီ order ရဲ့ reserve ကုန်သွားပါပြီ။ Order အသစ် ပြန်လုပ်ပါ။",
}


def friendly_proof_error(status: str) -> str:
    return PROOF_ERRORS.get(str(status), f"Receipt မတင်နိုင်ပါ ({status})။ Order အခြေအနေကို စစ်ပါ။")


def validate_image_upload(file: UploadFile, data: bytes):
    if not data:
        raise HTTPException(status_code=400, detail="ပုံဖိုင် ဗလာဖြစ်နေပါတယ်။ Screenshot ကို ပြန်ရွေးပါ။")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="ပုံဖိုင်ကြီးလွန်းပါတယ် (အများဆုံး 10MB)။")
    ctype = (file.content_type or "").lower()
    if ctype and not ctype.startswith("image/") and ctype != "application/octet-stream":
        raise HTTPException(status_code=400, detail="ပုံ (JPG/PNG) ဖိုင်ကိုပဲ တင်လို့ရပါတယ်။")


def _hash_password(password: str, salt: str = "eni_salt_2026") -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), 100_000
    ).hex()


def create_jwt_token(user_id: int) -> str:
    payload = {
        "user_id": int(user_id),
        "exp": datetime.utcnow() + timedelta(days=30),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)


def get_current_user(authorization: str = Header(...)) -> int:
    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError("Invalid token scheme")
        decoded = jwt.decode(token.strip(), JWT_SECRET, algorithms=[JWT_ALGO])
        return int(decoded["user_id"])
    except Exception:
        raise HTTPException(status_code=401, detail="Session expired or invalid token. Please login again.")


# ==================== Pydantic Models ====================

class RegisterRequest(BaseModel):
    phone_or_email: str
    password: str
    full_name: str = "ENI Customer"
    telegram_user_id: Optional[int] = None


class LoginRequest(BaseModel):
    phone_or_email: str
    password: str


class CreateOrderRequest(BaseModel):
    item_id: int
    quantity: int = 1
    payment_method: str  # KPay, WavePay, Wallet, USDT_BEP20, USDT_ERC20, BINANCE_PAY
    coupon_code: Optional[str] = None
    target_username: Optional[str] = None


class CouponCheckRequest(BaseModel):
    code: str
    total_amount: float


class CryptoVerifyRequest(BaseModel):
    order_id: int
    network: str  # bep20, erc20, binance
    tx_hash_or_note: str


class SupportTicketRequest(BaseModel):
    order_id: int
    issue_text: str


# ==================== 1. Authentication ====================

@app.post("/api/auth/register")
def api_register(req: RegisterRequest):
    identifier = req.phone_or_email.strip().lower()
    if len(identifier) < 4 or len(req.password) < 4:
        raise HTTPException(status_code=400, detail="Username/Phone and password must be at least 4 characters.")

    now_str = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cur = conn.cursor()
        exists = cur.execute(
            "SELECT 1 FROM app_accounts WHERE phone_or_email = ?", (identifier,)
        ).fetchone()
        if exists:
            raise HTTPException(status_code=400, detail="This phone/email is already registered.")

        # SECURITY: never attach a Telegram ID at registration (it is unverified and would let
        # anyone claim another user's wallet). Use POST /api/account/telegram/request + /verify.
        new_user_id = None

        if not new_user_id:
            max_row = cur.execute("SELECT MAX(user_id) FROM app_accounts WHERE user_id >= 9000000000").fetchone()
            new_user_id = max(9000000000, (max_row[0] or 9000000000) + 1)

        cur.execute(
            """
            INSERT INTO app_accounts (user_id, phone_or_email, password_hash, full_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (new_user_id, identifier, _hash_password(req.password), req.full_name.strip(), now_str),
        )
        conn.commit()

    add_user(new_user_id, join_date=now_str, username=identifier, first_name=req.full_name.strip())
    return {
        "ok": True,
        "token": create_jwt_token(new_user_id),
        "user_id": new_user_id,
        "full_name": req.full_name.strip(),
    }


@app.post("/api/auth/login")
def api_login(req: LoginRequest):
    identifier = req.phone_or_email.strip().lower()
    with get_db_connection(DATABASE_NAME) as conn:
        row = conn.execute(
            "SELECT user_id, password_hash, full_name FROM app_accounts WHERE phone_or_email = ?",
            (identifier,),
        ).fetchone()
    if not row or row[1] != _hash_password(req.password):
        raise HTTPException(status_code=401, detail="Invalid phone/email or password.")
    return {
        "ok": True,
        "token": create_jwt_token(row[0]),
        "user_id": int(row[0]),
        "full_name": row[2],
    }


# ==================== 1b. Account / Profile Management ====================

class UpdateProfileRequest(BaseModel):
    full_name: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str


class TelegramLinkRequest(BaseModel):
    telegram_user_id: int


class TelegramVerifyRequest(BaseModel):
    code: str


def _is_app_only(user_id: int) -> bool:
    return int(user_id) >= 9000000000


@app.get("/api/account/me")
def api_account_me(user_id: int = Depends(get_current_user)):
    with get_db_connection(DATABASE_NAME) as conn:
        row = conn.execute(
            "SELECT phone_or_email, full_name, created_at FROM app_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Account not found")
    return {
        "user_id": int(user_id),
        "identifier": row[0],
        "full_name": row[1],
        "created_at": row[2],
        "telegram_linked": not _is_app_only(user_id),
        "telegram_user_id": None if _is_app_only(user_id) else int(user_id),
    }


@app.put("/api/account/profile")
def api_update_profile(req: UpdateProfileRequest, user_id: int = Depends(get_current_user)):
    name = req.full_name.strip()
    if len(name) < 2 or len(name) > 60:
        raise HTTPException(status_code=400, detail="နာမည်သည် ၂ လုံးမှ ၆၀ လုံးအတွင်း ဖြစ်ရပါမည်။")
    with get_db_connection(DATABASE_NAME) as conn:
        conn.execute("UPDATE app_accounts SET full_name = ? WHERE user_id = ?", (name, user_id))
        conn.execute("UPDATE users SET first_name = ? WHERE user_id = ?", (name, user_id))
        conn.commit()
    return {"ok": True, "full_name": name}


@app.post("/api/account/change-password")
def api_change_password(req: ChangePasswordRequest, user_id: int = Depends(get_current_user)):
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password အသစ်သည် အနည်းဆုံး ၄ လုံး ရှိရပါမည်။")
    with get_db_connection(DATABASE_NAME) as conn:
        row = conn.execute(
            "SELECT password_hash FROM app_accounts WHERE user_id = ?", (user_id,)
        ).fetchone()
        if not row or row[0] != _hash_password(req.old_password):
            raise HTTPException(status_code=400, detail="Password အဟောင်း မမှန်ပါ။")
        conn.execute(
            "UPDATE app_accounts SET password_hash = ? WHERE user_id = ?",
            (_hash_password(req.new_password), user_id),
        )
        conn.commit()
    return {"ok": True, "message": "Password ပြောင်းပြီးပါပြီ။"}


@app.post("/api/account/telegram/request")
def api_telegram_link_request(req: TelegramLinkRequest, user_id: int = Depends(get_current_user)):
    """Step 1: the bot DMs a 6-digit code to the Telegram ID, proving the person owns it."""
    if not _is_app_only(user_id):
        raise HTTPException(status_code=400, detail="ဒီ account မှာ Telegram ချိတ်ပြီးသား ဖြစ်ပါတယ်။")
    tg_id = int(req.telegram_user_id)
    if tg_id <= 0 or tg_id >= 9000000000:
        raise HTTPException(status_code=400, detail="Telegram User ID မမှန်ပါ။")
    if not bot:
        raise HTTPException(status_code=503, detail="Bot မချိတ်ထားသေးပါ။ Admin ကို ဆက်သွယ်ပါ။")

    with get_db_connection(DATABASE_NAME) as conn:
        taken = conn.execute("SELECT 1 FROM app_accounts WHERE user_id = ?", (tg_id,)).fetchone()
        if taken:
            raise HTTPException(status_code=400, detail="ဒီ Telegram ID ကို တခြား app account က ချိတ်ထားပြီးသား ဖြစ်ပါတယ်။")
        name_row = conn.execute(
            "SELECT full_name FROM app_accounts WHERE user_id = ?", (user_id,)
        ).fetchone()

    code = f"{secrets.randbelow(900000) + 100000}"
    expires = (yangon_now() + timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
    try:
        bot.send_message(
            tg_id,
            "🔗 <b>ENI Store App Link Code</b>\n"
            f"App account: <b>{html.escape(str(name_row[0] if name_row else 'App User'))}</b>\n\n"
            f"Code: <code>{code}</code>\n"
            "⏱ ၁၀ မိနစ်အတွင်း App ထဲမှာ ထည့်ပါ။\n"
            "သင်မလုပ်ခဲ့ရင် ဒီ message ကို လျစ်လျူရှုပါ။",
        )
    except Exception:
        raise HTTPException(
            status_code=400,
            detail="Telegram ကို code မပို့နိုင်ပါ။ Bot ကို Telegram မှာ /start လုပ်ထားပြီး ID မှန်မမှန် စစ်ပါ။",
        )

    with get_db_connection(DATABASE_NAME) as conn:
        conn.execute("DELETE FROM telegram_link_codes WHERE app_user_id = ?", (user_id,))
        conn.execute(
            "INSERT INTO telegram_link_codes (code, telegram_user_id, expires_at, app_user_id) VALUES (?, ?, ?, ?)",
            (f"{user_id}:{code}", tg_id, expires, user_id),
        )
        conn.commit()
    return {"ok": True, "message": "Telegram Bot ဆီကို code ပို့လိုက်ပါပြီ။"}


@app.post("/api/account/telegram/verify")
def api_telegram_link_verify(req: TelegramVerifyRequest, user_id: int = Depends(get_current_user)):
    """Step 2: merge this app account (wallet, orders, points) into the Telegram user's data."""
    if not _is_app_only(user_id):
        raise HTTPException(status_code=400, detail="Telegram ချိတ်ပြီးသား ဖြစ်ပါတယ်။")
    code = req.code.strip()
    now_str = yangon_now().strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection(DATABASE_NAME, timeout=15) as conn:
        row = conn.execute(
            "SELECT telegram_user_id, expires_at FROM telegram_link_codes WHERE code = ? AND app_user_id = ?",
            (f"{user_id}:{code}", user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=400, detail="Code မမှန်ပါ။")
        if str(row[1]) < now_str:
            conn.execute("DELETE FROM telegram_link_codes WHERE app_user_id = ?", (user_id,))
            conn.commit()
            raise HTTPException(status_code=400, detail="Code သက်တမ်းကုန်သွားပါပြီ။ ပြန်တောင်းပါ။")
        new_id = int(row[0])
        old_id = int(user_id)

        if conn.execute("SELECT 1 FROM app_accounts WHERE user_id = ?", (new_id,)).fetchone():
            raise HTTPException(status_code=400, detail="ဒီ Telegram ID ကို တခြား account က ချိတ်ထားပြီးသား ဖြစ်ပါတယ်။")

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute("INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)", (new_id, now_str))
            # wallet: add app balance/points on top of the bot wallet
            conn.execute(
                "INSERT OR IGNORE INTO user_wallets (user_id, balance, points, streak, last_checkin_date) "
                "VALUES (?, 0, 0, 0, '')", (new_id,)
            )
            old_w = conn.execute(
                "SELECT balance, points FROM user_wallets WHERE user_id = ?", (old_id,)
            ).fetchone()
            if old_w:
                conn.execute(
                    "UPDATE user_wallets SET balance = balance + ?, points = points + ? WHERE user_id = ?",
                    (float(old_w[0] or 0), int(old_w[1] or 0), new_id),
                )
                conn.execute("DELETE FROM user_wallets WHERE user_id = ?", (old_id,))

            for table in (
                "orders", "wallet_topups", "support_tickets", "payment_submissions",
                "stock_reservations", "stock_waitlist", "promotion_claims", "gw_claims",
                "referral_rewards", "app_notifications",
            ):
                conn.execute(f"UPDATE OR IGNORE {table} SET user_id = ? WHERE user_id = ?", (new_id, old_id))
            conn.execute("UPDATE OR IGNORE orders SET gift_recipient_id = ? WHERE gift_recipient_id = ?", (new_id, old_id))

            conn.execute("UPDATE app_accounts SET user_id = ? WHERE user_id = ?", (new_id, old_id))
            conn.execute("DELETE FROM users WHERE user_id = ?", (old_id,))
            conn.execute("DELETE FROM telegram_link_codes WHERE app_user_id = ?", (old_id,))
            conn.commit()
        except Exception as e:
            conn.rollback()
            raise HTTPException(status_code=500, detail=f"Link failed: {e}")

    return {
        "ok": True,
        "token": create_jwt_token(new_id),
        "user_id": new_id,
        "message": "Telegram ချိတ်ဆက်ပြီးပါပြီ။ Bot ထဲက balance နဲ့ order တွေ ပေါင်းထည့်ပေးပြီးပါပြီ။",
    }


# ==================== 1c. In-app Notifications ====================

class MarkReadRequest(BaseModel):
    ids: Optional[list[int]] = None  # None / empty = mark all


@app.get("/api/notifications")
def api_notifications(user_id: int = Depends(get_current_user)):
    with get_db_connection(DATABASE_NAME) as conn:
        rows = conn.execute(
            "SELECT id, kind, title, body, order_id, is_read, created_at FROM app_notifications "
            "WHERE user_id = ? ORDER BY id DESC LIMIT 50",
            (user_id,),
        ).fetchall()
        unread = conn.execute(
            "SELECT COUNT(*) FROM app_notifications WHERE user_id = ? AND is_read = 0", (user_id,)
        ).fetchone()[0]
    return {
        "unread": int(unread),
        "notifications": [
            {"id": r[0], "kind": r[1], "title": r[2], "body": r[3], "order_id": r[4],
             "is_read": bool(r[5]), "created_at": r[6]}
            for r in rows
        ],
    }


@app.post("/api/notifications/read")
def api_notifications_read(req: MarkReadRequest, user_id: int = Depends(get_current_user)):
    with get_db_connection(DATABASE_NAME) as conn:
        if req.ids:
            marks = ",".join("?" for _ in req.ids)
            conn.execute(
                f"UPDATE app_notifications SET is_read = 1 WHERE user_id = ? AND id IN ({marks})",
                (user_id, *req.ids),
            )
        else:
            conn.execute("UPDATE app_notifications SET is_read = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
    return {"ok": True}


# ==================== 2. Store Catalog & Config ====================

@app.get("/api/store/config")
def api_store_config():
    return {
        "mmk_per_usd": get_mmk_per_usd(),
        "support_url": SUPPORT_URL,
        "payment_methods": {
            "KPay": KPAY_INFO,
            "WavePay": WAVEPAY_INFO,
            "USDT_BEP20": USDT_BEP20_ADDRESS,
            "USDT_ERC20": USDT_ERC20_ADDRESS,
            "BINANCE_PAY": BINANCE_PAY_ID,
        },
    }


@app.get("/api/products")
def api_list_products():
    items = get_all_items()
    stock_map = get_available_stock_map()
    discounts = {int(d[0]): d for d in get_active_discounts()}
    mmk_per_usd = get_mmk_per_usd()

    product_list = []
    for item in items:
        item_id = int(item[0])
        price_mmk = float(item[3] or 0)
        disc = discounts.get(item_id)
        product_list.append({
            "item_id": item_id,
            "name": item[1],
            "details": item[2] or "",
            "price_mmk": price_mmk,
            "price_usd": round(price_mmk / mmk_per_usd, 2) if mmk_per_usd else 0,
            "original_price_mmk": float(disc[2]) if disc else None,
            "discount_percent": float(disc[4]) if disc else None,
            "discount_ends_at": disc[6] if disc else None,
            "available_stock": stock_map.get(item_id, 0),
            "description_mm": item[5] or "",
            "details_en": item[6] if len(item) > 6 and item[6] else "",
            "description_en": item[7] if len(item) > 7 and item[7] else "",
            "renewable": bool(item[8]) if len(item) > 8 else False,
        })
    return {"products": product_list, "mmk_per_usd": mmk_per_usd}


@app.post("/api/coupons/check")
def api_check_coupon(req: CouponCheckRequest, user_id: int = Depends(get_current_user)):
    res, err = get_coupon_for_user(req.code.strip(), user_id, req.total_amount)
    if err or not res:
        raise HTTPException(status_code=400, detail=f"Coupon invalid: {err}")
    return {"ok": True, "coupon": res}


# ==================== 3. Orders & Instant Delivery ====================

def _auto_deliver_order(order_id: int) -> dict:
    """Attempt automatic stock or Outline key delivery (used for Wallet & Crypto auto-verified orders)."""
    order = get_order_details(order_id)
    if not order:
        return {"delivered": False, "reason": "Order not found"}
    user_id = int(order[1])
    item_name = str(order[2])
    quantity = max(1, int(order[3] or 1))
    order_code = str(order[8] or f"ORD-{order_id}")
    expiry_date = str(order[9] or "")

    claim_stock_reservation_for_processing(order_id, admin_id=0)

    delivered_accounts = []
    if "outline" in item_name.lower() and is_outline_configured():
        for _ in range(quantity):
            created = create_access_key(item_name, order_code, expiry_date)
            if created.get("ok"):
                delivered_accounts.append(created["formatted"])
    if not delivered_accounts:
        delivered_accounts = pull_accounts_from_stock_by_name(item_name, quantity)

    if delivered_accounts and len(delivered_accounts) >= quantity:
        combined = "\n\n---\n\n".join(delivered_accounts)
        update_order_delivery(order_id, combined)
        update_order_status(order_id, "Success", reduce_stock=False)
        complete_stock_reservation(order_id)
        mark_payment_submission_status(order_id, "approved", admin_id=0)
        return {"delivered": True, "delivered_data": combined}

    return {"delivered": False, "reason": "Manual delivery queued for Admin"}


def _order_dict(order_id):
    """Fetch an order as a dict keyed by column NAME (tuple indexes differ between DBs)."""
    with get_db_connection(DATABASE_NAME) as conn:
        cur = conn.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
        row = cur.fetchone()
        if not row:
            return None
        return dict(zip([d[0] for d in cur.description], row))


def _user_orders_dicts(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cur = conn.execute(
            "SELECT * FROM orders WHERE user_id = ? AND status = 'Success' ORDER BY order_id DESC",
            (int(user_id),),
        )
        names = [d[0] for d in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


@app.post("/api/orders")
def api_create_order(req: CreateOrderRequest, user_id: int = Depends(get_current_user)):
    res = create_reserved_order(
        user_id=user_id,
        item_id=req.item_id,
        quantity=req.quantity,
        payment_method=req.payment_method,
        coupon_code=req.coupon_code,
        target_username=req.target_username,
        reservation_minutes=10,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=friendly_order_error(res))

    order_id = int(res["order_id"])
    total_amount = float(res["total_amount"])

    # Wallet payment: check the balance BEFORE keeping the reservation, so a failed attempt
    # never leaves stock locked / an order hanging.
    if req.payment_method.upper() == "WALLET" and total_amount > 0:
        balance = get_user_wallet(user_id)["balance"]
        if balance < total_amount:
            try:
                cancel_user_stock_reservation(order_id, user_id)
            except Exception as e:
                print(f"release after insufficient wallet failed: {e}")
            shortage = total_amount - balance
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "insufficient_wallet",
                    "message": (
                        f"Wallet လက်ကျန်ငွေ မလောက်ပါ။\n"
                        f"လိုအပ်ငွေ: {total_amount:,.0f} Ks\n"
                        f"လက်ကျန်: {balance:,.0f} Ks\n"
                        f"ကျန်ငွေ {shortage:,.0f} Ks ကို Wallet မှာ Top-Up အရင်လုပ်ပါ၊ "
                        f"ဒါမှမဟုတ် တခြား payment နည်းလမ်း ရွေးပါ။"
                    ),
                    "needed": total_amount,
                    "balance": balance,
                    "shortage": shortage,
                },
            )
    mmk_per_usd = get_mmk_per_usd()
    res["total_usd"] = round(total_amount / mmk_per_usd, 2) if mmk_per_usd else 0

    # If user pays with Wallet Balance, deduct immediately and auto-deliver!
    if req.payment_method.upper() == "WALLET" or res.get("fully_discounted"):
        if total_amount > 0:
            ok, new_bal = adjust_user_wallet_balance(user_id, -total_amount)
            if not ok:
                try:
                    cancel_user_stock_reservation(order_id, user_id)
                except Exception:
                    pass
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "insufficient_wallet",
                        "message": f"Wallet လက်ကျန်ငွေ မလောက်ပါ (လက်ကျန် {new_bal:,.0f} Ks)။ Top-Up လုပ်ပါ။",
                    },
                )
        delivery_res = _auto_deliver_order(order_id)
        res["wallet_paid"] = True
        res["auto_delivered"] = delivery_res.get("delivered", False)
        res["delivered_data"] = delivery_res.get("delivered_data")

        if not delivery_res.get("delivered") and bot:
            markup = telebot.types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                telebot.types.InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_{order_id}"),
                telebot.types.InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{order_id}"),
            )
            for admin_id in get_all_admin_ids():
                try:
                    bot.send_message(
                        admin_id,
                        f"📱 <b>Wallet Order (Manual Stock Needed)</b>\n"
                        f"👤 User ID: <code>{user_id}</code>\n"
                        f"📦 Item: <b>{html.escape(res['item_name'])}</b> (x{res['quantity']})\n"
                        f"💰 Paid via Wallet: <b>{total_amount:,.0f} MMK</b>\n"
                        f"🧾 Order Code: <code>{res['order_code']}</code>",
                        reply_markup=markup,
                    )
                except Exception:
                    pass

    return res


@app.post("/api/orders/{order_id}/proof")
async def api_upload_payment_proof(
    order_id: int,
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user),
):
    image_bytes = await file.read()
    validate_image_upload(file, image_bytes)

    file_hash = "APP_" + hashlib.sha256(image_bytes).hexdigest()[:32]
    status = submit_payment_proof(order_id, user_id, file_unique_id=file_hash)
    if status != "submitted":
        raise HTTPException(status_code=400, detail=friendly_proof_error(status))

    order = _order_dict(order_id) or {}
    item_name = order.get("item_name") or "Product"
    qty = order.get("quantity") or 1
    method = order.get("payment_method") or "App"
    order_code = order.get("order_code") or f"ORD-{order_id}"
    amount = order.get("total_amount") or 0

    if bot:
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            telebot.types.InlineKeyboardButton("✅ Approve", callback_data=f"admin_approve_{order_id}"),
            telebot.types.InlineKeyboardButton("❌ Reject", callback_data=f"admin_reject_{order_id}"),
        )
        caption = (
            f"📱 <b>Mobile App Payment Receipt</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"📦 Item: <b>{html.escape(str(item_name))}</b> (x{qty})\n"
            f"💳 Method: <b>{html.escape(str(method))}</b>\n"
            f"💰 Total: <b>{float(amount):,.0f} MMK</b>\n"
            f"🧾 Order ID: <code>{html.escape(str(order_code))}</code>"
        )
        for admin_id in get_all_admin_ids():
            try:
                bot.send_photo(admin_id, image_bytes, caption=caption, reply_markup=markup)
            except Exception as e:
                print(f"Failed sending receipt to admin {admin_id}: {e}")

    return {"ok": True, "message": "Receipt ပို့ပြီးပါပြီ။ Admin အတည်ပြုပြီးရင် ပစ္စည်း Orders tab ထဲ ရောက်လာပါမယ်။"}


@app.post("/api/orders/verify-crypto")
def api_verify_crypto(req: CryptoVerifyRequest, user_id: int = Depends(get_current_user)):
    order = get_order_details(req.order_id)
    if not order or int(order[1]) != int(user_id):
        raise HTTPException(status_code=404, detail="Order ကို ရှာမတွေ့ပါ။")

    order_code = str(order[8] or f"ORD-{req.order_id}")
    total_mmk = float((_order_dict(req.order_id) or {}).get("total_amount") or 0)
    mmk_per_usd = get_mmk_per_usd()
    expected_usd = round(total_mmk / mmk_per_usd, 2) if mmk_per_usd else 1.0

    net = req.network.strip().lower()
    if net == "binance":
        check = verify_binance_pay_transaction(order_code, expected_usd, req.tx_hash_or_note)
    else:
        check = verify_evm_usdt_transaction(req.tx_hash_or_note, expected_usd, network=net)

    if not check.get("ok"):
        raise HTTPException(
            status_code=400,
            detail=f"Payment ကို စစ်ဆေးလို့မရသေးပါ: {check.get('reason', 'ရှာမတွေ့ပါ')}\nTransaction Hash / Order ID မှန်မမှန်နဲ့ ငွေပမာဏ ပြည့်မပြည့် ပြန်စစ်ပါ။",
        )

    tx_id = check["tx_id"]
    sub_status = submit_payment_proof(req.order_id, user_id, file_unique_id=tx_id)
    if sub_status not in ("submitted", "already_submitted"):
        raise HTTPException(status_code=400, detail=friendly_proof_error(sub_status))

    delivery_res = _auto_deliver_order(req.order_id)
    return {
        "ok": True,
        "tx_id": tx_id,
        "auto_delivered": delivery_res.get("delivered", False),
        "delivered_data": delivery_res.get("delivered_data"),
    }


@app.post("/api/orders/{order_id}/renew")
def api_renew_existing_key(
    order_id: int,
    payment_method: str = "KPay",
    user_id: int = Depends(get_current_user),
):
    res = create_existing_key_renewal_order(
        source_order_id=order_id,
        user_id=user_id,
        payment_method=payment_method,
        reservation_minutes=10,
    )
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=res.get("reason", "Renewal failed"))
    return res


# ==================== 4. User Dashboard, Wallet & Tickets ====================

@app.get("/api/user/dashboard")
def api_user_dashboard(user_id: int = Depends(get_current_user)):
    profile = get_user_profile_stats(user_id)
    raw_orders = _user_orders_dicts(user_id)
    orders_out = []
    for o in raw_orders:
        outline_key_id = o.get("outline_key_id")
        usage = None
        if outline_key_id:
            u_res = get_key_data_usage(outline_key_id, o["item_name"])
            if u_res.get("ok"):
                usage = u_res
        orders_out.append({
            "order_id": o["order_id"],
            "item_name": o["item_name"],
            "quantity": o["quantity"],
            "payment_method": o["payment_method"],
            "status": o["status"],
            "timestamp": o["timestamp"],
            "delivered_data": o["delivered_data"] or "",
            "order_code": o["order_code"] or f"ORD-{o['order_id']}",
            "expiry_date": o["expiry_date"] or "Lifetime / Non-expiring",
            "total_amount": float(o.get("total_amount") or 0),
            "outline_key_id": outline_key_id,
            "outline_usage": usage,
        })
    return {"profile": profile, "orders": orders_out}


@app.post("/api/wallet/checkin")
def api_daily_checkin(user_id: int = Depends(get_current_user)):
    res = claim_daily_checkin(user_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail="ဒီနေ့ Check-in လုပ်ပြီးသားပါ။ မနက်ဖြန်မှ ပြန်လာပါ။")
    return res


@app.post("/api/wallet/redeem")
def api_redeem_points(user_id: int = Depends(get_current_user)):
    res = redeem_points_to_wallet(user_id, points_needed=500, mmk_reward=1000)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=f"Points မလုံလောက်ပါ။ 500 pts လိုပါတယ် (လက်ရှိ {res.get('points', 0)} pts)။")
    return res


@app.post("/api/wallet/topup")
async def api_wallet_topup(
    amount: float,
    payment_method: str = "KPay",
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user),
):
    if amount < 1000:
        raise HTTPException(status_code=400, detail="Top-Up ငွေပမာဏ အနည်းဆုံး 1,000 Ks ဖြစ်ရပါမယ်။")
    if amount > 5_000_000:
        raise HTTPException(status_code=400, detail="တစ်ကြိမ်လျှင် Top-Up အများဆုံး 5,000,000 Ks ပဲ လက်ခံပါတယ်။")
    if payment_method not in ("KPay", "WavePay"):
        raise HTTPException(status_code=400, detail="Top-Up နည်းလမ်းကို KBZPay သို့မဟုတ် WavePay ရွေးပါ။")
    image_bytes = await file.read()
    validate_image_upload(file, image_bytes)

    file_hash = "TOPUP_" + hashlib.sha256(image_bytes).hexdigest()[:32]
    topup_id, err = create_wallet_topup_request(user_id, amount, payment_method, file_hash)
    if err or not topup_id:
        raise HTTPException(
            status_code=400,
            detail="ဒီ Receipt ပုံကို အရင်က တင်ပြီးသား ဖြစ်နေပါတယ်။ ငွေလွှဲပြီးသား screenshot အသစ်ကို တင်ပါ။",
        )

    if bot:
        markup = telebot.types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            telebot.types.InlineKeyboardButton("✅ Approve Top-up", callback_data=f"topup_approve_{topup_id}"),
            telebot.types.InlineKeyboardButton("❌ Reject Top-up", callback_data=f"topup_reject_{topup_id}"),
        )
        caption = (
            f"💳 <b>Mobile App Wallet Top-Up Request</b>\n\n"
            f"👤 User ID: <code>{user_id}</code>\n"
            f"💰 Amount: <b>{amount:,.0f} MMK</b>\n"
            f"🏦 Method: <b>{html.escape(payment_method)}</b>\n"
            f"🆔 Topup ID: <code>{topup_id}</code>"
        )
        for admin_id in get_all_admin_ids():
            try:
                bot.send_photo(admin_id, image_bytes, caption=caption, reply_markup=markup)
            except Exception:
                pass

    return {"ok": True, "topup_id": topup_id, "message": "Top-Up Receipt ကို Admin ဆီ ပို့ပြီးပါပြီ။ အတည်ပြုပြီးရင် အသိပေးပါမယ်။"}


@app.post("/api/support/ticket")
def api_create_ticket(req: SupportTicketRequest, user_id: int = Depends(get_current_user)):
    ticket_id = create_support_ticket(req.order_id, user_id, req.issue_text)
    if bot:
        for admin_id in get_all_admin_ids():
            try:
                bot.send_message(
                    admin_id,
                    f"🆘 <b>New App Support Ticket #{ticket_id}</b>\n"
                    f"👤 User ID: <code>{user_id}</code>\n"
                    f"🧾 Order ID: <code>{req.order_id}</code>\n"
                    f"📝 Issue: {html.escape(req.issue_text)}",
                )
            except Exception:
                pass
    return {"ok": True, "ticket_id": ticket_id}