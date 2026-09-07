from flask import Flask, request, jsonify
import sqlite3
import re
from datetime import datetime, timedelta
import os
import uuid
import requests

app = Flask(__name__)

# ==================== CONFIGURATION ====================
# আপনার নগদ/বিকাশ নাম্বার দিন
NAGAD_NUMBER = "017XXXXXXXX"  # আপনার নগদ পার্সোনাল নাম্বার
BKASH_NUMBER = "018XXXXXXXX"  # আপনার বিকাশ পার্সোনাল নাম্বার

# API Key (আপনার ওয়েবসাইট থেকে API কল করার জন্য)
API_KEY = "your-secret-api-key-123"  # এটি পরিবর্তন করুন

# Telegram Bot (ঐচ্ছিক)
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    # পেমেন্ট টেবিল
    c.execute('''CREATE TABLE IF NOT EXISTS payments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  transaction_id TEXT,
                  amount REAL,
                  method TEXT,
                  sender TEXT,
                  received_at DATETIME)''')
    
    # পেমেন্ট রিকোয়েস্ট টেবিল
    c.execute('''CREATE TABLE IF NOT EXISTS payment_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id TEXT UNIQUE,
                  amount REAL,
                  method TEXT,
                  website_url TEXT,
                  callback_url TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at DATETIME,
                  matched_transaction_id TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== API KEY VERIFICATION ====================
def verify_api_key(api_key):
    return api_key == API_KEY

# ==================== SMS PARSING ====================
def parse_sms(sms_text):
    """SMS থেকে পেমেন্ট তথ্য বের করুন"""
    trx_match = re.search(r'TrxID[:\s]*([A-Z0-9]+)', sms_text, re.IGNORECASE)
    amount_match = re.search(r'(?:BDT|Tk|Amount)[:\s]*([\d,]+\.?\d*)', sms_text, re.IGNORECASE)
    
    if trx_match and amount_match:
        return {
            'transaction_id': trx_match.group(1),
            'amount': float(amount_match.group(1).replace(',', '')),
            'method': 'nagad' if 'nagad' in sms_text.lower() else 'bkash'
        }
    return None

def save_payment(payment_info, sender=''):
    """পেমেন্ট ডাটাবেসে সেভ করুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""INSERT INTO payments 
               (transaction_id, amount, method, sender, received_at) 
               VALUES (?, ?, ?, ?, ?)""",
              (payment_info['transaction_id'], 
               payment_info['amount'], 
               payment_info['method'], 
               sender, 
               datetime.now()))
    conn.commit()
    conn.close()

def match_pending_request(payment_info):
    """পেন্ডিং রিকোয়েস্টের সাথে পেমেন্ট ম্যাচ করুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("""SELECT id, callback_url FROM payment_requests 
               WHERE amount=? AND method=? AND status='pending'
               AND created_at > ?
               ORDER BY created_at DESC LIMIT 1""",
              (payment_info['amount'], 
               payment_info['method'], 
               datetime.now() - timedelta(minutes=30)))
    
    result = c.fetchone()
    
    if result:
        request_id, callback_url = result
        
        # পেমেন্ট সম্পূর্ণ মার্ক করুন
        c.execute("""UPDATE payment_requests 
                   SET status='completed', matched_transaction_id=?
                   WHERE id=?""",
                  (payment_info['transaction_id'], request_id))
        conn.commit()
        
        # Callback পাঠান
        if callback_url:
            try:
                callback_data = {
                    'status': 'completed',
                    'transaction_id': payment_info['transaction_id'],
                    'amount': payment_info['amount']
                }
                requests.post(callback_url, json=callback_data, timeout=5)
            except:
                pass
        
        return True
    
    conn.close()
    return False

def send_telegram_notification(payment_info):
    """Telegram এ নোটিফিকেশন পাঠান"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    
    message = f"💰 *পেমেন্ট রিসিভড!*\n\n"
    message += f"📱 Method: `{payment_info['method'].upper()}`\n"
    message += f"💵 Amount: `{payment_info['amount']} Taka`\n"
    message += f"🔢 Transaction: `{payment_info['transaction_id']}`\n"
    message += f"⏰ Time: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
    
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
    except:
        pass

# ==================== API ENDPOINTS ====================

# SMS রিসিভ করুন (MacroDroid থেকে)
@app.route('/api/sms', methods=['POST'])
def receive_sms():
    try:
        data = request.json
        sms_text = data.get('sms', '')
        sender = data.get('sender', '')
        
        # SMS পার্স করুন
        payment_info = parse_sms(sms_text)
        
        if payment_info:
            # পেমেন্ট সেভ করুন
            save_payment(payment_info, sender)
            
            # পেন্ডিং রিকোয়েস্ট ম্যাচ করুন
            match_pending_request(payment_info)
            
            # Telegram নোটিফিকেশন
            send_telegram_notification(payment_info)
            
            return jsonify({
                'success': True,
                'message': 'Payment received successfully',
                'payment': {
                    'transaction_id': payment_info['transaction_id'],
                    'amount': payment_info['amount'],
                    'method': payment_info['method']
                }
            })
        
        return jsonify({'success': False, 'error': 'No payment found in SMS'}), 400
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# পেমেন্ট রিকোয়েস্ট তৈরি করুন (ওয়েবসাইট থেকে)
@app.route('/api/create-payment', methods=['POST'])
def create_payment():
    try:
        # API Key ভেরিফাই করুন
        api_key = request.headers.get('X-API-Key', '')
        if not verify_api_key(api_key):
            return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
        data = request.json
        amount = float(data.get('amount', 0))
        method = data.get('method', 'nagad').lower()
        website_url = data.get('website_url', '')
        callback_url = data.get('callback_url', '')
        customer_phone = data.get('customer_phone', '')
        
        # ভ্যালিডেশন
        if amount < 10:
            return jsonify({'success': False, 'error': 'Minimum amount is 10 Taka'}), 400
        
        if method not in ['nagad', 'bkash']:
            return jsonify({'success': False, 'error': 'Invalid method'}), 400
        
        # ইউনিক রিকোয়েস্ট ID
        request_id = f"REQ{uuid.uuid4().hex[:10].upper()}"
        
        # পেমেন্ট নাম্বার
        payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
        
        # ডাটাবেসে সেভ করুন
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("""INSERT INTO payment_requests 
                   (request_id, amount, method, website_url, callback_url, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                  (request_id, amount, method, website_url, callback_url, datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'payment_number': payment_number,
            'amount': amount,
            'method': method,
            'payment_url': f'/pay/{request_id}',
            'message': f'Please send {amount} Taka to {payment_number} ({method.upper()})'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# Webhook Receiver (ওয়েবসাইট থেকে)
@app.route('/webhook/create-payment', methods=['POST'])
def webhook_create_payment():
    """আপনার ওয়েবসাইট থেকে পেমেন্ট রিকোয়েস্ট গ্রহণ করুন"""
    try:
        # API Key ভেরিফাই করুন
        api_key = request.headers.get('X-API-Key', '')
        if not verify_api_key(api_key):
            return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
        data = request.json
        amount = float(data.get('amount', 0))
        method = data.get('method', 'nagad').lower()
        order_id = data.get('order_id', '')
        customer_phone = data.get('customer_phone', '')
        callback_url = data.get('callback_url', '')
        
        # ভ্যালিডেশন
        if amount < 10:
            return jsonify({'success': False, 'error': 'Minimum amount is 10 Taka'}), 400
        
        # ইউনিক রিকোয়েস্ট ID
        request_id = f"REQ{uuid.uuid4().hex[:10].upper()}"
        
        # পেমেন্ট নাম্বার
        payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
        
        # ডাটাবেসে সেভ করুন
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("""INSERT INTO payment_requests 
                   (request_id, amount, method, website_url, callback_url, created_at) 
                   VALUES (?, ?, ?, ?, ?, ?)""",
                  (request_id, amount, method, order_id, callback_url, datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'payment_number': payment_number,
            'amount': amount,
            'method': method,
            'payment_url': f'https://your-app.onrender.com/pay/{request_id}'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# পেমেন্ট স্ট্যাটাস চেক করুন
@app.route('/api/check-payment/<request_id>', methods=['GET'])
def check_payment(request_id):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT status, matched_transaction_id, amount, method 
               FROM payment_requests WHERE request_id=?""", (request_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            'success': True,
            'status': result[0],
            'transaction_id': result[1],
            'amount': result[2],
            'method': result[3],
            'is_completed': result[0] == 'completed'
        })
    
    return jsonify({'success': False, 'error': 'Request not found'}), 404

# সব পেমেন্ট দেখুন
@app.route('/api/payments', methods=['GET'])
def get_payments():
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
            'received_at': p[5]
        })
    
    return jsonify({'payments': payment_list})

# ==================== PAYMENT PAGE ====================
@app.route('/pay/<request_id>')
def payment_page(request_id):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT amount, method FROM payment_requests WHERE request_id=?", (request_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return "Payment request not found", 404
    
    amount, method = result
    payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
    
    return f'''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment - {amount} Taka</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }}
            .payment-card {{
                background: white;
                border-radius: 15px;
                padding: 30px;
                max-width: 400px;
                width: 100%;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }}
            h2 {{ text-align: center; color: #333; margin-bottom: 20px; }}
            .amount-display {{
                text-align: center;
                font-size: 36px;
                font-weight: bold;
                color: #667eea;
                margin-bottom: 10px;
            }}
            .method-display {{
                text-align: center;
                color: #666;
                margin-bottom: 20px;
                font-size: 18px;
            }}
            .number-box {{
                background: #fff3cd;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                font-size: 24px;
                font-weight: bold;
                color: #856404;
                margin-bottom: 20px;
            }}
            .copy-btn {{
                width: 100%;
                padding: 12px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                cursor: pointer;
                margin-bottom: 20px;
            }}
            .verify-btn {{
                width: 100%;
                padding: 14px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
            }}
            .status {{
                text-align: center;
                margin-top: 15px;
                font-weight: bold;
                display: none;
            }}
            .spinner {{
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #28a745;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                vertical-align: middle;
                margin-right: 10px;
            }}
            @keyframes spin {{
                0% {{ transform: rotate(0deg); }}
                100% {{ transform: rotate(360deg); }}
            }}
        </style>
    </head>
    <body>
        <div class="payment-card">
            <h2>💰 পেমেন্ট করুন</h2>
            <div class="amount-display">{amount} টাকা</div>
            <div class="method-display">Method: {method.upper()}</div>
            
            <p style="text-align:center; margin-bottom:10px;">সেন্ড মানি করুন এই নাম্বারে:</p>
            <div class="number-box">{payment_number}</div>
            
            <button class="copy-btn" onclick="copyNumber()">📋 নাম্বার কপি করুন</button>
            
            <p style="text-align:center; margin-bottom:10px;">টাকা পাঠানোর পর চাপুন:</p>
            <button class="verify-btn" onclick="verifyPayment()">✓ পেমেন্ট ভেরিফাই করুন</button>
            
            <div class="status" id="status"></div>
        </div>
        
        <script>
            function copyNumber() {{
                navigator.clipboard.writeText('{payment_number}');
                alert('নাম্বার কপি হয়েছে!');
            }}
            
            async function verifyPayment() {{
                const statusDiv = document.getElementById('status');
                statusDiv.style.display = 'block';
                statusDiv.innerHTML = '<span class="spinner"></span> পেমেন্ট চেক হচ্ছে...';
                
                try {{
                    const response = await fetch('/api/check-payment/{request_id}');
                    const data = await response.json();
                    
                    if (data.is_completed) {{
                        statusDiv.innerHTML = '✅ পেমেন্ট সফল!<br>Transaction: ' + data.transaction_id;
                        statusDiv.style.color = '#28a745';
                    }} else {{
                        statusDiv.innerHTML = '⏳ এখনো পেমেন্ট পাওয়া যায়নি';
                        statusDiv.style.color = '#ffc107';
                        setTimeout(verifyPayment, 5000);
                    }}
                }} catch (error) {{
                    statusDiv.innerHTML = '❌ Server error';
                    statusDiv.style.color = '#dc3545';
                }}
            }}
        </script>
    </body>
    </html>
    '''

# ==================== DASHBOARD ====================
@app.route('/')
def dashboard():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 50")
    payments = c.fetchall()
    
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments")
    stats = c.fetchone()
    conn.close()
    
    total_count = stats[0] or 0
    total_amount = stats[1] or 0
    
    html = '''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment Dashboard</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial, sans-serif; background: #f0f2f5; padding: 20px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white; padding: 30px; border-radius: 10px; margin-bottom: 20px;
            }
            .header h1 { font-size: 28px; margin-bottom: 10px; }
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
            .stat-card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .stat-card h3 { color: #333; margin-bottom: 10px; font-size: 16px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow-x: auto; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            tr:hover { background: #f8f9fa; }
            .nagad { color: #f47721; font-weight: bold; }
            .bkash { color: #d12053; font-weight: bold; }
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
                        <th>Time</th>
                    </tr>
                    ''' + ''.join([f'''
                    <tr>
                        <td><strong>{p[1]}</strong></td>
                        <td>{p[2]} Taka</td>
                        <td class="{p[3]}">{p[3].upper()}</td>
                        <td>{p[4] or 'N/A'}</td>
                        <td>{p[5]}</td>
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
