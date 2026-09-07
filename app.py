from flask import Flask, request, jsonify, render_template_string
import sqlite3
import re
from datetime import datetime, timedelta
import requests
import os
import json

app = Flask(__name__)

# ==================== CONFIGURATION ====================
# আপনার নগদ/বিকাশ নাম্বার দিন
NAGAD_NUMBER = "017XXXXXXXX"  # আপনার নগদ পার্সোনাল নাম্বার
BKASH_NUMBER = "018XXXXXXXX"  # আপনার বিকাশ পার্সোনাল নাম্বার

# Telegram Bot Configuration (ফ্রি নোটিফিকেশন)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    # পেমেন্ট টেবিল
    c.execute('''CREATE TABLE IF NOT EXISTS payments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  transaction_id TEXT UNIQUE,
                  amount REAL,
                  method TEXT,
                  sender TEXT,
                  status TEXT DEFAULT 'verified',
                  sms_content TEXT,
                  received_at DATETIME)''')
    
    # পেমেন্ট রিকোয়েস্ট টেবিল
    c.execute('''CREATE TABLE IF NOT EXISTS payment_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id TEXT UNIQUE,
                  amount REAL,
                  method TEXT,
                  customer_phone TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at DATETIME,
                  matched_transaction_id TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== SMS PARSING ====================
def parse_payment_sms(sms_text, sender=""):
    """SMS থেকে পেমেন্ট তথ্য বের করুন"""
    
    # Transaction ID খুঁজুন
    trx_match = re.search(r'TrxID[:\s]*([A-Z0-9]+)', sms_text, re.IGNORECASE)
    if not trx_match:
        return None
    
    # Amount খুঁজুন
    amount_match = re.search(r'(?:BDT|Tk|Amount)[:\s]*([\d,]+\.?\d*)', sms_text, re.IGNORECASE)
    if not amount_match:
        return None
    
    # Method নির্ধারণ
    if 'nagad' in sms_text.lower():
        method = 'nagad'
    elif 'bkash' in sms_text.lower() or 'bKash' in sms_text:
        method = 'bkash'
    else:
        method = 'unknown'
    
    return {
        'transaction_id': trx_match.group(1),
        'amount': float(amount_match.group(1).replace(',', '')),
        'method': method,
        'sender': sender,
        'sms_content': sms_text,
        'received_at': datetime.now().isoformat()
    }

def save_payment(payment):
    """পেমেন্ট ডাটাবেসে সেভ করুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    try:
        c.execute("""INSERT OR IGNORE INTO payments 
                   (transaction_id, amount, method, sender, sms_content, received_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                  (payment['transaction_id'],
                   payment['amount'],
                   payment['method'],
                   payment['sender'],
                   payment['sms_content'],
                   payment['received_at']))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def match_pending_request(payment):
    """পেন্ডিং রিকোয়েস্টের সাথে পেমেন্ট ম্যাচ করুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    # একই এমাউন্টের পেন্ডিং রিকোয়েস্ট খুঁজুন (৩০ মিনিটের মধ্যে)
    c.execute("""SELECT id, request_id FROM payment_requests 
               WHERE amount=? AND method=? AND status='pending'
               AND created_at > ?
               ORDER BY created_at DESC LIMIT 1""",
              (payment['amount'], payment['method'], 
               datetime.now() - timedelta(minutes=30)))
    
    result = c.fetchone()
    
    if result:
        request_id, request_code = result
        
        # পেমেন্ট সম্পূর্ণ মার্ক করুন
        c.execute("""UPDATE payment_requests 
                   SET status='completed', matched_transaction_id=?
                   WHERE id=?""",
                  (payment['transaction_id'], request_id))
        conn.commit()
        
        print(f"✅ Payment matched: {payment['transaction_id']} -> {request_code}")
        return True
    
    conn.close()
    return False

def send_telegram_notification(payment):
    """Telegram এ নোটিফিকেশন পাঠান"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    message = f"💰 *পেমেন্ট রিসিভড!*\n\n"
    message += f"📱 Method: `{payment['method'].upper()}`\n"
    message += f"💵 Amount: `{payment['amount']} Taka`\n"
    message += f"🔢 Transaction: `{payment['transaction_id']}`\n"
    message += f"👤 Sender: `{payment['sender'] or 'N/A'}`\n"
    message += f"⏰ Time: `{payment['received_at']}`"
    
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'Markdown'
            },
            timeout=5
        )
    except Exception as e:
        print(f"Telegram notification error: {e}")

# ==================== API ENDPOINTS ====================
@app.route('/api/sms', methods=['POST'])
def receive_sms():
    """SMS রিসিভ করুন (MacroDroid থেকে)"""
    try:
        data = request.json
        sms_text = data.get('sms', '')
        sender = data.get('sender', '')
        
        # পেমেন্ট SMS পার্স করুন
        payment = parse_payment_sms(sms_text, sender)
        
        if payment:
            # ডাটাবেসে সেভ করুন
            if save_payment(payment):
                # পেন্ডিং রিকোয়েস্ট ম্যাচ করুন
                match_pending_request(payment)
                
                # Telegram নোটিফিকেশন পাঠান
                send_telegram_notification(payment)
                
                return jsonify({
                    'success': True,
                    'message': 'Payment verified successfully',
                    'payment': {
                        'transaction_id': payment['transaction_id'],
                        'amount': payment['amount'],
                        'method': payment['method'],
                        'received_at': payment['received_at']
                    }
                })
        
        return jsonify({'success': False, 'error': 'No payment found in SMS'}), 400
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/create-payment', methods=['POST'])
def create_payment():
    """পেমেন্ট রিকোয়েস্ট তৈরি করুন"""
    try:
        data = request.json
        amount = float(data.get('amount', 0))
        method = data.get('method', 'nagad').lower()
        customer_phone = data.get('phone', '')
        
        # ভ্যালিডেশন
        if amount < 10:
            return jsonify({'success': False, 'error': 'Minimum amount is 10 Taka'}), 400
        
        if method not in ['nagad', 'bkash']:
            return jsonify({'success': False, 'error': 'Invalid method. Use nagad or bkash'}), 400
        
        # ইউনিক রিকোয়েস্ট ID তৈরি করুন
        request_id = f"REQ{datetime.now().strftime('%Y%m%d%H%M%S')}{os.urandom(4).hex().upper()}"
        
        # পেমেন্ট নাম্বার
        payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("""INSERT INTO payment_requests 
                   (request_id, amount, method, customer_phone, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                  (request_id, amount, method, customer_phone, datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'payment_number': payment_number,
            'amount': amount,
            'method': method,
            'instructions': f'Please send {amount} Taka to {payment_number} ({method.upper()})',
            'note': 'After sending money, SMS will auto-verify within 30 seconds'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/check-payment/<request_id>', methods=['GET'])
def check_payment(request_id):
    """পেমেন্ট স্ট্যাটাস চেক করুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT status, matched_transaction_id, amount 
               FROM payment_requests WHERE request_id=?""", (request_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'success': False, 'error': 'Request not found'}), 404
    
    status, transaction_id, amount = result
    
    return jsonify({
        'success': True,
        'status': status,
        'transaction_id': transaction_id,
        'amount': amount,
        'is_completed': status == 'completed'
    })

@app.route('/api/payments', methods=['GET'])
def get_payments():
    """সব পেমেন্ট দেখুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 50")
    payments = c.fetchall()
    conn.close()
    
    payment_list = []
    for p in payments:
        payment_list.append({
            'id': p[0],
            'transaction_id': p[1],
            'amount': p[2],
            'method': p[3],
            'sender': p[4],
            'status': p[5],
            'received_at': p[7]
        })
    
    return jsonify({'payments': payment_list})

# ==================== DASHBOARD ====================
@app.route('/')
def dashboard():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 20")
    payments = c.fetchall()
    
    # মোট পেমেন্ট
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments WHERE status='verified'")
    stats = c.fetchone()
    conn.close()
    
    total_count = stats[0] or 0
    total_amount = stats[1] or 0
    
    html = '''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <title>Payment Dashboard</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { 
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif; 
                background: #f0f2f5; 
                padding: 20px; 
            }
            .container { max-width: 1000px; margin: 0 auto; }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 30px;
                border-radius: 10px;
                margin-bottom: 20px;
            }
            .header h1 { font-size: 28px; margin-bottom: 10px; }
            .stats {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 15px;
                margin-bottom: 20px;
            }
            .stat-card {
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .stat-card h3 { color: #333; margin-bottom: 10px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container {
                background: white;
                border-radius: 10px;
                padding: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow-x: auto;
            }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; font-weight: 600; }
            tr:hover { background: #f8f9fa; }
            .success { color: #28a745; font-weight: bold; }
            .nagad { color: #f47721; font-weight: bold; }
            .bkash { color: #d12053; font-weight: bold; }
            @media (max-width: 600px) {
                .header h1 { font-size: 22px; }
                th, td { padding: 8px; font-size: 14px; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>💰 Payment Dashboard</h1>
                <p>Real-time payment monitoring system</p>
            </div>
            <div class="stats">
                <div class="stat-card">
                    <h3>Total Payments</h3>
                    <p>''' + str(total_count) + '''</p>
                </div>
                <div class="stat-card">
                    <h3>Total Amount</h3>
                    <p>''' + str(total_amount) + ''' Taka</p>
                </div>
            </div>
            <div class="table-container">
                <h3>Recent Payments</h3>
                <table>
                    <tr>
                        <th>Transaction ID</th>
                        <th>Amount</th>
                        <th>Method</th>
                        <th>Sender</th>
                        <th>Status</th>
                        <th>Time</th>
                    </tr>
                    ''' + ''.join([f'''
                    <tr>
                        <td><strong>{p[1]}</strong></td>
                        <td>{p[2]} Taka</td>
                        <td class="{p[3]}">{p[3].upper()}</td>
                        <td>{p[4] or 'N/A'}</td>
                        <td class="success">✓ Verified</td>
                        <td>{p[7]}</td>
                    </tr>''' for p in payments]) + '''
                </table>
            </div>
        </div>
    </body>
    </html>
    '''
    
    return html

# ==================== HEALTH CHECK ====================
@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'time': datetime.now().isoformat()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
