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
    PushMessageRequest,
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
from datetime import datetime, timedelta,timezone

LINE_CHANNEL_ACCESS_TOKEN = os.getenv('LINE_CHANNEL_ACCESS_TOKEN', '你的 Channel Access Token')
LINE_CHANNEL_SECRET       = os.getenv('LINE_CHANNEL_SECRET', '你的 Channel Secret')

config        = Configuration(access_token=LINE_CHANNEL_ACCESS_TOKEN)
api_client    = ApiClient(config)
messaging_api = MessagingApi(api_client)
handler       = WebhookHandler(channel_secret=LINE_CHANNEL_SECRET)

import requests
from flask import Response

current_status = "🟢 偵測中"
# 前端 AJAX 每秒 GET 狀態
@app.route('/status')
def get_status():
    return jsonify({"status": current_status})

# 本機 YOLO 用 POST 更新狀態
@app.route('/status', methods=['POST'])
def update_status():
    global current_status
    data = request.json
    current_status = data.get("status", "❓ 未知狀態")
    
    return "OK"

MJPEG_SOURCE = "https://expense-samba-spiritual-bouquet.trycloudflare.com/video_feed"  # 換成 cloudflare 給的網址+/video_feed

@app.route('/stream')
def stream():
    def generate():
        with requests.get(MJPEG_SOURCE, stream=True) as r:
            for chunk in r.iter_content(chunk_size=1024):
                if chunk:
                    yield chunk
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/view')
def view_stream():
    return render_template('stream.html')

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
    if user_text == "坐臥時長":
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
                messages=[FlexMessage(altText="坐臥時長-時間選擇",contents=FlexContainer.from_json(line_flex_str))]
          )
        )
    elif user_text == "移動範圍":
        bot_reply = user_text
        steps, level, message = estimate_steps_and_activity()
        line_flex_json = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    {"type": "text", "text": f"一小時內活動分析", "weight": "bold", "size": "xl", "align": "center"},
                    {"type": "text", "text": f"推估步數：{steps} 步", "size": "lg", "margin": "md"},
                    {"type": "text", "text": f"活動量評估：{level}", "size": "lg", "margin": "md", "color": "#555555"},
                    {"type": "text", "text": message, "wrap": True, "margin": "md", "color": "#ff4444"}
                ]
            }
        }
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[FlexMessage(
                    altText="一小時活動量分析", 
                    contents=FlexContainer.from_json(json.dumps(line_flex_json))
                )]
            )
        )
    elif user_text == "分析報告":
        bot_reply = user_text
        image_url, change_list, health_advice = generate_posture_step_chart()
        percent_flex_json = {
            "type": "bubble",
            "body": {
                "type": "box",
                "layout": "vertical",
                "contents": [
                    { "type": "text", "text": "活動變化分析", "weight": "bold", "size": "xl", "align": "center" },
                    { "type": "text", "text": change_list[0], "size": "md", "margin": "md", "color": "#222222" }, # 站立
                    { "type": "text", "text": change_list[1], "size": "md", "margin": "md", "color": "#222222" }, # 坐下
                    { "type": "text", "text": change_list[2], "size": "md", "margin": "md", "color": "#222222" }, # 躺下
                    { "type": "text", "text": change_list[3], "size": "md", "margin": "md", "color": "#222222" }, # 步數
                    { "type": "separator", "margin": "lg" }
                ]
            },
            "footer": {
                "type": "box",
                "layout": "vertical",
                "spacing": "sm",
                "contents": [
                    {
                        "type": "text",
                        "text": "\n".join(health_advice),  # 每條建議換行顯示
                        "size": "md",
                        "color": "#ff4444",
                        "wrap": True
                    }
                ]
            }
        }
        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[
                    ImageMessage(original_content_url=image_url, preview_image_url=image_url),
                    FlexMessage(
                        altText="分析報告-百分比", 
                        contents=FlexContainer.from_json(json.dumps(percent_flex_json))
                    )
                ]
            )
        )
    elif user_text == "聯絡照顧者":
        bot_reply = user_text
        notify_msg = f"⚠️ 使用者主動聯絡照顧者！請儘速確認安全狀況！"
        caregiver_user_id = 'Uce4b2cb2114bfcb00ea533f77c3a3d6d'  # ← 記得換成實際照顧者 ID
        
        # 發送推播訊息給照顧者
        push_message_request = PushMessageRequest(
            to=caregiver_user_id,
            messages=[TextMessage(text=notify_msg)]
        )
        try:
            messaging_api.push_message(push_message_request)  # 使用正確的推播 API
            print(f"已成功推送通知到照顧者: {caregiver_user_id}")
        except Exception as e:
            print(f"推播錯誤: {str(e)}")

        messaging_api.reply_message(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text="已通知照顧者，請稍候。")]
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
    
