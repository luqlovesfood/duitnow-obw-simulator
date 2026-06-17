import os
import base64
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo  # Python 3.9+ native timezone handling
from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from apscheduler.schedulers.background import BackgroundScheduler
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Target operational timezone for PayNet validation matching
MY_TZ = ZoneInfo("Asia/Kuala_Lumpur")

# ==========================================
# 1. DATABASE CONFIGURATION
# ==========================================
# Render automatically provides DATABASE_URL in production environments.
# Falls back to a local SQLite instance for easy local debugging.
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///obw_simulator.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


# ==========================================
# 2. DATABASE MODELS
# ==========================================
class BankList(db.Model):
    __tablename__ = 'bank_list'
    id = db.Column(db.Integer, primary_key=True)
    bank_code = db.Column(db.String(20), unique=True, nullable=False)
    bank_name = db.Column(db.String(100), nullable=False)
    banking_type = db.Column(db.String(15), nullable=False) # 'personal', 'corporate', 'both'
    last_updated = db.Column(db.DateTime, nullable=False)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    ip_address = db.Column(db.String(45), nullable=False)
    endpoint = db.Column(db.String(255), nullable=False)
    method = db.Column(db.String(10), nullable=False)
    user_agent = db.Column(db.Text, nullable=False)

class PayNetApiLog(db.Model):
    __tablename__ = 'paynet_api_logs'
    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False)
    endpoint = db.Column(db.String(255), nullable=False)
    status_code = db.Column(db.Integer, nullable=False)
    response_body = db.Column(db.Text, nullable=False)  # Stores every raw response body string


# ==========================================
# EXTRA CRITICAL FIX: FORCE GUNICORN CONTEXT TABLE GENERATION
# ==========================================
with app.app_context():
    try:
        db.create_all()
        print("✅ Production Database tables verified/created successfully.")
    except Exception as e:
        print(f"❌ Database table pre-creation error: {str(e)}")


# ==========================================
# 3. ENCRYPTION & KEY CONFIGURATION
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
# 4. STATE ENGINE CORE
# ==========================================
access_token_data = {
    "token": None,
    "expires_in": None,
    "timestamp": None
}

sequence_counter = {
    "value": 1,
    "date": datetime.now(MY_TZ).date()
}

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
# 5. PAYNET INTERACTION & RECURSIVE DB SYNC
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
        
        # Log the raw response parameters to DB
        with app.app_context():
            token_log = PayNetApiLog(
                timestamp=datetime.now(MY_TZ),
                endpoint=url,
                status_code=response.status_code,
                response_body=response.text
            )
            db.session.add(token_log)
            db.session.commit()

        if response.status_code == 200:
            response_data = response.json()
            access_token_data["token"] = response_data.get("access_token")
            access_token_data["expires_in"] = response_data.get("expires_in")
            access_token_data["timestamp"] = datetime.now(MY_TZ)
    except Exception as e:
        print(f"❌ Exception in fetch_token: {str(e)}")

def sync_banks_to_db(page_key=None, accumulated_banks=None):
    """Fetches paginated banks, logs every raw response body, and commits to Database."""
    if accumulated_banks is None:
        accumulated_banks = []

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
        print(f"❌ Signature generation error: {str(e)}")
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
        
        # --- REQUIREMENT: LOG EVERY RESPONSE BODY FROM PAYNET TO DB ---
        with app.app_context():
            api_log = PayNetApiLog(
                timestamp=datetime.now(MY_TZ),
                endpoint=url if not page_key else f"{url}?pageKey={page_key}",
                status_code=response.status_code,
                response_body=response.text  # Capture raw text body completely
            )
            db.session.add(api_log)
            db.session.commit()

        if response.status_code == 200:
            data = response.json()
            raw_banks = data.get("banks", []) or data.get("bankList", []) or []

            for bank in raw_banks:
                code = bank.get("code") or bank.get("bankId") or bank.get("bic")
                name = bank.get("name") or bank.get("bankName")
                
                redirect_urls = bank.get("redirectUrls", [])
                is_p = False
                is_c = False
                
                for route in redirect_urls:
                    route_type = str(route.get("type", "")).strip().lower()
                    if route_type == "ret":
                        is_p = True
                    elif route_type == "cor":
                        is_c = True

                # Determine standard structure categorization mappings
                if is_p and is_c:
                    b_type = 'both'
                elif not is_p and not is_c:
                    b_type = 'both'
                else:
                    b_type = 'personal' if is_p else 'corporate'

                accumulated_banks.append({
                    "code": code,
                    "name": name,
                    "type": b_type
                })

            # Check for continuation page structures
            next_page_key = data.get("pageKey")
            if next_page_key:
                sync_banks_to_db(page_key=next_page_key, accumulated_banks=accumulated_banks)
            else:
                # All paginated data collected -> Commit batch records to DB
                with app.app_context():
                    current_time = datetime.now(MY_TZ)
                    for item in accumulated_banks:
                        existing_bank = BankList.query.filter_by(bank_code=item["code"]).first()
                        if existing_bank:
                            existing_bank.bank_name = item["name"]
                            existing_bank.banking_type = item["type"]
                            existing_bank.last_updated = current_time
                        else:
                            new_bank = BankList(
                                bank_code=item["code"],
                                bank_name=item["name"],
                                banking_type=item["type"],
                                last_updated=current_time
                            )
                            db.session.add(new_bank)
                    db.session.commit()
                print(f"✅ DB Synchronization Complete. Processed records: {len(accumulated_banks)}")
    except Exception as e:
        print(f"❌ Exception in sync_banks_to_db: {str(e)}")


