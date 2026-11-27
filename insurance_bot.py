import json
import os
import base64
from datetime import datetime, timezone, timedelta, date
import requests

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GH_TOKEN = os.getenv("GH_PAT")
GH_REPO = os.getenv("GITHUB_REPOSITORY")
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
    # รองรับช่วงล่วงหน้า 7 วัน และย้อนหลังได้ถึง 65 วัน (30 วันผ่อนผัน + 30 วันเตือนซ้ำ)
    for d in sorted(candidates):
        diff = (d - ref_date).days
        if -65 <= diff <= 7:
            return d
    return min([d for d in candidates if d >= ref_date], default=candidates[-1])

def send_telegram_message(message, reply_markup=None):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Error: ไม่พบ TELEGRAM_BOT_TOKEN หรือ TELEGRAM_CHAT_ID")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    res = requests.post(url, json=payload)
    if res.status_code != 200:
        print(f"ส่งข้อความไม่สำเร็จ: {res.text}")

def process_telegram_clicks(policies):
    """เช็กว่ามีการกดปุ่ม 'จ่ายแล้ว' ใน Telegram หรือไม่ และอัปเดตสถานะ"""
    if not TELEGRAM_TOKEN:
        return policies, False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
    res = requests.get(url).json()
    if not res.get("ok"):
        return policies, False

    updates = res.get("result", [])
    if not updates:
        return policies, False

    updated = False
    last_update_id = 0

    for item in updates:
        last_update_id = max(last_update_id, item["update_id"])
        callback = item.get("callback_query")
        if not callback:
            continue

        data = callback.get("data", "")
        callback_id = callback.get("id")

        if data.startswith("PAY_"):
            policy_id = data.replace("PAY_", "")
            for p in policies:
                if p["id"] == policy_id:
                    p["status"] = "paid"
                    p["paid_date"] = today.strftime("%Y-%m-%d")
                    updated = True

                    requests.post(
                        f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery",
                        json={"callback_query_id": callback_id, "text": f"บันทึกจ่าย {p['id']} เรียบร้อย!"}
                    )

                    confirm_msg = (
                        f"✅ <b>บันทึกการชำระเงินเรียบร้อยแล้ว!</b>\n"
                        f"👤 ผู้เอาประกัน: <b>{p['owner']}</b>\n"
                        f"🏢 บริษัท: <b>{p['company']}</b> ({p['id']})\n"
                        f"💰 ยอดชำระ: <b>{p['amount']:,.2f} บาท</b>\n"
                        f"📅 วันที่กดยืนยัน: {today.strftime('%d/%m/%Y')}\n"
                        f"🔕 <i>ระบบจะหยุดแจ้งเตือนรายการนี้สำหรับรอบปีปัจจุบันครับ</i>"
                    )
                    send_telegram_message(confirm_msg)
                    break

    if last_update_id > 0:
        requests.get(url, params={"offset": last_update_id + 1})

    return policies, updated

