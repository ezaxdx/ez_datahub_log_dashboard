"""
discord_utils.py — Discord 웹훅 알림 유틸리티

기능:
  - 알람 감지 시 Discord 채널로 Embed 메시지 전송
  - 오류 발생 시 Discord 채널로 에러 알림 전송

설정:
  .streamlit/secrets.toml 에 아래 항목 추가
  ----------------------------------------
  [discord]
  webhook_url = "https://discord.com/api/webhooks/..."
  ----------------------------------------
"""

import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone


# ── 웹훅 URL 로드 ─────────────────────────────────────────────────────────────

def _get_webhook_url():
    # 1. Streamlit secrets 시도
    try:
        import streamlit as st
        if hasattr(st, "secrets") and "discord" in st.secrets:
            url = st.secrets["discord"].get("webhook_url", "")
            if url and url.startswith("http"):
                return url
    except Exception:
        pass

    # 2. TOML 파일 직접 읽기
    try:
        import toml
        secrets_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            ".streamlit", "secrets.toml"
        )
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            url = secrets.get("discord", {}).get("webhook_url", "")
            if url and url.startswith("http"):
                return url
    except Exception:
        pass

    return ""


# ── 메시지 전송 ───────────────────────────────────────────────────────────────

def send_alert(users_data, threshold, interval_start, interval_end):
    """
    위험 인원 감지 알림 전송

    users_data: list of dict
      - name, dept, rank, detail, total_count
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        print("[Discord] webhook_url 미설정 — 알람 전송 건너뜀")
        return False

    lines = []
    for u in users_data:
        lines.append(f"**{u['name']}** ({u['dept']} / {u['rank']})\n└ {u['detail']}")
    user_block = "\n".join(lines) if lines else "—"

    embed = {
        "title": "🚨 EZ 데이터허브 — 다운로드 이상 감지",
        "color": 0xFF4444,
        "fields": [
            {
                "name": "📅 분석 구간",
                "value": f"`{interval_start}` ~ `{interval_end}`",
                "inline": False,
            },
            {
                "name": f"⚠️ 초과 인원 {len(users_data)}명  (기준: 단일 카테고리 {threshold}건 이상)",
                "value": user_block,
                "inline": False,
            },
        ],
        "footer": {"text": "EZ DataHub Notifier"},
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    return _post(webhook_url, {"embeds": [embed]})


def send_error(error_msg, context="trigger_notif.py"):
    """
    오류 발생 알림 전송
    """
    webhook_url = _get_webhook_url()
    if not webhook_url:
        print("[Discord] webhook_url 미설정 — 에러 알림 건너뜀")
        return False

    desc = f"**발생 위치:** `{context}`\n```\n{error_msg}\n```"

    embed = {
        "title": "🔴 EZ 데이터허브 — 알림 시스템 오류",
        "description": desc,
        "color": 0xCC0000,
        "footer": {"text": "EZ DataHub Notifier"},
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
    }

    return _post(webhook_url, {"embeds": [embed]})


# ── 내부 HTTP 전송 ────────────────────────────────────────────────────────────

def _post(url, payload):
    # discordapp.com(구 도메인) → discord.com 으로 자동 정규화
    url = url.replace("discordapp.com", "discord.com")
    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                # Discord Cloudflare가 Python-urllib 를 봇으로 차단하는 것 방지
                "User-Agent": "DiscordBot (EZDataHub, 1.0)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            ok = resp.status in (200, 204)
            print(f"[Discord] {'전송 성공' if ok else '전송 실패'} (HTTP {resp.status})")
            return ok
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"[Discord] HTTP 오류 {e.code}: {body}")
        return False
    except Exception as e:
        print(f"[Discord] 전송 오류: {e}")
        return False
