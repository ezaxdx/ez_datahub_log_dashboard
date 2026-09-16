# config.py

# 연도 설정
CURRENT_YEAR = 2026
PREV_YEAR    = 2025

# 서비스 오픈 기준일 (D+카운터용)
BASE_DATE = "2025-01-17"

# 직원정보 시트: 연도별 컬럼명 패턴
YEAR_COL_DEPT = "{year}_부서명"
YEAR_COL_HQ   = "{year}_본부/실"
YEAR_COL_RANK = "{year}_통계 직급"
YEAR_COL_DIVISION = "{year}_사업부"

# 부서별 현황 페이지 전용: 본부명(hqNm)을 사업부 대신 그룹명으로 사용할 목록
# MICE부문 하위의 컨벤션/E&E 사업부는 API가 divisionNm='MICE부문'으로 묶어 반환하므로
# hqNm 기준으로 분리 표시 (CP실·주최사업실·디지털마케팅팀도 동일 처리)
DEPT_SHOW_AS_HQ = ["CP실", "주최사업실", "컨벤션 사업부", "E&E 사업부", "MICE혁신본부", "디지털마케팅팀"]

# deptNm을 부서_그룹으로 직접 사용할 팀 목록 (hqNm보다 우선 적용)
# MICE혁신본부 안에 묶여있는 IP솔루션팀을 별도 그룹으로 분리
DEPT_SHOW_AS_TEAM = ["IP솔루션팀"]

# 직급 정렬 순서 (사원 -> 임원)
RANK_ORDER = ['사원', '대리', '과장', '차장', '팀장', '부장', '본부장', '임원']

# 비표준 직급 → 표준 직급 정규화 매핑
# 피벗·직급그룹·명부 등 모든 집계에 일괄 적용됨
RANK_NORMALIZE = {
    '선임':       '대리',    # ICT융합개발본부 선임 (김세민, 강재연)
    '선임연구원':  '대리',    # ICT융합연구소 퇴사자 (김민지, 강명우, 이동석, 이새롬) — API 수정 전 임시
    # 책임연구원 → 기타 (매핑 없음, add_rank_group에서 '기타' 처리)
    # I-nori (디키디키) 직급 매핑
    '관장':       '본부장',
    '부관장':     '팀장',
    '책임매니저':  '차장',
    '선임매니저':  '대리',
    '매니저':     '사원',
}

# 표준 이메일(ID) 컬럼명 
COL_NAME_EMAIL = "PRS ID"

# 시트 이름
SHEET_NAME_USERS    = "직원정보"
SHEET_NAME_IGNORE   = "퇴사자_ignore"
SHEET_NAME_LOGIN    = "login"
SHEET_NAME_DOWNLOAD = "download"
SHEET_NAME_PROPOSAL = "제안서_ezPDF"

# 사이드바 기본 제외 대상 (초기 선택에서 제외, Select All 시 포함)
DEFAULT_EXCLUDE_DEPTS = [
    "AXDX팀",       # 내부 운영팀 (hq=MICE혁신본부)
    "MICE혁신본부",  # 곽은경 본부장 — AXDX팀과 동일 처리 (사이드바 필터로 제외)
    "M-Level",      # 임원·정보미등록
    "㈜이즈피엠피",  # 계열사 (류두영 팀장)
    "Test",          # 테스트·관리자 계정
]

# 완전 제외 대상 (df_users + 로그 모두 제거 → 명부에도 안 보임)
DEFAULT_EXCLUDE_USERNO = [
    "416",   # 김미선: 이즈피엠피 DDP점 F&B 매니저 — 당사 소속 아님
]

# 로그에서만 제외 (df_users 유지 → 명부에 보임, 사용 카운팅 제외)
LOG_EXCLUDE_USERNOS = []   # 로그 전용 제외 계정 (현재 없음 — 곽은경은 사이드바 필터로 처리)

# 테스트/관리자 계정 UserNo 목록
# - 로그(로그인·다운로드·제안서)에서 완전 제외
# - 직원 명부에서는 'Test' 부서로 표시
TEST_ACCOUNT_USERNOS = ["007", "484", "492", "493", "503", "514", "527", "538", "556"]
# 007: 마스터관리자        484: 연구소업무활동        492: 구성원1(a@ezpmp.co.kr)
# 493: pm1(b@ezpmp.co.kr) 503: 연구소 구성원 테스트   514: 마스터관리자2
# 527: 신규임원(사업부장)OT용  538: 엑셀6(exel6@ezpmp.co.kr)  556: AXDX 테스트 계정
# 515 조민경: Test 제거 → 퇴사자(status_overrides)로 처리, 컨벤션 3팀/사원으로 표시

