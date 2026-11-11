"""Auto-Verification Client for English/Crypto Payments:
1. USDT (ERC20 / BEP20) On-Chain Transaction Hash (TxID) Verification via Etherscan V2 / BscScan API.
2. Binance Pay Auto-Verification via Personal Read-Only API (`GET /sapi/v1/pay/transactions`).
3. Telegram @CryptoBot (Crypto Pay API) One-Click Invoice Creation & Verification.
"""
import hashlib
import hmac
import json
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from config import (
    USDT_ERC20_ADDRESS,
    USDT_BEP20_ADDRESS,
    BINANCE_API_KEY,
    BINANCE_API_SECRET,
    ETHERSCAN_API_KEY,
    BSCSCAN_API_KEY,
    CRYPTOPAY_API_TOKEN,
)

# Official USDT Smart Contract Addresses & Transfer Event Topic
ERC20_USDT_CONTRACT = "0xdac17f958d2ee523a2206206994597c13d831ec7"
BEP20_USDT_CONTRACT = "0x55d398326f99059ff775485246999027b3197955"
TRANSFER_EVENT_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"


def is_binance_api_configured():
    return bool(BINANCE_API_KEY and BINANCE_API_SECRET)


def is_onchain_api_configured(network="erc20"):
    if str(network).lower() == "bep20":
        return bool(BSCSCAN_API_KEY or ETHERSCAN_API_KEY)
    return bool(ETHERSCAN_API_KEY)


def is_cryptopay_configured():
    return bool(CRYPTOPAY_API_TOKEN)


