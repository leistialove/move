import os, json
from flask import Flask, request, abort, jsonify, render_template, redirect, url_for
from dotenv import load_dotenv

# === 載入 .env 環境變數（可選）===
load_dotenv()

# ===== Firebase Firestore 設定 =====
import firebase_admin
from firebase_admin import credentials, firestore, storage

# 從環境變數載入 Firebase 金鑰 JSON
firebase_json = os.getenv("FIREBASE_CREDENTIAL_JSON")
key_dict = json.loads(firebase_json)
cred = credentials.Certificate(key_dict)
#firebase_admin.initialize_app(cred)
firebase_admin.initialize_app(cred, {
    'storageBucket': 'move-92fdd.firebasestorage.app'
})
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
    FlexContainer,
    ImageMessage   
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
    
    duration_map = {
        "report_10": 10,
        "report_30": 30,
        "report_60": 60
    }

    if postback_data in duration_map:
        minutes = duration_map[postback_data]
        image_url = generate_posture_chart(minutes)

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    ImageMessage(
                        original_content_url=image_url,
                        preview_image_url=image_url
                    )
                ]
            )
        )

from matplotlib import pyplot as plt
from google.cloud.firestore import SERVER_TIMESTAMP
def get_recent_records(minutes):
    now = datetime.now()
    cutoff = now - timedelta(minutes=minutes)
    docs = db.collection("yolo_detections")\
            .where("timestamp", ">=", cutoff)\
            .order_by("timestamp", direction=firestore.Query.DESCENDING)\
            .stream()
    #docs = db.collection("yolo_detections").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(minutes).stream()

    records = []
    for doc in docs:
        records.append(doc.to_dict())
    return records

def summarize_records(records):
    return {
        "站立秒數": sum(r.get("standing_frames", 0) for r in records),
        "坐下秒數": sum(r.get("sitting_frames", 0) for r in records),
        "移動量": sum(r.get("total_movement", 0) for r in records)
    }

from matplotlib import font_manager
import time
def generate_chart_image(summary, minutes):
    font_path = "fonts/jf-openhuninn-1.1.ttf"  # 確保檔案在 fonts 資料夾
    font_prop = font_manager.FontProperties(fname=font_path)

    llabels = ["站立", "坐下"]
    values = [float(summary["站立秒數"]), float(summary["坐下秒數"])]  # 保證是 float

    print("🔥 Debug: values =", values)
    print("🔥 Debug: summary =", summary)
    print("🔥 Debug: total =", sum(values))

    if sum(values) == 0:
        labels = ["無資料", "無資料"]
        values = [1, 1]
    elif values[0] == 0:
        labels = ["無站立", "坐下"]
        values = [1, values[1]]
    elif values[1] == 0:
        labels = ["站立", "無坐下"]
        values = [values[0], 1]

    plt.figure(figsize=(6, 6))
    wedges, texts, autotexts = plt.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        textprops={
            'fontproperties': font_prop,
            'fontsize': 30       # ⬅️ 圓餅圖中文字大小
        }
    )
    plt.title(f"{minutes} 分鐘內站坐分佈", fontproperties=font_prop, fontsize=36)
        # ✅ 調整下方註解文字大小
    plt.figtext(
        0.5,
        0.01,
        f"總移動量：{summary['移動量']:.2f}",
        ha="center",
        fontproperties=font_prop,
        fontsize=30
    )
    plt.tight_layout()  # 🔧 可改善邊緣裁切
    save_path = f"/tmp/report_{minutes}_{int(time.time())}.png"
    plt.savefig(save_path)
    plt.close()
    return save_path

def upload_to_firebase(local_path, remote_filename):
    bucket = storage.bucket()
    blob = bucket.blob(f"charts/{remote_filename}")
    blob.upload_from_filename(local_path)
    blob.make_public()  # ⚠️ 如果需要私有分享，可以改為產生簽名 URL
    return blob.public_url

def generate_posture_chart(minutes=10):
    records = get_recent_records(minutes)
    summary = summarize_records(records)
    image_path = generate_chart_image(summary, minutes)
    remote_name = os.path.basename(image_path)
    image_url = upload_to_firebase(image_path, remote_name)
    return image_url

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
