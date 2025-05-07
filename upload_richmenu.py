# setup_richmenu.py
import json
import os
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi,
    CreateRichMenuRequest, RichMenuArea, RichMenuBounds, RichMenuAction, RichMenuSize
)

# 讀 JSON
with open("richmenu.json", encoding="utf-8") as f:
    data = json.load(f)

areas = [
    RichMenuArea(
        bounds=RichMenuBounds(**area["bounds"]),
        action=RichMenuAction(**area["action"])
    ) for area in data["areas"]
]

# 抓環境變數
access_token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
config = Configuration(access_token=access_token)

with ApiClient(config) as api_client:
    api = MessagingApi(api_client)

    result = api.create_rich_menu(
        create_rich_menu_request=CreateRichMenuRequest(
            size=RichMenuSize(**data["size"]),
            selected=data["selected"],
            name=data["name"],
            chat_bar_text=data["chatBarText"],
            areas=areas
        )
    )

    richmenu_id = result.rich_menu_id
    print("✅ Rich Menu ID:", richmenu_id)

    # 上傳圖片
    with open("richmenu.png", "rb") as f:
        api.set_rich_menu_image(richmenu_id, f, content_type="image/png")
        print("✅ 圖片已上傳")

    api.set_default_rich_menu(richmenu_id)
    print("✅ 設為預設 Rich Menu")
