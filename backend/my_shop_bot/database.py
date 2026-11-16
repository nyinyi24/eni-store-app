import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import secrets
import string
import re
from config import DATABASE_NAME, ADMIN_ID

YANGON_TZ = ZoneInfo("Asia/Yangon")
SQLITE_BUSY_TIMEOUT_MS = 30_000


def get_db_connection(database_name=DATABASE_NAME, timeout=30, **kwargs):
    """Open a SQLite connection configured for concurrent bot activity."""
    conn = sqlite3.connect(database_name, timeout=timeout, **kwargs)
    conn.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def yangon_now():
    return datetime.now(YANGON_TZ).replace(tzinfo=None)

def init_db():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # WAL lets readers continue while a short write transaction is active.
        cursor.execute("PRAGMA journal_mode = WAL")
        cursor.execute("PRAGMA synchronous = NORMAL")
        
        # 1. Users Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS users 
            (user_id INTEGER PRIMARY KEY, join_date TEXT, role TEXT DEFAULT 'user')''')
        ensure_user_profile_columns(cursor)
        
        # 2. Items Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS items 
            (item_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, details TEXT, price REAL, stock INTEGER, type TEXT)''')
        ensure_item_language_columns(cursor)
        ensure_item_custom_emoji_column(cursor)
        
        # 3. Item Stocks Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS item_stocks 
            (stock_id INTEGER PRIMARY KEY AUTOINCREMENT, item_name TEXT, account_info TEXT, is_sold BOOLEAN DEFAULT FALSE)''')
        
        # 4. Orders Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS orders 
            (order_id INTEGER PRIMARY KEY AUTOINCREMENT, 
             user_id INTEGER, 
             item_name TEXT, 
             quantity INTEGER, 
             payment_method TEXT, 
             status TEXT, 
             timestamp TEXT,
             delivered_data TEXT,
             order_code TEXT UNIQUE,
             expiry_date TEXT,
             renewal_notice_sent INTEGER DEFAULT 0,
             expiry_admin_notice_sent INTEGER DEFAULT 0,
             sell_proof_status INTEGER DEFAULT 0)''')
        ensure_order_code_column(cursor)
        ensure_order_renewal_columns(cursor)
        ensure_order_amount_column(cursor)
        ensure_order_sell_proof_column(cursor)
        ensure_order_outline_columns(cursor)
        ensure_order_target_username_column(cursor)
        backfill_missing_order_expiry_dates(cursor)
        normalize_order_expiry_dates(cursor)
        
        # 5. Giveaway Tables
        cursor.execute('''CREATE TABLE IF NOT EXISTS gw_items 
            (gw_item_id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, content TEXT, stock INTEGER DEFAULT 0, is_used BOOLEAN DEFAULT FALSE)''')
        ensure_gw_items_columns(cursor)
            
        cursor.execute('''CREATE TABLE IF NOT EXISTS gw_claims 
            (claim_id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, claim_date TEXT)''')

        # 6. Settings Table
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings 
            (key TEXT PRIMARY KEY, value TEXT)''')
        
        # Default settings
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('shop_status', 'open')")

        # Single-use coupons.  A coupon sent to one user is locked to that
        # account; public coupons are claimed atomically by the first user.
        cursor.execute('''CREATE TABLE IF NOT EXISTS coupons
            (coupon_id INTEGER PRIMARY KEY AUTOINCREMENT,
             code TEXT NOT NULL UNIQUE,
             discount_type TEXT NOT NULL CHECK(discount_type IN ('percent', 'fixed')),
             discount_value REAL NOT NULL,
             expires_at TEXT NOT NULL,
             status TEXT NOT NULL DEFAULT 'active',
             assigned_user_id INTEGER,
             reserved_order_id INTEGER,
             used_by_user_id INTEGER,
             used_order_id INTEGER,
             created_at TEXT NOT NULL,
             sent_at TEXT,
             used_at TEXT)''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_coupons_status ON coupons(status, expires_at)")
        ensure_coupon_reservation_column(cursor)

        # Promotion gifts are separate from normal products.  A gift may have
        # auto-delivery stock, but it can always be completed manually by admin.
        cursor.execute('''CREATE TABLE IF NOT EXISTS promotion_gifts
            (gift_id INTEGER PRIMARY KEY AUTOINCREMENT,
             name TEXT NOT NULL,
             details TEXT DEFAULT '',
             is_active INTEGER NOT NULL DEFAULT 1,
             created_at TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS promotion_gift_stock
            (gift_stock_id INTEGER PRIMARY KEY AUTOINCREMENT,
             gift_id INTEGER NOT NULL,
             content TEXT NOT NULL,
             is_used INTEGER NOT NULL DEFAULT 0,
             used_at TEXT)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS promotion_claims
            (claim_id INTEGER PRIMARY KEY AUTOINCREMENT,
             order_id INTEGER NOT NULL UNIQUE,
             user_id INTEGER NOT NULL,
             gift_id INTEGER,
             status TEXT NOT NULL,
             selected_at TEXT NOT NULL,
             delivered_at TEXT,
             delivered_by INTEGER,
             delivery_data TEXT)''')
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_promotion_claims_status ON promotion_claims(status)")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('promotion_status', 'off')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('promotion_start_at', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('promotion_end_at', '')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('promotion_minimum_amount', '10000')")

        # 7. Referral Program Tables
        cursor.execute('''CREATE TABLE IF NOT EXISTS referrals
            (referral_id INTEGER PRIMARY KEY AUTOINCREMENT,
             referrer_id INTEGER NOT NULL,
             referred_user_id INTEGER NOT NULL UNIQUE,
             status TEXT DEFAULT 'pending',
             created_at TEXT,
             verified_at TEXT)''')

        cursor.execute('''CREATE TABLE IF NOT EXISTS referral_rewards
            (reward_id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL,
             status TEXT DEFAULT 'pending',
             created_at TEXT,
             reviewed_at TEXT,
             admin_note TEXT)''')

        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_status', 'open')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_required_count', '10')")
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('referral_reward_text', '10,000 MMK တန် product 1 ခု')")
        repair_duration_parser_v2_expiry_dates(cursor)

        # 8. Extra Admin Users
        cursor.execute('''CREATE TABLE IF NOT EXISTS admin_users
            (user_id INTEGER PRIMARY KEY,
             added_at TEXT,
             added_by INTEGER)''')

        # 9. Time-limited Product Discounts
        cursor.execute('''CREATE TABLE IF NOT EXISTS product_discounts
            (item_id INTEGER PRIMARY KEY,
             original_price REAL NOT NULL,
             discounted_price REAL NOT NULL,
             discount_percent REAL NOT NULL,
             starts_at TEXT NOT NULL,
             ends_at TEXT NOT NULL,
             status TEXT NOT NULL DEFAULT 'active',
             created_by INTEGER)''')

        # 10. Temporary stock reservations created before payment review
        cursor.execute('''CREATE TABLE IF NOT EXISTS stock_reservations
            (reservation_id INTEGER PRIMARY KEY AUTOINCREMENT,
             order_id INTEGER NOT NULL UNIQUE,
             user_id INTEGER NOT NULL,
             item_id INTEGER NOT NULL,
             item_name TEXT NOT NULL,
             quantity INTEGER NOT NULL,
             status TEXT NOT NULL DEFAULT 'active',
             created_at TEXT NOT NULL,
             expires_at TEXT,
             submitted_at TEXT,
             released_at TEXT,
             completed_at TEXT)''')
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_stock_reservations_item_status "
            "ON stock_reservations(item_id, status)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_stock_reservations_user_status "
            "ON stock_reservations(user_id, status)"
        )

        # 11. One payment proof per order and one-time screenshot fingerprints
        cursor.execute('''CREATE TABLE IF NOT EXISTS payment_submissions
            (submission_id INTEGER PRIMARY KEY AUTOINCREMENT,
             order_id INTEGER NOT NULL UNIQUE,
             user_id INTEGER NOT NULL,
             file_unique_id TEXT NOT NULL UNIQUE,
             telegram_file_id TEXT,
             status TEXT NOT NULL DEFAULT 'pending',
             submitted_at TEXT NOT NULL,
             processed_at TEXT,
             processed_by INTEGER)''')
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_payment_submissions_status "
            "ON payment_submissions(status)"
        )

        conn.commit()

# --- Settings Functions ---

def get_shop_status():
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = 'shop_status'")
            result = cursor.fetchone()
            return result[0] if result else 'open'
    except:
        return 'open'

def set_shop_status(status):
    """ဆိုင်ရဲ့ status ကို update လုပ်ရန် (Fix: config import ကို ဖယ်ရှားထားသည်)"""
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE settings SET value = ? WHERE key = 'shop_status'", (status,))
            conn.commit()
    except Exception as e:
        print(f"Error setting shop status: {e}")

def get_setting(key, default=None):
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
            result = cursor.fetchone()
            return result[0] if result else default
    except Exception as e:
        print(f"Error getting setting {key}: {e}")
        return default

def set_setting(key, value):
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value))
            )
            conn.commit()
    except Exception as e:
        print(f"Error setting {key}: {e}")

# --- Promotion Gifts ---

def get_promotion_config():
    return {
        "status": get_setting("promotion_status", "off"),
        "start_at": get_setting("promotion_start_at", ""),
        "end_at": get_setting("promotion_end_at", ""),
        "minimum_amount": float(get_setting("promotion_minimum_amount", "10000") or 10000),
    }

def set_promotion_config(status=None, start_at=None, end_at=None, minimum_amount=None):
    values = {
        "promotion_status": status,
        "promotion_start_at": start_at,
        "promotion_end_at": end_at,
        "promotion_minimum_amount": minimum_amount,
    }
    for key, value in values.items():
        if value is not None:
            set_setting(key, value)

def add_promotion_gift(name, details=""):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO promotion_gifts (name, details, created_at) VALUES (?, ?, ?)",
            (name.strip(), details.strip(), yangon_now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        return cursor.lastrowid

def get_promotion_gifts(active_only=False):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        query = "SELECT gift_id, name, details, is_active FROM promotion_gifts"
        if active_only:
            query += " WHERE is_active = 1"
        cursor.execute(query + " ORDER BY gift_id ASC")
        return cursor.fetchall()

def set_promotion_gift_active(gift_id, is_active):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE promotion_gifts SET is_active = ? WHERE gift_id = ?", (int(bool(is_active)), gift_id))
        return cursor.rowcount > 0

def add_promotion_gift_stock(gift_id, contents):
    rows = [(gift_id, str(content).strip()) for content in contents if str(content).strip()]
    if not rows:
        return 0
    with get_db_connection(DATABASE_NAME) as conn:
        conn.executemany("INSERT INTO promotion_gift_stock (gift_id, content) VALUES (?, ?)", rows)
    return len(rows)

def get_promotion_gift_stock_count(gift_id):
    with get_db_connection(DATABASE_NAME) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM promotion_gift_stock WHERE gift_id = ? AND is_used = 0", (gift_id,)
        ).fetchone()[0]

def get_promotion_claim(order_id):
    with get_db_connection(DATABASE_NAME) as conn:
        return conn.execute(
            "SELECT claim_id, order_id, user_id, gift_id, status, selected_at, delivered_at, delivered_by, delivery_data "
            "FROM promotion_claims WHERE order_id = ?", (order_id,)
        ).fetchone()

def is_order_promotion_eligible(order_id):
    config = get_promotion_config()
    if config["status"] != "on":
        return False
    now = yangon_now()
    try:
        start = datetime.strptime(config["start_at"], "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(config["end_at"], "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return False
    if not start <= now <= end:
        return False
    with get_db_connection(DATABASE_NAME) as conn:
        row = conn.execute("SELECT total_amount, item_name FROM orders WHERE order_id = ?", (order_id,)).fetchone()
    if not row or is_gift_card_product(row[1]):
        return False
    return bool(float(row[0] or 0) >= config["minimum_amount"])

def create_promotion_claim(order_id, user_id, gift_id=None, status="selected"):
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        existing = cursor.execute(
            "SELECT claim_id, user_id, status FROM promotion_claims WHERE order_id = ?", (order_id,)
        ).fetchone()
        if existing:
            claim_id, existing_user_id, existing_status = existing
            if int(existing_user_id) != int(user_id) or existing_status != "offered":
                conn.rollback()
                return None
            cursor.execute(
                "UPDATE promotion_claims SET gift_id = ?, status = ?, selected_at = ? WHERE claim_id = ?",
                (gift_id, status, now, claim_id),
            )
            return claim_id
        cursor.execute(
            "INSERT INTO promotion_claims (order_id, user_id, gift_id, status, selected_at) VALUES (?, ?, ?, ?, ?)",
            (order_id, user_id, gift_id, status, now),
        )
        return cursor.lastrowid

def claim_promotion_gift_stock(claim_id, gift_id):
    """Reserve one auto-delivery gift atomically; returns its content or None."""
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        stock = cursor.execute(
            "SELECT gift_stock_id, content FROM promotion_gift_stock WHERE gift_id = ? AND is_used = 0 ORDER BY gift_stock_id LIMIT 1",
            (gift_id,),
        ).fetchone()
        if not stock:
            cursor.execute("UPDATE promotion_claims SET status = 'manual_pending' WHERE claim_id = ?", (claim_id,))
            return None
        cursor.execute("UPDATE promotion_gift_stock SET is_used = 1, used_at = ? WHERE gift_stock_id = ?", (now, stock[0]))
        cursor.execute(
            "UPDATE promotion_claims SET status = 'auto_delivered', delivered_at = ?, delivery_data = ? WHERE claim_id = ?",
            (now, stock[1], claim_id),
        )
        return stock[1]

def complete_promotion_manual_claim(claim_id, admin_id, delivery_data):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE promotion_claims SET status = 'manual_delivered', delivered_at = ?, delivered_by = ?, delivery_data = ? "
            "WHERE claim_id = ? AND status = 'manual_pending'",
            (yangon_now().strftime("%Y-%m-%d %H:%M:%S"), admin_id, delivery_data, claim_id),
        )
        return cursor.rowcount > 0

def get_pending_promotion_claims(limit=30):
    with get_db_connection(DATABASE_NAME) as conn:
        return conn.execute(
            "SELECT c.claim_id, c.order_id, c.user_id, g.name, g.details, c.selected_at "
            "FROM promotion_claims c JOIN promotion_gifts g ON g.gift_id = c.gift_id "
            "WHERE c.status = 'manual_pending' ORDER BY c.selected_at ASC LIMIT ?", (limit,)
        ).fetchall()

# --- Admin Users Functions ---

def is_admin_user(user_id):
    if str(user_id) == str(ADMIN_ID):
        return True
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM admin_users WHERE user_id = ? LIMIT 1", (int(user_id),))
            return cursor.fetchone() is not None
    except Exception as e:
        print(f"Error checking admin user {user_id}: {e}")
        return False

def is_master_admin(user_id):
    return str(user_id) == str(ADMIN_ID)

