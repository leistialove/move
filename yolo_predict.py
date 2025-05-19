import cv2
import darknet
import os
import time
import datetime
import json
import firebase_admin
from firebase_admin import credentials, firestore

# ===== YOLO 初始化（只做一次）=====
configPath = "./cfg/yolov4_movingdetect.cfg"
weightPath = "./weight/yolov4_movingdetect_best.weights"
metaPath = "./data/movingdetect.data"

if not os.path.exists(configPath):
    raise ValueError("找不到 config：" + os.path.abspath(configPath))
if not os.path.exists(weightPath):
    raise ValueError("找不到 weights：" + os.path.abspath(weightPath))
if not os.path.exists(metaPath):
    raise ValueError("找不到 data：" + os.path.abspath(metaPath))

netMain = darknet.load_net_custom(configPath.encode("ascii"), weightPath.encode("ascii"), 0, 1)
metaMain = darknet.load_meta(metaPath.encode("ascii"))

# 讀取 class names
altNames = None
try:
    with open(metaPath) as metaFH:
        import re
        match = re.search("names *= *(.*)$", metaFH.read(), re.IGNORECASE | re.MULTILINE)
        if match:
            namesPath = match.group(1)
            if os.path.exists(namesPath):
                with open(namesPath) as namesFH:
                    altNames = [x.strip() for x in namesFH.read().strip().split("\n")]
except:
    pass

# YOLO 輸出用畫框
def convertBack(x, y, w, h): 
    xmin = int(round(x - (w / 2)))
    xmax = int(round(x + (w / 2)))
    ymin = int(round(y - (h / 2)))
    ymax = int(round(y + (h / 2)))
    return xmin, ymin, xmax, ymax

def cvDrawBoxes(detections, img): 
    for detection in detections:
        x, y, w, h = detection[2]
        xmin, ymin, xmax, ymax = convertBack(x, y, w, h)
        cv2.rectangle(img, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
        cv2.putText(img, f"{detection[0]} [{round(detection[1], 2)}]", (xmin, ymin - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, [0, 255, 0], 2)
    return img

# ===== Firebase 初始化 =====
if not firebase_admin._apps:
    cred_json = os.getenv("FIREBASE_CREDENTIAL_JSON")
    cred_dict = json.loads(cred_json)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
db = firestore.client()

# ===== 狀態統計變數 =====
posture_state = "Unknown"
total_standing_frames = 0
total_sitting_frames = 0
total_frame_count = 0
prev_body_center = None
total_movement = 0.0

# ===== 主函式 perform_detect =====
def perform_detect(frame):  # 給串流用，傳入一幀影像
    global posture_state, total_standing_frames, total_sitting_frames
    global total_frame_count, prev_body_center, total_movement

    frame_h, frame_w, _ = frame.shape

    darknet_image = darknet.make_image(darknet.network_width(netMain), darknet.network_height(netMain), 3)
    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    frame_resized = cv2.resize(frame_rgb, (darknet.network_width(netMain), darknet.network_height(netMain)))
    darknet.copy_image_from_bytes(darknet_image, frame_resized.tobytes())

    detections = darknet.detect_image(netMain, altNames, darknet_image, thresh=0.9)
    total_frame_count += 1

    # 偵測資訊
    head_center = None
    body_center = None
    body_w = body_h = 0

    for class_name, confidence, (x, y, w, h) in detections:
        if class_name == "head":
            head_center = (x, y)
        elif class_name == "body":
            body_center = (x, y)
            body_w, body_h = w, h

    # 姿勢與移動偵測
    if body_center is not None:
        aspect_ratio = body_h / body_w if body_w else 0
        relative_height = body_h / frame_h if frame_h else 0

        if aspect_ratio > 3.5 and relative_height > 0.6 and posture_state != "Standing":
            posture_state = "Standing"
        elif aspect_ratio <= 3.5 and relative_height <= 0.6 and posture_state != "Sitting":
            posture_state = "Sitting"

        if posture_state == "Standing":
            total_standing_frames += 1
        elif posture_state == "Sitting":
            total_sitting_frames += 1

        if posture_state == "Standing" and prev_body_center is not None:
            dx = body_center[0] - prev_body_center[0]
            dy = body_center[1] - prev_body_center[1]
            distance = (dx**2 + dy**2)**0.5
            if distance > 3.5:
                total_movement += distance

        prev_body_center = body_center

    # 每 900 幀（約 1 分鐘）上傳 Firebase
    if total_frame_count % 900 == 0:
        datetime_str = datetime.datetime.now().strftime("%m%d_%H:%M")
        stats = {
            "timestamp": datetime_str,
            "standing_frames": total_standing_frames / 15,
            "sitting_frames": total_sitting_frames / 15,
            "total_movement": total_movement
        }
        db.collection("yolo_detections").document(datetime_str).set(stats)

        total_standing_frames = 0
        total_sitting_frames = 0
        total_movement = 0

    # 畫框並回傳 OpenCV 畫面
    result_frame = cvDrawBoxes(detections, frame)
    return result_frame