def update_github_json(policies):
    """บันทึกไฟล์ policies.json กลับขึ้น GitHub"""
    if not GH_TOKEN or not GH_REPO:
        print("ไม่มี GH_PAT หรือ GITHUB_REPOSITORY ข้ามการอัปเดตไฟล์บน GitHub")
        return

    api_url = f"https://api.github.com/repos/{GH_REPO}/contents/{DATA_FILE}"
    headers = {
        "Authorization": f"token {GH_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }

    get_res = requests.get(api_url, headers=headers)
    if get_res.status_code != 200:
        print(f"ดึงข้อมูลไฟล์จาก GitHub ไม่สำเร็จ: {get_res.text}")
        return

    sha = get_res.json()["sha"]
    new_content = json.dumps(policies, ensure_ascii=False, indent=2)
    encoded_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")

    put_payload = {
        "message": f"Update payment status via Telegram ({today.strftime('%Y-%m-%d')})",
        "content": encoded_content,
        "sha": sha
    }
    put_res = requests.put(api_url, headers=headers, json=put_payload)
    if put_res.status_code in [200, 201]:
        print("อัปเดตไฟล์ policies.json บน GitHub สำเร็จ")
    else:
        print(f"อัปเดตไฟล์ไม่สำเร็จ: {put_res.text}")

def run_bot():
    if not os.path.exists(DATA_FILE):
        print(f"ไม่พบไฟล์ {DATA_FILE}")
        return

    with open(DATA_FILE, "r", encoding="utf-8") as f:
        policies = json.load(f)

    # 1. ตรวจสอบการกดปุ่ม 'จ่ายแล้ว' จาก Telegram
    policies, is_changed = process_telegram_clicks(policies)

    # 2. รีเซ็ตสถานะ 'paid' กลับเป็น 'pending' อัตโนมัติเมื่อพ้นรอบปีไปแล้วเกิน 65 วัน
    for p in policies:
        if p.get("status") == "paid":
            due_date = get_nearest_due_date(p["due_mm_dd"], today)
            if (today - due_date).days > 65:
                p["status"] = "pending"
                p.pop("paid_date", None)
                is_changed = True

    if is_changed:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump(policies, f, ensure_ascii=False, indent=2)
        update_github_json(policies)

    # 3. ตรวจสอบเงื่อนไขแจ้งเตือนตามไทม์ไลน์ใหม่
    period_label = get_time_period(current_hour)
    is_morning = (current_hour < 11)
    is_manual_run = os.getenv("GITHUB_EVENT_NAME") == "workflow_dispatch"

    alerts = []
    inline_buttons = []

    # วันที่แจ้งเตือนรายสัปดาห์ (ล่วงหน้า 7 วัน, วันครบกำหนด 0, และทุกๆ 7 วันในช่วงผ่อนผัน 30 วัน)
    weekly_days = [7, 0, -7, -14, -21]
    # 3 วันสุดท้ายของระยะเวลาผ่อนผัน 30 วัน (วันที่เลยกำหนดมาแล้ว 27, 28, 29 และครบ 30 วัน)
    grace_final_days = [-27, -28, -29, -30]

    for p in policies:
        if p.get("status") == "paid":
            continue

        due_date = get_nearest_due_date(p["due_mm_dd"], today)
        grace_end_date = due_date + timedelta(days=30)
        days_left = (due_date - today).days        # บวก = ก่อนครบกำหนด, ลบ = เลยวันครบกำหนด
        grace_days_left = (grace_end_date - today).days  # วันที่เหลือของระยะเวลาผ่อนผัน 30 วัน

        should_notify = False

        if days_left in grace_final_days:
            # 3 วันสุดท้ายของช่วงผ่อนผัน 30 วัน -> เตือนทั้ง เช้า กลางวัน เย็น
            should_notify = True
        elif days_left in weekly_days or (-60 <= days_left <= -31):
            # ล่วงหน้า 7 วัน / วันครบกำหนด / ทุก 7 วันในช่วงผ่อนผัน / หรือเกิน 30 วันไปแล้ว -> เตือนรอบเช้า (หรือตอนกดรันทดสอบ)
            if is_morning or is_manual_run:
                should_notify = True

        if should_notify:
            if days_left > 0:
                badge = f"⏳ <b>ล่วงหน้า {days_left} วันก่อนครบกำหนด</b>"
            elif days_left == 0:
                badge = "📅 <b>ครบกำหนดชำระวันนี้! (มีระยะผ่อนผันถึง " + grace_end_date.strftime("%d/%m/%Y") + ")</b>"
            elif days_left in grace_final_days:
                if grace_days_left == 0:
                    badge = "🔥 <b>วันสุดท้ายของระยะผ่อนผัน 30 วัน! (ต้องจ่ายวันนี้)</b>"
                else:
                    badge = f"⚠️ <b>โค้งสุดท้ายระยะผ่อนผัน! เหลืออีก {grace_days_left} วัน</b>"
            elif -29 <= days_left <= -1:
                badge = f"🔔 <b>อยู่ในช่วงผ่อนผัน (เลยวันครบกำหนด {abs(days_left)} วัน / เหลือเวลาอีก {grace_days_left} วัน)</b>"
            else:
                badge = f"🚨 <b>เกินระยะผ่อนผัน 30 วันแล้ว! (เลยกำหนดมา {abs(days_left)} วัน)</b>"

            formatted_amount = f"{p['amount']:,.2f}"
            formatted_due = due_date.strftime("%d/%m/%Y")
            formatted_grace = grace_end_date.strftime("%d/%m/%Y")

            msg_block = (
                f"{badge}\n"
                f"👤 <b>{p['owner']}</b> | 🏢 <b>{p['company']}</b>\n"
                f"💰 ยอดชำระ: <b>{formatted_amount} บาท</b>\n"
                f"📆 วันครบกำหนด: {formatted_due} (ผ่อนผันถึง {formatted_grace})\n"
                f"📝 หมายเหตุ: {p.get('note', '-')}"
            )
            alerts.append(msg_block)

            btn_text = f"✅ จ่ายแล้ว: {p['owner']} - {p['company']} ({formatted_amount} บ.)"
            inline_buttons.append([{"text": btn_text, "callback_data": f"PAY_{p['id']}"}])

    if alerts:
        header = (
            f"🛡️ <b>แจ้งเตือนเบี้ยประกันชีวิต (รอบ{period_label})</b>\n"
            f"📆 วันที่ {today.strftime('%d/%m/%Y')}\n"
        )
        full_message = header + "\n" + ("\n" + "—" * 15 + "\n").join(alerts)
        reply_markup = {"inline_keyboard": inline_buttons}
        send_telegram_message(full_message, reply_markup=reply_markup)
        print(f"ส่งแจ้งเตือนพร้อมปุ่มกดเรียบร้อย ({len(alerts)} รายการ)")
    else:
        print("ไม่มีรายการที่ต้องแจ้งเตือนในรอบนี้")

if __name__ == "__main__":
    run_bot()