def add_admin_user(user_id, added_by=None):
    user_id = int(user_id)
    if str(user_id) == str(ADMIN_ID):
        return False, "master"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO admin_users (user_id, added_at, added_by) VALUES (?, ?, ?)",
            (user_id, now, added_by)
        )
        cursor.execute("UPDATE users SET role = 'admin' WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0, "added"

def remove_admin_user(user_id):
    user_id = int(user_id)
    if str(user_id) == str(ADMIN_ID):
        return False, "master"
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admin_users WHERE user_id = ?", (user_id,))
        cursor.execute("UPDATE users SET role = 'user' WHERE user_id = ?", (user_id,))
        conn.commit()
        return cursor.rowcount > 0, "removed"

def get_admin_users():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT user_id, added_at, added_by
            FROM admin_users
            ORDER BY added_at DESC
        """)
        return cursor.fetchall()

def get_all_admin_ids():
    admin_ids = [int(ADMIN_ID)] if ADMIN_ID else []
    for user_id, _, _ in get_admin_users():
        if int(user_id) not in admin_ids:
            admin_ids.append(int(user_id))
    return admin_ids

# --- Items Functions ---

def ensure_item_language_columns(cursor):
    cursor.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]
    for column_name in ("details_en", "type_en"):
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE items ADD COLUMN {column_name} TEXT")
    if "renewable" not in columns:
        cursor.execute("ALTER TABLE items ADD COLUMN renewable INTEGER DEFAULT 0")
        cursor.execute(
            """
            UPDATE items
            SET renewable = 1
            WHERE LOWER(COALESCE(name, '')) LIKE '%outline%'
              AND LOWER(COALESCE(name, '')) LIKE '%vpn%'
            """
        )

def ensure_item_custom_emoji_column(cursor):
    cursor.execute("PRAGMA table_info(items)")
    columns = [row[1] for row in cursor.fetchall()]
    if "custom_emoji_id" not in columns:
        cursor.execute("ALTER TABLE items ADD COLUMN custom_emoji_id TEXT")

def set_product_custom_emoji(item_id, custom_emoji_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE items SET custom_emoji_id = ? WHERE item_id = ?",
            (custom_emoji_id or None, item_id),
        )
        return cursor.rowcount > 0

def get_product_custom_emoji(item_id):
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            row = conn.execute(
                "SELECT custom_emoji_id FROM items WHERE item_id = ?", (item_id,)
            ).fetchone()
            return row[0] if row and row[0] else ""
    except Exception as error:
        print(f"Product custom emoji lookup failed: {error}")
        return ""

def get_all_items():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM items")
        return cursor.fetchall()

def get_item_by_id(item_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM items WHERE item_id = ?", (item_id,))
        return cursor.fetchone()

def get_item_by_name(item_name):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM items WHERE TRIM(name) = TRIM(?) COLLATE NOCASE LIMIT 1",
            (item_name,)
        )
        return cursor.fetchone()

def set_product_renewable(item_id, enabled):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE items SET renewable = ? WHERE item_id = ?",
            (1 if enabled else 0, item_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def is_item_renewable(item_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(renewable, 0) FROM items WHERE item_id = ?", (item_id,))
        row = cursor.fetchone()
        return bool(row and int(row[0] or 0))

def is_product_renewable_by_name(item_name):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(renewable, 0)
            FROM items
            WHERE TRIM(name) = TRIM(?) COLLATE NOCASE
            LIMIT 1
            """,
            (item_name,)
        )
        row = cursor.fetchone()
        return bool(row and int(row[0] or 0))

def get_product_removal_preview(item_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT item_id, name, price, stock FROM items WHERE item_id = ?",
            (item_id,)
        )
        item = cursor.fetchone()
        if not item:
            return None

        item_id, item_name, price, stock = item
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM item_stocks
            WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE
              AND COALESCE(is_sold, 0) = 0
            """,
            (item_name,)
        )
        unsold_accounts = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM orders
            WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE
              AND status = 'Success'
            """,
            (item_name,)
        )
        completed_orders = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            """
            SELECT COUNT(*)
            FROM orders AS o
            LEFT JOIN stock_reservations AS r ON r.order_id = o.order_id
            WHERE TRIM(o.item_name) = TRIM(?) COLLATE NOCASE
              AND (
                    r.status IN ('active', 'awaiting_review', 'processing', 'partial')
                    OR (
                        r.order_id IS NULL
                        AND o.status IN ('Pending', 'Payment Submitted', 'Partial')
                    )
              )
            """,
            (item_name,)
        )
        active_orders = int(cursor.fetchone()[0] or 0)
        cursor.execute(
            "SELECT COUNT(*) FROM items WHERE TRIM(name) = TRIM(?) COLLATE NOCASE",
            (item_name,)
        )
        same_name_products = int(cursor.fetchone()[0] or 0)
        return {
            "item_id": item_id,
            "name": item_name,
            "price": float(price or 0),
            "stock": int(stock or 0),
            "unsold_accounts": unsold_accounts,
            "completed_orders": completed_orders,
            "active_orders": active_orders,
            "same_name_products": same_name_products,
        }

def remove_product(item_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT name FROM items WHERE item_id = ?",
            (item_id,)
        )
        item = cursor.fetchone()
        if not item:
            conn.rollback()
            return {"ok": False, "reason": "not_found"}

        item_name = item[0]
        cursor.execute(
            "SELECT COUNT(*) FROM items WHERE TRIM(name) = TRIM(?) COLLATE NOCASE",
            (item_name,)
        )
        if int(cursor.fetchone()[0] or 0) > 1:
            conn.rollback()
            return {"ok": False, "reason": "duplicate_name", "name": item_name}

        cursor.execute(
            """
            SELECT COUNT(*)
            FROM orders AS o
            LEFT JOIN stock_reservations AS r ON r.order_id = o.order_id
            WHERE TRIM(o.item_name) = TRIM(?) COLLATE NOCASE
              AND (
                    r.status IN ('active', 'awaiting_review', 'processing', 'partial')
                    OR (
                        r.order_id IS NULL
                        AND o.status IN ('Pending', 'Payment Submitted', 'Partial')
                    )
              )
            """,
            (item_name,)
        )
        active_orders = int(cursor.fetchone()[0] or 0)
        if active_orders:
            conn.rollback()
            return {
                "ok": False,
                "reason": "active_orders",
                "name": item_name,
                "active_orders": active_orders,
            }

        cursor.execute(
            "DELETE FROM product_discounts WHERE item_id = ?",
            (item_id,)
        )
        cursor.execute(
            "DELETE FROM item_stocks WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE",
            (item_name,)
        )
        removed_stock_rows = cursor.rowcount
        cursor.execute("DELETE FROM items WHERE item_id = ?", (item_id,))
        if cursor.rowcount != 1:
            conn.rollback()
            return {"ok": False, "reason": "not_found"}
        conn.commit()
        return {
            "ok": True,
            "name": item_name,
            "removed_stock_rows": int(removed_stock_rows or 0),
        }

def add_product(name, details, price, stock, product_info, details_en=None, product_info_en=None):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO items (name, details, price, stock, type, details_en, type_en)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (name, details, price, stock, product_info, details_en, product_info_en)
        )
        conn.commit()
        return cursor.lastrowid

def update_product(item_id, name=None, details=None, price=None, stock=None, product_info=None, details_en=None, product_info_en=None):
    fields = []
    values = []
    field_map = {
        "name": name,
        "details": details,
        "stock": stock,
        "type": product_info,
        "details_en": details_en,
        "type_en": product_info_en,
    }
    for field, value in field_map.items():
        if value is not None:
            fields.append(f"{field} = ?")
            values.append(value)

    active_discount = None
    if price is not None:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT discount_percent FROM product_discounts WHERE item_id = ? AND status = 'active'",
                (item_id,)
            )
            active_discount = cursor.fetchone()
        if active_discount:
            discounted_price = round(float(price) * (1 - float(active_discount[0]) / 100), 2)
            fields.append("price = ?")
            values.append(discounted_price)
        else:
            fields.append("price = ?")
            values.append(price)

    if not fields:
        return False

    values.append(item_id)
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(f"UPDATE items SET {', '.join(fields)} WHERE item_id = ?", values)
        updated = cursor.rowcount > 0
        if price is not None and active_discount:
            cursor.execute(
                """
                UPDATE product_discounts
                SET original_price = ?, discounted_price = ?
                WHERE item_id = ? AND status = 'active'
                """,
                (float(price), discounted_price, item_id)
            )
        conn.commit()
        return updated

def set_product_discount(item_id, discount_percent, duration_seconds, created_by=None, sale_price=None):
    now = yangon_now()
    ends_at = now + timedelta(seconds=int(duration_seconds))
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute("SELECT name, price FROM items WHERE item_id = ?", (item_id,))
        item = cursor.fetchone()
        if not item:
            return None

        cursor.execute(
            "SELECT original_price FROM product_discounts WHERE item_id = ? AND status = 'active'",
            (item_id,)
        )
        current_discount = cursor.fetchone()
        original_price = float(current_discount[0]) if current_discount else float(item[1])
        if sale_price is not None:
            discounted_price = round(float(sale_price), 2)
            if not 0 < discounted_price < original_price:
                raise ValueError("Sale price must be greater than zero and lower than the original price.")
            discount_percent = round((original_price - discounted_price) / original_price * 100, 2)
        else:
            if not 0 < float(discount_percent) < 100:
                raise ValueError("Discount percent must be between zero and 100.")
            discounted_price = round(original_price * (1 - float(discount_percent) / 100), 2)

        cursor.execute("UPDATE items SET price = ? WHERE item_id = ?", (discounted_price, item_id))
        cursor.execute(
            """
            INSERT INTO product_discounts
                (item_id, original_price, discounted_price, discount_percent,
                 starts_at, ends_at, status, created_by)
            VALUES (?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(item_id) DO UPDATE SET
                original_price = excluded.original_price,
                discounted_price = excluded.discounted_price,
                discount_percent = excluded.discount_percent,
                starts_at = excluded.starts_at,
                ends_at = excluded.ends_at,
                status = 'active',
                created_by = excluded.created_by
            """,
            (
                item_id, original_price, discounted_price, float(discount_percent),
                now.strftime("%Y-%m-%d %H:%M:%S"),
                ends_at.strftime("%Y-%m-%d %H:%M:%S"), created_by
            )
        )
        conn.commit()
        return {
            "item_id": int(item_id), "name": item[0], "original_price": original_price,
            "discounted_price": discounted_price, "discount_percent": float(discount_percent),
            "starts_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "ends_at": ends_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

def get_active_discounts():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT d.item_id, i.name, d.original_price, d.discounted_price,
                   d.discount_percent, d.starts_at, d.ends_at
            FROM product_discounts d
            JOIN items i ON i.item_id = d.item_id
            WHERE d.status = 'active'
            ORDER BY d.ends_at ASC
            """
        )
        return cursor.fetchall()

def cancel_product_discount(item_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT original_price FROM product_discounts WHERE item_id = ? AND status = 'active'",
            (item_id,)
        )
        row = cursor.fetchone()
        if not row:
            return False
        cursor.execute("UPDATE items SET price = ? WHERE item_id = ?", (row[0], item_id))
        cursor.execute("UPDATE product_discounts SET status = 'cancelled' WHERE item_id = ?", (item_id,))
        conn.commit()
        return True

def expire_product_discounts(now=None):
    check_text = (now or yangon_now()).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            SELECT d.item_id, i.name, d.original_price
            FROM product_discounts d
            JOIN items i ON i.item_id = d.item_id
            WHERE d.status = 'active' AND d.ends_at <= ?
            """,
            (check_text,)
        )
        expired = cursor.fetchall()
        for item_id, _, original_price in expired:
            cursor.execute("UPDATE items SET price = ? WHERE item_id = ?", (original_price, item_id))
            cursor.execute("UPDATE product_discounts SET status = 'expired' WHERE item_id = ?", (item_id,))
        conn.commit()
        return expired

def set_product_stock(item_id, stock):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE items SET stock = ? WHERE item_id = ?", (stock, item_id))
        conn.commit()
        return cursor.rowcount > 0

def add_item_stock_accounts(item_name, account_infos):
    clean_accounts = [account.strip() for account in account_infos if account.strip()]
    if not clean_accounts:
        return 0

    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        existing = {
            str(row[0]).strip()
            for row in cursor.execute(
                "SELECT account_info FROM item_stocks WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE",
                (item_name,),
            ).fetchall()
        }
        unique_new = []
        for acc in clean_accounts:
            if acc not in existing and acc not in unique_new:
                unique_new.append(acc)
        if not unique_new:
            return 0
        cursor.executemany(
            "INSERT INTO item_stocks (item_name, account_info) VALUES (?, ?)",
            [(item_name, account) for account in unique_new]
        )
        cursor.execute(
            "UPDATE items SET stock = stock + ? WHERE TRIM(name) = TRIM(?) COLLATE NOCASE",
            (len(unique_new), item_name)
        )
        conn.commit()
        return len(unique_new)

# --- Stocks Functions ---

def reduce_item_stock_manual(item_name, quantity=1):
    """[ADDED] Manual စနစ်အတွက် Admin က Approve လုပ်ချိန်တွင် Stock တိုက်ရိုက်လျှော့ပေးရန် function"""
    try:
        with get_db_connection(DATABASE_NAME, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE items 
                SET stock = MAX(0, stock - ?) 
                WHERE TRIM(name) = TRIM(?) COLLATE NOCASE
            """, (quantity, item_name))
            conn.commit()
            return True
    except Exception as e:
        print(f"Error reducing manual stock: {e}")
        return False

def pull_account_from_stock_by_name(item_name):
    with get_db_connection(DATABASE_NAME, check_same_thread=False, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stock_id, account_info FROM item_stocks 
            WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE 
            AND is_sold = 0 LIMIT 1
        """, (item_name,))
        res = cursor.fetchone()
        if res:
            stock_id, acc_info = res[0], res[1]
            cursor.execute("UPDATE item_stocks SET is_sold = 1 WHERE stock_id = ?", (stock_id,))
            cursor.execute("UPDATE items SET stock = stock - 1 WHERE name = ? COLLATE NOCASE", (item_name,))
            conn.commit()
            return acc_info
        return None

