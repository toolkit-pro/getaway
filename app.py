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
    
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  username TEXT UNIQUE,
                  password TEXT,
                  email TEXT,
                  role TEXT DEFAULT 'provider',
                  created_at DATETIME)''')
    
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
    return 'pk_live_' + secrets.token_urlsafe(32)

def generate_api_secret():
    return 'sk_live_' + secrets.token_urlsafe(32)

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
            return "⛔ Access Denied. Admin only!", 403
        
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

def verify_api_key(api_key):
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
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
        
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        
        c.execute("SELECT id FROM users WHERE username=?", (username,))
        if c.fetchone():
            conn.close()
            return "Username already exists!"
        
        password_hash = hashlib.sha256(password.encode()).hexdigest()
        c.execute("""INSERT INTO users (username, password, email, role, created_at)
                   VALUES (?, ?, ?, 'provider', ?)""",
                  (username, password_hash, email, datetime.now()))
        user_id = c.lastrowid
        
        api_key = generate_api_key()
        api_secret = generate_api_secret()
        
        c.execute("""INSERT INTO providers 
                   (user_id, provider_name, nagad_number, bkash_number, api_key, api_secret, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                  (user_id, provider_name, nagad_number, bkash_number, api_key, api_secret, datetime.now()))
        
        conn.commit()
        conn.close()
        
        log_action(user_id, 'register', f'New provider: {provider_name}', request.remote_addr)
        
        return redirect(url_for('login_page'))
    
    return '''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
                <input type="text" name="provider_name" placeholder="প্রোভাইডার নাম" required>
                <input type="text" name="nagad_number" placeholder="নগদ নাম্বার (01XXXXXXXXX)">
                <input type="text" name="bkash_number" placeholder="বিকাশ নাম্বার (01XXXXXXXXX)">
                <button type="submit">রেজিস্টার করুন</button>
            </form>
        </div>
    </body>
    </html>
    '''

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

# ==================== ADMIN DASHBOARD ====================
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM providers WHERE status='active'")
    total_providers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM payments")
    total_payments = c.fetchone()[0]
    
    c.execute("SELECT SUM(amount) FROM payments")
    total_revenue = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM payments WHERE received_at >= date('now')")
    today_payments = c.fetchone()[0]
    
    c.execute("""SELECT p.*, pr.provider_name FROM payments p
               LEFT JOIN providers pr ON p.provider_id = pr.id
               ORDER BY p.id DESC LIMIT 10""")
    recent_payments = c.fetchall()
    
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Dashboard - PayBD</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: #f0f2f5; }
            .sidebar { width: 250px; background: #2c3e50; height: 100vh; position: fixed; padding: 20px; }
            .sidebar h2 { color: white; margin-bottom: 30px; }
            .sidebar a { display: block; color: #ecf0f1; padding: 12px; text-decoration: none; border-radius: 5px; margin-bottom: 5px; }
            .sidebar a:hover { background: #34495e; }
            .main { margin-left: 250px; padding: 20px; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .stats { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin-bottom: 20px; }
            .stat-card { background: white; padding: 20px; border-radius: 10px; }
            .stat-card h3 { color: #666; margin-bottom: 10px; font-size: 14px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container { background: white; padding: 20px; border-radius: 10px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>⚙️ Admin</h2>
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/providers">👥 Providers</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <div class="header">
                <h1>Admin Dashboard</h1>
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
                <div class="stat-card">
                    <h3>Today</h3>
                    <p>{{ today_payments }}</p>
                </div>
            </div>
            <div class="table-container">
                <h3>Recent Payments</h3>
                <table>
                    <tr>
                        <th>Transaction</th>
                        <th>Amount</th>
                        <th>Method</th>
                        <th>Provider</th>
                    </tr>
                    {% for p in recent_payments %}
                    <tr>
                        <td>{{ p[1] }}</td>
                        <td>{{ p[2] }} Tk</td>
                        <td>{{ p[3].upper() }}</td>
                        <td>{{ p[9] or 'N/A' }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body>
    </html>
    ''', total_providers=total_providers, total_payments=total_payments,
       total_revenue=total_revenue, today_payments=today_payments,
       recent_payments=recent_payments)