# ==========================================
# 6. GLOBAL VISITORS AUDIT LOG INTERCEPTOR
# ==========================================
@app.before_request
def log_visitor_access():
    """Fires automatically before every route execution to log active access metadata."""
    if request.path.startswith('/static'):
        return

    try:
        new_log = AuditLog(
            timestamp=datetime.now(MY_TZ),
            ip_address=request.headers.get('X-Forwarded-For', request.remote_addr).split(',')[0].strip(),
            endpoint=request.path,
            method=request.method,
            user_agent=request.user_agent.string
        )
        db.session.add(new_log)
        db.session.commit()
    except Exception as e:
        print(f"❌ Failed to write visitor audit log trail: {str(e)}")


# ==========================================
# 7. FLASK WEB ROUTES
# ==========================================
@app.route('/')
def home():
    return render_template('DuitNow OBW Simulator.html')

@app.route('/api/banks')
def get_banks():
    """Reads transactional list direct from the local cached database rows."""
    try:
        all_banks = BankList.query.all()
        
        # Emergency backup seed mechanism if the listing table is empty
        if not all_banks:
            sync_banks_to_db()
            all_banks = BankList.query.all()

        personal_list = []
        corporate_list = []

        for b in all_banks:
            item = {"code": b.bank_code, "name": b.bank_name}
            if b.banking_type in ['personal', 'both']:
                personal_list.append(item)
            if b.banking_type in ['corporate', 'both']:
                corporate_list.append(item)

        # Alphabetical sorting
        personal_list = sorted(personal_list, key=lambda x: x["name"].lower())
        corporate_list = sorted(corporate_list, key=lambda x: x["name"].lower())
        
        return jsonify({
            "status": "success",
            "data": {
                "personal": personal_list,
                "corporate": corporate_list
            }
        })
    except Exception as e:
        return jsonify({"status": "error", "message": f"Database processing failure: {str(e)}"}), 500

@app.route('/use-token')
def use_token():
    if is_token_expired():
        fetch_token()

    token = access_token_data.get("token")
    if not token:
        return "Token not available. Try again later.", 401

    return f"Token is ready: {token}"


# ==========================================
# NEW ADMIN WEB DASHBOARD ENDPOINT
# ==========================================
@app.route('/secret-admin-dashboard')
def admin_dashboard():
    """Builds a basic web table layout layout for direct visual inspection of live cloud entries."""
    try:
        visitors = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(50).all()
        api_payloads = PayNetApiLog.query.order_by(PayNetApiLog.timestamp.desc()).limit(50).all()
        banks = BankList.query.order_by(BankList.bank_name.asc()).all()
        
        html = "<h1>🖥️ System Database Admin Dashboard</h1>"
        
        html += "<h2>1. Active Cached Banks List</h2><table border='1'><tr><th>Bank Name</th><th>Bank Code</th><th>Type</th></tr>"
        for b in banks:
            html += f"<tr><td>{b.bank_name}</td><td>{b.bank_code}</td><td>{b.banking_type}</td></tr>"
        html += "</table>"
        
        html += "<h2>2. Recent Visitor Audit Logs (Last 50)</h2><table border='1'><tr><th>Timestamp</th><th>IP Address</th><th>Endpoint</th><th>Method</th></tr>"
        for v in visitors:
            html += f"<tr><td>{v.timestamp}</td><td>{v.ip_address}</td><td>{v.endpoint}</td><td>{v.method}</td></tr>"
        html += "</table>"
        
        html += "<h2>3. Raw PayNet API Response Payload Logs (Last 50)</h2><table border='1'><tr><th>Timestamp</th><th>Status</th><th>Raw Response Body</th></tr>"
        for p in api_payloads:
            truncated_body = p.response_body[:200] + "..." if len(p.response_body) > 200 else p.response_body
            html += f"<tr><td>{p.timestamp}</td><td>{p.status_code}</td><td><code>{truncated_body}</code></td></tr>"
        html += "</table>"
        
        return html
    except Exception as e:
        return f"Database Panel Visibility Error: {str(e)}", 500


# ==========================================
# 8. PROCESS INITIALIZER & SCHEDULER BLOCK
# ==========================================
def initialize_engine():
    # Context forced at the module root to guarantee schemas exist for Gunicorn.
    scheduler = BackgroundScheduler()
    # Task 1: Fetch client credentials token at midnight every day
    scheduler.add_job(fetch_token, 'cron', hour=0, minute=0, timezone=MY_TZ)
    # Task 2: Sync bank lists & log raw responses every single night at 23:00 (11:00 PM) Malaysia Time
    scheduler.add_job(sync_banks_to_db, 'cron', hour=23, minute=0, timezone=MY_TZ)
    scheduler.start()

# Gunicorn triggers execution outside of main. Trigger background scheduler directly during import.
initialize_engine()

if __name__ == "__main__":
    # Run initial startup checks to seed base application data if executed standalone
    fetch_token()
    sync_banks_to_db()
    
    port = int(os.environ.get("PORT", 5001))
    app.run(host="0.0.0.0", port=port, debug=False)