// ওয়েবসাইটে API Key ব্যবহার করুন
const API_KEY = 'pk_XXXXXXXXXXXX'; // আপনার API Key

fetch('https://your-gateway.onrender.com/api/v1/create-payment', {
    method: 'POST',
    headers: {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY
    },
    body: JSON.stringify({
        amount: 500,
        method: 'nagad',
        order_id: 'ORDER_123'
    })
});
