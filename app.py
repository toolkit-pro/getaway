from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string
import sqlite3
import re
from datetime import datetime, timedelta
import os
import uuid
import requests
import hashlib
import json
from functools import wraps
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-123')
CORS(app)  # Cross-Origin Resource Sharing - যেকোনো ওয়েবসাইট থেকে API কল করতে পারবে

# ==================== DATABASE SETUP ====================
def init_db():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    # Users Table
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password TEXT,
                  email TEXT,
                  role TEXT DEFAULT 'provider',
                  created_at DATETIME)''')
    
    # Providers Table
    c.execute('''CREATE TABLE IF NOT EXISTS providers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  provider_name TEXT,
                  nagad_number TEXT,
                  bkash_number TEXT,
                  api_key TEXT UNIQUE,
                  balance REAL DEFAULT 0,
                  total_received REAL DEFAULT 0,
                  status TEXT DEFAULT 'active',
                  created_at DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id))''')
    
    # Payments Table
    c.execute('''CREATE TABLE IF NOT EXISTS payments
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  transaction_id TEXT,
                  amount REAL,
                  method TEXT,
                  sender TEXT,
                  provider_id INTEGER,
                  website_url TEXT,
                  order_id TEXT,
                  status TEXT DEFAULT 'verified',
                  received_at DATETIME,
                  FOREIGN KEY (provider_id) REFERENCES providers(id))''')
    
    # Payment Requests Table
    c.execute('''CREATE TABLE IF NOT EXISTS payment_requests
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  request_id TEXT UNIQUE,
                  amount REAL,
                  method TEXT,
                  provider_id INTEGER,
                  website_url TEXT,
                  callback_url TEXT,
                  order_id TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at DATETIME,
                  matched_transaction_id TEXT,
                  FOREIGN KEY (provider_id) REFERENCES providers(id))''')
    
    # API Keys Table (Website Integration)
    c.execute('''CREATE TABLE IF NOT EXISTS api_keys
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  api_key TEXT UNIQUE,
                  website_name TEXT,
                  website_url TEXT,
                  provider_id INTEGER,
                  status TEXT DEFAULT 'active',
                  created_at DATETIME,
                  FOREIGN KEY (provider_id) REFERENCES providers(id))''')
    
    # Logs Table
    c.execute('''CREATE TABLE IF NOT EXISTS logs
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  action TEXT,
                  details TEXT,
                  ip_address TEXT,
                  created_at DATETIME)''')
    
    conn.commit()
    conn.close()

init_db()

# ==================== DEFAULT ADMIN ====================
def create_default_admin():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("SELECT id FROM users WHERE username='admin'")
    if not c.fetchone():
        password_hash = hashlib.sha256('admin123'.encode()).hexdigest()
        c.execute("""INSERT INTO users (username, password, email, role, created_at)
                   VALUES ('admin', ?, 'admin@example.com', 'admin', ?)""",
                  (password_hash, datetime.now()))
        conn.commit()
        print("✅ Default admin created: admin/admin123")
    
    conn.close()

create_default_admin()

# ==================== AUTHENTICATION ====================
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login_page'))
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("SELECT role FROM users WHERE id=?", (session['user_id'],))
        result = c.fetchone()
        conn.close()
        
        if not result or result[0] != 'admin':
            return "⛔ Access Denied", 403
        
        return f(*args, **kwargs)
    return decorated_function

def log_action(user_id, action, details, ip_address=''):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""INSERT INTO logs (user_id, action, details, ip_address, created_at)
               VALUES (?, ?, ?, ?, ?)""",
              (user_id, action, details, ip_address, datetime.now()))
    conn.commit()
    conn.close()

# ==================== API KEY VERIFICATION ====================
def verify_api_key(api_key):
    """API Key ভেরিফাই করুন"""
    if not api_key:
        return None
    
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT ak.*, p.id as provider_id, p.provider_name 
               FROM api_keys ak
               JOIN providers p ON ak.provider_id = p.id
               WHERE ak.api_key=? AND ak.status='active'""", (api_key,))
    result = c.fetchone()
    conn.close()
    
    return result if result else None

# ==================== LOGIN ====================
@app.route('/login', methods=['GET', 'POST'])
def login_page():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("SELECT id, role FROM users WHERE username=? AND password=?",
                  (username, password_hash))
        user = c.fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user[0]
            session['role'] = user[1]
            
            log_action(user[0], 'login', 'User logged in', request.remote_addr)
            
            if user[1] == 'admin':
                return redirect(url_for('admin_dashboard'))
            else:
                return redirect(url_for('provider_dashboard'))
        
        return render_template_string('''
            <script>alert("❌ Invalid credentials!"); window.location.href="/login";</script>
        ''')
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Login - Payment Gateway</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; }
            .login-box { background: white; padding: 40px; border-radius: 15px; box-shadow: 0 10px 40px rgba(0,0,0,0.2); width: 380px; }
            h2 { text-align: center; margin-bottom: 30px; color: #333; }
            input { width: 100%; padding: 12px; margin-bottom: 15px; border: 2px solid #ddd; border-radius: 8px; font-size: 16px; }
            button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: bold; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>🔐 Login</h2>
            <form method="POST">
                <input type="text" name="username" placeholder="Username" required>
                <input type="password" name="password" placeholder="Password" required>
                <button type="submit">Login</button>
            </form>
            <p style="text-align:center; margin-top:15px; color:#666;">Admin: admin/admin123</p>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# ==================== PUBLIC API (Website Integration) ====================
@app.route('/api/v1/create-payment', methods=['POST'])
def api_create_payment():
    """যেকোনো ওয়েবসাইট থেকে পেমেন্ট তৈরি করুন"""
    try:
        # API Key নিন (Header বা Body থেকে)
        api_key = request.headers.get('X-API-Key') or request.json.get('api_key', '')
        
        # API Key ভেরিফাই করুন
        key_info = verify_api_key(api_key)
        if not key_info:
            return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
        data = request.json
        amount = float(data.get('amount', 0))
        method = data.get('method', 'nagad').lower()
        order_id = data.get('order_id', str(uuid.uuid4().hex[:8]))
        callback_url = data.get('callback_url', '')
        website_url = data.get('website_url', '')
        customer_phone = data.get('customer_phone', '')
        customer_name = data.get('customer_name', '')
        
        # ভ্যালিডেশন
        if amount < 1:
            return jsonify({'success': False, 'error': 'Amount must be at least 1 Taka'}), 400
        
        if method not in ['nagad', 'bkash']:
            return jsonify({'success': False, 'error': 'Method must be nagad or bkash'}), 400
        
        # প্রোভাইডার খুঁজুন
        provider_id = key_info[4]  # provider_id
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("SELECT nagad_number, bkash_number FROM providers WHERE id=?", (provider_id,))
        provider = c.fetchone()
        
        if not provider:
            conn.close()
            return jsonify({'success': False, 'error': 'Provider not found'}), 404
        
        # পেমেন্ট নাম্বার
        payment_number = provider[0] if method == 'nagad' else provider[1]
        
        # রিকোয়েস্ট ID
        request_id = f"PAY{uuid.uuid4().hex[:12].upper()}"
        
        # রিকোয়েস্ট সেভ করুন
        c.execute("""INSERT INTO payment_requests 
                   (request_id, amount, method, provider_id, website_url, callback_url, order_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                  (request_id, amount, method, provider_id, website_url, callback_url, order_id, datetime.now()))
        conn.commit()
        conn.close()
        
        # পেমেন্ট URL
        payment_url = f"{request.host_url}pay/{request_id}"
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'payment_url': payment_url,
            'payment_number': payment_number,
            'amount': amount,
            'method': method,
            'order_id': order_id,
            'message': f'Please send {amount} Taka to {payment_number}'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v1/check-payment/<request_id>', methods=['GET'])
def api_check_payment(request_id):
    """পেমেন্ট স্ট্যাটাস চেক করুন"""
    try:
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("""SELECT status, matched_transaction_id, amount, method 
                   FROM payment_requests WHERE request_id=?""", (request_id,))
        result = c.fetchone()
        conn.close()
        
        if not result:
            return jsonify({'success': False, 'error': 'Payment request not found'}), 404
        
        return jsonify({
            'success': True,
            'status': result[0],
            'transaction_id': result[1],
            'amount': result[2],
            'method': result[3],
            'is_completed': result[0] == 'completed'
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v1/payments', methods=['GET'])
def api_get_payments():
    """সব পেমেন্ট দেখুন (API Key দিয়ে)"""
    try:
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key', '')
        
        key_info = verify_api_key(api_key)
        if not key_info:
            return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
        provider_id = key_info[4]
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("""SELECT * FROM payments WHERE provider_id=? 
                   ORDER BY id DESC LIMIT 100""", (provider_id,))
        payments = c.fetchall()
        conn.close()
        
        payment_list = []
        for p in payments:
            payment_list.append({
                'transaction_id': p[1],
                'amount': p[2],
                'method': p[3],
                'sender': p[4],
                'order_id': p[7],
                'status': p[8],
                'received_at': p[9]
            })
        
        return jsonify({
            'success': True,
            'payments': payment_list,
            'total': len(payment_list)
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== PAYMENT PAGE (Hosted) ====================
@app.route('/pay/<request_id>')
def payment_page(request_id):
    """হোস্টেড পেমেন্ট পেজ"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT amount, method, status FROM payment_requests 
               WHERE request_id=?""", (request_id,))
    result = c.fetchone()
    
    if not result:
        return "Payment request not found", 404
    
    amount, method, status = result
    
    if status == 'completed':
        return '''
        <div style="text-align:center; margin-top:100px;">
            <h1 style="color:green;">✅ Payment Already Completed!</h1>
        </div>
        '''
    
    # প্রোভাইডার নাম্বার খুঁজুন
    c.execute("""SELECT p.nagad_number, p.bkash_number 
               FROM providers p
               JOIN payment_requests pr ON p.id = pr.provider_id
               WHERE pr.request_id=?""", (request_id,))
    provider = c.fetchone()
    conn.close()
    
    if not provider:
        return "Provider not found", 404
    
    payment_number = provider[0] if method == 'nagad' else provider[1]
    
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment - {{ amount }} Taka</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }
            .payment-card {
                background: white;
                border-radius: 15px;
                padding: 30px;
                max-width: 400px;
                width: 100%;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h2 { text-align: center; color: #333; margin-bottom: 20px; }
            .amount-display {
                text-align: center;
                font-size: 36px;
                font-weight: bold;
                color: #667eea;
                margin-bottom: 10px;
            }
            .method-display {
                text-align: center;
                color: #666;
                margin-bottom: 20px;
                font-size: 18px;
            }
            .number-box {
                background: #fff3cd;
                padding: 15px;
                border-radius: 8px;
                text-align: center;
                font-size: 24px;
                font-weight: bold;
                color: #856404;
                margin-bottom: 20px;
            }
            .copy-btn {
                width: 100%;
                padding: 12px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                cursor: pointer;
                margin-bottom: 20px;
            }
            .verify-btn {
                width: 100%;
                padding: 14px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
            }
            .status {
                text-align: center;
                margin-top: 15px;
                font-weight: bold;
                display: none;
            }
            .spinner {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #28a745;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                vertical-align: middle;
                margin-right: 10px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        </style>
    </head>
    <body>
        <div class="payment-card">
            <h2>💰 পেমেন্ট করুন</h2>
            <div class="amount-display">{{ amount }} টাকা</div>
            <div class="method-display">Method: {{ method.upper() }}</div>
            
            <p style="text-align:center; margin-bottom:10px;">সেন্ড মানি করুন:</p>
            <div class="number-box">{{ payment_number }}</div>
            
            <button class="copy-btn" onclick="copyNumber()">📋 নাম্বার কপি করুন</button>
            
            <p style="text-align:center; margin-bottom:10px;">টাকা পাঠানোর পর:</p>
            <button class="verify-btn" onclick="verifyPayment()">✓ পেমেন্ট ভেরিফাই করুন</button>
            
            <div class="status" id="status"></div>
        </div>
        
        <script>
            function copyNumber() {
                navigator.clipboard.writeText('{{ payment_number }}');
                alert('নাম্বার কপি হয়েছে!');
            }
            
            async function verifyPayment() {
                const statusDiv = document.getElementById('status');
                statusDiv.style.display = 'block';
                statusDiv.innerHTML = '<span class="spinner"></span> পেমেন্ট চেক হচ্ছে...';
                
                try {
                    const response = await fetch('/api/v1/check-payment/{{ request_id }}');
                    const data = await response.json();
                    
                    if (data.is_completed) {
                        statusDiv.innerHTML = '✅ পেমেন্ট সফল!<br>Transaction: ' + data.transaction_id;
                        statusDiv.style.color = '#28a745';
                        
                        // Callback পাঠান
                        fetch('/api/v1/callback/{{ request_id }}');
                    } else {
                        statusDiv.innerHTML = '⏳ এখনো পেমেন্ট পাওয়া যায়নি';
                        statusDiv.style.color = '#ffc107';
                        setTimeout(verifyPayment, 5000);
                    }
                } catch (error) {
                    statusDiv.innerHTML = '❌ Server error';
                    statusDiv.style.color = '#dc3545';
                }
            }
        </script>
    </body>
    </html>
    ''', amount=amount, method=method, payment_number=payment_number, request_id=request_id)

