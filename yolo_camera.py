import cv2
from yolo_predict import perform_detect  # 你已有這個函式

def gen_frames():
    # 雲端不能用實體攝影機，請改成 MJPEG / 影片 URL
    cap = cv2.VideoCapture("https://your_stream_url")  # 或上傳一段影片

    while True:
        success, frame = cap.read()
        if not success:
            break

        frame = perform_detect(frame)  # 回傳加框後的 frame

        _, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
