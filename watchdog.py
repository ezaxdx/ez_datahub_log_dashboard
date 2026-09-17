"""
watchdog.py — 노티파이어 실행 여부 감시 (heartbeat 체크)

10:05 / 16:05 에 스케줄러로 실행.
최근 10분 안에 notifier_log.txt 에 실행 기록이 없으면 Discord 경보.
"""
import sys, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timedelta
import discord_utils

LOG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkpoints", "notifier_log.txt")
WINDOW_MINUTES = 10  # 최근 N분 안에 실행 기록이 있어야 정상


def check():
    now = datetime.now()
    cutoff = now - timedelta(minutes=WINDOW_MINUTES)

    if not os.path.exists(LOG_PATH):
        discord_utils.send_error(
            f"notifier_log.txt 파일 자체가 없습니다.\n경로: {LOG_PATH}",
            context="watchdog.py — 로그 파일 없음"
        )
        return

    recent_found = False
    with open(LOG_PATH, encoding='utf-8', errors='replace') as f:
        for line in f:
            # 형식: [2026-09-17 10:00:12] ...
            if not line.startswith('['):
                continue
            try:
                ts_str = line[1:20]
                ts = datetime.strptime(ts_str, '%Y-%m-%d %H:%M:%S')
                if ts >= cutoff:
                    recent_found = True
                    break
            except ValueError:
                continue

    if not recent_found:
        expected_hour = 10 if now.hour < 16 else 16
        discord_utils.send_error(
            f"노티파이어가 {expected_hour:02d}:00 에 실행되지 않았습니다.\n\n"
            f"확인 시각: {now.strftime('%Y-%m-%d %H:%M')}\n"
            f"최근 {WINDOW_MINUTES}분 내 실행 기록 없음\n\n"
            "▶ 작업 스케줄러 경로가 맞는지 확인하세요.\n"
            "▶ PC가 해당 시간에 켜져 있었는지 확인하세요.",
            context="watchdog.py — 노티파이어 미실행 감지"
        )
        print(f"[Watchdog] 경보 전송 — {expected_hour}시 실행 기록 없음")
    else:
        print(f"[Watchdog] 정상 — 최근 {WINDOW_MINUTES}분 내 실행 기록 확인")


if __name__ == "__main__":
    check()
