from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string
import sqlite3
import re
from datetime import datetime, timedelta
import os
import uuid
import requests
import hashlib
import secrets
from functools import wraps
from flask_cors import CORS

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-123')
CORS(app)

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
                  api_secret TEXT UNIQUE,
                  balance REAL DEFAULT 0,
                  total_received REAL DEFAULT 0,
                  total_transactions INTEGER DEFAULT 0,
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
                  customer_name TEXT,
                  customer_phone TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at DATETIME,
                  matched_transaction_id TEXT,
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

# ==================== API KEY GENERATION ====================
def generate_api_key():
    """ইউনিক API Key জেনারেট করুন"""
    return 'pk_' + secrets.token_urlsafe(32)

def generate_api_secret():
    """ইউনিক API Secret জেনারেট করুন"""
    return 'sk_' + secrets.token_urlsafe(32)

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
    c.execute("""SELECT * FROM providers 
               WHERE api_key=? AND status='active'""", (api_key,))
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
        <title>Login - PayBD</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; }
            .login-box { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 400px; }
            h2 { text-align: center; margin-bottom: 30px; color: #333; }
            input { width: 100%; padding: 14px; margin-bottom: 15px; border: 2px solid #ddd; border-radius: 10px; font-size: 16px; }
            input:focus { outline: none; border-color: #667eea; }
            button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; }
            .register-link { text-align: center; margin-top: 20px; }
            .register-link a { color: #667eea; text-decoration: none; }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>🔐 লগইন</h2>
            <form method="POST">
                <input type="text" name="username" placeholder="ইউজারনেম" required>
                <input type="password" name="password" placeholder="পাসওয়ার্ড" required>
                <button type="submit">লগইন করুন</button>
            </form>
            <div class="register-link">
                <a href="/register">নতুন অ্যাকাউন্ট তৈরি করুন</a>
            </div>
        </div>
    </body>
    </html>
    '''

# ==================== REGISTRATION ====================
@app.route('/register', methods=['GET', 'POST'])
def register_page():
    if request.method == 'POST':
        username = request.form.get('username', '')
        password = request.form.get('password', '')
        email = request.form.get('email', '')
        provider_name = request.form.get('provider_name', '')
        nagad_number = request.form.get('nagad_number', '')
        bkash_number = request.form.get('bkash_number', '')
        
        # Check if username exists
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=?", (username,))
        if c.fetchone():
            conn.close()
            return "Username already exists!"
        
        # Create user
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("""INSERT INTO users (username, password, email, role, created_at)
                   VALUES (?, ?, ?, 'provider', ?)""",
                  (username, password_hash, email, datetime.now()))
        user_id = c.lastrowid
        
        # Generate API Key & Secret
        api_key = generate_api_key()
        api_secret = generate_api_secret()
        
        # Create provider
        c.execute("""INSERT INTO providers 
                   (user_id, provider_name, nagad_number, bkash_number, api_key, api_secret, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (user_id, provider_name, nagad_number, bkash_number, api_key, api_secret, datetime.now()))
        
        conn.commit()
        conn.close()
        
        log_action(user_id, 'register', f'New provider registered: {provider_name}', request.remote_addr)
        
        return redirect(url_for('login_page'))
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Register - PayBD</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }
            .register-box { background: white; padding: 40px; border-radius: 20px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 450px; max-width: 100%; }
            h2 { text-align: center; margin-bottom: 30px; color: #333; }
            input { width: 100%; padding: 14px; margin-bottom: 15px; border: 2px solid #ddd; border-radius: 10px; font-size: 16px; }
            input:focus { outline: none; border-color: #667eea; }
            button { width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; }
        </style>
    </head>
    <body>
        <div class="register-box">
            <h2>📝 প্রোভাইডার রেজিস্ট্রেশন</h2>
            <form method="POST">
                <input type="text" name="username" placeholder="ইউজারনেম" required>
                <input type="password" name="password" placeholder="পাসওয়ার্ড" required>
                <input type="email" name="email" placeholder="ইমেইল" required>
                <input type="text" name="provider_name" placeholder="প্রোভাইডার নাম (আপনার নাম)" required>
                <input type="text" name="nagad_number" placeholder="নগদ নাম্বার (01XXXXXXXXX)">
                <input type="text" name="bkash_number" placeholder="বিকাশ নাম্বার (01XXXXXXXXX)">
                <button type="submit">রেজিস্টার করুন</button>
            </form>
        </div>
    </body>
    </html>
    '''

# ==================== PROVIDER DASHBOARD ====================
@app.route('/provider')
@login_required
def provider_dashboard():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("SELECT * FROM providers WHERE user_id=?", (session['user_id'],))
    provider = c.fetchone()
    
    if not provider:
        return "Provider not found", 404
    
    provider_id = provider[0]
    
    # Stats
    c.execute("SELECT COUNT(*) FROM payments WHERE provider_id=?", (provider_id,))
    total_payments = c.fetchone()[0]
    
    c.execute("SELECT SUM(amount) FROM payments WHERE provider_id=?", (provider_id,))
    total_received = c.fetchone()[0] or 0
    
    c.execute("""SELECT * FROM payments WHERE provider_id=? 
               ORDER BY id DESC LIMIT 10""", (provider_id,))
    recent_payments = c.fetchall()
    
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Provider Dashboard - PayBD</title>
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
            .api-section { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .api-key-box { background: #f8f9fa; padding: 15px; border-radius: 5px; margin-bottom: 10px; }
            .api-key-box code { font-size: 14px; color: #d63384; word-break: break-all; }
            .table-container { background: white; padding: 20px; border-radius: 10px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>🏪 Provider</h2>
            <a href="/provider">📊 Dashboard</a>
            <a href="/provider/api">🔑 API Key</a>
            <a href="/provider/payments">💰 Payments</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        
        <div class="main">
            <div class="header">
                <h1>Welcome, {{ provider_name }}!</h1>
            </div>
            
            <div class="stats">
                <div class="stat-card">
                    <h3>Balance</h3>
                    <p>{{ balance }} Tk</p>
                </div>
                <div class="stat-card">
                    <h3>Total Received</h3>
                    <p>{{ total_received }} Tk</p>
                </div>
                <div class="stat-card">
                    <h3>Total Payments</h3>
                    <p>{{ total_payments }}</p>
                </div>
            </div>
            
            <div class="api-section">
                <h3>🔑 আপনার API Key</h3>
                <div class="api-key-box">
                    <code>{{ api_key }}</code>
                </div>
                <p style="color: #666;">এই API Key ব্যবহার করে আপনার ওয়েবসাইটে পেমেন্ট গ্রহণ করুন</p>
            </div>
            
            <div class="table-container">
                <h3>Recent Payments</h3>
                <table>
                    <tr>
                        <th>Transaction ID</th>
                        <th>Amount</th>
                        <th>Method</th>
                        <th>Time</th>
                    </tr>
                    {% for p in recent_payments %}
                    <tr>
                        <td>{{ p[1] }}</td>
                        <td>{{ p[2] }} Tk</td>
                        <td>{{ p[3].upper() }}</td>
                        <td>{{ p[7] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body>
    </html>
    ''', provider_name=provider[2], balance=provider[5],
       total_received=provider[6], total_payments=total_payments,
       api_key=provider[4], recent_payments=recent_payments)

# ==================== API ENDPOINTS ====================
@app.route('/api/v1/create-payment', methods=['POST'])
def api_create_payment():
    """যেকোনো ওয়েবসাইট থেকে পেমেন্ট তৈরি করুন"""
    try:
        api_key = request.headers.get('X-API-Key') or request.json.get('api_key', '')
        
        provider = verify_api_key(api_key)
        if not provider:
            return jsonify({'success': False, 'error': 'Invalid API Key'}), 401
        
        data = request.json
        amount = float(data.get('amount', 0))
        method = data.get('method', 'nagad').lower()
        order_id = data.get('order_id', str(uuid.uuid4().hex[:8]))
        callback_url = data.get('callback_url', '')
        
        if amount < 1:
            return jsonify({'success': False, 'error': 'Amount must be at least 1 Taka'}), 400
        
        provider_id = provider[0]
        payment_number = provider[3] if method == 'nagad' else provider[4]
        
        request_id = f"PAY{uuid.uuid4().hex[:12].upper()}"
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("""INSERT INTO payment_requests 
                   (request_id, amount, method, provider_id, callback_url, order_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (request_id, amount, method, provider_id, callback_url, order_id, datetime.now()))
        conn.commit()
        conn.close()
        
        return jsonify({
            'success': True,
            'request_id': request_id,
            'payment_url': f"{request.host_url}pay/{request_id}",
            'payment_number': payment_number,
            'amount': amount,
            'method': method,
            'order_id': order_id
        })
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/v1/check-payment/<request_id>', methods=['GET'])
def api_check_payment(request_id):
    """পেমেন্ট স্ট্যাটাস চেক করুন"""
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT status, matched_transaction_id, amount, method 
               FROM payment_requests WHERE request_id=?""", (request_id,))
    result = c.fetchone()
    conn.close()
    
    if not result:
        return jsonify({'success': False, 'error': 'Not found'}), 404
    
    return jsonify({
        'success': True,
        'status': result[0],
        'transaction_id': result[1],
        'amount': result[2],
        'method': result[3],
        'is_completed': result[0] == 'completed'
    })

# ==================== SMS RECEIVER ====================
@app.route('/api/sms', methods=['POST'])
def receive_sms():
    try:
        data = request.json
        sms_text = data.get('sms', '')
        sender = data.get('sender', '')
        
        trx_match = re.search(r'TrxID[:\s]*([A-Z0-9]+)', sms_text, re.IGNORECASE)
        amount_match = re.search(r'(?:BDT|Tk)[:\s]*([\d,]+\.?\d*)', sms_text, re.IGNORECASE)
        
        if trx_match and amount_match:
            transaction_id = trx_match.group(1)
            amount = float(amount_match.group(1).replace(',', ''))
            method = 'nagad' if 'nagad' in sms_text.lower() else 'bkash'
            
            conn = sqlite3.connect('payments.db')
            c = conn.cursor()
            
            # Find provider by number
            c.execute("""SELECT id FROM providers 
                       WHERE nagad_number=? OR bkash_number=?""", (sender, sender))
            provider = c.fetchone()
            provider_id = provider[0] if provider else None
            
            # Save payment
            c.execute("""INSERT INTO payments 
                       (transaction_id, amount, method, sender, provider_id, received_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                      (transaction_id, amount, method, sender, provider_id, datetime.now()))
            
            # Update provider
            if provider_id:
                c.execute("""UPDATE providers 
                           SET balance = balance + ?, 
                               total_received = total_received + ?,
                               total_transactions = total_transactions + 1
                           WHERE id = ?""",
                          (amount, amount, provider_id))
            
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
        
        return jsonify({'success': False, 'error': 'No payment found'}), 400
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

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
    app.run(host='0.0.0.0', port=port)