# ==================== SMS RECEIVER ====================
@app.route('/api/sms', methods=['POST'])
def receive_sms():
    try:
        data = request.json
        sms_text = data.get('sms', '')
        sender = data.get('sender', '')
        
        # Parse SMS
        trx_match = re.search(r'TrxID[:\s]*([A-Z0-9]+)', sms_text, re.IGNORECASE)
        amount_match = re.search(r'(?:BDT|Tk)[:\s]*([\d,]+\.?\d*)', sms_text, re.IGNORECASE)
        
        if trx_match and amount_match:
            transaction_id = trx_match.group(1)
            amount = float(amount_match.group(1).replace(',', ''))
            method = 'nagad' if 'nagad' in sms_text.lower() else 'bkash'
            
            conn = sqlite3.connect('payments.db')
            c = conn.cursor()
            
            # Find provider
            c.execute("""SELECT id, nagad_number, bkash_number FROM providers 
                       WHERE status='active' LIMIT 1""")
            provider = c.fetchone()
            provider_id = provider[0] if provider else None
            
            # Save payment
            c.execute("""INSERT INTO payments 
                       (transaction_id, amount, method, sender, provider_id, received_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                      (transaction_id, amount, method, sender, provider_id, datetime.now()))
            
            # Update provider balance
            if provider_id:
                c.execute("""UPDATE providers 
                           SET balance = balance + ?, total_received = total_received + ?
                           WHERE id = ?""",
                          (amount, amount, provider_id))
            
            # Match pending requests
            c.execute("""SELECT id, callback_url FROM payment_requests 
                       WHERE amount=? AND method=? AND status='pending'
                       AND created_at > ?
                       ORDER BY created_at DESC LIMIT 1""",
                      (amount, method, datetime.now() - timedelta(minutes=30)))
            
            pending = c.fetchone()
            
            if pending:
                request_id, callback_url = pending
                
                c.execute("""UPDATE payment_requests 
                           SET status='completed', matched_transaction_id=?
                           WHERE id=?""",
                          (transaction_id, request_id))
                
                # Send callback
                if callback_url:
                    try:
                        callback_data = {
                            'status': 'completed',
                            'transaction_id': transaction_id,
                            'amount': amount,
                            'request_id': request_id
                        }
                        requests.post(callback_url, json=callback_data, timeout=5)
                    except:
                        pass
            
            conn.commit()
            conn.close()
            
            return jsonify({
                'success': True,
                'message': 'Payment received',
                'payment': {
                    'transaction_id': transaction_id,
                    'amount': amount,
                    'method': method
                }
            })
        
        return jsonify({'success': False, 'error': 'No payment found in SMS'}), 400
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

# ==================== ADMIN DASHBOARD ====================
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    # Stats
    c.execute("SELECT COUNT(*) FROM providers WHERE status='active'")
    total_providers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM payments")
    total_payments = c.fetchone()[0]
    
    c.execute("SELECT SUM(amount) FROM payments")
    total_revenue = c.fetchone()[0] or 0
    
    # API Keys
    c.execute("SELECT * FROM api_keys")
    api_keys = c.fetchall()
    
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Dashboard</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: #f0f2f5; }
            .sidebar { width: 250px; background: #2c3e50; height: 100vh; position: fixed; padding: 20px; }
            .sidebar h2 { color: white; margin-bottom: 30px; }
            .sidebar a { display: block; color: #ecf0f1; padding: 12px; text-decoration: none; border-radius: 5px; margin-bottom: 5px; }
            .sidebar a:hover { background: #34495e; }
            .main { margin-left: 250px; padding: 20px; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }
            .stat-card { background: white; padding: 20px; border-radius: 10px; }
            .stat-card h3 { color: #666; margin-bottom: 10px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container { background: white; padding: 20px; border-radius: 10px; overflow-x: auto; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>⚙️ Admin Panel</h2>
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/api-keys">🔑 API Keys</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        
        <div class="main">
            <div class="header">
                <h1>📊 Admin Dashboard</h1>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>Total Providers</h3>
                    <p>{{ total_providers }}</p>
                </div>
                <div class="stat-card">
                    <h3>Total Payments</h3>
                    <p>{{ total_payments }}</p>
                </div>
                <div class="stat-card">
                    <h3>Total Revenue</h3>
                    <p>{{ total_revenue }} Tk</p>
                </div>
            </div>
            
            <div class="table-container">
                <h3>API Keys</h3>
                <table>
                    <tr>
                        <th>API Key</th>
                        <th>Website</th>
                        <th>Provider ID</th>
                        <th>Status</th>
                    </tr>
                    {% for key in api_keys %}
                    <tr>
                        <td><code>{{ key[1] }}</code></td>
                        <td>{{ key[2] }}</td>
                        <td>{{ key[4] }}</td>
                        <td>{{ key[5] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body>
    </html>
    ''', total_providers=total_providers, total_payments=total_payments,
       total_revenue=total_revenue, api_keys=api_keys)

# ==================== WEBSITE INTEGRATION GUIDE ====================
@app.route('/integration')
def integration_guide():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Integration Guide</title>
        <style>
            body { font-family: Arial; max-width: 800px; margin: 50px auto; padding: 20px; background: #f5f5f5; }
            .container { background: white; padding: 30px; border-radius: 10px; }
            h1 { color: #333; }
            h2 { color: #667eea; margin-top: 30px; }
            pre { background: #f4f4f4; padding: 15px; border-radius: 5px; overflow-x: auto; }
            code { color: #d63384; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 Payment Gateway Integration Guide</h1>
            <p>যেকোনো ওয়েবসাইটে পেমেন্ট গেটওয়ে যুক্ত করুন</p>
            
            <h2>1. API Key নিন</h2>
            <p>Admin Panel থেকে API Key সংগ্রহ করুন</p>
            
            <h2>2. JavaScript Integration</h2>
            <pre><code>
// আপনার ওয়েবসাইটে যোগ করুন
async function processPayment(amount, method) {
    const response = await fetch('https://your-gateway.com/api/v1/create-payment', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-API-Key': 'YOUR_API_KEY'
        },
        body: JSON.stringify({
            amount: amount,
            method: method,
            order_id: 'ORDER_' + Date.now(),
            callback_url: 'https://your-website.com/callback'
        })
    });
    
    const data = await response.json();
    
    if (data.success) {
        // কাস্টমারকে পেমেন্ট পেজে পাঠান
        window.location.href = data.payment_url;
    }
}
            </code></pre>
            
            <h2>3. PHP Integration</h2>
            <pre><code>
// PHP উদাহরণ
$ch = curl_init();
curl_setopt($ch, CURLOPT_URL, 'https://your-gateway.com/api/v1/create-payment');
curl_setopt($ch, CURLOPT_POST, true);
curl_setopt($ch, CURLOPT_HTTPHEADER, [
    'Content-Type: application/json',
    'X-API-Key: YOUR_API_KEY'
]);
curl_setopt($ch, CURLOPT_POSTFIELDS, json_encode([
    'amount' => 500,
    'method' => 'nagad',
    'order_id' => 'ORDER_123'
]));
$response = curl_exec($ch);
curl_close($ch);
            </code></pre>
            
            <h2>4. Check Payment Status</h2>
            <pre><code>
// পেমেন্ট স্ট্যাটাস চেক করুন
const checkResponse = await fetch('https://your-gateway.com/api/v1/check-payment/PAY123456');
const checkData = await checkResponse.json();

if (checkData.is_completed) {
    console.log('Payment successful!');
    console.log('Transaction ID:', checkData.transaction_id);
}
            </code></pre>
        </div>
    </body>
    </html>
    '''

# ==================== HOME ====================
@app.route('/')
def home():
    if 'user_id' in session:
        if session.get('role') == 'admin':
            return redirect(url_for('admin_dashboard'))
        else:
            return redirect(url_for('provider_dashboard'))
    return redirect(url_for('login_page'))

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)
