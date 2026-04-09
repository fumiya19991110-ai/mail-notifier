#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Xserver メール監視スクリプト
件名に「新規お客様メッセージ」が含まれるメールをntfyに通知する
"""
import email
import email.header
import imaplib
import json
import os
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

IMAP_HOST = "sv13147.xserver.jp"
IMAP_PORT = 993
MAIL_USER = "sekimoto@greatwork.jp"
MAIL_PASS = os.environ["MAIL_PASSWORD"]

SUBJECT_KEYWORD = "新規お客様メッセージ"
NTFY_URL = "https://ntfy.sh/new-customer-message"
STATE_FILE = Path(__file__).parent.parent / "data" / "state.json"

JST = timezone(timedelta(hours=9))
BODY_MAX_LEN = 1000


def decode_header_value(value: str) -> str:
    parts = email.header.decode_header(value)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def get_body(msg) -> str:
    body = ""
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            cdispo = str(part.get("Content-Disposition", ""))
            if ctype == "text/plain" and "attachment" not in cdispo:
                charset = part.get_content_charset() or "utf-8"
                try:
                    body = part.get_payload(decode=True).decode(charset, errors="replace")
                    break
                except Exception:
                    continue
    else:
        charset = msg.get_content_charset() or "utf-8"
        try:
            body = msg.get_payload(decode=True).decode(charset, errors="replace")
        except Exception:
            body = ""
    return body.strip()


def load_state() -> dict:
    with open(STATE_FILE, encoding="utf-8") as f:
        return json.load(f)


def save_state(state: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def send_ntfy(subject: str, body: str) -> None:
    body_preview = body[:BODY_MAX_LEN] + ("..." if len(body) > BODY_MAX_LEN else "")
    message = f"{subject}\n\n{body_preview}".strip()
    data = message.encode("utf-8")
    req = urllib.request.Request(
        NTFY_URL,
        data=data,
        method="POST",
        headers={
            "Content-Type": "text/plain; charset=utf-8",
            "Title": "New customer message",
            "Priority": "high",
            "Tags": "email,envelope",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        print(f"ntfy送信完了: {resp.status}")


def main() -> None:
    state = load_state()
    last_uid = state["last_uid"]
    now_jst = datetime.now(JST).isoformat()

    print(f"最終確認UID: {last_uid}")
    print(f"IMAP接続中: {IMAP_HOST}:{IMAP_PORT}")

    mail = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    try:
        mail.login(MAIL_USER, MAIL_PASS)
        mail.select("INBOX")

        search_criterion = f"UID {last_uid + 1}:*"
        status, data = mail.uid("search", None, search_criterion)
        if status != "OK":
            print("メール検索失敗")
            return

        uid_list = data[0].split() if data[0] else []
        print(f"未確認メール数: {len(uid_list)}")

        max_uid = last_uid
        notified = 0

        for uid_bytes in uid_list:
            uid = int(uid_bytes)
            if uid <= last_uid:
                continue

            status, msg_data = mail.uid("fetch", uid_bytes, "(RFC822)")
            if status != "OK":
                continue

            raw = msg_data[0][1]
            msg = email.message_from_bytes(raw)

            subject_raw = msg.get("Subject", "")
            subject = decode_header_value(subject_raw)

            print(f"UID {uid}: {subject}")

            if SUBJECT_KEYWORD in subject:
                body = get_body(msg)
                print(f"  -> キーワード一致！通知送信")
                send_ntfy(subject, body)
                notified += 1

            max_uid = max(max_uid, uid)

        state["last_uid"] = max_uid
        state["last_checked"] = now_jst
        save_state(state)

        print(f"完了: {notified}件通知, 最新UID={max_uid}")

    finally:
        mail.logout()


if __name__ == "__main__":
    main()
