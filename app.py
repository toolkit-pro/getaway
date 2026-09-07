from flask import Flask, request, jsonify
import sqlite3
import re
from datetime import datetime, timedelta
import os
import uuid

app = Flask(__name__)

# আপনার নগদ/বিকাশ নাম্বার
NAGAD_NUMBER = "017XXXXXXXX"  # আপনার নগদ নাম্বার দিন
BKASH_NUMBER = "018XXXXXXXX"  # আপনার বিকাশ নাম্বার দিন

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
                  status TEXT DEFAULT 'pending',
                  created_at DATETIME,
                  matched_transaction_id TEXT)''')
    
    conn.commit()
    conn.close()

init_db()

# ============ SMS রিসিভ করুন (MacroDroid থেকে) ============
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
        
        # পেমেন্ট সেভ করুন
        conn = sqlite3.connect('payments.db')
        c = conn.cursor()
        c.execute("INSERT INTO payments (transaction_id, amount, method, sender, received_at) VALUES (?, ?, ?, ?, ?)",
                  (transaction_id, amount, method, data.get('sender', ''), datetime.now()))
        conn.commit()
        
        # পেন্ডিং রিকোয়েস্ট ম্যাচ করুন
        c.execute("""SELECT id FROM payment_requests 
                   WHERE amount=? AND method=? AND status='pending'
                   AND created_at > ?
                   ORDER BY created_at DESC LIMIT 1""",
                  (amount, method, datetime.now() - timedelta(minutes=30)))
        
        result = c.fetchone()
        if result:
            c.execute("""UPDATE payment_requests 
                       SET status='completed', matched_transaction_id=?
                       WHERE id=?""",
                      (transaction_id, result[0]))
            conn.commit()
        
        conn.close()
        
        return jsonify({'success': True, 'message': 'Payment saved'})
    
    return jsonify({'success': False, 'error': 'No payment found'})

# ============ পেমেন্ট রিকোয়েস্ট তৈরি করুন ============
@app.route('/api/create-payment', methods=['POST'])
def create_payment():
    data = request.json
    amount = float(data.get('amount', 0))
    method = data.get('method', 'nagad')
    
    if amount < 10:
        return jsonify({'success': False, 'error': 'Minimum amount is 10 Taka'})
    
    request_id = f"REQ{uuid.uuid4().hex[:10].upper()}"
    payment_number = NAGAD_NUMBER if method == 'nagad' else BKASH_NUMBER
    
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("INSERT INTO payment_requests (request_id, amount, method, created_at) VALUES (?, ?, ?, ?)",
              (request_id, amount, method, datetime.now()))
    conn.commit()
    conn.close()
    
    return jsonify({
        'success': True,
        'request_id': request_id,
        'payment_number': payment_number,
        'amount': amount,
        'method': method,
        'message': f'Please send {amount} Taka to {payment_number} ({method.upper()})'
    })

# ============ পেমেন্ট স্ট্যাটাস চেক করুন ============
@app.route('/api/check-payment/<request_id>')
def check_payment(request_id):
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT status, matched_transaction_id FROM payment_requests WHERE request_id=?", (request_id,))
    result = c.fetchone()
    conn.close()
    
    if result:
        return jsonify({
            'success': True,
            'status': result[0],
            'transaction_id': result[1],
            'is_completed': result[0] == 'completed'
        })
    
    return jsonify({'success': False, 'error': 'Request not found'})

# ============ সব পেমেন্ট দেখুন ============
@app.route('/api/payments')
def get_payments():
    conn = sqlite3.connect('payments.db')
    c = conn.cursor()
    c.execute("SELECT * FROM payments ORDER BY id DESC LIMIT 50")
    payments = c.fetchall()
    conn.close()
    
    payment_list = []
    for p in payments:
        payment_list.append({
            'transaction_id': p[1],
            'amount': p[2],
            'method': p[3],
            'sender': p[4],
            'received_at': p[5]
        })
    
    return jsonify({'payments': payment_list})

# ============ পেমেন্ট পেজ ============
@app.route('/pay')
def payment_page():
    return '''
    <!DOCTYPE html>
    <html lang="bn">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Payment Gateway</title>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                padding: 20px;
            }
            .payment-box {
                background: white;
                border-radius: 15px;
                padding: 30px;
                max-width: 400px;
                width: 100%;
                box-shadow: 0 10px 40px rgba(0,0,0,0.2);
            }
            h2 {
                text-align: center;
                color: #333;
                margin-bottom: 10px;
            }
            .subtitle {
                text-align: center;
                color: #666;
                margin-bottom: 20px;
                font-size: 14px;
            }
            .form-group {
                margin-bottom: 15px;
            }
            label {
                display: block;
                margin-bottom: 5px;
                color: #555;
                font-weight: 600;
                font-size: 14px;
            }
            input, select {
                width: 100%;
                padding: 12px;
                border: 2px solid #ddd;
                border-radius: 8px;
                font-size: 16px;
                transition: border-color 0.3s;
            }
            input:focus, select:focus {
                outline: none;
                border-color: #667eea;
            }
            .pay-btn {
                width: 100%;
                padding: 14px;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 16px;
                font-weight: bold;
                cursor: pointer;
                transition: transform 0.2s;
            }
            .pay-btn:hover {
                transform: translateY(-2px);
            }
            .pay-btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
            }
            .instructions {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 8px;
                margin-top: 20px;
                display: none;
            }
            .instructions h3 {
                color: #333;
                margin-bottom: 10px;
                font-size: 16px;
            }
            .number-box {
                background: #fff3cd;
                padding: 12px;
                border-radius: 6px;
                text-align: center;
                font-size: 20px;
                font-weight: bold;
                color: #856404;
                margin-bottom: 10px;
            }
            .verify-btn {
                width: 100%;
                padding: 12px;
                background: #28a745;
                color: white;
                border: none;
                border-radius: 8px;
                font-size: 14px;
                cursor: pointer;
                margin-top: 10px;
            }
            .status {
                text-align: center;
                margin-top: 15px;
                font-weight: bold;
                display: none;
            }
            .success {
                color: #28a745;
            }
            .pending {
                color: #ffc107;
            }
            .error {
                color: #dc3545;
            }
            .spinner {
                display: inline-block;
                width: 20px;
                height: 20px;
                border: 3px solid #f3f3f3;
                border-top: 3px solid #28a745;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-right: 10px;
                vertical-align: middle;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        </style>
    </head>
    <body>
        <div class="payment-box">
            <h2>💰 পেমেন্ট করুন</h2>
            <p class="subtitle">নগদ/বিকাশে পেমেন্ট করুন</p>
            
            <div class="form-group">
                <label>পেমেন্টের পরিমাণ (টাকা)</label>
                <input type="number" id="amount" min="10" placeholder="যেমন: 500">
            </div>
            
            <div class="form-group">
                <label>পেমেন্ট মাধ্যম</label>
                <select id="method">
                    <option value="nagad">নগদ (Personal)</option>
                    <option value="bkash">বিকাশ (Personal)</option>
                </select>
            </div>
            
            <button class="pay-btn" onclick="createPayment()">পেমেন্ট করুন</button>
            
            <div class="instructions" id="instructions">
                <h3>📱 সেন্ড মানি করুন</h3>
                <p>নিচের নাম্বারে টাকা পাঠান:</p>
                <div class="number-box" id="paymentNumber"></div>
                <p>টাকা পাঠানোর পর "Verify" বাটনে চাপুন</p>
                <button class="verify-btn" onclick="verifyPayment()">✓ Verify Payment</button>
            </div>
            
            <div class="status" id="status"></div>
        </div>
        
        <script>
            let currentRequestId = null;
            const API_BASE = window.location.origin;
            
            async function createPayment() {
                const amount = document.getElementById('amount').value;
                const method = document.getElementById('method').value;
                
                if (!amount || amount < 10) {
                    alert('সর্বনিম্ন ১০ টাকা পেমেন্ট করতে হবে');
                    return;
                }
                
                try {
                    const response = await fetch(API_BASE + '/api/create-payment', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({amount: amount, method: method})
                    });
                    
                    const data = await response.json();
                    
                    if (data.success) {
                        currentRequestId = data.request_id;
                        document.getElementById('paymentNumber').textContent = data.payment_number;
                        document.getElementById('instructions').style.display = 'block';
                        document.querySelector('.pay-btn').disabled = true;
                    } else {
                        alert('Error: ' + data.error);
                    }
                } catch (error) {
                    alert('Server error. Please try again.');
                }
            }
            
            async function verifyPayment() {
                if (!currentRequestId) return;
                
                const statusDiv = document.getElementById('status');
                statusDiv.style.display = 'block';
                statusDiv.className = 'status pending';
                statusDiv.innerHTML = '<span class="spinner"></span> পেমেন্ট ভেরিফাই হচ্ছে...';
                
                try {
                    const response = await fetch(API_BASE + '/api/check-payment/' + currentRequestId);
                    const data = await response.json();
                    
                    if (data.is_completed) {
                        statusDiv.className = 'status success';
                        statusDiv.innerHTML = '✅ পেমেন্ট সফল হয়েছে!<br>Transaction ID: ' + data.transaction_id;
                        document.getElementById('instructions').style.display = 'none';
                    } else {
                        statusDiv.className = 'status pending';
                        statusDiv.innerHTML = '⏳ পেমেন্ট পাওয়া যায়নি। আবার চেষ্টা করুন';
                        
                        // ৫ সেকেন্ড পর আবার চেক করুন
                        setTimeout(verifyPayment, 5000);
                    }
                } catch (error) {
                    statusDiv.className = 'status error';
                    statusDiv.innerHTML = '❌ Server error';
                }
            }
        </script>
    </body>
    </html>
    '''

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
                display: flex; justify-content: space-between; align-items: center;
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
            .pay-link {
                background: #28a745; color: white; padding: 10px 20px;
                border-radius: 5px; text-decoration: none; font-weight: bold;
            }
            .pay-link:hover { background: #218838; }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1>💰 Payment Dashboard</h1>
                    <p>Real-time payment monitoring</p>
                </div>
                <a href="/pay" class="pay-link">💳 Payment Page</a>
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