# 제안서 열람 로그 제외 계정 (구축·테스트용 계정)
# userNm 또는 prsId 가 아래 값과 일치하는 레코드를 제외
PROPOSAL_EXCLUDE_ACCOUNTS = [
    "admin",
    "Group1_admin",
    "테스트입니다.",
    "bella@ezpmp.co.kr",
    "msbfox",
    "dskim",
]

# --- [이메일 알림 설정] ---
# 발신용 SMTP 설정 (보안을 위해 .streamlit/secrets.toml 에서 로드)
SMTP_CONFIG = {
    "host": "smtp.gmail.com",
    "port": 587,
    "user": "",
    "password": ""
}

try:
    # 1. Streamlit 환경인 경우 st.secrets 시도
    import streamlit as st
    if hasattr(st, "secrets") and "smtp" in st.secrets:
        SMTP_CONFIG["host"] = st.secrets["smtp"].get("host", "smtp.gmail.com")
        SMTP_CONFIG["port"] = st.secrets["smtp"].get("port", 587)
        SMTP_CONFIG["user"] = st.secrets["smtp"].get("user", "")
        SMTP_CONFIG["password"] = st.secrets["smtp"].get("password", "")
    else:
        raise Exception("Not in streamlit or no smtp secret")
except Exception:
    # 2. Streamlit 환경이 아니거나 secrets가 없는 경우 직접 TOML 파일 읽기 시도
    try:
        import toml
        import os
        secrets_path = os.path.join(".streamlit", "secrets.toml")
        if os.path.exists(secrets_path):
            secrets = toml.load(secrets_path)
            if "smtp" in secrets:
                SMTP_CONFIG["host"] = secrets["smtp"].get("host", "smtp.gmail.com")
                SMTP_CONFIG["port"] = secrets["smtp"].get("port", 587)
                SMTP_CONFIG["user"] = secrets["smtp"].get("user", "")
                SMTP_CONFIG["password"] = secrets["smtp"].get("password", "")
    except Exception:
        pass

# 알림 수신자 리스트 (회사 이메일 등 여러 명 가능)
NOTIFICATION_RECIPIENTS = ["ekks55@ezpmp.co.kr","hyj@ezpmp.co.kr","k2cow0610@ezpmp.co.kr"]

# 위험 감지 임계치 (다운로드 횟수)
NOTIFICATION_THRESHOLD = 10

# 알림 대상 카테고리 (경로 메뉴명에 포함된 경우 합산)
ALERT_CATEGORIES = ["제안서", "운영자료", "서포트", "프로젝트"]

# --- [API 연동 소스 설정] ---
# "GSPREAD" (기본 구글시트 연동) 또는 "REST_API" (사내 REST API 연동) 선택
DATA_SOURCE_MODE = "REST_API"

# SSL 검증 여부 (개발/운영 서버 자체 서명 인증서 대응)
API_VERIFY_SSL = False

# 운영 서버 Base URL (끝에 / 없이)
API_BASE_URL = "http://221.148.122.133:31692"

# 각 엔드포인트 경로 (path만, Base URL 제외)
API_ENDPOINT_USERS    = "/admin/user/evaluation/get"          # GET  직원정보 전체 조회
API_ENDPOINT_LOGIN    = "/api/v1/admin/login-history/search"  # POST 로그인 이력 목록 조회
API_ENDPOINT_DOWNLOAD = "/api/v1/admin/download-logs/search"  # POST 다운로드 로그 목록 조회
API_ENDPOINT_PROPOSAL = "/admin/drm/open-log/get"             # POST 제안서(ezPDF DRM) 열람 로그

# 페이지당 최대 레코드 수 (API 허용 최대치)
API_PAGE_SIZE = 200

# 다운로드 filePath 키워드 → 경로 메뉴명 매핑
# API 응답의 filePath URL 안에 포함된 키워드로 카테고리를 구분합니다.
DOWNLOAD_PATH_CATEGORIES = {
    "manage-file":    "운영자료 찾기",
    "project-search": "프로젝트 찾기",
    "performance":    "프로젝트 실적",   # 검색결과 엑셀 다운 → str.contains('프로젝트')에 자동 포함
    "support":        "서포트 센터",
}

# API 인증 헤더 (토큰은 .streamlit/secrets.toml [api] token 에서 자동 로드)
# secrets.toml에 없을 경우 아래 값을 직접 입력
API_HEADERS = {
    "Content-Type": "application/json",
    # "Authorization": "Bearer <token>",  ← secrets.toml에서 자동 주입됨
}

