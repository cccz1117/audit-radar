# -*- coding: utf-8 -*-
"""SMTP 邮件发送。"""
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

import config


class Sender:
    """邮件发送器。"""

    def send(self, html_body: str, subject: str = "AI审计日报"):
        if not config.MAIL_HOST or not config.MAIL_USER:
            print("  ⚠️ 邮件未配置，仅打印")
            print(f"  Subject: {subject}")
            print(f"  Body: {html_body[:500]}...")
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = config.MAIL_FROM
        msg["To"] = ",".join(config.MAIL_TO_LIST)

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(config.MAIL_HOST, config.MAIL_PORT) as server:
            if config.MAIL_PORT == 587:
                server.starttls()
            if config.MAIL_PASS:
                server.login(config.MAIL_USER, config.MAIL_PASS)
            server.sendmail(
                config.MAIL_FROM, config.MAIL_TO_LIST, msg.as_string()
            )
        print(f"  📧 邮件已发送: {subject}")
