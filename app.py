from flask import Flask, request, jsonify, session, redirect, url_for, render_template_string
import sqlite3
import re
from datetime import datetime, timedelta
import os
import uuid
import requests
import hashlib
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-this-123')

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
            <script>alert("❌ Invalid username or password!"); window.location.href="/login";</script>
        ''')
    
    return '''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Login - Payment Gateway</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: Arial, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
            }
            .login-box {
                background: white;
                padding: 40px;
                border-radius: 15px;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
                width: 380px;
            }
            h2 { text-align: center; color: #333; margin-bottom: 30px; font-size: 28px; }
            .form-group { margin-bottom: 20px; }
            label { display: block; margin-bottom: 5px; color: #555; font-weight: 600; }
            input {
                width: 100%;
                padding: 12px;
                border: 2px solid #ddd;
                border-radius: 8px;
                font-size: 16px;
                transition: border-color 0.3s;
            }
            input:focus { outline: none; border-color: #667eea; }
            button {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                margin-top: 10px;
            }
            button:hover { transform: translateY(-2px); }
            .info {
                text-align: center;
                margin-top: 20px;
                color: #666;
                font-size: 14px;
            }
        </style>
    </head>
    <body>
        <div class="login-box">
            <h2>🔐 Login</h2>
            <form method="POST">
                <div class="form-group">
                    <label>Username</label>
                    <input type="text" name="username" placeholder="Enter username" required>
                </div>
                <div class="form-group">
                    <label>Password</label>
                    <input type="password" name="password" placeholder="Enter password" required>
                </div>
                <button type="submit">Login</button>
            </form>
            <div class="info">
                Default Admin: admin / admin123
            </div>
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
    
    # Stats
    c.execute("SELECT COUNT(*) FROM providers WHERE status='active'")
    total_providers = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM payments")
    total_payments = c.fetchone()[0]
    
    c.execute("SELECT SUM(amount) FROM payments")
    total_revenue = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM payments WHERE received_at >= date('now')")
    today_payments = c.fetchone()[0]
    
    # Recent payments
    c.execute("""SELECT p.*, pr.provider_name FROM payments p
               LEFT JOIN providers pr ON p.provider_id = pr.id
               ORDER BY p.id DESC LIMIT 10""")
    recent_payments = c.fetchall()
    
    # Providers
    c.execute("""SELECT p.*, u.username FROM providers p 
               JOIN users u ON p.user_id = u.id""")
    providers = c.fetchall()
    
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Admin Dashboard</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial, sans-serif; background: #f0f2f5; }
            .sidebar {
                width: 250px;
                background: #2c3e50;
                height: 100vh;
                position: fixed;
                padding: 20px;
            }
            .sidebar h2 { color: white; margin-bottom: 30px; text-align: center; }
            .sidebar a {
                display: block;
                color: #ecf0f1;
                padding: 12px;
                text-decoration: none;
                border-radius: 5px;
                margin-bottom: 5px;
                transition: background 0.3s;
            }
            .sidebar a:hover { background: #34495e; }
            .main { margin-left: 250px; padding: 20px; }
            .header {
                background: white;
                padding: 20px;
                border-radius: 10px;
                margin-bottom: 20px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .stats {
                display: grid;
                grid-template-columns: repeat(4, 1fr);
                gap: 15px;
                margin-bottom: 20px;
            }
            .stat-card {
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .stat-card h3 { color: #666; margin-bottom: 10px; font-size: 14px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container {
                background: white;
                padding: 20px;
                border-radius: 10px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
                overflow-x: auto;
                margin-bottom: 20px;
            }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            tr:hover { background: #f8f9fa; }
            .nagad { color: #f47721; font-weight: bold; }
            .bkash { color: #d12053; font-weight: bold; }
            .status-active { color: #28a745; font-weight: bold; }
            .status-inactive { color: #dc3545; font-weight: bold; }
            @media (max-width: 768px) {
                .sidebar { width: 100%; height: auto; position: relative; }
                .main { margin-left: 0; }
                .stats { grid-template-columns: repeat(2, 1fr); }
            }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>⚙️ Admin Panel</h2>
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/providers">👥 Providers</a>
            <a href="/admin/transactions">💰 Transactions</a>
            <a href="/admin/logs">📝 Logs</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        
        <div class="main">
            <div class="header">
                <h1>📊 Admin Dashboard</h1>
                <p>Welcome back, Admin!</p>
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
                    <h3>Today's Payments</h3>
                    <p>{{ today_payments }}</p>
                </div>
            </div>
            
            <div class="table-container">
                <h3>Recent Payments</h3>
                <table>
                    <tr>
                        <th>Transaction ID</th>
                        <th>Amount</th>
                        <th>Method</th>
                        <th>Provider</th>
                        <th>Time</th>
                    </tr>
                    {% for p in recent_payments %}
                    <tr>
                        <td><strong>{{ p[1] }}</strong></td>
                        <td>{{ p[2] }} Tk</td>
                        <td class="{{ p[3] }}">{{ p[3].upper() }}</td>
                        <td>{{ p[9] if p[9] else 'N/A' }}</td>
                        <td>{{ p[7] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
            
            <div class="table-container">
                <h3>Providers</h3>
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Username</th>
                        <th>Nagad</th>
                        <th>Bkash</th>
                        <th>Balance</th>
                        <th>Status</th>
                    </tr>
                    {% for p in providers %}
                    <tr>
                        <td>{{ p[0] }}</td>
                        <td>{{ p[2] }}</td>
                        <td>{{ p[8] }}</td>
                        <td>{{ p[3] }}</td>
                        <td>{{ p[4] }}</td>
                        <td>{{ p[5] }} Tk</td>
                        <td class="status-{{ p[6] }}">{{ p[6] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body>
    </html>
    ''', total_providers=total_providers, total_payments=total_payments,
       total_revenue=total_revenue, today_payments=today_payments,
       recent_payments=recent_payments, providers=providers)

# ==================== ADMIN - PROVIDERS ====================
@app.route('/admin/providers')
@admin_required
def admin_providers():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT p.*, u.username FROM providers p 
               JOIN users u ON p.user_id = u.id""")
    providers = c.fetchall()
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Providers Management</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: #f0f2f5; }
            .sidebar { width: 250px; background: #2c3e50; height: 100vh; position: fixed; padding: 20px; }
            .sidebar h2 { color: white; margin-bottom: 30px; }
            .sidebar a { display: block; color: #ecf0f1; padding: 12px; text-decoration: none; border-radius: 5px; margin-bottom: 5px; }
            .sidebar a:hover { background: #34495e; }
            .main { margin-left: 250px; padding: 20px; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
            .btn { padding: 10px 20px; border: none; border-radius: 5px; cursor: pointer; font-size: 14px; margin-right: 5px; }
            .btn-primary { background: #007bff; color: white; }
            .btn-success { background: #28a745; color: white; }
            .btn-danger { background: #dc3545; color: white; }
            .table-container { background: white; padding: 20px; border-radius: 10px; overflow-x: auto; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
            .modal { display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.5); }
            .modal-content { background: white; padding: 30px; border-radius: 10px; width: 400px; margin: 100px auto; }
            input { width: 100%; padding: 10px; margin-bottom: 10px; border: 1px solid #ddd; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>⚙️ Admin Panel</h2>
            <a href="/admin">📊 Dashboard</a>
            <a href="/admin/providers">👥 Providers</a>
            <a href="/admin/transactions">💰 Transactions</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        
        <div class="main">
            <div class="header">
                <h1>👥 Providers Management</h1>
                <button class="btn btn-success" onclick="showAddForm()">+ Add Provider</button>
            </div>
            
            <div class="table-container">
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Username</th>
                        <th>Nagad</th>
                        <th>Bkash</th>
                        <th>Balance</th>
                        <th>Status</th>
                        <th>Actions</th>
                    </tr>
                    {% for p in providers %}
                    <tr>
                        <td>{{ p[0] }}</td>
                        <td>{{ p[2] }}</td>
                        <td>{{ p[8] }}</td>
                        <td>{{ p[3] }}</td>
                        <td>{{ p[4] }}</td>
                        <td>{{ p[5] }} Tk</td>
                        <td>{{ p[6] }}</td>
                        <td>
                            <button class="btn btn-primary">Edit</button>
                            <button class="btn btn-danger">Delete</button>
                        </td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
        
        <div class="modal" id="addModal">
            <div class="modal-content">
                <h2>Add Provider</h2>
                <form method="POST" action="/admin/add-provider">
                    <input type="text" name="username" placeholder="Username" required>
                    <input type="password" name="password" placeholder="Password" required>
                    <input type="text" name="provider_name" placeholder="Provider Name" required>
                    <input type="text" name="nagad_number" placeholder="Nagad Number">
                    <input type="text" name="bkash_number" placeholder="Bkash Number">
                    <button type="submit" class="btn btn-success">Add Provider</button>
                    <button type="button" class="btn btn-danger" onclick="hideAddForm()">Cancel</button>
                </form>
            </div>
        </div>
        
        <script>
            function showAddForm() { document.getElementById('addModal').style.display = 'block'; }
            function hideAddForm() { document.getElementById('addModal').style.display = 'none'; }
        </script>
    </body>
    </html>
    ''', providers=providers)

@app.route('/admin/add-provider', methods=['POST'])
@admin_required
def add_provider():
    username = request.form.get('username')
    password = request.form.get('password')
    provider_name = request.form.get('provider_name')
    nagad_number = request.form.get('nagad_number', '')
    bkash_number = request.form.get('bkash_number', '')
    
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    
    c.execute("""INSERT INTO users (username, password, role, created_at)
               VALUES (?, ?, 'provider', ?)""",
              (username, password_hash, datetime.now()))
    user_id = c.lastrowid
    
    c.execute("""INSERT INTO providers (user_id, provider_name, nagad_number, bkash_number, created_at)
               VALUES (?, ?, ?, ?, ?)""",
              (user_id, provider_name, nagad_number, bkash_number, datetime.now()))
    
    conn.commit()
    conn.close()
    
    log_action(session['user_id'], 'add_provider', f'Added provider: {provider_name}', request.remote_addr)
    
    return redirect(url_for('admin_providers'))

# ==================== ADMIN - TRANSACTIONS ====================
@app.route('/admin/transactions')
@admin_required
def admin_transactions():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("""SELECT p.*, pr.provider_name FROM payments p
               LEFT JOIN providers pr ON p.provider_id = pr.id
               ORDER BY p.id DESC""")
    payments = c.fetchall()
    conn.close()
    
    return render_template_string('''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Transactions</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body { font-family: Arial; background: #f0f2f5; }
            .sidebar { width: 250px; background: #2c3e50; height: 100vh; position: fixed; padding: 20px; }
            .sidebar h2 { color: white; margin-bottom: 30px; }
            .sidebar a { display: block; color: #ecf0f1; padding: 12px; text-decoration: none; border-radius: 5px; margin-bottom: 5px; }
            .sidebar a:hover { background: #34495e; }
            .main { margin-left: 250px; padding: 20px; }
            .header { background: white; padding: 20px; border-radius: 10px; margin-bottom: 20px; }
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
            <a href="/admin/providers">👥 Providers</a>
            <a href="/admin/transactions">💰 Transactions</a>
            <a href="/logout">🚪 Logout</a>
        </div>
        
        <div class="main">
            <div class="header">
                <h1>💰 All Transactions</h1>
            </div>
            
            <div class="table-container">
                <table>
                    <tr>
                        <th>ID</th>
                        <th>Transaction ID</th>
                        <th>Amount</th>
                        <th>Method</th>
                        <th>Sender</th>
                        <th>Provider</th>
                        <th>Time</th>
                    </tr>
                    {% for p in payments %}
                    <tr>
                        <td>{{ p[0] }}</td>
                        <td><strong>{{ p[1] }}</strong></td>
                        <td>{{ p[2] }} Tk</td>
                        <td>{{ p[3].upper() }}</td>
                        <td>{{ p[4] or 'N/A' }}</td>
                        <td>{{ p[9] if p[9] else 'N/A' }}</td>
                        <td>{{ p[7] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body>
    </html>
    ''', payments=payments)

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
        <title>Provider Dashboard</title>
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
            .stat-card h3 { color: #666; margin-bottom: 10px; font-size: 14px; }
            .stat-card p { font-size: 24px; font-weight: bold; color: #667eea; }
            .table-container { background: white; padding: 20px; border-radius: 10px; overflow-x: auto; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 12px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background: #667eea; color: white; }
        </style>
    </head>
    <body>
        <div class="sidebar">
            <h2>🏪 Provider</h2>
            <a href="/provider">📊 Dashboard</a>
            <a href="/provider/payments">💰 Payments</a>
            <a href="/provider/settings">⚙️ Settings</a>
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
                    {% for p in recent_payments %}
                    <tr>
                        <td><strong>{{ p[1] }}</strong></td>
                        <td>{{ p[2] }} Tk</td>
                        <td>{{ p[3].upper() }}</td>
                        <td>{{ p[4] or 'N/A' }}</td>
                        <td>{{ p[7] }}</td>
                    </tr>
                    {% endfor %}
                </table>
            </div>
        </div>
    </body>
    </html>
    ''', provider_name=provider[2], balance=provider[5],
       total_received=total_received, total_payments=total_payments,
       recent_payments=recent_payments)

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
            
            # Find provider by method
            c.execute("""SELECT id FROM providers 
                       WHERE status='active' 
                       ORDER BY id ASC LIMIT 1""")
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

# ==================== HEALTH CHECK ====================
@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'time': datetime.now().isoformat()
    })

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
