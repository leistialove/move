import os
import json
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# === 載入 .env 環境變數（可選）===
load_dotenv()

# ===== Firebase Firestore 設定 =====
import firebase_admin
from firebase_admin import credentials, firestore

# 從環境變數載入 Firebase 金鑰 JSON
firebase_json = os.getenv("FIREBASE_CREDENTIAL_JSON")
key_dict = json.loads(firebase_json)
cred = credentials.Certificate(key_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

# ===== Flask App =====
app = Flask(__name__)

# ===== LINE Bot v3 SDK 設定 =====
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '你的 Channel Access Token')
LINE_CHANNEL_SECRET       = os.getenv('LINE_CHANNEL_SECRET', '你的 Channel Secret')

config        = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
api_client    = ApiClient(config)
messaging_api = MessagingApi(api_client)
handler       = WebhookHandler(channel_secret=LINE_CHANNEL_SECRET)

# ===== LINE Webhook 接收 =====
@app.route('/callback', methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body      = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400, 'Invalid signature')
    return 'OK'

# ===== 處理使用者訊息並存入 Firebase =====
@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_id   = event.source.user_id
    user_text = event.message.text
    bot_reply = f"你說：「{user_text}」"

    # 儲存到 Firebase 的 chat_log 集合
    db.collection("chat_log").add({
        "user_id": user_id,
        "user_text": user_text,
        "bot_reply": bot_reply
    })

    # 回覆 LINE 使用者
    messaging_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[ TextMessage(text=bot_reply) ]
        )
    )

# ===== API：列出 Firestore 中所有集合名稱（模擬 /tables）=====
@app.route('/tables', methods=['GET'])
def list_collections():
    collections = db.collections()
    names = [col.id for col in collections]
    return jsonify(names)

# ===== API：取得 chat_log 的前 100 筆資料（模擬 /data/<table_name>）=====
@app.route('/data/<collection_name>', methods=['GET'])
def get_collection_data(collection_name):
    if not collection_name.isidentifier():
        abort(400, 'Invalid collection name')

    try:
        docs = db.collection(collection_name).limit(100).stream()
    except Exception:
        abort(404, f"Collection `{collection_name}` not found")

    results = []
    for doc in docs:
        data = doc.to_dict()
        data['id'] = doc.id
        results.append(data)

    return jsonify(results)

# ===== 啟動應用程式 =====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
