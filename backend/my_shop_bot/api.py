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
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Header
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
        conn.commit()


init_app_auth_tables()


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

        if req.telegram_user_id:
            # Check if this telegram_user_id is already linked
            linked = cur.execute(
                "SELECT 1 FROM app_accounts WHERE user_id = ?", (int(req.telegram_user_id),)
            ).fetchone()
            new_user_id = int(req.telegram_user_id) if not linked else None
        else:
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
        raise HTTPException(status_code=400, detail=res.get("reason", "Could not create order"))

    order_id = int(res["order_id"])
    total_amount = float(res["total_amount"])
    mmk_per_usd = get_mmk_per_usd()
    res["total_usd"] = round(total_amount / mmk_per_usd, 2) if mmk_per_usd else 0

    # If user pays with Wallet Balance, deduct immediately and auto-deliver!
    if req.payment_method.upper() == "WALLET" or res.get("fully_discounted"):
        if total_amount > 0:
            ok, new_bal = adjust_user_wallet_balance(user_id, -total_amount)
            if not ok:
                raise HTTPException(status_code=400, detail=f"Insufficient wallet balance ({new_bal:,.0f} MMK)")
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
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded screenshot is empty")

    file_hash = "APP_" + hashlib.sha256(image_bytes).hexdigest()[:32]
    status = submit_payment_proof(order_id, user_id, file_unique_id=file_hash)
    if status != "submitted":
        raise HTTPException(status_code=400, detail=f"Cannot submit receipt: {status}")

    order = get_order_details(order_id)
    item_name = order[2] if order else "Product"
    qty = order[3] if order else 1
    method = order[4] if order else "App"
    order_code = order[8] if order and len(order) > 8 else f"ORD-{order_id}"
    amount = order[12] if order and len(order) > 12 and order[12] is not None else 0

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
            f"📦 Product: <b>{html.escape(str(item_name))}</b> (x{qty})\n"
            f"💳 Method: <b>{html.escape(str(method))}</b>\n"
            f"💰 Total: <b>{float(amount):,.0f} MMK</b>\n"
            f"🧾 Order ID: <code>{html.escape(str(order_code))}</code>"
        )
        for admin_id in get_all_admin_ids():
            try:
                bot.send_photo(admin_id, image_bytes, caption=caption, reply_markup=markup)
            except Exception as e:
                print(f"Failed sending receipt to admin {admin_id}: {e}")

    return {"ok": True, "message": "Receipt uploaded! Admin will approve your order shortly."}


@app.post("/api/orders/verify-crypto")
def api_verify_crypto(req: CryptoVerifyRequest, user_id: int = Depends(get_current_user)):
    order = get_order_details(req.order_id)
    if not order or int(order[1]) != int(user_id):
        raise HTTPException(status_code=404, detail="Order not found")

    order_code = str(order[8] or f"ORD-{req.order_id}")
    total_mmk = float(order[12] or 0)
    mmk_per_usd = get_mmk_per_usd()
    expected_usd = round(total_mmk / mmk_per_usd, 2) if mmk_per_usd else 1.0

    net = req.network.strip().lower()
    if net == "binance":
        check = verify_binance_pay_transaction(order_code, expected_usd, req.tx_hash_or_note)
    else:
        check = verify_evm_usdt_transaction(req.tx_hash_or_note, expected_usd, network=net)

    if not check.get("ok"):
        raise HTTPException(status_code=400, detail=check.get("reason", "Verification failed"))

    tx_id = check["tx_id"]
    sub_status = submit_payment_proof(req.order_id, user_id, file_unique_id=tx_id)
    if sub_status not in ("submitted", "already_submitted"):
        raise HTTPException(status_code=400, detail=f"Order state error: {sub_status}")

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
    raw_orders = get_user_orders(user_id)
    orders_out = []
    for o in raw_orders:
        outline_key_id = o[13] if len(o) > 13 else None
        usage = None
        if outline_key_id:
            u_res = get_key_data_usage(outline_key_id, o[2])
            if u_res.get("ok"):
                usage = u_res
        orders_out.append({
            "order_id": o[0],
            "item_name": o[2],
            "quantity": o[3],
            "payment_method": o[4],
            "status": o[5],
            "timestamp": o[6],
            "delivered_data": o[7] or "",
            "order_code": o[8] or f"ORD-{o[0]}",
            "expiry_date": o[9] or "Lifetime / Non-expiring",
            "total_amount": float(o[12] or 0) if len(o) > 12 else 0,
            "outline_key_id": outline_key_id,
            "outline_usage": usage,
        })
    return {"profile": profile, "orders": orders_out}


@app.post("/api/wallet/checkin")
def api_daily_checkin(user_id: int = Depends(get_current_user)):
    res = claim_daily_checkin(user_id)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail="You have already checked in today! Come back tomorrow.")
    return res


@app.post("/api/wallet/redeem")
def api_redeem_points(user_id: int = Depends(get_current_user)):
    res = redeem_points_to_wallet(user_id, points_needed=500, mmk_reward=1000)
    if not res.get("ok"):
        raise HTTPException(status_code=400, detail=f"Need 500 points to redeem 1,000 MMK (Current: {res.get('points', 0)} pts)")
    return res


@app.post("/api/wallet/topup")
async def api_wallet_topup(
    amount: float,
    payment_method: str = "KPay",
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user),
):
    if amount < 1000:
        raise HTTPException(status_code=400, detail="Minimum top-up amount is 1,000 MMK")
    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Empty receipt image")

    file_hash = "TOPUP_" + hashlib.sha256(image_bytes).hexdigest()[:32]
    topup_id, err = create_wallet_topup_request(user_id, amount, payment_method, file_hash)
    if err or not topup_id:
        raise HTTPException(status_code=400, detail="Duplicate receipt or invalid top-up request")

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

    return {"ok": True, "topup_id": topup_id, "message": "Top-up receipt submitted to Admin!"}


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