def pull_accounts_from_stock_by_name(item_name, quantity):
    quantity = max(1, int(quantity))
    with get_db_connection(DATABASE_NAME, check_same_thread=False, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT stock_id, account_info FROM item_stocks
            WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE
              AND is_sold = 0
            ORDER BY stock_id ASC
            LIMIT ?
        """, (item_name, quantity))
        rows = cursor.fetchall()
        if not rows:
            return []

        stock_ids = [row[0] for row in rows]
        account_infos = [row[1] for row in rows]
        placeholders = ",".join("?" for _ in stock_ids)
        cursor.execute(f"UPDATE item_stocks SET is_sold = 1 WHERE stock_id IN ({placeholders})", stock_ids)
        cursor.execute(
            "UPDATE items SET stock = MAX(0, stock - ?) WHERE TRIM(name) = TRIM(?) COLLATE NOCASE",
            (len(account_infos), item_name)
        )
        conn.commit()
        return account_infos

# --- User Functions ---

def ensure_user_profile_columns(cursor):
    cursor.execute("PRAGMA table_info(users)")
    columns = [row[1] for row in cursor.fetchall()]
    for column_name in (
        "username", "first_name", "last_name", "language",
        "last_active", "last_action"
    ):
        if column_name not in columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {column_name} TEXT")
    if "is_active" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")

def record_user_activity(
    user_id,
    action,
    username=None,
    first_name=None,
    last_name=None,
):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    safe_action = str(action or "unknown")[:120]
    try:
        with get_db_connection(DATABASE_NAME, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)",
                (int(user_id), now_text)
            )
            cursor.execute(
                """
                UPDATE users
                SET username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    last_name = COALESCE(?, last_name),
                    last_active = ?,
                    last_action = ?,
                    is_active = 1
                WHERE user_id = ?
                """,
                (
                    username, first_name, last_name, now_text,
                    safe_action, int(user_id)
                )
            )
            conn.commit()
            return True
    except Exception as error:
        print(f"Error recording user activity for {user_id}: {error}")
        return False

def get_active_users_for_admin(limit=20):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                user_id,
                COALESCE(username, ''),
                COALESCE(first_name, ''),
                COALESCE(last_name, ''),
                last_active,
                COALESCE(last_action, 'unknown')
            FROM users
            WHERE last_active IS NOT NULL AND TRIM(last_active) != ''
            ORDER BY datetime(last_active) DESC, user_id DESC
            LIMIT ?
            """,
            (max(1, int(limit)),)
        )
        return cursor.fetchall()