def _http_get_json(url, headers=None, timeout=15):
    req = Request(url, headers=headers or {"User-Agent": "ENIStoreBot/1.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post_json(url, payload, headers=None, timeout=15):
    data = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json", "User-Agent": "ENIStoreBot/1.0"}
    if headers:
        req_headers.update(headers)
    req = Request(url, data=data, headers=req_headers, method="POST")
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def verify_evm_usdt_transaction(tx_hash, expected_usd_amount, network="bep20"):
    """Verify an ERC20 or BEP20 USDT transfer on-chain by Transaction Hash (0x...)."""
    net = str(network or "bep20").lower()
    clean_tx = str(tx_hash or "").strip()
    if not re.fullmatch(r"0x[a-fA-F0-9]{64}", clean_tx):
        return {
            "ok": False,
            "reason": "Invalid Transaction Hash (TxID) format. It must start with 0x followed by 64 hex characters.",
        }

    if net == "erc20":
        chain_id = 1
        api_key = ETHERSCAN_API_KEY
        expected_wallet = (USDT_ERC20_ADDRESS or "").strip().lower()
        usdt_contract = ERC20_USDT_CONTRACT
        decimals = 6
    else:
        chain_id = 56
        api_key = BSCSCAN_API_KEY or ETHERSCAN_API_KEY
        expected_wallet = (USDT_BEP20_ADDRESS or "").strip().lower()
        usdt_contract = BEP20_USDT_CONTRACT
        decimals = 18

    if not expected_wallet or not expected_wallet.startswith("0x"):
        return {"ok": False, "reason": f"Store {net.upper()} wallet address is not configured."}
    if not api_key:
        return {"ok": False, "reason": "Blockchain Explorer API Key (ETHERSCAN_API_KEY) is not configured in .env."}

    url = (
        f"https://api.etherscan.io/v2/api?chainid={chain_id}"
        f"&module=proxy&action=eth_getTransactionReceipt&txhash={clean_tx}&apikey={api_key}"
    )
    try:
        data = _http_get_json(url)
    except Exception as err:
        return {"ok": False, "reason": f"Blockchain API connection error: {err}"}

    receipt = data.get("result")
    if not isinstance(receipt, dict):
        return {
            "ok": False,
            "reason": "Transaction not found or still pending on the blockchain. Please wait 30 seconds and try again.",
        }

    status = str(receipt.get("status") or "").lower()
    if status != "0x1":
        return {"ok": False, "reason": "This transaction failed (reverted) on the blockchain."}

    logs = receipt.get("logs") or []
    matched_usdt = 0.0
    target_topic_suffix = expected_wallet[2:].lower().rjust(64, "0")

    for log in logs:
        contract_addr = str(log.get("address") or "").lower()
        topics = [str(t).lower() for t in (log.get("topics") or [])]
        if contract_addr != usdt_contract or len(topics) < 3:
            continue
        if topics[0] != TRANSFER_EVENT_TOPIC:
            continue
        if not topics[2].endswith(target_topic_suffix):
            continue
        raw_hex = str(log.get("data") or "0x0")
        try:
            raw_val = int(raw_hex, 16)
            matched_usdt += raw_val / (10 ** decimals)
        except ValueError:
            continue

    if matched_usdt <= 0:
        return {
            "ok": False,
            "reason": f"No USDT ({net.upper()}) transfer to our store wallet ({expected_wallet[:8]}...{expected_wallet[-4:]}) was found in this transaction.",
        }

    required = round(float(expected_usd_amount), 2)
    # Allow a tiny $0.03 rounding/fee tolerance
    if matched_usdt + 0.03 < required:
        return {
            "ok": False,
            "reason": f"Insufficient USDT amount sent. Expected ${required:.2f} USDT, but received ${matched_usdt:.2f} USDT.",
        }

    return {
        "ok": True,
        "network": net.upper(),
        "tx_id": f"TX:{clean_tx.lower()}",
        "paid_amount": round(matched_usdt, 2),
    }


def verify_binance_pay_transaction(order_code, expected_usd_amount, user_input_tx_or_note=""):
    """Check recent Binance Pay incoming transactions via Read-Only Personal API."""
    if not is_binance_api_configured():
        return {"ok": False, "reason": "BINANCE_API_KEY / BINANCE_API_SECRET is not configured in .env."}

    timestamp = int(time.time() * 1000)
    params = {"limit": 50, "timestamp": timestamp, "recvWindow": 10000}
    query_string = urlencode(params)
    signature = hmac.new(
        BINANCE_API_SECRET.encode("utf-8"),
        query_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    url = f"https://api.binance.com/sapi/v1/pay/transactions?{query_string}&signature={signature}"
    try:
        resp = _http_get_json(url, headers={"X-MBX-APIKEY": BINANCE_API_KEY})
    except HTTPError as err:
        body = err.read().decode("utf-8", errors="replace")[:200]
        return {"ok": False, "reason": f"Binance API HTTP {err.code}: {body}"}
    except Exception as err:
        return {"ok": False, "reason": f"Binance API connection error: {err}"}

    if not resp.get("success") and "data" not in resp:
        return {"ok": False, "reason": f"Binance API response error: {resp.get('message', 'Unknown error')}"}

    tx_list = resp.get("data") or []
    required = round(float(expected_usd_amount), 2)
    clean_order_code = str(order_code or "").strip().upper()
    clean_user_tx = str(user_input_tx_or_note or "").strip().upper()

    for tx in tx_list:
        amt = float(tx.get("amount") or 0)
        if amt <= 0:
            # Negative amount means outgoing transfer; skip
            continue
        currency = str(tx.get("currency") or "").upper()
        if currency not in ("USDT", "USDC", "BUSD", "FDUSD"):
            continue
        if amt + 0.03 < required:
            continue

        tx_id = str(tx.get("transactionId") or tx.get("orderId") or "").strip()
        note = str(tx.get("note") or "").strip().upper()

        matched = False
        if clean_order_code and clean_order_code in note:
            matched = True
        elif clean_user_tx and len(clean_user_tx) >= 6 and (clean_user_tx == tx_id.upper() or clean_user_tx in note):
            matched = True

        if matched and tx_id:
            return {
                "ok": True,
                "tx_id": f"BINANCE:{tx_id}",
                "paid_amount": round(amt, 2),
                "currency": currency,
            }

    return {
        "ok": False,
        "reason": (
            f"No matching incoming Binance Pay transfer of ${required:.2f} USDT was found yet. "
            f"Make sure you included '{clean_order_code}' in the payment note, or send your Binance Pay Order/Transaction ID."
        ),
    }


def create_cryptopay_invoice(amount_usd, order_code, item_name):
    """Create a Telegram @CryptoBot invoice for instant 1-click USDT payment."""
    if not is_cryptopay_configured():
        return {"ok": False, "reason": "CRYPTOPAY_API_TOKEN is not configured in .env."}
    url = "https://pay.crypt.bot/api/createInvoice"
    payload = {
        "asset": "USDT",
        "amount": f"{max(0.10, float(amount_usd)):.2f}",
        "description": f"ENI Store - {item_name} ({order_code})"[:250],
        "payload": str(order_code),
        "expires_in": 600,
    }
    try:
        resp = _http_post_json(url, payload, headers={"Crypto-Pay-API-Token": CRYPTOPAY_API_TOKEN})
        if not resp.get("ok"):
            return {"ok": False, "reason": str(resp.get("error") or "CryptoBot error")}
        res = resp["result"]
        return {
            "ok": True,
            "invoice_id": int(res["invoice_id"]),
            "pay_url": res.get("bot_invoice_url") or res.get("pay_url"),
            "amount": res.get("amount"),
        }
    except Exception as err:
        return {"ok": False, "reason": str(err)}


def check_cryptopay_invoice(invoice_id):
    """Check whether a @CryptoBot invoice has been paid."""
    if not is_cryptopay_configured():
        return {"ok": False, "reason": "CRYPTOPAY_API_TOKEN is not configured."}
    url = f"https://pay.crypt.bot/api/getInvoices?invoice_ids={int(invoice_id)}"
    try:
        resp = _http_get_json(url, headers={"Crypto-Pay-API-Token": CRYPTOPAY_API_TOKEN})
        items = (resp.get("result") or {}).get("items") or []
        if not items:
            return {"ok": False, "reason": "Invoice not found."}
        inv = items[0]
        status = str(inv.get("status") or "")
        if status == "paid":
            return {
                "ok": True,
                "status": "paid",
                "tx_id": f"CRYPTOBOT:{inv['invoice_id']}",
                "paid_amount": float(inv.get("amount") or 0),
            }
        return {"ok": False, "status": status, "reason": f"Invoice status is '{status}' (not paid yet)."}
    except Exception as err:
        return {"ok": False, "reason": str(err)}
