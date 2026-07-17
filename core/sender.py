# -*- coding: utf-8 -*-
"""SMTP 邮件发送器：支持 HTML + 纯文本双版本。"""
import html
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header

import config

class Sender:
    """邮件发送器。"""

    @staticmethod
    def _html_to_text(html_body: str) -> str:
        text = re.sub(r"<style[^>]*>.*?</style>", "", html_body, flags=re.DOTALL)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</div>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"</li>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _build_text_footer() -> str:
        return (
            "\n\n---\n"
            "【IT 监管日报】由 Audit Radar 自动生成\n"
            f"发件人：{config.MAIL_FROM}\n"
            "本邮件仅供信息参考，不构成任何投资或业务建议。"
        )

    @staticmethod
    def _build_html_footer() -> str:
        return (
            '<div style="margin-top:32px;padding-top:12px;border-top:1px solid #ddd;'
            'text-align:center;color:#999;font-size:12px;line-height:1.6;">'
            "<p>【IT 监管日报】由 Audit Radar 自动生成</p>"
            f'<p>发件人：{config.MAIL_FROM}</p>'
            "<p>本邮件仅供信息参考，不构成任何投资或业务建议。</p>"
            "</div>"
        )

    def send(self, html_body: str, subject: str = "IT 监管日报") -> None:
        if not config.MAIL_HOST or not config.MAIL_USER or not config.MAIL_TO_LIST:
            raise RuntimeError(
                "邮件未配置：MAIL_HOST, MAIL_USER, MAIL_TO_LIST 至少一个缺失。"
                "日报已生成但未发送。请检查 FC 环境变量或 GitHub Secrets。"
            )

        # HTML 插入页脚
        html_footer = self._build_html_footer()
        if "</body>" in html_body:
            html_with_footer = html_body.replace("</body>", f"{html_footer}\n</body>", 1)
        else:
            html_with_footer = html_body + html_footer

        # 纯文本版本
        text_body = self._html_to_text(html_with_footer) + self._build_text_footer()

        # 构建 multipart/alternative
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")

        # From/To 必须是纯字符串，不能是 Header 对象。
        # 邮箱地址含 ASCII 以外的字符（或编码后）会被 QQ/阿里云判定为 invalid。
        msg["From"] = config.MAIL_FROM
        msg["To"] = ",".join(config.MAIL_TO_LIST)

        # 辅助反垃圾头
        msg["X-Mailer"] = "Audit-Radar/1.0"
        msg["Precedence"] = "bulk"

        # 双版本：plain 在前，html 在后
        msg.attach(MIMEText(text_body, "plain", "utf-8"))
        msg.attach(MIMEText(html_with_footer, "html", "utf-8"))

        # SMTP 发送
        host = config.MAIL_HOST
        port = config.MAIL_PORT
        timeout = 10

        print(f"  [MAIL] 连接 {host}:{port} ...")

        server = None
        try:
            if port == 465:
                server = smtplib.SMTP_SSL(host, port, timeout=timeout)
            elif port == 587:
                server = smtplib.SMTP(host, port, timeout=timeout)
                server.starttls()
            else:
                try:
                    server = smtplib.SMTP(host, port, timeout=timeout)
                except Exception as e:
                    print(f"  [MAIL] 端口 {port} 失败: {e}，尝试 fallback 到 465 (SSL)")
                    server = smtplib.SMTP_SSL(host, 465, timeout=timeout)
                    print(f"  [MAIL] fallback 到 465 成功")

            if config.MAIL_PASS:
                print(f"  [MAIL] 登录 {config.MAIL_USER} ...")
                server.login(config.MAIL_USER, config.MAIL_PASS)

            print(f"  [MAIL] 发送邮件到 {config.MAIL_TO_LIST} ...")
            rejected = server.sendmail(
                config.MAIL_FROM, config.MAIL_TO_LIST, msg.as_string()
            )
            if rejected:
                print(f"  ⚠️ 部分收件人被拒绝: {rejected}")
                raise RuntimeError(f"SMTP 收件人拒绝: {rejected}")

            print(f"  [MAIL] 邮件已发送: {subject}")
        except smtplib.SMTPException as e:
            raise RuntimeError(f"SMTP 错误: {e}") from e
        except TimeoutError:
            raise RuntimeError(
                f"连接 {host}:{port} 超时（{timeout}s）。"
                "建议：1) 检查 FC 公网访问是否开启；"
                "2) 尝试端口 465（SSL）或 587（STARTTLS）；"
                "3) 确认 DirectMail 发信地址已启用"
            ) from None
        finally:
            if server is not None:
                try:
                    server.quit()
                except Exception:
                    pass