def get_user_activity_summary():
    now = yangon_now()
    day_ago = (now - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    month_ago = (now - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                SUM(CASE WHEN datetime(last_active) >= datetime(?) THEN 1 ELSE 0 END),
                SUM(CASE WHEN datetime(last_active) >= datetime(?) THEN 1 ELSE 0 END),
                SUM(CASE WHEN datetime(last_active) >= datetime(?) THEN 1 ELSE 0 END),
                SUM(CASE WHEN last_active IS NOT NULL AND TRIM(last_active) != '' THEN 1 ELSE 0 END)
            FROM users
            """,
            (day_ago, week_ago, month_ago)
        )
        row = cursor.fetchone() or (0, 0, 0, 0)
        return tuple(int(value or 0) for value in row)

def add_user(user_id, join_date=None, username=None, first_name=None, last_name=None):
    """User အသစ်မှတ်ရန် (Fix: join_date မပါလျှင် ယနေ့ရက်စွဲ Auto ထည့်ပေးရန် ပြင်ဆင်ထားသည်)"""
    if join_date is None:
        join_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_connection(DATABASE_NAME, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT OR IGNORE INTO users (user_id, join_date) VALUES (?, ?)", (user_id, join_date))
            inserted = cursor.rowcount > 0
            cursor.execute("""
                UPDATE users
                SET username = COALESCE(?, username),
                    first_name = COALESCE(?, first_name),
                    last_name = COALESCE(?, last_name)
                WHERE user_id = ?
            """, (username, first_name, last_name, user_id))
            conn.commit()
            return inserted
    except sqlite3.OperationalError as e:
        print(f"Database Lock Error while adding user {user_id}: {e}")
    except Exception as e:
        print(f"Error adding user {user_id}: {e}")
    return False

def get_user(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        return cursor.fetchone()

def get_user_language(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT language FROM users WHERE user_id = ?", (user_id,))
        result = cursor.fetchone()
        return result[0] if result and result[0] in ("my", "en") else None

def set_user_language(user_id, language):
    if language not in ("my", "en"):
        language = "my"
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET language = ? WHERE user_id = ?", (language, user_id))
        conn.commit()

def get_user_count():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        return cursor.fetchone()[0]

def get_all_user_ids():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE COALESCE(is_active, 1) = 1")
        return [row[0] for row in cursor.fetchall()]


def generate_coupons(quantity, discount_type, discount_value, valid_days=7):
    quantity = max(1, min(int(quantity), 500))
    if discount_type not in ('percent', 'fixed') or float(discount_value) <= 0:
        raise ValueError('Invalid coupon discount')
    if discount_type == 'percent' and float(discount_value) > 100:
        raise ValueError('Percent discount cannot exceed 100')
    valid_days = max(1, int(valid_days))
    now = yangon_now()
    expiry = (now + timedelta(days=valid_days)).replace(hour=23, minute=59, second=59)
    created_at = now.strftime('%Y-%m-%d %H:%M:%S')
    expires_at = expiry.strftime('%Y-%m-%d %H:%M:%S')
    codes = []
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        for _ in range(quantity):
            code = 'ENI-' + secrets.token_urlsafe(5).replace('-', 'A').replace('_', 'B').upper()[:6]
            while cursor.execute('SELECT 1 FROM coupons WHERE code = ?', (code,)).fetchone():
                code = 'ENI-' + secrets.token_urlsafe(5).replace('-', 'A').replace('_', 'B').upper()[:6]
            cursor.execute('INSERT INTO coupons (code, discount_type, discount_value, expires_at, created_at) VALUES (?, ?, ?, ?, ?)',
                           (code, discount_type, float(discount_value), expires_at, created_at))
            codes.append(code)
    return {'codes': codes, 'expires_at': expires_at}


def assign_coupon_to_user(code, user_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE coupons SET assigned_user_id = ?, sent_at = ? WHERE UPPER(code) = ? AND status = 'active' AND datetime(expires_at) > datetime(?) AND assigned_user_id IS NULL",
                       (int(user_id), yangon_now().strftime('%Y-%m-%d %H:%M:%S'), str(code).upper(), yangon_now().strftime('%Y-%m-%d %H:%M:%S')))
        return cursor.rowcount > 0


def get_coupon_for_user(code, user_id, total_amount):
    now = yangon_now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db_connection(DATABASE_NAME) as conn:
        row = conn.execute("SELECT coupon_id, discount_type, discount_value, assigned_user_id, reserved_order_id FROM coupons WHERE UPPER(code) = ? AND status = 'active' AND datetime(expires_at) > datetime(?)", (str(code).upper(), now)).fetchone()
    if not row:
        return None, 'invalid_or_expired'
    coupon_id, kind, value, assigned, reserved_order_id = row
    if reserved_order_id is not None:
        return None, 'already_reserved'
    if assigned is not None and int(assigned) != int(user_id):
        return None, 'assigned_to_other_user'
    discount = (float(total_amount) * float(value) / 100) if kind == 'percent' else float(value)
    return {'coupon_id': coupon_id, 'code': str(code).upper(), 'discount': min(float(total_amount), discount)}, None


def ensure_coupon_reservation_column(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(coupons)").fetchall()}
    if "reserved_order_id" not in columns:
        cursor.execute("ALTER TABLE coupons ADD COLUMN reserved_order_id INTEGER")


def _release_order_coupon(cursor, order_id):
    cursor.execute(
        "UPDATE coupons SET reserved_order_id = NULL WHERE reserved_order_id = ? AND status = 'active'",
        (int(order_id),),
    )


def _consume_order_coupon(cursor, order_id):
    cursor.execute(
        "UPDATE coupons SET status = 'used', used_order_id = ?, used_by_user_id = "
        "(SELECT user_id FROM orders WHERE order_id = ?), used_at = ?, reserved_order_id = NULL "
        "WHERE reserved_order_id = ? AND status = 'active'",
        (int(order_id), int(order_id), yangon_now().strftime('%Y-%m-%d %H:%M:%S'), int(order_id)),
    )


def get_active_coupons(limit=100):
    now = yangon_now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db_connection(DATABASE_NAME) as conn:
        return conn.execute("SELECT code, discount_type, discount_value, expires_at, assigned_user_id FROM coupons WHERE status = 'active' AND datetime(expires_at) > datetime(?) ORDER BY coupon_id DESC LIMIT ?", (now, int(limit))).fetchall()


def get_coupon_details(code):
    with get_db_connection(DATABASE_NAME) as conn:
        return conn.execute(
            "SELECT code, discount_type, discount_value, expires_at, assigned_user_id FROM coupons WHERE UPPER(code) = ?",
            (str(code).strip().upper(),),
        ).fetchone()


def mark_user_inactive(user_id):
    """Stop sending broadcasts to a user who blocked or deactivated the bot."""
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET is_active = 0 WHERE user_id = ?", (int(user_id),))
        return cursor.rowcount > 0

def get_users_for_admin(limit=50):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                u.user_id,
                u.join_date,
                COALESCE(u.role, 'user') AS role,
                COALESCE(u.username, '') AS username,
                COALESCE(u.first_name, '') AS first_name,
                COALESCE(u.last_name, '') AS last_name,
                COUNT(o.order_id) AS order_count,
                SUM(CASE WHEN o.status = 'Success' THEN 1 ELSE 0 END) AS success_count
            FROM users u
            LEFT JOIN orders o ON o.user_id = u.user_id
            GROUP BY u.user_id
            ORDER BY u.join_date DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()

# --- Orders Functions ---

def ensure_order_code_column(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "order_code" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN order_code TEXT")
    cursor.execute("SELECT order_id FROM orders WHERE order_code IS NULL OR order_code = ''")
    for (order_id,) in cursor.fetchall():
        order_code = generate_order_code()
        while cursor.execute("SELECT 1 FROM orders WHERE order_code = ?", (order_code,)).fetchone():
            order_code = generate_order_code()
        cursor.execute("UPDATE orders SET order_code = ? WHERE order_id = ?", (order_code, order_id))

def ensure_order_renewal_columns(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "expiry_date" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN expiry_date TEXT")
    if "renewal_notice_sent" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN renewal_notice_sent INTEGER DEFAULT 0")
    if "expiry_admin_notice_sent" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN expiry_admin_notice_sent INTEGER DEFAULT 0")
        # Prevent a notification flood for orders that expired before this feature existed.
        cursor.execute(
            """
            UPDATE orders
            SET expiry_admin_notice_sent = 1
            WHERE expiry_date IS NOT NULL
              AND datetime(expiry_date) <= datetime(?)
            """,
            (yangon_now().strftime("%Y-%m-%d %H:%M:%S"),)
        )

def ensure_order_amount_column(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "total_amount" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN total_amount REAL")

def ensure_order_sell_proof_column(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "sell_proof_status" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN sell_proof_status INTEGER DEFAULT 0")
        # Do not publish historical orders when this feature is first deployed.
        cursor.execute(
            "UPDATE orders SET sell_proof_status = 1 WHERE status = 'Success'"
        )

def ensure_order_outline_columns(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "outline_key_id" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN outline_key_id TEXT")
    if "outline_access_url" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN outline_access_url TEXT")
    if "renewal_of_order_id" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN renewal_of_order_id INTEGER")
    if "order_type" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN order_type TEXT DEFAULT 'normal'")

def generate_order_code():
    alphabet = string.ascii_uppercase + string.digits
    return "ORD-" + "".join(secrets.choice(alphabet) for _ in range(10))

def get_public_order_id(order):
    if order and len(order) > 8 and order[8]:
        return order[8]
    if isinstance(order, (tuple, list)) and order:
        return f"ORD-{int(order[0]):010d}"
    return "ORD-UNKNOWN"

def parse_duration_days(text):
    if not text:
        return None
    normalized = str(text).lower()

    patterns = [
        (r"(\d+)\s*(?:years?|yrs?|y\b|နှစ်)", 365),
        (
            r"(\d+)\s*(?:months?|mos?|m\b|လစာ|လသက်တမ်း|လ(?![\u1000-\u109f]))",
            30,
        ),
        (r"(\d+)\s*(?:days?|d\b|ရက်)", 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1)) * multiplier

    if "monthly" in normalized or "လစဉ်" in normalized:
        return 30
    if "lifetime" in normalized:
        return None
    return None

def parse_legacy_duration_days(text):
    if not text:
        return None
    normalized = str(text).lower()
    patterns = [
        (r"(\d+)\s*(?:years?|yrs?|y\b|နှစ်)", 365),
        (r"(\d+)\s*(?:months?|mos?|m\b|လ)", 30),
        (r"(\d+)\s*(?:days?|d\b|ရက်)", 1),
    ]
    for pattern, multiplier in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1)) * multiplier
    return None

def repair_duration_parser_v2_expiry_dates(cursor):
    migration_key = "expiry_duration_parser_v2_repaired"
    cursor.execute("SELECT value FROM settings WHERE key = ?", (migration_key,))
    if cursor.fetchone():
        return

    cursor.execute(
        """
        SELECT
            o.order_id,
            o.timestamp,
            o.expiry_date,
            o.item_name,
            COALESCE(i.details, ''),
            COALESCE(i.type, ''),
            COALESCE(i.details_en, ''),
            COALESCE(i.type_en, '')
        FROM orders AS o
        LEFT JOIN items AS i
          ON i.item_id = (
              SELECT matched.item_id
              FROM items AS matched
              WHERE TRIM(matched.name) = TRIM(o.item_name) COLLATE NOCASE
              LIMIT 1
          )
        WHERE o.status = 'Success'
          AND o.expiry_date IS NOT NULL
          AND TRIM(o.expiry_date) != ''
        """
    )
    for row in cursor.fetchall():
        (
            order_id, timestamp, expiry_date, item_name,
            details, product_info, details_en, product_info_en
        ) = row
        product_text = " ".join(
            str(part)
            for part in (
                item_name, details, product_info, details_en, product_info_en
            )
            if part
        )
        legacy_days = parse_legacy_duration_days(product_text)
        corrected_days = parse_duration_days(product_text)
        if not legacy_days or not corrected_days or legacy_days == corrected_days:
            continue
        try:
            ordered_at = datetime.strptime(str(timestamp), "%Y-%m-%d %H:%M:%S")
            current_expiry = datetime.strptime(
                str(expiry_date),
                "%Y-%m-%d %H:%M:%S"
            )
        except (TypeError, ValueError):
            continue

        expected_legacy_expiry = ordered_at + timedelta(days=legacy_days)
        if abs((current_expiry - expected_legacy_expiry).total_seconds()) > 7 * 86400:
            continue
        corrected_expiry = current_expiry + timedelta(
            days=corrected_days - legacy_days
        )
        cursor.execute(
            """
            UPDATE orders
            SET expiry_date = ?,
                renewal_notice_sent = 0,
                expiry_admin_notice_sent = 0
            WHERE order_id = ?
            """,
            (
                corrected_expiry.strftime("%Y-%m-%d %H:%M:%S"),
                order_id,
            )
        )

    cursor.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (migration_key, yangon_now().strftime("%Y-%m-%d %H:%M:%S"))
    )

def calculate_expiry_date(timestamp, product_text):
    if is_non_expiring_product(product_text):
        return None
    duration_days = parse_duration_days(product_text)
    if not duration_days:
        return None
    try:
        start_date = datetime.strptime(timestamp, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        start_date = datetime.now()
    return (start_date + timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")

def calculate_renewed_expiry_date(current_expiry, product_text):
    duration_days = parse_duration_days(product_text) or 30
    now = yangon_now()
    base_date = now
    if current_expiry:
        try:
            expiry_date = datetime.strptime(str(current_expiry), "%Y-%m-%d %H:%M:%S")
            if expiry_date > now:
                base_date = expiry_date
        except (TypeError, ValueError):
            pass
    return (base_date + timedelta(days=duration_days)).strftime("%Y-%m-%d %H:%M:%S")

def parse_outline_key_info(account_info):
    text = str(account_info or "")
    key_id = None
    access_url = None

    id_patterns = [
        r"(?:outline[_\s-]*key[_\s-]*id|key[_\s-]*id|id)\s*[:=]\s*([A-Za-z0-9_-]+)",
        r"^\s*([A-Za-z0-9_-]+)\s*\|\s*ss://",
    ]
    for pattern in id_patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            key_id = match.group(1).strip()
            break

    url_match = re.search(r"(ss://\S+)", text)
    if url_match:
        access_url = url_match.group(1).strip()

    return key_id, access_url

def is_outline_renewable_product(item_name):
    return is_product_renewable_by_name(item_name)

def backfill_missing_order_expiry_dates(cursor):
    cursor.execute("""
        SELECT
            o.order_id,
            o.timestamp,
            o.item_name,
            COALESCE(i.details, ''),
            COALESCE(i.type, ''),
            COALESCE(i.details_en, ''),
            COALESCE(i.type_en, '')
        FROM orders o
        LEFT JOIN items i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
        WHERE o.expiry_date IS NULL OR o.expiry_date = ''
    """)
    rows = cursor.fetchall()
    for order_id, timestamp, item_name, details, product_info, details_en, product_info_en in rows:
        product_text = " ".join(
            str(part) for part in (item_name, details, product_info, details_en, product_info_en) if part
        )
        expiry_date = calculate_expiry_date(timestamp, product_text)
        if expiry_date:
            cursor.execute(
                "UPDATE orders SET expiry_date = ? WHERE order_id = ?",
                (expiry_date, order_id)
            )

def normalize_order_expiry_dates(cursor):
    cursor.execute(
        """
        SELECT order_id, expiry_date
        FROM orders
        WHERE expiry_date IS NOT NULL AND TRIM(expiry_date) != ''
        """
    )
    for order_id, expiry_date in cursor.fetchall():
        raw_value = str(expiry_date).strip()
        parsed = None
        for date_format in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                parsed = datetime.strptime(raw_value, date_format)
                break
            except ValueError:
                continue
        if parsed is None:
            continue
        normalized = parsed.strftime("%Y-%m-%d %H:%M:%S")
        if normalized != raw_value:
            cursor.execute(
                "UPDATE orders SET expiry_date = ? WHERE order_id = ?",
                (normalized, order_id)
            )

def create_order(user_id, item_name, quantity, payment_method, status, timestamp, product_text=None, total_amount=None):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        order_code = generate_order_code()
        while cursor.execute("SELECT 1 FROM orders WHERE order_code = ?", (order_code,)).fetchone():
            order_code = generate_order_code()
        expiry_date = calculate_expiry_date(timestamp, product_text or item_name)
        cursor.execute(
            "INSERT INTO orders (user_id, item_name, quantity, payment_method, status, timestamp, order_code, expiry_date, total_amount) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, item_name, quantity, payment_method, status, timestamp, order_code, expiry_date, total_amount)
        )
        conn.commit()
        return cursor.lastrowid

def create_reserved_order(
    user_id,
    item_id,
    quantity,
    payment_method,
    product_text=None,
    reservation_minutes=10,
    coupon_code=None,
    target_username=None,
):
    quantity = int(quantity)
    if quantity <= 0:
        return {"ok": False, "reason": "invalid_quantity"}

    now = yangon_now()
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_at = now + timedelta(minutes=max(1, int(reservation_minutes)))
    expires_text = expires_at.strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT order_id
            FROM stock_reservations
            WHERE status = 'active'
              AND expires_at IS NOT NULL
              AND datetime(expires_at) <= datetime(?)
            """,
            (now_text,)
        )
        expired_order_ids = [row[0] for row in cursor.fetchall()]
        if expired_order_ids:
            placeholders = ",".join("?" for _ in expired_order_ids)
            cursor.execute(
                f"""
                UPDATE stock_reservations
                SET status = 'expired', released_at = ?
                WHERE order_id IN ({placeholders})
                """,
                [now_text, *expired_order_ids]
            )
            cursor.execute(
                f"""
                UPDATE orders
                SET status = 'Reservation Expired'
                WHERE order_id IN ({placeholders}) AND status = 'Pending'
                """,
                expired_order_ids
            )
            placeholders = ",".join("?" for _ in expired_order_ids)
            cursor.execute(
                f"UPDATE coupons SET reserved_order_id = NULL WHERE reserved_order_id IN ({placeholders}) AND status = 'active'",
                expired_order_ids,
            )

        cursor.execute(
            """
            SELECT order_id
            FROM stock_reservations
            WHERE user_id = ?
              AND status IN ('awaiting_review', 'processing', 'partial')
            LIMIT 1
            """,
            (user_id,)
        )
        if cursor.fetchone():
            conn.rollback()
            return {"ok": False, "reason": "existing_order_under_review"}

        cursor.execute(
            "SELECT order_id FROM stock_reservations WHERE user_id = ? AND status = 'active'",
            (user_id,)
        )
        replaced_order_ids = [row[0] for row in cursor.fetchall()]
        if replaced_order_ids:
            placeholders = ",".join("?" for _ in replaced_order_ids)
            cursor.execute(
                f"""
                UPDATE stock_reservations
                SET status = 'released', released_at = ?
                WHERE order_id IN ({placeholders})
                """,
                [now_text, *replaced_order_ids]
            )
            cursor.execute(
                f"""
                UPDATE orders
                SET status = 'Reservation Replaced'
                WHERE order_id IN ({placeholders}) AND status = 'Pending'
                """,
                replaced_order_ids
            )
            placeholders = ",".join("?" for _ in replaced_order_ids)
            cursor.execute(
                f"UPDATE coupons SET reserved_order_id = NULL WHERE reserved_order_id IN ({placeholders}) AND status = 'active'",
                replaced_order_ids,
            )

        cursor.execute("SELECT name, price, stock FROM items WHERE item_id = ?", (item_id,))
        item = cursor.fetchone()
        if not item:
            conn.rollback()
            return {"ok": False, "reason": "item_not_found"}
        item_name, unit_price, physical_stock = item

        cursor.execute(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM stock_reservations
            WHERE item_id = ?
              AND (
                    status IN ('awaiting_review', 'processing', 'partial')
                    OR (
                        status = 'active'
                        AND expires_at IS NOT NULL
                        AND datetime(expires_at) > datetime(?)
                    )
                  )
            """,
            (item_id, now_text)
        )
        held_quantity = int(cursor.fetchone()[0] or 0)
        available_stock = max(0, int(physical_stock or 0) - held_quantity)
        if quantity > available_stock:
            conn.rollback()
            return {
                "ok": False,
                "reason": "insufficient_stock",
                "available_stock": available_stock,
            }

        order_code = generate_order_code()
        while cursor.execute("SELECT 1 FROM orders WHERE order_code = ?", (order_code,)).fetchone():
            order_code = generate_order_code()
        subtotal = float(unit_price) * quantity
        vip_percent = 0
        vip_discount_amount = 0.0
        if not is_gift_card_product(item_name):
            spent_row = cursor.execute(
                "SELECT COALESCE(SUM(total_amount), 0) FROM orders WHERE user_id = ? AND status = 'Success'",
                (int(user_id),),
            ).fetchone()
            spent_total = float(spent_row[0] or 0.0) if spent_row else 0.0
            if spent_total >= 300000:
                vip_percent = 6
            elif spent_total >= 150000:
                vip_percent = 4
            elif spent_total >= 50000:
                vip_percent = 2
            if vip_percent > 0:
                vip_discount_amount = round(subtotal * vip_percent / 100.0)
        after_vip = max(0.0, subtotal - vip_discount_amount)
        coupon_id = None
        discount_amount = 0.0
        if coupon_code:
            cursor.execute(
                "SELECT coupon_id, discount_type, discount_value, assigned_user_id FROM coupons WHERE UPPER(code) = ? AND status = 'active' AND reserved_order_id IS NULL AND datetime(expires_at) > datetime(?)",
                (str(coupon_code).strip().upper(), now_text),
            )
            coupon = cursor.fetchone()
            if not coupon:
                conn.rollback()
                return {"ok": False, "reason": "coupon_unavailable"}
            coupon_id, discount_type, discount_value, assigned_user_id = coupon
            if assigned_user_id is not None and int(assigned_user_id) != int(user_id):
                conn.rollback()
                return {"ok": False, "reason": "coupon_unavailable"}
            discount_amount = min(after_vip, after_vip * float(discount_value) / 100 if discount_type == "percent" else float(discount_value))
        total_amount = max(0.0, after_vip - discount_amount)
        fully_discounted = total_amount <= 0
        expiry_date = calculate_expiry_date(now_text, product_text or item_name)
        ensure_order_target_username_column(cursor)
        cursor.execute(
            """
            INSERT INTO orders
                (user_id, item_name, quantity, payment_method, status, timestamp,
                 order_code, expiry_date, total_amount, target_username)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id, item_name, quantity, payment_method,
                'Payment Submitted' if fully_discounted else 'Pending', now_text,
                order_code, expiry_date, total_amount, target_username
            )
        )
        order_id = cursor.lastrowid
        if coupon_id is not None:
            if fully_discounted:
                cursor.execute(
                    "UPDATE coupons SET status = 'used', used_order_id = ?, used_by_user_id = ?, used_at = ?, reserved_order_id = NULL "
                    "WHERE coupon_id = ? AND status = 'active' AND reserved_order_id IS NULL",
                    (order_id, int(user_id), now_text, coupon_id),
                )
            else:
                cursor.execute(
                    "UPDATE coupons SET reserved_order_id = ? "
                    "WHERE coupon_id = ? AND status = 'active' AND reserved_order_id IS NULL",
                    (order_id, coupon_id),
                )
            if cursor.rowcount != 1:
                conn.rollback()
                return {"ok": False, "reason": "coupon_unavailable"}
        cursor.execute(
            """
            INSERT INTO stock_reservations
                (order_id, user_id, item_id, item_name, quantity, status,
                 created_at, expires_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (order_id, user_id, item_id, item_name, quantity,
             'awaiting_review' if fully_discounted else 'active', now_text,
             None if fully_discounted else expires_text)
        )
        conn.commit()
        return {
            "ok": True,
            "order_id": order_id,
            "order_code": order_code,
            "item_name": item_name,
            "quantity": quantity,
            "unit_price": float(unit_price),
            "subtotal": subtotal,
            "vip_percent": vip_percent,
            "vip_discount_amount": vip_discount_amount,
            "discount_amount": discount_amount,
            "total_amount": total_amount,
            "expires_at": expires_text,
            "coupon_id": coupon_id,
            "fully_discounted": fully_discounted,
        }

def create_existing_key_renewal_order(
    source_order_id,
    user_id,
    payment_method,
    reservation_minutes=10,
):
    now = yangon_now()
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    expires_text = (now + timedelta(minutes=max(1, int(reservation_minutes)))).strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            """
            SELECT order_id
            FROM stock_reservations
            WHERE user_id = ?
              AND status IN ('awaiting_review', 'processing', 'partial')
            LIMIT 1
            """,
            (user_id,)
        )
        if cursor.fetchone():
            conn.rollback()
            return {"ok": False, "reason": "existing_order_under_review"}

        cursor.execute(
            "SELECT order_id FROM stock_reservations WHERE user_id = ? AND status = 'active'",
            (user_id,)
        )
        replaced_order_ids = [row[0] for row in cursor.fetchall()]
        if replaced_order_ids:
            placeholders = ",".join("?" for _ in replaced_order_ids)
            cursor.execute(
                f"""
                UPDATE stock_reservations
                SET status = 'released', released_at = ?, expires_at = NULL
                WHERE order_id IN ({placeholders})
                """,
                [now_text, *replaced_order_ids]
            )
            cursor.execute(
                f"""
                UPDATE orders
                SET status = 'Reservation Replaced'
                WHERE order_id IN ({placeholders}) AND status = 'Pending'
                """,
                replaced_order_ids
            )

        cursor.execute(
            """
            SELECT
                o.order_id,
                o.item_name,
                o.quantity,
                o.expiry_date,
                o.delivered_data,
                o.outline_key_id,
                o.outline_access_url,
                i.item_id,
                i.price,
                COALESCE(i.details, ''),
                COALESCE(i.type, ''),
                COALESCE(i.details_en, ''),
                COALESCE(i.type_en, '')
            FROM orders AS o
            LEFT JOIN items AS i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
            WHERE o.order_id = ?
              AND o.user_id = ?
              AND o.status = 'Success'
            LIMIT 1
            """,
            (source_order_id, user_id)
        )
        source = cursor.fetchone()
        if not source:
            conn.rollback()
            return {"ok": False, "reason": "source_order_not_found"}

        (
            _, item_name, source_quantity, current_expiry, delivered_data, outline_key_id,
            outline_access_url, item_id, price, details, product_info,
            details_en, product_info_en
        ) = source
        if not is_outline_renewable_product(item_name):
            conn.rollback()
            return {"ok": False, "reason": "product_not_renewable"}

        renewal_quantity = max(1, int(source_quantity or 1))
        parsed_key_id, parsed_access_url = parse_outline_key_info(delivered_data)
        outline_key_id = outline_key_id or parsed_key_id
        outline_access_url = outline_access_url or parsed_access_url

        if outline_key_id != source[5] or outline_access_url != source[6]:
            cursor.execute(
                """
                UPDATE orders
                SET outline_key_id = ?, outline_access_url = ?
                WHERE order_id = ?
                """,
                (outline_key_id, outline_access_url, source_order_id)
            )

        order_code = generate_order_code()
        while cursor.execute("SELECT 1 FROM orders WHERE order_code = ?", (order_code,)).fetchone():
            order_code = generate_order_code()

        product_text = " ".join(
            str(part)
            for part in (item_name, details, product_info, details_en, product_info_en)
            if part
        )
        renewal_expiry = calculate_renewed_expiry_date(current_expiry, product_text)
        unit_price = float(price or 0)
        total_amount = unit_price * renewal_quantity
        cursor.execute(
            """
            INSERT INTO orders
                (user_id, item_name, quantity, payment_method, status, timestamp,
                 delivered_data, order_code, expiry_date, total_amount,
                 outline_key_id, outline_access_url, renewal_of_order_id, order_type)
            VALUES (?, ?, ?, ?, 'Pending', ?, ?, ?, ?, ?, ?, ?, ?, 'renewal')
            """,
            (
                user_id, item_name, renewal_quantity, payment_method, now_text, delivered_data,
                order_code, renewal_expiry, total_amount, outline_key_id,
                outline_access_url, source_order_id
            )
        )
        renewal_order_id = cursor.lastrowid
        cursor.execute(
            """
            INSERT INTO stock_reservations
                (order_id, user_id, item_id, item_name, quantity, status,
                 created_at, expires_at)
            VALUES (?, ?, ?, ?, 1, 'active', ?, ?)
            """,
            (
                renewal_order_id, user_id, 0, item_name,
                now_text, expires_text
            )
        )
        conn.commit()
        return {
            "ok": True,
            "order_id": renewal_order_id,
            "order_code": order_code,
            "item_name": item_name,
            "quantity": renewal_quantity,
            "unit_price": unit_price,
            "total_amount": total_amount,
            "expires_at": expires_text,
            "source_order_id": source_order_id,
            "outline_key_id": outline_key_id,
            "outline_access_url": outline_access_url,
            "renewal_expiry": renewal_expiry,
        }

def get_available_stock(item_id):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                MAX(
                    0,
                    COALESCE(i.stock, 0) - COALESCE(SUM(
                        CASE
                            WHEN r.status IN ('awaiting_review', 'processing', 'partial') THEN r.quantity
                            WHEN r.status = 'active'
                                 AND r.expires_at IS NOT NULL
                                 AND datetime(r.expires_at) > datetime(?) THEN r.quantity
                            ELSE 0
                        END
                    ), 0)
                )
            FROM items i
            LEFT JOIN stock_reservations r ON r.item_id = i.item_id
            WHERE i.item_id = ?
            GROUP BY i.item_id
            """,
            (now_text, item_id)
        )
        row = cursor.fetchone()
        return int(row[0]) if row else 0