# ==================== ADMIN - PROVIDERS ====================
@app.route('/admin/providers')
@admin_required
def admin_providers():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    search = request.args.get('search', '')
    status_filter = request.args.get('status', '')
    
    query = """SELECT p.id, p.provider_name, p.nagad_number, p.bkash_number, 
                      p.api_key, p.balance, p.total_received, p.status,
                      u.username, u.email
               FROM providers p 
               JOIN users u ON p.user_id = u.id
               WHERE 1=1"""
    
    params = []
    
    if search:
        query += """ AND (p.provider_name LIKE ? OR u.username LIKE ? 
                    OR p.nagad_number LIKE ? OR p.bkash_number LIKE ?)"""
        search_param = f"%{search}%"
        params.extend([search_param, search_param, search_param, search_param])
    
    if status_filter:
        query += " AND p.status = ?"
        params.append(status_filter)
    
    query += " ORDER BY p.id DESC"
    
    c.execute(query, params)
    providers = c.fetchall()
    
    c.execute("SELECT COUNT(*) FROM providers WHERE status='active'")
    active_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM providers WHERE status='inactive'")
    inactive_count = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM providers WHERE status='pending'")
    pending_count = c.fetchone()[0]
    
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Providers - PayBD Admin</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: #f0f2f5; }
            .sidebar { width: 250px; background: #2c3e50; height: 100vh; position: fixed; padding: 20px; }
            .sidebar h2 { color: white; margin-bottom: 30px; }
            .sidebar a { display: block; color: #ecf0f1; padding: 12px; text-decoration: none; border-radius: 5px; margin-bottom: 5px; }
            .sidebar a:hover { background: #34495e; }
            .main { margin-left: 250px; padding: 20px; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; }
            .stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 15px; margin-bottom: 20px; }
            .stat-card { background: white; padding: 20px; border-radius: 10px; text-align: center; }
            .stat-card h3 { color: #666; font-size: 14px; }
            .stat-card p { font-size: 24px; font-weight: bold; }
            .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; }
            .btn-success { background: #28a745; color: white; }
            .btn-danger { background: #dc3545; color: white; }
            .btn-sm { padding: 5px 10px; font-size: 12px; }
            .table-container { background: white; padding: 20px; border-radius: 10px; overflow-x: auto; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            .status-badge { padding: 4px 10px; border-radius: 20px; font-size: 12px; font-weight: bold; }
            .status-active { background: #d4edda; color: #155724; }
            .status-inactive { background: #f8d7da; color: #721c24; }
            .status-pending { background: #fff3cd; color: #856404; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); z-index: 1000; }
            .modal-content { background: white; padding: 30px; border-radius: 10px; width: 500px; max-width: 90%; margin: 50px auto; }
            .modal-content input { width: 100%; padding: 10px; margin-bottom: 15px; border: 1px solid #ddd; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>⚙️ Admin</h2>
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/providers">👥 Providers</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <div class="header">
                <h1>👥 Providers Management</h1>
                <button class="btn btn-success" onclick="showAddModal()">+ Add Provider</button>
            </div>
            <div class="stats">
                <div class="stat-card">
                    <h3>Active</h3>
                    <p style="color: #28a745;">{{ active_count }}</p>
                </div>
                <div class="stat-card">
                    <h3>Pending</h3>
                    <p style="color: #ffc107;">{{ pending_count }}</p>
                </div>
                <div class="stat-card">
                    <h3>Inactive</h3>
                    <p style="color: #dc3545;">{{ inactive_count }}</p>
                </div>
            </div>
            <div class="table-container">
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Provider</th>
                        <th>Numbers</th>
                        <th>API Key</th>
                        <th>Balance</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                    {% for p in providers %}
                    <tr>
                        <td>#{{ p[0] }}</td>
                        <td>
                            <strong>{{ p[1] }}</strong><br>
                            <small>@{{ p[8] }}</small><br>
                            <small>{{ p[9] }}</small>
                        </td>
                        <td>
                            <small>Nagad: {{ p[2] or 'N/A' }}</small><br>
                            <small>Bkash: {{ p[3] or 'N/A' }}</small>
                        </td>
                        <td><code style="font-size:12px;">{{ p[4][:20] }}...</code></td>
                        <td>{{ p[5] }} Tk</td>
                        <td><span class="status-badge status-{{ p[7] }}">{{ p[7] }}</span></td>
                        <td>
                            <button class="btn btn-danger btn-sm" onclick="deleteProvider({{ p[0] }})">Delete</button>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
        <div class="modal" id="addModal">
            <div class="modal-content">
                <h2>Add New Provider</h2>
                <form method="POST" action="/admin/add-provider">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="password" name="password" placeholder="Password" required>
                    <input type="email" name="email" placeholder="Email" required>
                    <input type="text" name="provider_name" placeholder="Provider Name" required>
                    <input type="text" name="nagad_number" placeholder="Nagad Number">
                    <input type="text" name="bkash_number" placeholder="Bkash Number">
                    <button type="submit" class="btn btn-success">Create</button>
                    <button type="button" class="btn btn-danger" onclick="hideAddModal()">Cancel</button>
                </form>
            </div>
        </div>
        <script>
            function showAddModal() { document.getElementById('addModal').style.display = 'block'; }
            function hideAddModal() { document.getElementById('addModal').style.display = 'none'; }
            function deleteProvider(id) {
                if (confirm('Delete this provider?')) {
                    fetch('/admin/delete-provider/' + id, { method: 'POST' })
                        .then(r => r.json())
                        .then(d => { if (d.success) location.reload(); });
                }
            }
        </script>
    </body>
    </html>
    ''', providers=providers, active_count=active_count,
       inactive_count=inactive_count, pending_count=pending_count,
       search=search, status_filter=status_filter)

# ==================== ADD PROVIDER ====================
@app.route('/admin/add-provider', methods=['POST'])
@admin_required
def add_provider():
    username = request.form.get('username')
    password = request.form.get('password')
    email = request.form.get('email')
    provider_name = request.form.get('provider_name')
    nagad_number = request.form.get('nagad_number', '')
    bkash_number = request.form.get('bkash_number', '')
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    api_key = generate_api_key()
    api_secret = generate_api_secret()
    
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("SELECT id FROM users WHERE username=?", (username,))
    if c.fetchone():
        conn.close()
        return "Username already exists!"
    
    c.execute("""INSERT INTO users (username, password, email, role, created_at)
               VALUES (?, ?, ?, 'provider', ?)""",
              (username, password_hash, email, datetime.now()))
    user_id = c.lastrowid
    
    c.execute("""INSERT INTO providers 
               (user_id, provider_name, nagad_number, bkash_number, api_key, api_secret, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
              (user_id, provider_name, nagad_number, bkash_number, api_key, api_secret, datetime.now()))
    
    conn.commit()
    conn.close()
    
    log_action(session['user_id'], 'add_provider', f'Added: {provider_name}', request.remote_addr)
    
    return redirect(url_for('admin_providers'))

# ==================== DELETE PROVIDER ====================
@app.route('/admin/delete-provider/<int:provider_id>', methods=['POST'])
@admin_required
def delete_provider(provider_id):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("SELECT user_id FROM providers WHERE id=?", (provider_id,))
    result = c.fetchone()
    
    if result:
        user_id = result[0]
        c.execute("DELETE FROM providers WHERE id=?", (provider_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        log_action(session['user_id'], 'delete_provider', f'Deleted #{provider_id}', request.remote_addr)
    
    conn.close()
    return jsonify({'success': True})

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
    
    c.execute("SELECT COUNT(*) FROM payments WHERE provider_id=?", (provider_id,))
    total_payments = c.fetchone()[0]
    
    c.execute("""SELECT * FROM payments WHERE provider_id=? 
               ORDER BY id DESC LIMIT 10""", (provider_id,))
    recent_payments = c.fetchall()
    
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
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
            .stat-card h3 { color: #666; font-size: 14px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .api-section { background: white; padding: 25px; border-radius: 15px; margin-bottom: 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            .api-section h3 { color: #333; margin-bottom: 15px; font-size: 18px; }
            .api-key-display { background: #f8f9fa; border: 2px dashed #667eea; padding: 15px; border-radius: 10px; margin-bottom: 15px; }
            .api-key-display code { font-size: 16px; color: #d63384; word-break: break-all; font-weight: bold; }
            .copy-btn { background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: bold; transition: all 0.3s; }
            .copy-btn:hover { background: #0056b3; }
            .copy-btn.copied { background: #28a745; }
            .api-info { background: #e8f4fd; padding: 15px; border-radius: 8px; margin-top: 15px; font-size: 14px; color: #0066cc; }
            .table-container { background: white; padding: 20px; border-radius: 10px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            @media (max-width: 768px) {
                .sidebar { width: 100%; height: auto; position: relative; }
                .main { margin-left: 0; }
                .stats { grid-template-columns: 1fr; }
            }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>🏪 Provider</h2>
            <a href="/provider">📊 Dashboard</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        <div class="main">
            <div class="header">
                <h1>Welcome, {{ provider[2] }}!</h1>
            </div>
            <div class="stats">
                <div class="stat-card">
                    <h3>Balance</h3>
                    <p>{{ provider[5] }} Tk</p>
                </div>
                <div class="stat-card">
                    <h3>Total Received</h3>
                    <p>{{ provider[6] }} Tk</p>
                </div>
                <div class="stat-card">
                    <h3>Total Payments</h3>
                    <p>{{ total_payments }}</p>
                </div>
            </div>
            <div class="api-section">
                <h3>🔑 আপনার API Key</h3>
                <div class="api-key-display">
                    <code id="apiKey">{{ provider[4] }}</code>
                </div>
                <button class="copy-btn" id="copyBtn" onclick="copyAPIKey()">📋 API Key কপি করুন</button>
                <div class="api-info">
                    <strong>ℹ️ ব্যবহার নিয়ম:</strong><br>
                    ১. এই API Key আপনার ওয়েবসাইটে ব্যবহার করুন<br>
                    ২. Header এ পাঠান: <code>X-API-Key: {{ provider[4][:20] }}...</code><br>
                    ৩. এই Key কারো সাথে শেয়ার করবেন না
                </div>
            </div>
            <div class="table-container">
                <h3>Recent Payments</h3>
                <table>
                    <tr>
                        <th>Transaction</th>
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
        <script>
            function copyAPIKey() {
                const apiKey = document.getElementById('apiKey').textContent;
                const copyBtn = document.getElementById('copyBtn');
                navigator.clipboard.writeText(apiKey).then(() => {
                    copyBtn.textContent = '✅ কপি হয়েছে!';
                    copyBtn.classList.add('copied');
                    setTimeout(() => {
                        copyBtn.textContent = '📋 API Key কপি করুন';
                        copyBtn.classList.remove('copied');
                    }, 2000);
                }).catch(() => {
                    const textArea = document.createElement('textarea');
                    textArea.value = apiKey;
                    document.body.appendChild(textArea);
                    textArea.select();
                    document.execCommand('copy');
                    document.body.removeChild(textArea);
                    copyBtn.textContent = '✅ কপি হয়েছে!';
                    setTimeout(() => {
                        copyBtn.textContent = '📋 API Key কপি করুন';
                    }, 2000);
                });
            }
        </script>
    </body>
    </html>
    ''', provider=provider, total_payments=total_payments, recent_payments=recent_payments)

# ==================== API ENDPOINTS ====================
@app.route('/api/v1/create-payment', methods=['POST'])
def api_create_payment():
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
            
            c.execute("""SELECT id FROM providers 
                       WHERE nagad_number=? OR bkash_number=?""", (sender, sender))
            provider = c.fetchone()
            provider_id = provider[0] if provider else None
            
            c.execute("""INSERT INTO payments 
                       (transaction_id, amount, method, sender, provider_id, received_at)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                      (transaction_id, amount, method, sender, provider_id, datetime.now()))
            
            if provider_id:
                c.execute("""UPDATE providers 
                           SET balance = balance + ?, 
                               total_received = total_received + ?,
                               total_transactions = total_transactions + 1
                           WHERE id = ?""",
                          (amount, amount, provider_id))
                
                c.execute("""SELECT id FROM payment_requests 
                           WHERE amount=? AND method=? AND status='pending'
                           AND provider_id=? AND created_at > ?
                           ORDER BY created_at DESC LIMIT 1""",
                          (amount, method, provider_id, datetime.now() - timedelta(minutes=30)))
                
                pending = c.fetchone()
                if pending:
                    c.execute("""UPDATE payment_requests 
                               SET status='completed', matched_transaction_id=?
                               WHERE id=?""",
                              (transaction_id, pending[0]))
            
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

# ==================== PAYMENT PAGE ====================
@app.route('/pay/<request_id>')
def payment_page(request_id):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT amount, method, status FROM payment_requests 
               WHERE request_id=?""", (request_id,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        return "Payment request not found", 404
    
    amount, method, status = result
    
    if status == 'completed':
        conn.close()
        return '<div style="text-align:center;margin-top:100px;"><h1 style="color:green;">✅ Payment Already Completed!</h1></div>'
    
    c.execute("""SELECT p.nagad_number, p.bkash_number 
               FROM providers p
               JOIN payment_requests pr ON p.id = pr.provider_id
               WHERE pr.request_id=?""", (request_id,))
    provider = c.fetchone()
    conn.close()
    
    if not provider:
        return "Provider not found", 404
    
    payment_number = provider[0] if method == 'nagad' else provider[1]
    
    return f'''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment - {amount} Taka</title>
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: Arial; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; justify-content: center; align-items: center; padding: 20px; }}
            .payment-card {{ background: white; border-radius: 20px; padding: 30px; max-width: 400px; width: 100%; box-shadow: 0 20px 60px rgba(0,0,0,0.3); }}
            h2 {{ text-align: center; color: #333; margin-bottom: 20px; }}
            .amount {{ text-align: center; font-size: 36px; font-weight: bold; color: #667eea; margin-bottom: 10px; }}
            .number-box {{ background: #fff3cd; padding: 15px; border-radius: 10px; text-align: center; font-size: 24px; font-weight: bold; color: #856404; margin-bottom: 20px; }}
            .btn {{ width: 100%; padding: 14px; border: none; border-radius: 10px; font-size: 16px; font-weight: bold; cursor: pointer; margin-bottom: 10px; }}
            .btn-copy {{ background: #007bff; color: white; }}
            .btn-verify {{ background: #28a745; color: white; }}
        </style>
    </head>
    <body>
        <div class="payment-card">
            <h2>💰 পেমেন্ট করুন</h2>
            <div class="amount">{amount} টাকা</div>
            <p style="text-align:center; margin-bottom:10px;">সেন্ড মানি করুন:</p>
            <div class="number-box">{payment_number}</div>
            <button class="btn btn-copy" onclick="copyNumber()">📋 নাম্বার কপি</button>
            <button class="btn btn-verify" onclick="verifyPayment()">✓ ভেরিফাই করুন</button>
            <div id="status" style="text-align:center; margin-top:15px; font-weight:bold;"></div>
        </div>
        <script>
            function copyNumber() {{
                navigator.clipboard.writeText('{payment_number}');
                alert('নাম্বার কপি হয়েছে!');
            }}
            async function verifyPayment() {{
                const statusDiv = document.getElementById('status');
                statusDiv.innerHTML = '⏳ চেক হচ্ছে...';
                const response = await fetch('/api/v1/check-payment/{request_id}');
                const data = await response.json();
                if (data.is_completed) {{
                    statusDiv.innerHTML = '✅ পেমেন্ট সফল!<br>Transaction: ' + data.transaction_id;
                    statusDiv.style.color = '#28a745';
                }} else {{
                    statusDiv.innerHTML = '⏳ এখনো পেমেন্ট পাওয়া যায়নি';
                    statusDiv.style.color = '#f59e0b';
                    setTimeout(verifyPayment, 5000);
                }}
            }}
        </script>
    </body>
    </html>
    '''

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
