"""
remind_smtp.py — 월 1회 Gmail 앱 비밀번호 갱신 알림
Windows 작업 스케줄러에서 매월 1일 실행
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import discord_utils

discord_utils.send_error(
    "📅 Gmail 앱 비밀번호 갱신 주기 알림\n\n"
    "매월 정기 알림입니다. 앱 비밀번호가 만료되기 전에 확인하세요.\n\n"
    "▶ Google 계정 → 보안 → 앱 비밀번호\n"
    "▶ 갱신 후 .streamlit/secrets.toml [smtp] password 업데이트",
    context="remind_smtp.py — 월간 정기 알림"
)
print("Discord 알림 전송 완료")