def get_available_stock_map():
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                i.item_id,
                MAX(
                    0,
                    COALESCE(i.stock, 0) - COALESCE(SUM(
                        CASE
                            WHEN r.status IN ('awaiting_review', 'processing', 'partial') THEN r.quantity
                            WHEN r.status = 'active'
                                 AND r.expires_at IS NOT NULL
                                 AND datetime(r.expires_at) > datetime(?) THEN r.quantity
                            ELSE 0
                        END
                    ), 0)
                ) AS available_stock
            FROM items i
            LEFT JOIN stock_reservations r ON r.item_id = i.item_id
            GROUP BY i.item_id
            """,
            (now_text,)
        )
        return {int(item_id): int(stock or 0) for item_id, stock in cursor.fetchall()}

def submit_payment_proof(order_id, user_id, file_unique_id, telegram_file_id=None):
    now = yangon_now()
    now_text = now.strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")

        cursor.execute(
            "SELECT order_id FROM payment_submissions WHERE file_unique_id = ?",
            (str(file_unique_id),)
        )
        existing_proof = cursor.fetchone()
        if existing_proof:
            conn.rollback()
            return "already_submitted" if int(existing_proof[0]) == int(order_id) else "duplicate_proof"

        cursor.execute(
            "SELECT 1 FROM payment_submissions WHERE order_id = ?",
            (order_id,)
        )
        if cursor.fetchone():
            conn.rollback()
            return "already_submitted"

        cursor.execute(
            """
            SELECT status, expires_at
            FROM stock_reservations
            WHERE order_id = ? AND user_id = ?
            """,
            (order_id, user_id)
        )
        reservation = cursor.fetchone()
        if not reservation:
            conn.rollback()
            return "not_found"
        status, expires_at = reservation
        if status == "awaiting_review":
            conn.rollback()
            return "already_submitted"
        if status != "active":
            conn.rollback()
            return status
        if not expires_at or datetime.strptime(expires_at, "%Y-%m-%d %H:%M:%S") <= now:
            cursor.execute(
                """
                UPDATE stock_reservations
                SET status = 'expired', released_at = ?
                WHERE order_id = ?
                """,
                (now_text, order_id)
            )
            cursor.execute(
                "UPDATE orders SET status = 'Reservation Expired' WHERE order_id = ?",
                (order_id,)
            )
            _release_order_coupon(cursor, order_id)
            conn.commit()
            return "expired"

        try:
            cursor.execute(
                """
                INSERT INTO payment_submissions
                    (order_id, user_id, file_unique_id, telegram_file_id, status, submitted_at)
                VALUES (?, ?, ?, ?, 'pending', ?)
                """,
                (order_id, user_id, str(file_unique_id), telegram_file_id, now_text)
            )
        except sqlite3.IntegrityError:
            conn.rollback()
            return "duplicate_proof"

        cursor.execute(
            """
            UPDATE stock_reservations
            SET status = 'awaiting_review', submitted_at = ?, expires_at = NULL
            WHERE order_id = ? AND status = 'active'
            """,
            (now_text, order_id)
        )
        cursor.execute(
            "UPDATE orders SET status = 'Payment Submitted' WHERE order_id = ?",
            (order_id,)
        )
        conn.commit()
        return "submitted"

def get_active_reserved_order_for_user(user_id):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_target_username_column(cursor)
        cursor.execute(
            """
            SELECT o.order_id, o.order_code, o.item_name, o.quantity,
                   o.total_amount, o.payment_method, r.expires_at,
                   COALESCE(o.target_username, '')
            FROM stock_reservations r
            JOIN orders o ON o.order_id = r.order_id
            WHERE r.user_id = ?
              AND r.status = 'active'
              AND r.expires_at IS NOT NULL
              AND datetime(r.expires_at) > datetime(?)
            ORDER BY r.reservation_id DESC
            LIMIT 1
            """,
            (user_id, now_text)
        )
        return cursor.fetchone()

def claim_stock_reservation_for_processing(order_id, admin_id=None):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT status FROM stock_reservations WHERE order_id = ?",
            (order_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return "legacy"
        if row[0] != "awaiting_review":
            conn.rollback()
            return row[0]
        cursor.execute(
            """
            UPDATE stock_reservations
            SET status = 'processing', submitted_at = COALESCE(submitted_at, ?)
            WHERE order_id = ? AND status = 'awaiting_review'
            """,
            (now_text, order_id)
        )
        claimed = cursor.rowcount > 0
        if claimed:
            _consume_order_coupon(cursor, order_id)
        cursor.execute(
            """
            UPDATE payment_submissions
            SET status = 'processing',
                processed_by = COALESCE(processed_by, ?)
            WHERE order_id = ? AND status = 'pending'
            """,
            (admin_id, order_id)
        )
        conn.commit()
        return "claimed" if claimed else "already_processed"

def reject_stock_reservation(order_id, admin_id=None):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            "SELECT status FROM stock_reservations WHERE order_id = ?",
            (order_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return "legacy"
        if row[0] not in ("active", "awaiting_review"):
            conn.rollback()
            return row[0]
        cursor.execute(
            """
            UPDATE stock_reservations
            SET status = 'rejected', released_at = ?, expires_at = NULL
            WHERE order_id = ? AND status IN ('active', 'awaiting_review')
            """,
            (now_text, order_id)
        )
        rejected = cursor.rowcount > 0
        if rejected:
            _release_order_coupon(cursor, order_id)
        cursor.execute(
            """
            UPDATE payment_submissions
            SET status = 'rejected', processed_at = ?, processed_by = ?
            WHERE order_id = ? AND status IN ('pending', 'processing')
            """,
            (now_text, admin_id, order_id)
        )
        conn.commit()
        return "rejected" if rejected else "already_processed"

def mark_payment_submission_status(order_id, status, admin_id=None):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE payment_submissions
            SET status = ?, processed_at = ?, processed_by = COALESCE(?, processed_by)
            WHERE order_id = ?
            """,
            (status, now_text, admin_id, order_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def set_stock_reservation_remainder(order_id, remaining_quantity):
    remaining_quantity = max(0, int(remaining_quantity))
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        if remaining_quantity:
            cursor.execute(
                """
                UPDATE stock_reservations
                SET status = 'partial', quantity = ?, expires_at = NULL
                WHERE order_id = ?
                """,
                (remaining_quantity, order_id)
            )
        else:
            cursor.execute(
                """
                UPDATE stock_reservations
                SET status = 'completed', quantity = 0, completed_at = ?, expires_at = NULL
                WHERE order_id = ?
                """,
                (now_text, order_id)
            )
        conn.commit()

def complete_stock_reservation(order_id):
    set_stock_reservation_remainder(order_id, 0)

def release_stock_reservation(order_id, status="released"):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE stock_reservations
            SET status = ?, released_at = ?, expires_at = NULL
            WHERE order_id = ?
              AND status IN ('active', 'awaiting_review', 'processing', 'partial')
            """,
            (status, now_text, order_id)
        )
        conn.commit()
        return cursor.rowcount > 0

def cancel_user_stock_reservation(order_id, user_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            UPDATE stock_reservations
            SET status = 'cancelled', released_at = ?, expires_at = NULL
            WHERE order_id = ? AND user_id = ?
              AND (
                    status = 'active'
                    OR (
                        status = 'awaiting_review'
                        AND NOT EXISTS (
                            SELECT 1 FROM payment_submissions
                            WHERE payment_submissions.order_id = stock_reservations.order_id
                        )
                    )
                  )
            """,
            (yangon_now().strftime("%Y-%m-%d %H:%M:%S"), order_id, user_id)
        )
        cancelled = cursor.rowcount > 0
        if cancelled:
            _release_order_coupon(cursor, order_id)
            cursor.execute(
                "UPDATE orders SET status = 'Cancelled' WHERE order_id = ?",
                (order_id,)
            )
        conn.commit()
        return cancelled

def expire_stock_reservations():
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            SELECT r.order_id, r.user_id, r.item_name, r.quantity, o.order_code
            FROM stock_reservations r
            JOIN orders o ON o.order_id = r.order_id
            WHERE r.status = 'active'
              AND r.expires_at IS NOT NULL
              AND datetime(r.expires_at) <= datetime(?)
            """,
            (now_text,)
        )
        expired = cursor.fetchall()
        if expired:
            order_ids = [row[0] for row in expired]
            placeholders = ",".join("?" for _ in order_ids)
            cursor.execute(
                f"""
                UPDATE stock_reservations
                SET status = 'expired', released_at = ?
                WHERE order_id IN ({placeholders})
                """,
                [now_text, *order_ids]
            )
            cursor.execute(
                f"""
                UPDATE orders
                SET status = 'Reservation Expired'
                WHERE order_id IN ({placeholders}) AND status = 'Pending'
                """,
                order_ids
            )
            for order_id in order_ids:
                _release_order_coupon(cursor, order_id)
        conn.commit()
        return expired

def get_monthly_sales_report(year_month=None):
    if year_month is None:
        year_month = datetime.now().strftime("%Y-%m")

    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.item_name,
                SUM(o.quantity) AS total_qty,
                SUM(COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity)) AS total_amount,
                COUNT(o.order_id) AS order_count
            FROM orders o
            LEFT JOIN items i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
            WHERE o.status = 'Success'
              AND substr(o.timestamp, 1, 7) = ?
              AND COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity) > 0
            GROUP BY o.item_name
            ORDER BY total_amount DESC, total_qty DESC
        """, (year_month,))
        items = cursor.fetchall()

        cursor.execute("""
            SELECT
                COUNT(order_id),
                COALESCE(SUM(quantity), 0),
                COALESCE(SUM(COALESCE(total_amount, COALESCE(i.price, 0) * quantity)), 0)
            FROM orders o
            LEFT JOIN items i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
            WHERE o.status = 'Success'
              AND substr(o.timestamp, 1, 7) = ?
              AND COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity) > 0
        """, (year_month,))
        total_order_count, total_quantity, total_amount = cursor.fetchone()

    return {
        "year_month": year_month,
        "total_order_count": total_order_count or 0,
        "total_quantity": total_quantity or 0,
        "total_amount": total_amount or 0,
        "items": items,
    }

def get_yearly_sales_report(year=None):
    if year is None:
        year = datetime.now().strftime("%Y")
    else:
        year = str(year)

    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.item_name,
                SUM(o.quantity) AS total_qty,
                SUM(COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity)) AS total_amount,
                COUNT(o.order_id) AS order_count
            FROM orders o
            LEFT JOIN items i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
            WHERE o.status = 'Success'
              AND substr(o.timestamp, 1, 4) = ?
              AND COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity) > 0
            GROUP BY o.item_name
            ORDER BY total_amount DESC, total_qty DESC
        """, (year,))
        items = cursor.fetchall()

        cursor.execute("""
            SELECT
                substr(o.timestamp, 1, 7) AS year_month,
                COUNT(o.order_id) AS order_count,
                COALESCE(SUM(o.quantity), 0) AS total_qty,
                COALESCE(SUM(COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity)), 0) AS total_amount
            FROM orders o
            LEFT JOIN items i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
            WHERE o.status = 'Success'
              AND substr(o.timestamp, 1, 4) = ?
              AND COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity) > 0
            GROUP BY substr(o.timestamp, 1, 7)
            ORDER BY year_month ASC
        """, (year,))
        months = cursor.fetchall()

        cursor.execute("""
            SELECT
                COUNT(o.order_id),
                COALESCE(SUM(o.quantity), 0),
                COALESCE(SUM(COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity)), 0)
            FROM orders o
            LEFT JOIN items i ON TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
            WHERE o.status = 'Success'
              AND substr(o.timestamp, 1, 4) = ?
              AND COALESCE(o.total_amount, COALESCE(i.price, 0) * o.quantity) > 0
        """, (year,))
        total_order_count, total_quantity, total_amount = cursor.fetchone()

    return {
        "year": year,
        "total_order_count": total_order_count or 0,
        "total_quantity": total_quantity or 0,
        "total_amount": total_amount or 0,
        "months": months,
        "items": items,
    }

def get_recent_orders_for_admin(limit=20):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.order_id,
                o.order_code,
                o.user_id,
                u.username,
                u.first_name,
                u.last_name,
                o.item_name,
                o.quantity,
                o.payment_method,
                o.status,
                o.timestamp,
                o.expiry_date,
                o.total_amount,
                CASE
                    WHEN o.delivered_data IS NULL OR TRIM(o.delivered_data) = '' THEN 0
                    ELSE 1
                END AS has_delivery
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            ORDER BY datetime(o.timestamp) DESC, o.order_id DESC
            LIMIT ?
        """, (limit,))
        return cursor.fetchall()


def get_pending_orders_for_admin(limit=50):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_target_username_column(cursor)
        return cursor.execute(
            """
            SELECT o.order_id, o.order_code, o.user_id, o.item_name, o.quantity,
                   o.payment_method, o.total_amount, o.timestamp,
                   COALESCE(o.target_username, ''), COALESCE(u.username, '')
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.status IN ('Pending', 'Payment Submitted', 'Partial')
            ORDER BY datetime(o.timestamp) ASC, o.order_id ASC
            LIMIT ?
            """,
            (int(limit),),
        ).fetchall()

