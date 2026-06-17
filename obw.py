import os
import base64
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+ native timezone handling
from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Target operational timezone for PayNet validation matching
MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")

# ==========================================
# 1. ENCRYPTION & KEY CONFIGURATION
# ==========================================
PRIVATE_KEY_PEM = b"""-----BEGIN PRIVATE KEY-----
MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDZs3E7WrYyeOTv
dyeUPoX1ZjOcvS1sAhm+1Jjf7098iTvbla5uc1IDDKPCzmRNSBEZvJlXo2OXiyMc
sRc4EqyFgc1GadcvBtXpjfec0Lk7yqQ1M8X08tr26fNB9PoTVu1U5zIUYUTQY0Ga
yNh0ZHUofjCq/dDd/HK/+BmwXo30HQoTY40r36gden/VJ82JUa0JGIBfyJEcIl+2
mFRKopGPEbWguqQDpaB+Oaab812arRnRnw58EpE6FPZz2hg/XTUiWFvv04EVtPqD
Y3dLzNgajEZcokAqcIyX04RJl/CFronAfEMKo7hZej/GPZcTVi2UXNCRoqtQYJOK
IFcYpg+NAgMBAAECggEAMXaaeyRsskISrjASD5Y3JJ9AidPX3qsJg3jVdUfv9PlP
XuB+/fx4vVWhXbE8S+zcac8WvjlS9ws3gpzgDC7+AOWRqPaCXF5+uu61PG2WMLYl
oirtxu5o/uIAEdPiAAPnr7tJ/yRsmLZ8oPkSaTur/PPTBf7edpmVzvVFjPOm6DhH
ZjzFlH+0seAmw3RPGYulbwSGl7rgmOCt/Xg8UVluvi4yH7BB+jcWlnm+aOPg0Xy9
2k/Ksruh27NqgJfogT+t15iOG62A8BSK3HrsWNGNtkAt2hZI/M2DZ44Vk4Z9UlIB
ZhrhzBJzz4JwweihzW6uBRegpoFcsX7g1bigCJzNwQKBgQD7MqQ0qeEzGfL8n5/f
aEpFTk5f8gDZ3lhMBkxE2+o0qvt6GdNobP5mp7lYd0dvf2hUzx4/2qK/1pG+pK0C
VXkIlMmCH7bqMy+/ieLKvZoB47YjiR9lSaXZNKMiH2DMNNoUn7MFT/MB3in3f4Bz
mWFEGORKX1w69wn2KM6V3f50IQKBgQDd3N4fc2+WOkfLxE+J+E4XVhQaSW2FIWIV
cI/V4Vg7M3JrmSefiR8yPxe3+ddJAPsT/Vw2pI9hlRKoSfSdwT7wQ45bexpjBfH6
/lrCetvuCY3d8yam8GTIMFWyYbXpNCgGX8yWMT5CCi9PzyBO17BOuOm/ZqsG3m4n
XOA40FLt7QKBgFtOxx1VesRmdEqbgzNj50tV8WsyvlhzV8kaqPKGtZU7aXmylYPp
yndqFBcyFEdVGolpV+eCA5KT3hpcJX8prnsOCklAWe67eGm5JzTmwmpZaUV1fHIG
2UAgwAORQFA6DeNdQWd27jAJn1uVfw2F/TMRkTnve8j7LyXJI36aWPnBAoGBAMKm
1G8tnVplmbYqb0pygzkwOYTypVcneeGrl1akVf/i3GGQxtXOvYMdHdc5KWwQozjf
kjcS3AVWgD8MW8TI1kqASvbyI617etmmrcRxfGH1GfYALgpLYXDOD3HpDmwjaXZm
OJ4RaDkSrH3OEN97l2EKFXLrReRJ5MU+VC8kf43lAoGBAPnGI5DBDGZSDsuC4e3z
PF8m7Fne7LeVAk3UvKStXKGgiZIh+eevdshFIZRzE1qCcV9X/vrFUtIrgmdY+ehk
PJW+X8NDyVU4OERJ/ME1d7KDTDzut9olJmuW3E+k6knIhP8Kijlfdv1oDCRqLUGn
I5XlRMgr/ra75mTU1dLd73vP
-----END PRIVATE KEY-----"""

