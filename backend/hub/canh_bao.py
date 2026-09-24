"""
GỬI MAIL CẢNH BÁO VẬN HÀNH — hiện dùng cho vòng cào 1688 dính captcha (18/09/2026).

Vì sao cần: 1688 bật slider Baxia định kỳ và CHỈ NGƯỜI giải được. Trước đây không ai biết nó bật
cho tới khi nhìn bảng lỗi — sáng 18/09/2026 182 ngành hỏng liền một mạch vì slider bật ở ngành
thứ ~20 và không ai hay. Mail đi ngay lúc dính, để người trực vào máy-thợ kéo slider trong lúc
vòng cào còn đang chờ (xem `market_snapshot.snapshot_keyword_categories`).

CẤU HÌNH (backend/.env.local), SMTP thường — Gmail cần "Mật khẩu ứng dụng", không phải mật khẩu
đăng nhập:
    SMTP_HOST=smtp.gmail.com        (mặc định)
    SMTP_PORT=587                   (mặc định; 465 thì tự dùng SSL)
    SMTP_USER=<tài khoản gửi>
    SMTP_PASS=<mật khẩu ứng dụng>
    SMTP_FROM=<địa chỉ gửi>         (mặc định = SMTP_USER)
    ALERT_EMAIL=aiteam.tnt@gmail.com (mặc định; nhiều người nhận thì ngăn bằng dấu phẩy)
Thiếu SMTP_USER/SMTP_PASS thì KHÔNG gửi được và chỉ ghi log — không làm hỏng vòng cào.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.message import EmailMessage

from lib.core.config import env_string

log = logging.getLogger("canh_bao")

ALERT_EMAIL_MAC_DINH = "aiteam.tnt@gmail.com"


def nguoi_nhan() -> list[str]:
    return [x.strip() for x in env_string("ALERT_EMAIL", ALERT_EMAIL_MAC_DINH).split(",") if x.strip()]


def gui_mail(tieu_de: str, noi_dung: str) -> str | None:
    """Gửi một mail chữ thường. Trả `None` khi gửi được, hoặc câu nói vì sao không gửi được."""
    host = env_string("SMTP_HOST", "smtp.gmail.com")
    port = int(env_string("SMTP_PORT", "587"))
    user, pw = env_string("SMTP_USER"), env_string("SMTP_PASS")
    den = nguoi_nhan()
    if not user or not pw:
        why = "chưa cấu hình SMTP_USER / SMTP_PASS trong backend/.env.local"
        log.warning("khong gui duoc mail canh bao (%s): %s", why, tieu_de)
        return why
    msg = EmailMessage()
    msg["Subject"] = tieu_de
    msg["From"] = env_string("SMTP_FROM", user)
    msg["To"] = ", ".join(den)
    msg.set_content(noi_dung)
    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as s:
                s.login(user, pw)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.starttls(context=ssl.create_default_context())
                s.login(user, pw)
                s.send_message(msg)
    except Exception as e:  # noqa: BLE001 — cảnh báo hỏng không được kéo vòng cào hỏng theo
        log.warning("gui mail canh bao hong: %s", e)
        return str(e) or type(e).__name__
    log.info("da gui mail canh bao toi %s: %s", den, tieu_de)
    return None