def get_orders_by_user_for_admin(user_id, limit=30):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.order_id,
                o.order_code,
                o.user_id,
                u.username,
                u.first_name,
                u.last_name,
                o.item_name,
                o.quantity,
                o.payment_method,
                o.status,
                o.timestamp,
                o.expiry_date,
                o.total_amount,
                CASE
                    WHEN o.delivered_data IS NULL OR TRIM(o.delivered_data) = '' THEN 0
                    ELSE 1
                END AS has_delivery
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.user_id = ?
            ORDER BY datetime(o.timestamp) DESC, o.order_id DESC
            LIMIT ?
        """, (user_id, limit))
        return cursor.fetchall()

def ensure_app_notifications_table(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS app_notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            kind TEXT NOT NULL,
            title TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '',
            order_id INTEGER,
            ref TEXT,
            is_read INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_notif_user ON app_notifications (user_id, id)")


def push_app_notification(user_id, kind, title, body="", order_id=None, ref=None):
    """Queue an in-app notification. Only app accounts get them; failures never break the caller."""
    try:
        with get_db_connection(DATABASE_NAME, timeout=10) as conn:
            cur = conn.cursor()
            has_accounts = cur.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='app_accounts'"
            ).fetchone()
            if not has_accounts:
                return
            if not cur.execute("SELECT 1 FROM app_accounts WHERE user_id = ?", (int(user_id),)).fetchone():
                return
            ensure_app_notifications_table(cur)
            dup = cur.execute(
                "SELECT 1 FROM app_notifications WHERE user_id = ? AND kind = ? "
                "AND COALESCE(order_id, -1) = COALESCE(?, -1) AND COALESCE(ref, '') = COALESCE(?, '')",
                (int(user_id), kind, order_id, ref),
            ).fetchone()
            if dup:
                return
            cur.execute(
                "INSERT INTO app_notifications (user_id, kind, title, body, order_id, ref, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (int(user_id), kind, title, body, order_id, ref,
                 yangon_now().strftime("%Y-%m-%d %H:%M:%S")),
            )
            conn.commit()
    except Exception as e:
        print(f"push_app_notification error: {e}")


def notify_order_status_change(order_id, status):
    kinds = {
        "success": ("order_success", "✅ ပစ္စည်း ရောက်ပါပြီ",
                    "{item} ({code}) ကို Orders tab မှာ ကြည့်နိုင်ပါပြီ။"),
        "partial": ("order_partial", "📦 ပစ္စည်း တစ်စိတ်တစ်ပိုင်း ပို့ပြီးပါပြီ",
                    "{item} ({code}) အချို့ ပို့ပြီးပါပြီ၊ ကျန်တာကို Admin က မကြာမီ ပို့ပေးပါမယ်။"),
        "rejected": ("order_rejected", "❌ ငွေပေးချေမှု လက်မခံပါ",
                     "{item} ({code}) ၏ payment ကို Admin က လက်မခံပါ။ ပြဿနာရှိရင် Admin ကို ဆက်သွယ်ပါ။"),
    }
    entry = kinds.get(str(status).strip().lower())
    if not entry:
        return
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            row = conn.execute(
                "SELECT user_id, item_name, order_code FROM orders WHERE order_id = ?", (order_id,)
            ).fetchone()
        if not row:
            return
        kind, title, body = entry
        push_app_notification(
            row[0], kind, title,
            body.format(item=str(row[1]).replace("\u200e", "").strip(), code=row[2] or f"ORD-{order_id}"),
            order_id=order_id,
        )
    except Exception as e:
        print(f"notify_order_status_change error: {e}")


def update_order_status(order_id, status, reduce_stock=True):
    """Update an order and start its product duration when delivery succeeds."""
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT status, item_name, quantity FROM orders WHERE order_id = ?",
            (order_id,)
        )
        order = cursor.fetchone()
        if not order:
            return

        previous_status, item_name, quantity = order
        is_new_success = (
            str(status).lower() == "success"
            and str(previous_status or "").lower() != "success"
        )

        if is_new_success:
            cursor.execute(
                """
                SELECT name, details, type, details_en, type_en
                FROM items
                WHERE TRIM(name) = TRIM(?) COLLATE NOCASE
                LIMIT 1
                """,
                (item_name,)
            )
            item = cursor.fetchone()
            product_text = " ".join(
                str(part)
                for part in ((item_name,) + tuple(item or ()))
                if part
            )
            delivered_at = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
            expiry_date = calculate_expiry_date(delivered_at, product_text)
            cursor.execute(
                """
                UPDATE orders
                SET status = ?,
                    expiry_date = ?,
                    renewal_notice_sent = 0,
                    expiry_admin_notice_sent = 0
                WHERE order_id = ?
                """,
                (status, expiry_date, order_id)
            )
        else:
            cursor.execute(
                "UPDATE orders SET status = ? WHERE order_id = ?",
                (status, order_id)
            )

        conn.commit()
        if reduce_stock and is_new_success:
            reduce_item_stock_manual(item_name, quantity)
    if str(status or "").lower() != str(previous_status or "").lower():
        notify_order_status_change(order_id, status)

def update_order_delivery(order_id, account_info):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        outline_key_id, outline_access_url = parse_outline_key_info(account_info)
        cursor.execute(
            """
            UPDATE orders
            SET delivered_data = ?,
                outline_key_id = COALESCE(outline_key_id, ?),
                outline_access_url = COALESCE(outline_access_url, ?)
            WHERE order_id = ?
            """,
            (account_info, outline_key_id, outline_access_url, order_id)
        )
        conn.commit()

def get_order_type(order_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COALESCE(order_type, 'normal')
            FROM orders
            WHERE order_id = ?
            """,
            (order_id,)
        )
        row = cursor.fetchone()
        return row[0] if row else None


def get_pending_renewal_outline_data(order_id):
    """Return the key and final expiry needed before an API renewal is approved."""
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                r.item_name,
                r.order_code,
                r.expiry_date,
                r.outline_key_id,
                r.outline_access_url,
                s.expiry_date
            FROM orders AS r
            JOIN orders AS s ON s.order_id = r.renewal_of_order_id
            WHERE r.order_id = ?
              AND COALESCE(r.order_type, 'normal') = 'renewal'
              AND r.status IN ('Payment Submitted', 'Pending')
            LIMIT 1
            """,
            (order_id,),
        )
        row = cursor.fetchone()
        if not row:
            return None

        item_name, order_code, expiry_date, key_id, access_url, previous_expiry = row
        return {
            "item_name": item_name,
            "order_code": order_code,
            "expiry_date": expiry_date or calculate_renewed_expiry_date(previous_expiry, item_name),
            "outline_key_id": key_id,
            "outline_access_url": access_url,
        }

def complete_existing_key_renewal_order(order_id):
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            SELECT
                r.order_id,
                r.user_id,
                r.item_name,
                r.delivered_data,
                r.expiry_date,
                r.order_code,
                r.outline_key_id,
                r.outline_access_url,
                r.renewal_of_order_id,
                s.expiry_date
            FROM orders AS r
            JOIN orders AS s ON s.order_id = r.renewal_of_order_id
            WHERE r.order_id = ?
              AND COALESCE(r.order_type, 'normal') = 'renewal'
              AND r.status IN ('Payment Submitted', 'Pending')
            LIMIT 1
            """,
            (order_id,)
        )
        row = cursor.fetchone()
        if not row:
            conn.rollback()
            return None

        (
            renewal_order_id, user_id, item_name, delivered_data,
            renewal_expiry, order_code, outline_key_id, outline_access_url,
            source_order_id, previous_expiry
        ) = row
        if not renewal_expiry:
            renewal_expiry = calculate_renewed_expiry_date(previous_expiry, item_name)

        cursor.execute(
            """
            UPDATE orders
            SET expiry_date = ?,
                renewal_notice_sent = 0,
                expiry_admin_notice_sent = 0,
                outline_key_id = COALESCE(outline_key_id, ?),
                outline_access_url = COALESCE(outline_access_url, ?)
            WHERE order_id = ?
            """,
            (renewal_expiry, outline_key_id, outline_access_url, source_order_id)
        )
        cursor.execute(
            """
            UPDATE orders
            SET status = 'Success',
                timestamp = ?,
                expiry_date = ?,
                delivered_data = ?,
                renewal_notice_sent = 1,
                expiry_admin_notice_sent = 0
            WHERE order_id = ?
            """,
            (now_text, renewal_expiry, delivered_data, renewal_order_id)
        )
        cursor.execute(
            """
            UPDATE stock_reservations
            SET status = 'completed', quantity = 0, completed_at = ?, expires_at = NULL
            WHERE order_id = ?
            """,
            (now_text, renewal_order_id)
        )
        conn.commit()
        return {
            "order_id": renewal_order_id,
            "order_code": order_code,
            "source_order_id": source_order_id,
            "user_id": user_id,
            "item_name": item_name,
            "delivered_data": delivered_data,
            "expiry_date": renewal_expiry,
            "outline_key_id": outline_key_id,
            "outline_access_url": outline_access_url,
        }