private_key = serialization.load_pem_private_key(
    PRIVATE_KEY_PEM,
    password=None,
)

def generate_signature(message_id: str, transaction_id: str) -> str:
    client_id = "M0043439"
    bic = "RPPEMYKL"
    message = f"{client_id}{bic}{message_id}{transaction_id}{message_id}{client_id}".encode()
    signature = private_key.sign(
        message,
        padding.PKCS1v15(),
        hashes.SHA256()
    )
    return base64.b64encode(signature).decode()


# ==========================================
# 2. STATE & DEDICATED LOGGING SETUP
# ==========================================
log_date_str = datetime.now(MY_TZ).strftime("%d%m%Y")
log_filename = f"api_payloads_{log_date_str}.log"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s]\n%(message)s\n' + '='*50 + '\n',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler()
    ]
)

access_token_data = {
    "token": None,
    "expires_in": None,
    "timestamp": None
}

sequence_counter = {
    "value": 1,
    "date": datetime.now(MY_TZ).date()
}

# Cache mapped cleanly to target structural categories
cached_bank_list = {
    "personal": [],
    "corporate": []
}


# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def get_sequence_number():
    today = datetime.now(MY_TZ).date()
    if sequence_counter["date"] != today:
        sequence_counter["value"] = 1
        sequence_counter["date"] = today
    sequence_number = f"{sequence_counter['value']:08d}"
    sequence_counter["value"] += 1
    return sequence_number

def is_token_expired():
    if not access_token_data["token"] or not access_token_data["timestamp"]:
        return True
    expiry_time = access_token_data["timestamp"] + timedelta(seconds=access_token_data["expires_in"] - 60)
    return datetime.now(MY_TZ) >= expiry_time


# ==========================================
# 4. API CALLS WITH CLEAN CACHE SORTING
# ==========================================
def fetch_token():
    url = "https://sandbox.api.paynet.my/auth/token"
    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    data = {
        "grant_type": "client_credentials",
        "client_id": "83b5f4201500412db72639889b59a7dc",
        "client_secret": "F9ae1de743124bcF94eba8FA7d93A2D3"
    }

    try:
        response = requests.post(url, headers=headers, data=data)
        
        log_msg = (
            f"🌐 [API REQUEST] -> POST Token\n"
            f"URL: {url}\n"
            f"Headers: {headers}\n"
            f"Body Data: {data}\n\n"
            f"📥 [API RESPONSE]\n"
            f"Status Code: {response.status_code}\n"
            f"Body Content: {response.text}"
        )
        logging.info(log_msg)

        if response.status_code == 200:
            response_data = response.json()
            access_token_data["token"] = response_data.get("access_token")
            access_token_data["expires_in"] = response_data.get("expires_in")
            access_token_data["timestamp"] = datetime.now(MY_TZ)

            timestamp_str = access_token_data["timestamp"].strftime("%d%m%Y%H%M%S")
            filename = f"token_{timestamp_str}.txt"
            with open(filename, "w") as f:
                f.write(access_token_data["token"])
    except Exception as e:
        logging.error(f"❌ Exception in fetch_token: {str(e)}")

