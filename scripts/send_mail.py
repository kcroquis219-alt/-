#!/usr/bin/env python3
"""生成済みレポートをGmail経由でメール送信する。

必要な環境変数(GitHub Secretsから渡される):
  GMAIL_ADDRESS      : 送信元Gmailアドレス(宛先を指定しない場合は宛先も兼ねる)
  GMAIL_APP_PASSWORD : Gmailのアプリパスワード(16文字)
  MAIL_TO            : 宛先(省略時は GMAIL_ADDRESS 宛)
  REPORT_PATH        : 送信するレポートファイルのパス

シークレット未設定の場合は何もせず正常終了する(レポート生成は止めない)。
"""

import os
import smtplib
import sys
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from email.header import Header

JST = timezone(timedelta(hours=9))


def main():
    sender = os.environ.get("GMAIL_ADDRESS", "").strip()
    password = os.environ.get("GMAIL_APP_PASSWORD", "").strip()
    report_path = os.environ.get("REPORT_PATH", "").strip()
    recipient = os.environ.get("MAIL_TO", "").strip() or sender

    if not sender or not password:
        print("GMAIL_ADDRESS / GMAIL_APP_PASSWORD が未設定のため、メール送信をスキップします。")
        return 0
    if not report_path or not os.path.exists(report_path):
        print(f"レポートファイルが見つかりません: {report_path}")
        return 1

    with open(report_path, encoding="utf-8") as fh:
        body = fh.read()

    today = datetime.now(JST).date().isoformat()
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = Header(f"📊 人事研究デイリーレポート {today}", "utf-8")
    msg["From"] = sender
    msg["To"] = recipient

    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as smtp:
        smtp.login(sender, password)
        smtp.sendmail(sender, [recipient], msg.as_string())
    print(f"メールを送信しました: {recipient}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