def claim_order_for_sell_proof(order_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(
            """
            UPDATE orders
            SET sell_proof_status = -1
            WHERE order_id = ?
              AND status = 'Success'
              AND COALESCE(sell_proof_status, 0) = 0
            """,
            (order_id,)
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return None
        cursor.execute(
            """
            SELECT
                o.order_id,
                o.order_code,
                o.item_name,
                o.quantity,
                o.payment_method,
                o.timestamp,
                u.first_name,
                u.username
            FROM orders AS o
            LEFT JOIN users AS u ON u.user_id = o.user_id
            WHERE o.order_id = ?
            """,
            (order_id,)
        )
        order = cursor.fetchone()
        conn.commit()
        return order

def complete_order_sell_proof(order_id, sent):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE orders
            SET sell_proof_status = ?
            WHERE order_id = ? AND sell_proof_status = -1
            """,
            (1 if sent else 0, order_id)
        )
        conn.commit()

def get_user_orders(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_gift_columns(cursor)
        cursor.execute(
            "SELECT * FROM orders WHERE (user_id = ? OR gift_recipient_id = ?) AND status = 'Success' ORDER BY order_id DESC",
            (int(user_id), int(user_id))
        )
        return cursor.fetchall()

def get_order_details(order_id):
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            return cursor.fetchone()
    except Exception as e:
        print(f"Error getting order details: {e}")
        return None

def get_order_renewal_option(order_id, user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                o.order_id,
                o.item_name,
                o.quantity,
                o.expiry_date,
                COALESCE(o.outline_key_id, ''),
                COALESCE(o.outline_access_url, ''),
                o.delivered_data,
                (
                    SELECT i.price
                    FROM items AS i
                    WHERE TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
                    LIMIT 1
                ) AS current_price,
                (
                    SELECT i.item_id
                    FROM items AS i
                    WHERE TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
                    LIMIT 1
                ) AS item_id
            FROM orders AS o
            WHERE o.order_id = ?
              AND o.user_id = ?
              AND o.status = 'Success'
            LIMIT 1
            """,
            (order_id, user_id)
        )
        row = cursor.fetchone()
        if not row:
            return None

        parsed_key_id, parsed_access_url = parse_outline_key_info(row[6])
        outline_key_id = row[4] or parsed_key_id
        outline_access_url = row[5] or parsed_access_url
        if outline_key_id and (outline_key_id != row[4] or outline_access_url != row[5]):
            cursor.execute(
                """
                UPDATE orders
                SET outline_key_id = ?, outline_access_url = ?
                WHERE order_id = ?
                """,
                (outline_key_id, outline_access_url, order_id)
            )
            conn.commit()

        return {
            "order_id": row[0],
            "item_name": row[1],
            "quantity": max(1, int(row[2] or 1)),
            "expiry_date": row[3],
            "outline_key_id": outline_key_id,
            "outline_access_url": outline_access_url,
            "current_price": float(row[7] or 0),
            "item_id": row[8],
        }

def get_orders_needing_renewal_notice(days_before=3):
    now = yangon_now()
    target = now + timedelta(days=days_before)
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                o.order_id,
                o.user_id,
                o.item_name,
                o.timestamp,
                o.order_code,
                o.expiry_date,
                (
                    SELECT i.item_id
                    FROM items AS i
                    WHERE TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
                    LIMIT 1
                ) AS item_id,
                o.outline_key_id
            FROM orders AS o
            WHERE o.status = 'Success'
              AND COALESCE(o.order_type, 'normal') != 'renewal'
              AND o.expiry_date IS NOT NULL
              AND o.renewal_notice_sent = 0
              AND datetime(o.expiry_date) >= datetime(?)
              AND datetime(o.expiry_date) <= datetime(?)
            ORDER BY datetime(o.expiry_date) ASC
        """, (
            now.strftime("%Y-%m-%d %H:%M:%S"),
            target.strftime("%Y-%m-%d %H:%M:%S"),
        ))
        return cursor.fetchall()

def get_recently_expired_orders_missing_user_notice(grace_days=7):
    now = yangon_now()
    cutoff = now - timedelta(days=grace_days)
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT
                o.order_id,
                o.user_id,
                o.item_name,
                o.timestamp,
                o.order_code,
                o.expiry_date,
                (
                    SELECT i.item_id
                    FROM items AS i
                    WHERE TRIM(i.name) = TRIM(o.item_name) COLLATE NOCASE
                    LIMIT 1
                ) AS item_id,
                o.outline_key_id
            FROM orders AS o
            WHERE o.status = 'Success'
              AND COALESCE(o.order_type, 'normal') != 'renewal'
              AND o.expiry_date IS NOT NULL
              AND TRIM(o.expiry_date) != ''
              AND COALESCE(o.renewal_notice_sent, 0) = 0
              AND datetime(o.expiry_date) < datetime(?)
              AND datetime(o.expiry_date) >= datetime(?)
            ORDER BY datetime(o.expiry_date) ASC
            """,
            (
                now.strftime("%Y-%m-%d %H:%M:%S"),
                cutoff.strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
        return cursor.fetchall()

def mark_renewal_notice_sent(order_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE orders SET renewal_notice_sent = 1 WHERE order_id = ?", (order_id,))
        conn.commit()

def get_orders_needing_admin_expiry_notice():
    now_text = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT o.order_id, o.user_id, u.username, u.first_name, u.last_name,
                   o.item_name, o.quantity, o.order_code, o.expiry_date, o.outline_key_id
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'Success'
              AND COALESCE(o.order_type, 'normal') != 'renewal'
              AND o.expiry_date IS NOT NULL
              AND TRIM(o.expiry_date) != ''
              AND COALESCE(o.expiry_admin_notice_sent, 0) = 0
              AND datetime(o.expiry_date) <= datetime(?)
            ORDER BY datetime(o.expiry_date) ASC
            """,
            (now_text,)
        )
        return cursor.fetchall()

def mark_admin_expiry_notice_sent(order_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE orders SET expiry_admin_notice_sent = 1 WHERE order_id = ?",
            (order_id,)
        )
        conn.commit()

# --- Giveaway Functions ---

def get_all_gw_item_types():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT name FROM gw_items")
        return [row[0] for row in cursor.fetchall()]

def get_user_last_gw_claim(user_id):
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT claim_date FROM gw_claims WHERE user_id = ? ORDER BY claim_date DESC LIMIT 1", (user_id,))
            res = cursor.fetchone()
            return res[0] if res else None
    except Exception as e:
        print(f"Database Error (get_user_last_gw_claim): {e}")
        return None

def add_gw_claim(user_id, claim_date):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT INTO gw_claims (user_id, claim_date) VALUES (?, ?)", (user_id, claim_date))
        conn.commit()

def get_available_gw_items_by_type(name):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM gw_items WHERE name = ? AND is_used = FALSE LIMIT 1", (name,))
        return cursor.fetchone()

def mark_gw_item_as_used(gw_item_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE gw_items SET is_used = TRUE WHERE gw_item_id = ?", (gw_item_id,))
        conn.commit()

def reduce_gw_stock(item_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE gw_items SET stock = stock - 1 WHERE gw_item_id = ?", (item_id,))
        cursor.execute("UPDATE gw_items SET is_used = 1 WHERE gw_item_id = ? AND stock <= 0", (item_id,))
        conn.commit()

# --- Referral Program Functions ---

def get_referral_status():
    return get_setting("referral_status", "open")

def set_referral_status(status):
    if status not in ("open", "paused"):
        status = "paused"
    set_setting("referral_status", status)

def get_referral_required_count():
    try:
        return max(1, int(get_setting("referral_required_count", "10")))
    except (TypeError, ValueError):
        return 10

def get_referral_reward_text():
    return get_setting("referral_reward_text", "10,000 MMK တန် product 1 ခု")

def get_valid_referral_count(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND status = 'valid'",
            (user_id,)
        )
        return cursor.fetchone()[0]

def get_pending_referral_for_user(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT referral_id, referrer_id, referred_user_id, status
            FROM referrals
            WHERE referred_user_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (user_id,)
        )
        return cursor.fetchone()

def create_pending_referral(referrer_id, referred_user_id):
    referrer_id = int(referrer_id)
    referred_user_id = int(referred_user_id)
    if referrer_id == referred_user_id:
        return False, "self"
    if get_referral_status() != "open":
        return False, "paused"
    if get_valid_referral_count(referrer_id) >= get_referral_required_count():
        return False, "limit"

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with get_db_connection(DATABASE_NAME) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO referrals (referrer_id, referred_user_id, status, created_at)
                VALUES (?, ?, 'pending', ?)
                """,
                (referrer_id, referred_user_id, now)
            )
            conn.commit()
            return True, "pending"
    except sqlite3.IntegrityError:
        return False, "duplicate"
    except Exception as e:
        print(f"Error creating referral: {e}")
        return False, "error"

def verify_pending_referral(referred_user_id):
    if get_referral_status() != "open":
        return False, "paused", None, 0

    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT referral_id, referrer_id
            FROM referrals
            WHERE referred_user_id = ? AND status = 'pending'
            LIMIT 1
            """,
            (referred_user_id,)
        )
        row = cursor.fetchone()
        if not row:
            return False, "missing", None, 0

        referral_id, referrer_id = row
        cursor.execute(
            "SELECT COUNT(*) FROM referrals WHERE referrer_id = ? AND status = 'valid'",
            (referrer_id,)
        )
        current_count = cursor.fetchone()[0]
        required_count = get_referral_required_count()
        if current_count >= required_count:
            return False, "limit", referrer_id, current_count

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute(
            "UPDATE referrals SET status = 'valid', verified_at = ? WHERE referral_id = ?",
            (now, referral_id)
        )
        conn.commit()
        return True, "valid", referrer_id, current_count + 1

def create_referral_reward_claim(user_id):
    required_count = get_referral_required_count()
    valid_count = get_valid_referral_count(user_id)
    if valid_count < required_count:
        return False, "not_enough", None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT reward_id, status
            FROM referral_rewards
            WHERE user_id = ? AND status IN ('pending', 'approved')
            ORDER BY reward_id DESC
            LIMIT 1
            """,
            (user_id,)
        )
        existing = cursor.fetchone()
        if existing:
            return False, existing[1], existing[0]

        cursor.execute(
            "INSERT INTO referral_rewards (user_id, status, created_at) VALUES (?, 'pending', ?)",
            (user_id, now)
        )
        conn.commit()
        return True, "pending", cursor.lastrowid

def get_referral_reward_status(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT reward_id, status, created_at, reviewed_at
            FROM referral_rewards
            WHERE user_id = ?
            ORDER BY reward_id DESC
            LIMIT 1
            """,
            (user_id,)
        )
        return cursor.fetchone()

def get_pending_referral_rewards(limit=20):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT reward_id, user_id, created_at
            FROM referral_rewards
            WHERE status = 'pending'
            ORDER BY reward_id ASC
            LIMIT ?
            """,
            (limit,)
        )
        return cursor.fetchall()

def update_referral_reward_status(reward_id, status, note=None):
    if status not in ("approved", "rejected"):
        return None
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM referral_rewards WHERE reward_id = ?", (reward_id,))
        row = cursor.fetchone()
        if not row:
            return None
        cursor.execute(
            """
            UPDATE referral_rewards
            SET status = ?, reviewed_at = ?, admin_note = ?
            WHERE reward_id = ?
            """,
            (status, now, note, reward_id)
        )
        conn.commit()
        return row[0]

def get_referral_stats():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE status = 'pending'")
        pending_refs = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM referrals WHERE status = 'valid'")
        valid_refs = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM referral_rewards WHERE status = 'pending'")
        pending_claims = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(DISTINCT referrer_id) FROM referrals WHERE status = 'valid'")
        active_referrers = cursor.fetchone()[0]
        return {
            "status": get_referral_status(),
            "required_count": get_referral_required_count(),
            "reward_text": get_referral_reward_text(),
            "pending_refs": pending_refs,
            "valid_refs": valid_refs,
            "pending_claims": pending_claims,
            "active_referrers": active_referrers,
        }



# --- Special Product Detection (Gift Cards, Telegram Premium & Stars, Outline) ---

def is_gift_card_product(item_name):
    text = str(item_name or "").lower()
    return any(k in text for k in ("gift card", "itunes", "apple card", "google play", "steam", "redeem code"))

def is_apple_gift_card(item_name):
    text = str(item_name or "").lower()
    return ("apple" in text or "itunes" in text) and ("gift" in text or "card" in text or "$" in text)

def is_telegram_direct_product(item_name):
    """Products delivered directly to a recipient @username via @PremiumBot / Fragment."""
    text = str(item_name or "").lower()
    if "link" in text or "code" in text:
        return False
    return ("telegram" in text or "tg " in text) and ("premium" in text or "star" in text)

def is_non_expiring_product(item_name):
    text = str(item_name or "").lower()
    return is_gift_card_product(text) or ("star" in text and ("telegram" in text or "tg" in text))

def ensure_gw_items_columns(cursor):
    cursor.execute("PRAGMA table_info(gw_items)")
    columns = [row[1] for row in cursor.fetchall()]
    if "rules" not in columns:
        cursor.execute("ALTER TABLE gw_items ADD COLUMN rules TEXT DEFAULT 'မည်သူ့ကိုမျှ မမျှဝေပါနှင့်၊၊'")

def ensure_order_target_username_column(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "target_username" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN target_username TEXT")

def update_order_target_username(order_id, target_username):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_target_username_column(cursor)
        cursor.execute("UPDATE orders SET target_username = ? WHERE order_id = ?", (target_username, int(order_id)))
        conn.commit()

def get_order_target_username(order_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_target_username_column(cursor)
        row = cursor.execute("SELECT target_username FROM orders WHERE order_id = ?", (int(order_id),)).fetchone()
        return row[0] if row and row[0] else None

def get_mmk_per_usd():
    from config import MMK_PER_USD
    try:
        val = get_setting("mmk_per_usd", None)
        return float(val) if val else float(MMK_PER_USD)
    except Exception:
        return float(MMK_PER_USD)

def set_mmk_per_usd(rate):
    rate = float(rate)
    if rate <= 0:
        raise ValueError("Rate must be positive")
    set_setting("mmk_per_usd", str(rate))
    return rate

def get_unsold_stock_rows(item_id, limit=30):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        item = cursor.execute("SELECT name FROM items WHERE item_id = ?", (int(item_id),)).fetchone()
        if not item:
            return None, []
        rows = cursor.execute(
            "SELECT stock_id, account_info FROM item_stocks "
            "WHERE TRIM(item_name) = TRIM(?) COLLATE NOCASE AND COALESCE(is_sold, 0) = 0 "
            "ORDER BY stock_id ASC LIMIT ?",
            (item[0], int(limit)),
        ).fetchall()
        return item[0], rows

def delete_unsold_stock_row(stock_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        row = cursor.execute(
            "SELECT item_name, is_sold FROM item_stocks WHERE stock_id = ?",
            (int(stock_id),),
        ).fetchone()
        if not row:
            conn.rollback()
            return {"ok": False, "reason": "not_found"}
        item_name, is_sold = row
        if is_sold:
            conn.rollback()
            return {"ok": False, "reason": "already_sold"}
        cursor.execute("DELETE FROM item_stocks WHERE stock_id = ?", (int(stock_id),))
        cursor.execute(
            "UPDATE items SET stock = MAX(0, stock - 1) WHERE TRIM(name) = TRIM(?) COLLATE NOCASE",
            (item_name,),
        )
        conn.commit()
        return {"ok": True, "item_name": item_name}

def add_gw_item(name, content, stock=1, rules="မည်သူ့ကိုမျှ မမျှဝေပါနှင့်၊၊"):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_gw_items_columns(cursor)
        cursor.execute(
            "INSERT INTO gw_items (name, content, stock, is_used, rules) VALUES (?, ?, ?, 0, ?)",
            (name.strip(), content.strip(), max(1, int(stock)), rules.strip()),
        )
        conn.commit()
        return cursor.lastrowid



# ==========================================================
# 🌟 ALL USER FEATURES: Wallet, Daily Check-in, VIP Discount,
#    Waitlist, Support Tickets & Profile
# ==========================================================

OUTLINE_GUIDE_POST_URL = "https://t.me/ENIpremiumstore/19"

def init_extra_feature_tables():
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        # 1. Stock Waitlist
        cursor.execute('''CREATE TABLE IF NOT EXISTS stock_waitlist
            (id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL,
             item_id INTEGER NOT NULL,
             created_at TEXT NOT NULL,
             UNIQUE(user_id, item_id))''')

        # 2. Support / Warranty Tickets
        cursor.execute('''CREATE TABLE IF NOT EXISTS support_tickets
            (ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
             order_id INTEGER NOT NULL,
             user_id INTEGER NOT NULL,
             issue_text TEXT NOT NULL,
             status TEXT NOT NULL DEFAULT 'open',
             created_at TEXT NOT NULL,
             resolved_at TEXT,
             resolved_by INTEGER)''')

        # 3. User Wallet & Daily Check-in Points
        cursor.execute('''CREATE TABLE IF NOT EXISTS user_wallets
            (user_id INTEGER PRIMARY KEY,
             balance REAL NOT NULL DEFAULT 0,
             points INTEGER NOT NULL DEFAULT 0,
             streak INTEGER NOT NULL DEFAULT 0,
             last_checkin_date TEXT DEFAULT '')''')

        # 4. Wallet Top-up Requests
        cursor.execute('''CREATE TABLE IF NOT EXISTS wallet_topups
            (topup_id INTEGER PRIMARY KEY AUTOINCREMENT,
             user_id INTEGER NOT NULL,
             amount REAL NOT NULL,
             payment_method TEXT NOT NULL,
             file_unique_id TEXT UNIQUE,
             status TEXT NOT NULL DEFAULT 'pending',
             created_at TEXT NOT NULL,
             reviewed_at TEXT,
             reviewed_by INTEGER)''')
        if ADMIN_ID:
            cursor.execute("UPDATE users SET role = 'owner' WHERE user_id = ?", (int(ADMIN_ID),))
        conn.commit()

init_extra_feature_tables()


# --- Wallet & Points Functions ---

def _ensure_wallet_row(cursor, user_id):
    cursor.execute(
        "INSERT OR IGNORE INTO user_wallets (user_id, balance, points, streak, last_checkin_date) VALUES (?, 0, 0, 0, '')",
        (int(user_id),)
    )

def get_user_wallet(user_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        _ensure_wallet_row(cursor, user_id)
        row = cursor.execute(
            "SELECT balance, points, streak, last_checkin_date FROM user_wallets WHERE user_id = ?",
            (int(user_id),)
        ).fetchone()
        conn.commit()
        return {
            "balance": float(row[0] or 0.0),
            "points": int(row[1] or 0),
            "streak": int(row[2] or 0),
            "last_checkin_date": str(row[3] or ""),
        }

def adjust_user_wallet_balance(user_id, delta_mmk):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        _ensure_wallet_row(cursor, user_id)
        current = float(cursor.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (int(user_id),)).fetchone()[0] or 0.0)
        new_balance = current + float(delta_mmk)
        if new_balance < 0:
            conn.rollback()
            return False, current
        cursor.execute("UPDATE user_wallets SET balance = ? WHERE user_id = ?", (new_balance, int(user_id)))
        conn.commit()
        return True, new_balance

def create_wallet_topup_request(user_id, amount, method, file_unique_id):
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        try:
            cursor.execute(
                "INSERT INTO wallet_topups (user_id, amount, payment_method, file_unique_id, status, created_at) VALUES (?, ?, ?, ?, 'pending', ?)",
                (int(user_id), float(amount), str(method), str(file_unique_id), now)
            )
            conn.commit()
            return cursor.lastrowid, None
        except sqlite3.IntegrityError:
            return None, "duplicate_proof"

def process_wallet_topup_request(topup_id, admin_id, approve=True):
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        row = cursor.execute(
            "SELECT user_id, amount, status FROM wallet_topups WHERE topup_id = ?",
            (int(topup_id),)
        ).fetchone()
        if not row:
            conn.rollback()
            return None, "not_found"
        user_id, amount, status = int(row[0]), float(row[1]), row[2]
        if status != "pending":
            conn.rollback()
            return None, status
        new_status = "approved" if approve else "rejected"
        cursor.execute(
            "UPDATE wallet_topups SET status = ?, reviewed_at = ?, reviewed_by = ? WHERE topup_id = ?",
            (new_status, now, int(admin_id), int(topup_id))
        )
        new_balance = 0.0
        if approve:
            _ensure_wallet_row(cursor, user_id)
            cursor.execute(
                "UPDATE user_wallets SET balance = balance + ? WHERE user_id = ?",
                (amount, user_id)
            )
            new_balance = float(cursor.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (user_id,)).fetchone()[0] or 0.0)
        conn.commit()
    if approve:
        push_app_notification(
            user_id, "topup_approved", "💰 Top-up အတည်ပြုပြီးပါပြီ",
            f"{amount:,.0f} Ks ထည့်ပေးပြီးပါပြီ။ လက်ကျန်: {new_balance:,.0f} Ks",
            ref=f"topup:{topup_id}",
        )
    else:
        push_app_notification(
            user_id, "topup_rejected", "❌ Top-up လက်မခံပါ",
            f"{amount:,.0f} Ks top-up ကို Admin က လက်မခံပါ။ Receipt မှန်မမှန် စစ်ပြီး ပြန်တင်ပါ။",
            ref=f"topup:{topup_id}",
        )
    return {"user_id": user_id, "amount": amount, "new_balance": new_balance, "status": new_status}, None

def claim_daily_checkin(user_id):
    today_dt = yangon_now().date()
    today_str = today_dt.strftime("%Y-%m-%d")
    yesterday_str = (today_dt - timedelta(days=1)).strftime("%Y-%m-%d")

    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        _ensure_wallet_row(cursor, user_id)
        points, streak, last_date = cursor.execute(
            "SELECT points, streak, last_checkin_date FROM user_wallets WHERE user_id = ?",
            (int(user_id),)
        ).fetchone()
        if last_date == today_str:
            conn.rollback()
            return {"ok": False, "points": int(points or 0), "streak": int(streak or 0)}

        new_streak = (int(streak or 0) + 1) if last_date == yesterday_str else 1
        earned = 20 + min(30, (new_streak - 1) * 5)
        bonus = 100 if (new_streak % 7 == 0) else 0
        total_earned = earned + bonus
        new_points = int(points or 0) + total_earned

        cursor.execute(
            "UPDATE user_wallets SET points = ?, streak = ?, last_checkin_date = ? WHERE user_id = ?",
            (new_points, new_streak, today_str, int(user_id))
        )
        conn.commit()
        return {
            "ok": True,
            "earned": total_earned,
            "bonus": bonus,
            "points": new_points,
            "streak": new_streak,
        }

def redeem_points_to_wallet(user_id, points_needed=500, mmk_reward=1000):
    """Exchange 500 Points -> 1,000 MMK Wallet Balance."""
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        _ensure_wallet_row(cursor, user_id)
        pts, bal = cursor.execute(
            "SELECT points, balance FROM user_wallets WHERE user_id = ?",
            (int(user_id),)
        ).fetchone()
        if int(pts or 0) < int(points_needed):
            conn.rollback()
            return {"ok": False, "points": int(pts or 0)}
        new_pts = int(pts) - int(points_needed)
        new_bal = float(bal or 0.0) + float(mmk_reward)
        cursor.execute(
            "UPDATE user_wallets SET points = ?, balance = ? WHERE user_id = ?",
            (new_pts, new_bal, int(user_id))
        )
        conn.commit()
        return {"ok": True, "points": new_pts, "balance": new_bal, "reward": mmk_reward}


# --- Profile & VIP Tier Auto-Discount ---

def get_user_profile_stats(user_id):
    user_id = int(user_id)
    wallet = get_user_wallet(user_id)
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        user_row = cursor.execute(
            "SELECT join_date, COALESCE(role, 'user') FROM users WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        order_row = cursor.execute(
            """
            SELECT COUNT(order_id), COALESCE(SUM(total_amount), 0)
            FROM orders
            WHERE user_id = ? AND status = 'Success'
            """,
            (user_id,)
        ).fetchone()
        join_date = user_row[0] if user_row else "-"
        db_role = user_row[1] if user_row else "user"
        total_orders = int(order_row[0] or 0) if order_row else 0
        total_spent = float(order_row[1] or 0.0) if order_row else 0.0

        if is_master_admin(user_id):
            role = "owner"
            tier = "👑 Store Owner (Master Admin)"
            vip_discount_percent = 6 if total_spent >= 300000 else (4 if total_spent >= 150000 else (2 if total_spent >= 50000 else 0))
        elif is_admin_user(user_id):
            role = "admin"
            tier = "🛡 Store Administrator"
            vip_discount_percent = 6 if total_spent >= 300000 else (4 if total_spent >= 150000 else (2 if total_spent >= 50000 else 0))
        else:
            role = db_role if db_role not in ("owner", "admin") else "user"
            if total_spent >= 300000:
                tier = "💎 Diamond VIP (6% OFF)"
                vip_discount_percent = 6
            elif total_spent >= 150000:
                tier = "🥇 Gold Member (4% OFF)"
                vip_discount_percent = 4
            elif total_spent >= 50000:
                tier = "🥈 Silver Member (2% OFF)"
                vip_discount_percent = 2
            else:
                tier = "🥉 Regular Member"
                vip_discount_percent = 0

        if user_row and db_role != role:
            cursor.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
            conn.commit()

        return {
            "user_id": user_id,
            "role": role,
            "join_date": join_date,
            "total_orders": total_orders,
            "total_spent": total_spent,
            "tier": tier,
            "vip_discount_percent": vip_discount_percent,
            "balance": wallet["balance"],
            "points": wallet["points"],
            "streak": wallet["streak"],
        }

def get_user_vip_discount_percent(user_id, item_name=""):
    """Return VIP discount percent (0 for Gift Cards)."""
    if is_gift_card_product(item_name):
        return 0
    stats = get_user_profile_stats(user_id)
    return int(stats.get("vip_discount_percent") or 0)


# --- Waitlist & Support Ticket Functions ---

def add_stock_waitlist(user_id, item_id):
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO stock_waitlist (user_id, item_id, created_at) VALUES (?, ?, ?)",
            (int(user_id), int(item_id), now)
        )
        conn.commit()
        return cursor.rowcount > 0

def pop_stock_waitlist_users(item_id):
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT user_id FROM stock_waitlist WHERE item_id = ?", (int(item_id),)).fetchall()
        if rows:
            cursor.execute("DELETE FROM stock_waitlist WHERE item_id = ?", (int(item_id),))
            conn.commit()
        return [int(r[0]) for r in rows]

def create_support_ticket(order_id, user_id, issue_text):
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO support_tickets (order_id, user_id, issue_text, status, created_at) VALUES (?, ?, ?, 'open', ?)",
            (int(order_id), int(user_id), str(issue_text).strip(), now)
        )
        conn.commit()
        return cursor.lastrowid

def close_support_ticket(ticket_id, admin_id):
    now = yangon_now().strftime("%Y-%m-%d %H:%M:%S")
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE support_tickets SET status = 'closed', resolved_at = ?, resolved_by = ? WHERE ticket_id = ?",
            (now, int(admin_id), int(ticket_id))
        )
        conn.commit()
        return cursor.rowcount > 0



