# 💰 Nagad/Bkash Payment Gateway

সম্পূর্ণ ফ্রি এবং অটোমেটিক পেমেন্ট গেটওয়ে সিস্টেম

## ✨ ফিচারসমূহ

- 📱 SMS Auto-Detection (MacroDroid)
- 🔄 Real-time Payment Verification
- 🤖 Telegram Notification
- 📊 Live Dashboard
- 💾 SQLite Database
- 🌐 REST API

## 🚀 ডিপ্লয়মেন্ট

### Render.com এ ডিপ্লয় করুন

1. GitHub এ এই repository push করুন
2. Render.com এ সাইন আপ করুন
3. New Web Service তৈরি করুন
4. Build Command: `pip install -r requirements.txt`
5. Start Command: `gunicorn app:app`

### MacroDroid সেটআপ

1. MacroDroid অ্যাপ ইনস্টল করুন
2. New Macro তৈরি করুন:
   - Trigger: SMS Received
   - Action: HTTP Request
   - URL: `https://your-app.onrender.com/api/sms`
   - Method: POST
   - Body: `{"sms":"[sms_message]","sender":"[sms_sender]"}`

### Telegram Bot সেটআপ (ঐচ্ছিক)

1. @BotFather থেকে Bot তৈরি করুন
2. Token কপি করুন
3. @userinfobot থেকে Chat ID নিন
4. Environment Variable এ সেট করুন:
   - `TELEGRAM_BOT_TOKEN`
   - `TELEGRAM_CHAT_ID`

## 📡 API Endpoints

### SMS Receive
```http
POST /api/sms
Content-Type: application/json

{
    "sms": "TrxID: ABC123 Amount: 500 BDT",
    "sender": "01712345678"
}
