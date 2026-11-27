import json
import os
from datetime import datetime, timezone, timedelta, date
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
DATA_FILE = "policies.json"

BKK_TZ = timezone(timedelta(hours=7))
now_bkk = datetime.now(BKK_TZ)
today = now_bkk.date()
current_hour = now_bkk.hour

def get_time_period(hour):
    if hour < 11:
        return "เช้า ☀️"
    elif hour < 16:
        return "กลางวัน 🌤️"
    else:
        return "เย็น 🌙"

def get_nearest_due_date(mm_dd, ref_date):
    month, day = map(int, mm_dd.split("-"))
    candidates = []
    for y in [ref_date.year - 1, ref_date.year, ref_date.year + 1]:
        try:
            candidates.append(date(y, month, day))
        except ValueError:
            pass
    # หาวันครบกำหนดที่ใกล้เคียงที่สุด (รองรับช่วงล่วงหน้า 7 วัน และย้อนหลังไม่เกิน 30 วัน)
    for d in sorted(candidates):
        diff = (d - ref_date).days
        if -30 <= diff <= 7:
            return d
    return min([d for d in candidates if d >= ref_date], default=candidates[-1])

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

    period_label = get_time_period(current_hour)
    is_morning = (current_hour < 11)
    # อนุญาตให้กดรันทดสอบเอง (workflow_dispatch) แล้วส่งข้อความทันที
    is_manual_run = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"

    alerts = []

    for p in policies:
        if p.get("status") == "paid":
            continue

        due_date = get_nearest_due_date(p["due_mm_dd"], today)
        days_left = (due_date - today).days

        # เช็กเงื่อนไข: ก่อนวันจ่าย 7 วัน (days_left <= 7) จนถึงหลังวันจ่าย 30 วัน (days_left >= -30)
        if -30 <= days_left <= 7:
            # เงื่อนไขความถี่ในการส่ง:
            # 1) ช่วง 3 วันสุดท้าย (days_left อยู่ใน 0, 1, 2, 3) -> ส่งทั้ง เช้า กลางวัน เย็น
            # 2) ช่วงอื่นๆ (ล่วงหน้า 4-7 วัน หรือ เลยกำหนด 1-30 วัน) -> ส่งเฉพาะรอบเช้า (หรือตอนกดรันทดสอบ)
            if (0 <= days_left <= 3) or is_morning or is_manual_run:
                if days_left < 0:
                    badge = f"🚨 <b>เลยกำหนดชำระ {abs(days_left)} วัน!</b>"
                elif days_left == 0:
                    badge = "🔥 <b>ครบกำหนดชำระวันนี้!</b>"
                elif days_left <= 3:
                    badge = f"⚠️ <b>โค้งสุดท้าย! เหลือ {days_left} วัน</b>"
                else:
                    badge = f"⏳ <b>ล่วงหน้า {days_left} วัน</b>"

                formatted_amount = f"{p['amount']:,.2f}"
                formatted_date = due_date.strftime("%d/%m/%Y")

                msg_block = (
                    f"{badge}\n"
                    f"👤 <b>{p['owner']}</b> | 🏢 <b>{p['company']}</b>\n"
                    f"💰 ยอดชำระ: <b>{formatted_amount} บาท</b>\n"
                    f"📅 ครบกำหนด: {formatted_date} ({p.get('note', '-')})"
                )
                alerts.append(msg_block)

    if alerts:
        header = (
            f"🛡️ <b>แจ้งเตือนเบี้ยประกันชีวิต (รอบ{period_label})</b>\n"
            f"📆 วันที่ {today.strftime('%d/%m/%Y')}\n"
        )
        full_message = header + "\n" + ("\n" + "—" * 15 + "\n").join(alerts)
        send_telegram_message(full_message)
        print(f"ส่งแจ้งเตือนเรียบร้อย ({len(alerts)} รายการ)")
    else:
        print("ไม่มีรายการที่ต้องแจ้งเตือนในรอบนี้")

if __name__ == "__main__":
    check_policies()