def calculate_percentage_change(new_value, old_value):
    # 防止除以0的情況
    if old_value == 0:
        return 0 if new_value == 0 else 100  # 如果昨天是0，今天是非零的話，視為100%的變化
    change = ((new_value - old_value) / old_value) * 100
    # 避免極端值
    if change > 200:
        return 200
    elif change < -100:
        return -100
    return change


def generate_posture_step_chart():
    # 🔹 取 Firestore 最近 30 筆資料
    docs = db.collection("yolo_detections")\
        .order_by("timestamp", direction=firestore.Query.DESCENDING)\
        .limit(30)\
        .stream()

    records = list(d.to_dict() for d in docs)
    records = list(reversed(records))  # 舊→新

    # 分割資料為今天和昨天
    yesterday_data = records[:15]
    today_data = records[15:]

    # 🔹 四個指標
    labels = ["站立時間", "坐下時間", "躺下時間", "推估步數"]
    units = ["秒", "秒", "秒", "步"]

    font_path = "fonts/jf-openhuninn-1.1.ttf"
    font_prop = font_manager.FontProperties(fname=font_path)

    plt.figure(figsize=(12, 10))

    # 健康建議初始化
    health_advice = []
    change_list = []

    for i in range(4):
        plt.subplot(2, 2, i+1)

        # 站立時間變化
        if labels[i] == "站立時間":
            old_vals = [r.get("standing_frames", 0) for r in yesterday_data]
            new_vals = [r.get("standing_frames", 0) for r in today_data]
            change_percent = calculate_percentage_change(sum(new_vals), sum(old_vals))
            change_list.append(f"站立時間變化：{'增加' if change_percent > 0 else '減少'} {abs(change_percent):.1f}%")
            if change_percent < 0:
                health_advice.append("站立時間減少，請多站立活動！")

        # 坐下時間變化
        elif labels[i] == "坐下時間":
            old_vals = [r.get("sitting_frames", 0) for r in yesterday_data]
            new_vals = [r.get("sitting_frames", 0) for r in today_data]
            change_percent = calculate_percentage_change(sum(new_vals), sum(old_vals))
            change_list.append(f"坐下時間變化：{'增加' if change_percent > 0 else '減少'} {abs(change_percent):.1f}%")
            if change_percent > 0:
                health_advice.append("坐下時間增加，請注意久坐問題！")

        # 躺下時間變化
        elif labels[i] == "躺下時間":
            old_vals = [r.get("lying_frames", 0) for r in yesterday_data]
            new_vals = [r.get("lying_frames", 0) for r in today_data]
            change_percent = calculate_percentage_change(sum(new_vals), sum(old_vals))
            change_list.append(f"躺下時間變化：{'增加' if change_percent > 0 else '減少'} {abs(change_percent):.1f}%")
            if change_percent > 0:
                health_advice.append("躺下時間增加，建議多活動，避免長時間躺下！")

        # 步數變化
        elif labels[i] == "推估步數":
            old_vals = [r.get("total_movement", 0) / 100 / 0.6 for r in yesterday_data]
            new_vals = [r.get("total_movement", 0) / 100 / 0.6 for r in today_data]
            change_percent = calculate_percentage_change(sum(new_vals), sum(old_vals))
            change_list.append(f"步數變化：{'增加' if change_percent > 0 else '減少'} {abs(change_percent):.1f}%")
            if change_percent > 0:
                health_advice.append("步數增加，保持良好活動！")
            else:
                health_advice.append("步數減少，記得保持日常活動，積極走動！")

        x = list(range(1, max(len(old_vals), len(new_vals)) + 1))
        plt.plot(x, old_vals, marker='o', label="昨天15筆", color='red')  # 這裡應該是昨天的資料為紅色
        plt.plot(x, new_vals, marker='o', label="今天15筆", color='blue')  # 今天的資料為藍色
        plt.title(f"{labels[i]}", fontproperties=font_prop, fontsize=14)
        plt.xlabel("筆數", fontproperties=font_prop)
        plt.ylabel(f"{units[i]}", fontproperties=font_prop)
        plt.grid(True)
        plt.legend(prop=font_prop)

    plt.tight_layout()
    plt.figtext(0.5, 0.01, "每筆資料約對應 1 分鐘，紅色為最近 15 筆", ha="center", fontproperties=font_prop, fontsize=14)

    save_path = f"/tmp/posture_chart_{int(time.time())}.png"
    plt.savefig(save_path)
    plt.close()

    remote_name = os.path.basename(save_path)
    image_url = upload_to_firebase(save_path, remote_name)

    # 返回圖片網址和健康建議與百分比
    return image_url, change_list, health_advice


