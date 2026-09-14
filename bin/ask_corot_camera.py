import os
import sys
import time
import requests

def main():
    if len(sys.argv) < 2:
        print("skip")
        return
    
    chat_id = sys.argv[1]
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("skip")
        return

    base_url = f"https://api.telegram.org/bot{bot_token}"
    
    # 1. Gửi tin nhắn với inline keyboard
    text = "🛠 <b>Xác nhận áp dụng Fix Camera (corot)</b>\n\nBạn có muốn áp dụng fix camera cho thiết bị nào dưới đây không?\n<i>(Tự động bỏ qua sau 120 giây nếu không có phản hồi)</i>"
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "Redmi K60 Ultra", "callback_data": "corot_camera_k60"},
                {"text": "Xiaomi 13T Pro", "callback_data": "corot_camera_13t"}
            ],
            [
                {"text": "Không áp dụng (Bỏ qua)", "callback_data": "corot_camera_skip"}
            ]
        ]
    }
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": keyboard
    }
    
    try:
        resp = requests.post(f"{base_url}/sendMessage", json=payload, timeout=10)
        resp_data = resp.json()
        if not resp_data.get("ok"):
            print("skip")
            return
        
        message_id = resp_data["result"]["message_id"]
    except Exception:
        print("skip")
        return

    # 2. Polling chờ phản hồi trong vòng 120 giây
    start_time = time.time()
    timeout = 120
    offset = None
    choice = "timeout"
    
    while time.time() - start_time < timeout:
        poll_url = f"{base_url}/getUpdates"
        params = {"timeout": 5}
        if offset is not None:
            params["offset"] = offset
            
        try:
            updates_resp = requests.get(poll_url, params=params, timeout=10)
            updates_data = updates_resp.json()
            
            if updates_data.get("ok"):
                for update in updates_data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    if "callback_query" in update:
                        cb = update["callback_query"]
                        if cb.get("message", {}).get("message_id") == message_id:
                            data = cb.get("data")
                            if data == "corot_camera_k60":
                                choice = "k60"
                            elif data == "corot_camera_13t":
                                choice = "13t"
                            elif data == "corot_camera_skip":
                                choice = "skip"
                                
                            if choice != "timeout":
                                # Phản hồi lại callback query
                                requests.post(f"{base_url}/answerCallbackQuery", json={
                                    "callback_query_id": cb["id"],
                                    "text": "Đã ghi nhận lựa chọn của bạn!"
                                })
                                break
            if choice != "timeout":
                break
        except Exception:
            pass
            
    # 3. Chỉnh sửa tin nhắn để thông báo trạng thái cuối cùng
    edit_text = "🛠 <b>Xác nhận áp dụng Fix Camera (corot)</b>\n\n"
    if choice == "k60":
        edit_text += "✅ Đã chọn: <b>Redmi K60 Ultra</b>"
    elif choice == "13t":
        edit_text += "✅ Đã chọn: <b>Xiaomi 13T Pro</b>"
    elif choice == "skip":
        edit_text += "✅ Đã chọn: <b>Không áp dụng (Bỏ qua)</b>"
    else:
        edit_text += "⏳ <b>Thời gian chờ 120s đã hết. Đã tự động bỏ qua (không apply mod).</b>"
        
    try:
        requests.post(f"{base_url}/editMessageText", json={
            "chat_id": chat_id,
            "message_id": message_id,
            "text": edit_text,
            "parse_mode": "HTML"
        }, timeout=10)
    except Exception:
        pass
    
    print(choice)

if __name__ == "__main__":
    main()