def fetch_bank_list(page_key=None):
    if is_token_expired():
        fetch_token()

    token = access_token_data.get("token")
    if not token:
        return

    now = datetime.now(MY_TZ)
    date_str = now.strftime("%Y%m%d")
    client_id = "M0043439"
    sequence_number = get_sequence_number()

    business_msg_id = f"{date_str}{client_id}650{sequence_number}"
    message_id = f"{date_str}{client_id}650OBW{sequence_number}"

    try:
        signature = generate_signature(message_id, business_msg_id)
    except Exception as e:
        logging.error(f"❌ Signature generation error: {str(e)}")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "X-Gps-Coordinates": "40.689263, 74.044505",
        "X-Ip-Address": "202.184.244.36",
        "X-Signature": signature,
        "X-Signature-Key": "7e83b4688b84cd26b77713191b57b13c5083a3c8"
    }

    params = {
        "clientId": client_id,
        "messageId": message_id,
        "transactionId": business_msg_id
    }

    if page_key:
        params["pageKey"] = page_key

    url = "https://sandbox.api.paynet.my/merchants/v1/payments/lists/bank"

    try:
        response = requests.get(url, headers=headers, params=params)
        
        log_msg = (
            f"🌐 [API REQUEST] -> GET Bank List\n"
            f"URL: {url}\n"
            f"Headers: {headers}\n"
            f"Params: {params}\n\n"
            f"📥 [API RESPONSE]\n"
            f"Status Code: {response.status_code}\n"
            f"Body Content: {response.text}"
        )
        logging.info(log_msg)

        if response.status_code == 200:
            try:
                data = response.json()
                raw_banks = data.get("banks", []) or data.get("bankList", []) or []
                
                # Wipe cache container fresh only on initial call setup
                if not page_key:
                    cached_bank_list["personal"] = []
                    cached_bank_list["corporate"] = []

                for bank in raw_banks:
                    bank_item = {
                        "code": bank.get("code") or bank.get("bankId") or bank.get("bic"),
                        "name": bank.get("name") or bank.get("bankName")
                    }
                    
                    redirect_urls = bank.get("redirectUrls", [])
                    is_personal = False
                    is_corporate = False
                    
                    # Core assignment rules checking redirect items explicit types
                    for route in redirect_urls:
                        route_type = str(route.get("type", "")).strip().lower()
                        if route_type == "ret":
                            is_personal = True
                        elif route_type == "cor":
                            is_corporate = True

                    if is_personal:
                        cached_bank_list["personal"].append(bank_item)
                    if is_corporate:
                        cached_bank_list["corporate"].append(bank_item)
                        
                    # Fallback policy mapping rules
                    if not is_personal and not is_corporate:
                        cached_bank_list["personal"].append(bank_item)
                        cached_bank_list["corporate"].append(bank_item)

                # Control programmatic pagination iteration loops
                next_page_key = data.get("pageKey")
                if next_page_key:
                    fetch_bank_list(page_key=next_page_key)
                else:
                    # Sort completely alphabetically from A-Z once all pagination arrays are complete
                    cached_bank_list["personal"] = sorted(cached_bank_list["personal"], key=lambda x: x["name"].lower())
                    cached_bank_list["corporate"] = sorted(cached_bank_list["corporate"], key=lambda x: x["name"].lower())
                    logging.info(f"✅ Bank lists sorted A-Z. Personal: {len(cached_bank_list['personal'])}, Corporate: {len(cached_bank_list['corporate'])}")

            except ValueError:
                logging.error("❌ Response body is not valid JSON parsing structure.")
    except Exception as e:
        logging.error(f"❌ Exception in fetch_bank_list: {str(e)}")


# ==========================================
# 5. FLASK WEB ROUTES & SCHEDULER
# ==========================================
@app.route('/')
def home():
    return render_template('DuitNow OBW Simulator.html')

@app.route('/api/banks')
def get_banks():
    # If cache is dry, force an emergency fetch run
    if not cached_bank_list["personal"] and not cached_bank_list["corporate"]:
        fetch_bank_list()
        
    # Standard health validation checks
    if not cached_bank_list["personal"] and not cached_bank_list["corporate"]:
        return jsonify({
            "status": "error",
            "message": "Bank cache list is dry. Verify system logging payloads for endpoint authorization errors."
        }), 500
        
    return jsonify({
        "status": "success",
        "data": cached_bank_list
    })

@app.route('/use-token')
def use_token():
    if is_token_expired():
        fetch_token()

    token = access_token_data.get("token")
    if not token:
        return "Token not available. Try again later.", 401

    return f"Token is ready: {token}"

def start_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(fetch_token, 'cron', hour=0, minute=0, timezone=MY_TZ)
    scheduler.add_job(fetch_bank_list, 'interval', hours=1)
    scheduler.start()

if __name__ == "__main__":
    start_scheduler()
    fetch_token()
    fetch_bank_list()
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)