import os
import json
from flask import Flask, request, abort, jsonify
from dotenv import load_dotenv

# === 載入 .env 環境變數（可選）===
load_dotenv()

# ===== Firebase Firestore 設定 =====
import firebase_admin
from firebase_admin import credentials, firestore

'''# 從環境變數載入 Firebase 金鑰 JSON
firebase_json = os.getenv("FIREBASE_CREDENTIAL_JSON")
key_dict = json.loads(firebase_json)
cred = credentials.Certificate(key_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()
'''
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
    TextMessage,
    FlexMessage
)

from linebot.v3.messaging.models import FlexMessage

from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
    PostbackEvent
)
from datetime import datetime, timedelta

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
    
    # ✅ 若為「分析報告」，回傳時間 Flex 選單##############################
    if event.message.text == "分析報告":
        # 最簡版 Flex JSON：只有 body/text
        test_json = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    { "type": "text", "text": "Hello Flex!" }
                ]
            }
        }

        flex_msg = FlexMessage(
            alt_text="test",
            contents=test_json
        )
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[flex_msg]
            )
        )
        return



######################################################
    
    bot_reply = f"你說：「{user_text}」"
    # 取得現在 UTC 時間
    now = datetime.utcnow() + timedelta(hours=8)
    doc_id = now.strftime("%d-%H:%M:%S") #"%Y%m%d%H%M%S%f"
    # e.g. "20250513234530123456"

    # 儲存到 Firebase 的 chat_log 集合
    db.collection("chat_log")\
      .document(user_id)\
      .collection("messages")\
      .document(doc_id)\
      .set({
            "user_id": user_id,
            "user_text": user_text,
            "bot_reply": bot_reply,
            "timestamp": datetime.utcnow() # UTC 時間，便於排序與比對
        })
    
    # 回覆 LINE 使用者
    messaging_api.reply_message(
        ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[ TextMessage(text=bot_reply) ]
        )
    )

# ===== 處理 Postback（時間選擇回應） =====
@handler.add(PostbackEvent)
def handle_postback(event):
    data = event.postback.data
    if data.startswith("report_"):
        minute = data.split("_")[1]
        msg = f"📊 為您產生最近 {minute} 分鐘的分析報告"

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=msg)]
            )
        )
######################################################################

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
