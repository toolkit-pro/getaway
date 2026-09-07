from flask import Flask, request, jsonify
import sqlite3
import re
from datetime import datetime, timedelta
import os
import uuid
import requests

app = Flask(__name__)

# ============ CONFIGURATION ============
NAGAD_NUMBER = "017XXXXXXXX"  # আপনার নগদ নাম্বার
BKASH_NUMBER = "018XXXXXXXX"  # আপনার বিকাশ নাম্বার

# API Key (আপনার ওয়েবসাইট থেকে আসবে)
API_KEY = "your-secret-api-key-123"  # এই key দিয়ে API কল হবে

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

# ============ API KEY ভেরিফিকেশন ============
def verify_api_key(api_key):
    return api_key == API_KEY

# ============ SMS রিসিভ (MacroDroid থেকে) ============
@app.route('/api/sms', methods=['POST'])
def receive_sms():
    data = request.json
    sms_text = data.get('sms', '')
    
    trx_match = re.search(r'TrxID[:\s]*([A-Z0-9]+)', sms_text, re.IGNORECASE)
    amount_match = re.search(r'(?:BDT|Tk)[:\s]*([\d,]+)', sms_text, re.IGNORECASE)
    
    if trx_match and amount_match:
        transaction_id = trx_match.group(1)
        amount = float(amount_match.group(1).replace(',', ''))
        method = 'nagad' if 'nagad' in sms_text.lower() else 'bkash'
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        
        # পেমেন্ট সেভ করুন
        c.execute("INSERT INTO payments (transaction_id, amount, method, sender, received_at) VALUES (?, ?, ?, ?, ?)",
                  (transaction_id, amount, method, data.get('sender', ''), datetime.now()))
        conn.commit()
        
        # পেন্ডিং রিকোয়েস্ট খুঁজুন
        c.execute("""SELECT id, callback_url FROM payment_requests 
                   WHERE amount=? AND method=? AND status='pending'
                   AND created_at > ?
                   ORDER BY created_at DESC LIMIT 1""",
                  (amount, method, datetime.now() - timedelta(minutes=30)))
        
        result = c.fetchone()
        
        if result:
            request_id, callback_url = result
            
            # পেমেন্ট সম্পূর্ণ মার্ক করুন
            c.execute("""UPDATE payment_requests 
                       SET status='completed', matched_transaction_id=?
                       WHERE id=?""",
                      (transaction_id, request_id))
            conn.commit()
            
            # Callback পাঠান (ওয়েবসাইটে নোটিফাই করুন)
            if callback_url:
                try:
                    callback_data = {
                        'status': 'completed',
                        'transaction_id': transaction_id,
                        'amount': amount
                    }
                    requests.post(callback_url, json=callback_data, timeout=5)
                except:
                    pass
        
        conn.close()
        
        return jsonify({'success': True, 'message': 'Payment received'})
    
    return jsonify({'success': False, 'error': 'No payment found'})

# ============ পেমেন্ট রিকোয়েস্ট তৈরি (ওয়েবসাইট থেকে) ============
@app.route('/api/create-payment', methods=['POST'])
def create_payment():
    # API Key ভেরিফাই করুন
    api_key = request.headers.get('X-API-Key', '')
    if not verify_api_key(api_key):
        return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
    
    data = request.json
    amount = float(data.get('amount', 0))
    method = data.get('method', 'nagad').lower()
    website_url = data.get('website_url', '')
    callback_url = data.get('callback_url', '')
    
    if amount < 10:
        return jsonify({'success': False, 'error': 'Minimum amount is 10 Taka'})
    
    request_id = f"REQ{uuid.uuid4().hex[:10].upper()}"
    payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
    
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
        'message': f'Please send {amount} Taka to {payment_number}'
    })

# ============ পেমেন্ট পেজ (কাস্টমারের জন্য) ============
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

# ============ পেমেন্ট স্ট্যাটাস চেক ============
@app.route('/api/check-payment/<request_id>')
def check_payment(request_id):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT status, matched_transaction_id, amount FROM payment_requests WHERE request_id=?", (request_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            'success': True,
            'status': result[0],
            'transaction_id': result[1],
            'amount': result[2],
            'is_completed': result[0] == 'completed'
        })
    
    return jsonify({'success': False, 'error': 'Request not found'})

# ============ Webhook Receiver (ওয়েবসাইট থেকে পেমেন্ট রিকোয়েস্ট) ============
@app.route('/webhook/create-payment', methods=['POST'])
def webhook_create_payment():
    """আপনার ওয়েবসাইট থেকে পেমেন্ট রিকোয়েস্ট গ্রহণ করুন"""
    
    # API Key ভেরিফাই করুন
    api_key = request.headers.get('X-API-Key', '')
    if not verify_api_key(api_key):
        return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
    
    data = request.json
    amount = data.get('amount')
    method = data.get('method', 'nagad')
    order_id = data.get('order_id', '')
    customer_phone = data.get('customer_phone', '')
    callback_url = data.get('callback_url', '')
    
    # পেমেন্ট রিকোয়েস্ট তৈরি করুন
    request_id = f"REQ{uuid.uuid4().hex[:10].upper()}"
    payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
    
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
        'payment_url': f'https://your-app.onrender.com/pay/{request_id}'
    })

# ============ ড্যাশবোর্ড ============
@app.route('/')
def dashboard():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 50")
    payments = c.fetchall()
    
    c.execute("SELECT COUNT(*), SUM(amount) FROM payments")
    stats = c.fetchone()
    conn.close()
    
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
            .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin-bottom: 20px; }
            .stat-card { background: white; padding: 20px; border-radius: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
            .stat-card h3 { color: #333; margin-bottom: 10px; font-size: 16px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container { background: white; border-radius: 10px; padding: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); overflow-x: auto; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            tr:hover { background: #f8f9fa; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>💰 Payment Dashboard</h1>
                <p>Real-time payment monitoring</p>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>Total Payments</h3>
                    <p>''' + str(stats[0] or 0) + '''</p>
                </div>
                <div class="stat-card">
                    <h3>Total Amount</h3>
                    <p>''' + str(stats[1] or 0) + ''' Taka</p>
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
                        <td>{p[3].upper()}</td>
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
