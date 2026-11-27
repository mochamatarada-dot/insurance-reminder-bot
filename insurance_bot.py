import json
import os
from datetime import datetime, timezone, timedelta
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "policies.json"

BKK_TZ = timezone(timedelta(hours=7))
today = datetime.now(BKK_TZ).date()

# แจ้งเตือนล่วงหน้า (วัน)
NOTIFY_DAYS = [30, 14, 7, 3, 1, 0]

def send_telegram_message(message):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Error: ไม่พบ TELEGRAM_BOT_TOKEN หรือ TELEGRAM_CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    response = requests.post(url, json=payload)
    if response.status_code != 200:
        print(f"ส่งข้อความไม่สำเร็จ: {response.text}")

def check_policies():
    if not os.path.exists(DATA_FILE):
        print(f"ไม่พบไฟล์ {DATA_FILE}")
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        policies = json.load(f)

    alerts = []
    
    for p in policies:
        if p.get("status") == "paid":
            continue
            
        due_date = datetime.strptime(p["due_date"], "%Y-%m-%d").date()
        days_left = (due_date - today).days
        
        if days_left in NOTIFY_DAYS or days_left < 0:
            if days_left < 0:
                status_badge = f"🚨 <b>เลยกำหนดชำระ {abs(days_left)} วัน!</b>"
            elif days_left == 0:
                status_badge = "🔥 <b>ครบกำหนดชำระวันนี้!</b>"
            else:
                status_badge = f"⏳ <b>เหลือเวลาอีก {days_left} วัน</b>"
                
            formatted_amount = f"{p['amount']:,.2f}"
            formatted_date = due_date.strftime("%d/%m/%Y")
            owner_name = p.get("owner", "ไม่ระบุชื่อ")
            
            msg_block = (
                f"{status_badge}\n"
                f"👤 <b>ผู้เอาประกัน: {owner_name}</b>\n"
                f"📌 <b>{p['name']}</b>\n"
                f"• เลขกรมธรรม์: <code>{p['policy_no']}</code>\n"
                f"• ยอดชำระ: <b>{formatted_amount} บาท</b> ({p['frequency']})\n"
                f"• วันครบกำหนด: {formatted_date}\n"
                f"• หมายเหตุ: {p.get('note', '-')}"
            )
            alerts.append(msg_block)

    if alerts:
        header = f"🛡️ <b>แจ้งเตือนชำระเบี้ยประกันชีวิต</b>\n📅 ประจำวันที่ {today.strftime('%d/%m/%Y')}\n"
        full_message = header + "\n" + ("\n" + "—" * 15 + "\n").join(alerts)
        send_telegram_message(full_message)
        print("ส่งแจ้งเตือนเรียบร้อยแล้ว")
    else:
        print("ไม่มีรายการประกันที่ต้องแจ้งเตือนในวันนี้")

if __name__ == "__main__":
    check_policies()