# --- Direct User-to-User Gift Purchase & Wallet Transfer Functions ---

def ensure_order_gift_columns(cursor):
    cursor.execute("PRAGMA table_info(orders)")
    columns = [row[1] for row in cursor.fetchall()]
    if "gift_recipient_id" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN gift_recipient_id INTEGER")
    if "gift_recipient_label" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN gift_recipient_label TEXT")
    if "gift_message" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN gift_message TEXT")
    if "gift_sender_name" not in columns:
        cursor.execute("ALTER TABLE orders ADD COLUMN gift_sender_name TEXT")

with get_db_connection(DATABASE_NAME) as _conn:
    ensure_order_gift_columns(_conn.cursor())
    _conn.commit()

def find_bot_user_by_identifier(identifier):
    """Find a bot user by numeric User ID or @username."""
    raw = str(identifier or "").strip()
    if not raw:
        return None
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        if re.fullmatch(r"\d{5,15}", raw):
            row = cursor.execute(
                "SELECT user_id, COALESCE(username, ''), COALESCE(first_name, ''), COALESCE(last_name, '') FROM users WHERE user_id = ?",
                (int(raw),)
            ).fetchone()
            if row:
                full_name = " ".join(p for p in (row[2], row[3]) if p).strip() or f"User {row[0]}"
                uname = f"@{row[1]}" if row[1] else f"ID:{row[0]}"
                return {"user_id": int(row[0]), "username": row[1], "name": full_name, "display": f"{full_name} ({uname})"}
            return None

        clean_uname = raw.lstrip("@").strip()
        if not clean_uname:
            return None
        row = cursor.execute(
            "SELECT user_id, COALESCE(username, ''), COALESCE(first_name, ''), COALESCE(last_name, '') "
            "FROM users WHERE LOWER(TRIM(COALESCE(username, ''))) = LOWER(TRIM(?)) LIMIT 1",
            (clean_uname,)
        ).fetchone()
        if row:
            full_name = " ".join(p for p in (row[2], row[3]) if p).strip() or f"@{clean_uname}"
            uname = f"@{row[1]}" if row[1] else f"@{clean_uname}"
            return {"user_id": int(row[0]), "username": row[1], "name": full_name, "display": f"{full_name} ({uname})"}
    return None

def set_order_gift_metadata(order_id, recipient_id, recipient_label, gift_message, sender_name):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_gift_columns(cursor)
        cursor.execute(
            """
            UPDATE orders
            SET gift_recipient_id = ?,
                gift_recipient_label = ?,
                gift_message = ?,
                gift_sender_name = ?
            WHERE order_id = ?
            """,
            (int(recipient_id), str(recipient_label or ""), str(gift_message or ""), str(sender_name or ""), int(order_id))
        )
        conn.commit()

def get_order_gift_metadata(order_id):
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_gift_columns(cursor)
        row = cursor.execute(
            "SELECT gift_recipient_id, gift_recipient_label, gift_message, gift_sender_name FROM orders WHERE order_id = ?",
            (int(order_id),)
        ).fetchone()
        if not row or not row[0]:
            return None
        return {
            "recipient_id": int(row[0]),
            "recipient_label": str(row[1] or f"ID:{row[0]}"),
            "gift_message": str(row[2] or "Enjoy your special digital gift! 🎉"),
            "sender_name": str(row[3] or "Your Friend"),
        }

def transfer_wallet_balance_between_users(sender_id, recipient_id, amount_mmk):
    """Atomically transfer MMK balance from one bot user's wallet to another."""
    sender_id, recipient_id = int(sender_id), int(recipient_id)
    amount = float(amount_mmk)
    if amount <= 0 or sender_id == recipient_id:
        return {"ok": False, "reason": "invalid"}
    with get_db_connection(DATABASE_NAME, timeout=10) as conn:
        cursor = conn.cursor()
        cursor.execute("BEGIN IMMEDIATE")
        _ensure_wallet_row(cursor, sender_id)
        _ensure_wallet_row(cursor, recipient_id)
        sender_bal = float(cursor.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (sender_id,)).fetchone()[0] or 0.0)
        if sender_bal < amount:
            conn.rollback()
            return {"ok": False, "reason": "insufficient_balance", "balance": sender_bal}
        new_sender_bal = round(sender_bal - amount, 2)
        cursor.execute("UPDATE user_wallets SET balance = ? WHERE user_id = ?", (new_sender_bal, sender_id))
        cursor.execute("UPDATE user_wallets SET balance = balance + ? WHERE user_id = ?", (amount, recipient_id))
        new_recipient_bal = float(cursor.execute("SELECT balance FROM user_wallets WHERE user_id = ?", (recipient_id,)).fetchone()[0] or 0.0)
        conn.commit()
        return {
            "ok": True,
            "amount": amount,
            "sender_balance": new_sender_bal,
            "recipient_balance": new_recipient_bal,
        }



# --- Admin Outline Key Mapping & Expiry Dashboard Functions ---

def get_outline_orders_map():
    """Map outline_key_id and order_code to buyer/order details for Admin Outline Usage report."""
    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_outline_columns(cursor)
        rows = cursor.execute(
            """
            SELECT
                o.order_id,
                o.order_code,
                o.user_id,
                COALESCE(u.username, ''),
                COALESCE(u.first_name, ''),
                COALESCE(u.last_name, ''),
                o.item_name,
                o.expiry_date,
                COALESCE(o.outline_key_id, ''),
                COALESCE(o.delivered_data, '')
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'Success'
              AND LOWER(COALESCE(o.item_name, '')) LIKE '%outline%'
            ORDER BY o.order_id DESC
            """
        ).fetchall()

        by_key_id = {}
        by_order_code = {}
        for r in rows:
            order_id, order_code, user_id, uname, fname, lname, item_name, expiry_date, key_id, delivered_data = r
            if not key_id and delivered_data:
                parsed_id, _ = parse_outline_key_info(delivered_data)
                key_id = parsed_id or ""
            full_name = " ".join(p for p in (fname, lname) if p).strip() or f"User {user_id}"
            uname_str = f"@{uname}" if uname else f"ID:{user_id}"
            info = {
                "order_id": order_id,
                "order_code": order_code or f"ORD-{order_id}",
                "user_id": user_id,
                "buyer_display": f"{full_name} ({uname_str})",
                "item_name": item_name,
                "expiry_date": expiry_date or "-",
                "key_id": str(key_id).strip(),
            }
            if info["key_id"] and info["key_id"] not in by_key_id:
                by_key_id[info["key_id"]] = info
            if order_code:
                by_order_code[str(order_code).upper()] = info
        return {"by_key_id": by_key_id, "by_order_code": by_order_code}

def get_expiring_and_expired_orders_for_admin(days_ahead=7, expired_days_back=14):
    """Return all active orders expiring within `days_ahead` days + recently expired orders."""
    now = yangon_now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    future_str = (now + timedelta(days=int(days_ahead))).strftime("%Y-%m-%d %H:%M:%S")
    past_str = (now - timedelta(days=int(expired_days_back))).strftime("%Y-%m-%d %H:%M:%S")

    with get_db_connection(DATABASE_NAME) as conn:
        cursor = conn.cursor()
        ensure_order_outline_columns(cursor)
        expiring_soon = cursor.execute(
            """
            SELECT
                o.order_id, o.order_code, o.user_id,
                COALESCE(u.username, ''), COALESCE(u.first_name, ''), COALESCE(u.last_name, ''),
                o.item_name, o.quantity, o.expiry_date, COALESCE(o.outline_key_id, '')
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'Success'
              AND COALESCE(o.order_type, 'normal') != 'renewal'
              AND o.expiry_date IS NOT NULL AND TRIM(o.expiry_date) != ''
              AND datetime(o.expiry_date) > datetime(?)
              AND datetime(o.expiry_date) <= datetime(?)
            ORDER BY datetime(o.expiry_date) ASC
            """,
            (now_str, future_str)
        ).fetchall()

        recently_expired = cursor.execute(
            """
            SELECT
                o.order_id, o.order_code, o.user_id,
                COALESCE(u.username, ''), COALESCE(u.first_name, ''), COALESCE(u.last_name, ''),
                o.item_name, o.quantity, o.expiry_date, COALESCE(o.outline_key_id, '')
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'Success'
              AND COALESCE(o.order_type, 'normal') != 'renewal'
              AND o.expiry_date IS NOT NULL AND TRIM(o.expiry_date) != ''
              AND datetime(o.expiry_date) <= datetime(?)
              AND datetime(o.expiry_date) >= datetime(?)
            ORDER BY datetime(o.expiry_date) DESC
            """,
            (now_str, past_str)
        ).fetchall()

        all_active_upcoming = cursor.execute(
            """
            SELECT
                o.order_id, o.order_code, o.user_id,
                COALESCE(u.username, ''), COALESCE(u.first_name, ''), COALESCE(u.last_name, ''),
                o.item_name, o.quantity, o.expiry_date, COALESCE(o.outline_key_id, '')
            FROM orders o
            LEFT JOIN users u ON u.user_id = o.user_id
            WHERE o.status = 'Success'
              AND COALESCE(o.order_type, 'normal') != 'renewal'
              AND o.expiry_date IS NOT NULL AND TRIM(o.expiry_date) != ''
              AND datetime(o.expiry_date) > datetime(?)
            ORDER BY datetime(o.expiry_date) ASC
            LIMIT 30
            """,
            (now_str,)
        ).fetchall()

    return {
        "now": now,
        "expiring_soon": expiring_soon,
        "recently_expired": recently_expired,
        "all_active_upcoming": all_active_upcoming,
    }