import os, json
from flask import Flask, request, abort, jsonify, render_template, redirect, url_for
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
    TextMessage,
    FlexMessage,
    FlexContainer   
)
from linebot.models import PostbackEvent
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent
)
from datetime import datetime, timedelta

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '你的 Channel Access Token')
LINE_CHANNEL_SECRET       = os.getenv('LINE_CHANNEL_SECRET', '你的 Channel Secret')

config        = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
api_client    = ApiClient(config)
messaging_api = MessagingApi(api_client)
handler       = WebhookHandler(channel_secret=LINE_CHANNEL_SECRET)

# === 新增變數儲存最新圖片 ===
latest_image = None

# === 接收本機 YOLO 傳來的 base64 畫面 ===
@app.route('/upload', methods=['POST'])
def upload_image():
    global latest_image
    data = request.json
    latest_image = data.get("image")  # base64 編碼字串
    return "OK"

@app.route('/stream')
def stream_view():
    return render_template('stream.html', image_data=latest_image)

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
    
    # 回覆 LINE 使用者
    if user_text == "分析報告":
        bot_reply = user_text
        line_flex_json={
          "type": "bubble",
  "body": {
    "type": "box",
    "layout": "vertical",
    "contents": [
      {
        "type": "text",
        "weight": "bold",
        "size": "xl",
        "text": "選擇時間",
        "align": "center"
      }
    ]
  },
  "footer": {
    "type": "box",
    "layout": "vertical",
    "spacing": "sm",
    "contents": [
      {
        "type": "button",
        "style": "link",
        "height": "sm",
        "action": {
          "type": "postback",
          "label": "10分鐘",
          "data": "report_10"
        }
      },
      {
        "type": "button",
        "style": "link",
        "height": "sm",
        "action": {
          "type": "postback",
          "label": "30分鐘",
          "data": "report_30"
        }
      },
      {
        "type": "button",
        "style": "link",
        "height": "sm",
        "action": {
          "type": "postback",
          "label": "1小時",
          "data": "report_60"
        }
      }
    ],
    "flex": 0
  }
}
        line_flex_str=json.dumps(line_flex_json)
        messaging_api.reply_message(
          ReplyMessageRequest(
            reply_token=event.reply_token,
            messages=[FlexMessage(altText="分析報告-時間選擇",contents=FlexContainer.from_json(line_flex_str))]
          )
        )
    else:
        bot_reply = f"你說：「{user_text}」"
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[ TextMessage(text=bot_reply) ]
            )
        )    
    
    doc_id = datetime.now().strftime("%d%H%M%S") #時間格式 "%Y%m%d%H%M%S%f"
    
    # 1) 先在 chat_log 底下建立或更新這個 user_id 的文件
    db.collection("chat_log") \
      .document(user_id) \
      .set(
          {"last_update": doc_id},   # 你想存的欄位都可以放這裡
          merge=True              # merge=True 表示不會覆蓋掉子集合
      )

    # 儲存到 Firebase 的 chat_log 集合
    db.collection("chat_log")\
      .document(user_id)\
      .collection("messages")\
      .document(doc_id)\
      .set({
            #"user_id": user_id,
            "user_text": user_text,
            "bot_reply": bot_reply,
            "timestamp": datetime.utcnow() # UTC 時間，便於排序與比對
        })
    
@handler.add(PostbackEvent)
def handle_postback(event):
    postback_data = event.postback.data
    user_id = event.source.user_id
    
    if postback_data == "report_10":
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="你選擇了 10 分鐘報告")]
            )
        )
    elif postback_data == "report_30":
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="你選擇了 30 分鐘報告")]
            )
        )
    elif postback_data == "report_60":
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="你選擇了 60 分鐘報告")]
            )
        )
# ===== API：列出 Firestore 中所有集合名稱（模擬 /tables）=====
@app.route('/tables', methods=['GET'])
def list_collections():
    collections = db.collections()
    names = [col.id for col in collections]
    return jsonify(names)

# ===== API：取得 chat_log 的前 100 筆資料（模擬 /data/<table_name>）=====
@app.route('/data/<collection>')
def get_collection_data_api(collection):
    if not collection.isidentifier():
        abort(400)
    docs = db.collection(collection).stream()
    return jsonify([{'id': d.id, **d.to_dict()} for d in docs])

# ===== Web UI：Firebase 瀏覽與刪除 =====
@app.route('/firebase')
def firebase_home():
    names = [c.id for c in db.collections()]
    return render_template('firebase_home.html', collections=names)

@app.route('/firebase/view/<collection>')
def view_collection(collection):
    docs = db.collection(collection).stream()
    records = [{'id': d.id} for d in docs]
    return render_template('firebase_docs.html', collection=collection, records=records)

@app.route('/firebase/view/<collection>/<doc_id>')
def view_messages(collection, doc_id):
    try:
        # 1. 讀 messages 子集合
        docs = db.collection(collection)\
                 .document(doc_id)\
                 .collection('messages')\
                 .stream()
        
        records = []
        for m in docs:
            data = m.to_dict()
            ts = data.get('timestamp')
            # 如果有 timestamp，轉成 UTC+8
            if hasattr(ts, 'tzinfo') or isinstance(ts, datetime):
                # Firestore 回傳的 timestamp 通常是帶 tzinfo 的 datetime
                local = ts + timedelta(hours=8)
                # 轉成字串，去掉微秒跟時區標誌
                data['timestamp'] = local.strftime("%Y-%m-%d %H:%M:%S")
            
            records.append({'id': m.id, **data})
        
        return render_template(
            'firebase_messages.html',
            collection=collection,
            doc_id=doc_id,
            messages=records
        )
    except Exception as e:
        return f"讀取失敗：{e}", 500

@app.route('/firebase/delete/<collection>/<doc_id>/messages/<msg_id>')
def delete_message(collection, doc_id, msg_id):
    db.collection(collection)\
      .document(doc_id)\
      .collection('messages')\
      .document(msg_id)\
      .delete()
    return redirect(url_for('view_messages',
                            collection=collection,
                            doc_id=doc_id))

# ===== 啟動應用程式 =====
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
