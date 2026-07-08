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
        if not config.MAIL_HOST or not config.MAIL_USER or not config.MAIL_TO_LIST:
            raise RuntimeError(
                "邮件未配置：MAIL_HOST, MAIL_USER, MAIL_TO_LIST 至少一个缺失。"
                "日报已生成但未发送。请检查 FC 环境变量或 GitHub Secrets。"
            )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = config.MAIL_FROM
        msg["To"] = ",".join(config.MAIL_TO_LIST)

        msg.attach(MIMEText(html_body, "html", "utf-8"))

        # 尝试端口优先级：465 (SSL) > 587 (STARTTLS) > 25 (明文)
        # 阿里云 DirectMail 在 FC 的 VPC 环境下，25 端口常被拦截，465 最可靠
        host = config.MAIL_HOST
        port = config.MAIL_PORT
        timeout = 10

        print(f"  [MAIL] 连接 {host}:{port} ...")

        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=timeout)
            elif port == 587:
                server = smtplib.SMTP(host, port, timeout=timeout)
                server.starttls()
            else:
                # 端口 25 或其他：先尝试，fallback 到 465
                try:
                    server = smtplib.SMTP(host, port, timeout=timeout)
                except (ConnectionRefusedError, TimeoutError, OSError) as e:
                    print(f"  [MAIL] 端口 {port} 失败: {e}，尝试 fallback 到 465 (SSL)")
                    server = smtplib.SMTP_SSL(host, 465, timeout=timeout)
                    print(f"  [MAIL] fallback 到 465 成功")

            if config.MAIL_PASS:
                print(f"  [MAIL] 登录 {config.MAIL_USER} ...")
                server.login(config.MAIL_USER, config.MAIL_PASS)

            print(f"  [MAIL] 发送邮件到 {config.MAIL_TO_LIST} ...")
            server.sendmail(
                config.MAIL_FROM, config.MAIL_TO_LIST, msg.as_string()
            )
            server.quit()
            print(f"  [MAIL] 邮件已发送: {subject}")
        except smtplib.SMTPException as e:
            raise RuntimeError(f"SMTP 错误: {e}")
        except TimeoutError:
            raise RuntimeError(f"连接 {host}:{port} 超时（{timeout}s）。建议：1) 检查 FC 公网访问是否开启；2) 尝试端口 465（SSL）或 587（STARTTLS）；3) 确认 DirectMail 发信地址已启用")
        except Exception as e:
            raise RuntimeError(f"邮件发送失败: {e}")