def estimate_steps_and_activity():
    records = get_recent_records(60)
    total_pixel = sum(r.get("total_movement", 0) for r in records)
    
    PIXELS_PER_METER = 100       # 建議依實際相機視角微調
    METERS_PER_STEP = 0.6

    total_meters = total_pixel / PIXELS_PER_METER
    estimated_steps = int(total_meters / METERS_PER_STEP)

    if estimated_steps < 200:
        level = "低活動量"
        message = "一小時內活動量偏低，建議多走動一下喔～"
    elif estimated_steps < 600:
        level = "中等活動量"
        message = "活動量不錯，再多動一點會更健康！"
    else:
        level = "高活動量"
        message = "很棒！你今天活動量很充足，繼續保持喔！" 

    return estimated_steps, level, message
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
#from google.cloud.firestore import SERVER_TIMESTAMP
def get_recent_records(minutes):
    now = datetime.now(timezone(timedelta(hours=8)))  # 台灣時間
    cutoff = now - timedelta(minutes=minutes)
    print("📌 查詢最近時間：", cutoff)
    
    '''docs = db.collection("yolo_detections") \
        .where("timestamp", ">=", cutoff) \
        .order_by("timestamp", direction=firestore.Query.DESCENDING) \
        .stream()'''
    docs = db.collection("yolo_detections").order_by("timestamp", direction=firestore.Query.DESCENDING).limit(minutes).stream()

    records = []
    for doc in docs:
        records.append(doc.to_dict())
    print(f"🔥 拿到 {len(records)} 筆資料")
    return records

def summarize_records(records):
    return {
        "站立秒數": sum(r.get("standing_frames", 0) for r in records),
        "坐下秒數": sum(r.get("sitting_frames", 0) for r in records),
        "躺下秒數": sum(r.get("lying_frames", 0) for r in records),
        "移動量": sum(r.get("total_movement", 0) for r in records)
    }

from matplotlib import font_manager
import time
def generate_chart_image(summary, minutes):
    font_path = "fonts/jf-openhuninn-1.1.ttf"
    font_prop = font_manager.FontProperties(fname=font_path)

    # === 直接用三類欄位
    labels = ["站立", "坐下", "躺下"]
    values = [
        summary["站立秒數"],
        summary["坐下秒數"],
        summary["躺下秒數"]
    ]

    # 如果沒有資料
    if sum(values) == 0:
        labels = ["無資料", "無資料", "無資料"]
        values = [1, 1, 1]
    
    plt.figure(figsize=(6, 6))
    wedges, texts, autotexts = plt.pie(
        values,
        labels=labels,
        autopct="%1.1f%%",
        startangle=90,
        textprops={
            'fontproperties': font_prop,
            'fontsize': 22
        }
    )
    plt.title(f"{minutes} 分鐘內站坐躺分佈", fontproperties=font_prop, fontsize=32)
    summary_text = f"站：{summary['站立秒數']:.0f} 秒 坐：{summary['坐下秒數']:.0f} 秒 躺：{summary['躺下秒數']:.0f} 秒"

    plt.figtext(
        0.5,
        0.01,
        summary_text,
        ha="center",
        fontproperties=font_prop,
        fontsize=18
    )

    total_time = summary['站立秒數'] + summary['坐下秒數'] + summary['躺下秒數']
    if summary['站立秒數'] < total_time / 3:
        encourage_text = "久坐久躺不健康，建議多起身活動一下喔！"
        plt.figtext(
            0.5, 0.06,
            encourage_text,
            ha="center",
            fontproperties=font_prop,
            fontsize=22,
            color="red"
        )

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
    exclude = ['yolo_detections']
    names = [c.id for c in db.collections() if c.id not in exclude]
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
            
            # ✅ 這裡是重點：合併使用者與機器人回應
            user_text = data.get('user_text', '-')
            bot_reply = data.get('bot_reply', '-')
            full_text = f"{user_text} ➜ {bot_reply}"

            records.append({
                'id': m.id,
                'timestamp': data.get('timestamp', '-'),
                'content': full_text
            })

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
