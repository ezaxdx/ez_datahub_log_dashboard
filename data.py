import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date as _date
import config

# 자체 서명 인증서 환경에서 urllib3 InsecureRequestWarning 억제
try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

try:
    import discord_utils as _discord
except ImportError:
    _discord = None

# --- [load 블록] ---

def _get_api_headers():
    """
    API 인증 헤더를 반환합니다.
    우선순위: st.secrets["api"]["token"] > config.API_HEADERS
    """
    import os, tomllib
    headers = dict(getattr(config, "API_HEADERS", {}))

    token = None
    # 1. Streamlit Secrets
    try:
        if hasattr(st, "secrets") and "api" in st.secrets:
            token = st.secrets["api"].get("token", None)
    except Exception:
        pass

    # 2. .streamlit/secrets.toml 직접 읽기 (스케줄러 등 비-Streamlit 환경)
    if not token:
        try:
            secrets_path = os.path.join(".streamlit", "secrets.toml")
            if os.path.exists(secrets_path):
                with open(secrets_path, "rb") as f:
                    sec = tomllib.load(f)
                if "api" in sec:
                    token = sec["api"].get("token", None)
        except Exception:
            pass

    if token:
        headers["Authorization"] = token if token.startswith("Bearer ") else f"Bearer {token}"

    return headers


def _paginate(endpoint_path, method="POST", payload=None, label=""):
    """
    API를 페이지 단위로 반복 호출하여 전체 레코드 리스트를 반환합니다.

    지원 응답 구조:
      A) {"data": {"list": [...], "totalCount": N, "page": N, "size": N}}  ← AI Gate / 로그인·다운로드
      B) {"list": [...], "totalCount": N}                                  ← DRM 제안서
      C) 단순 배열 [...]                                                    ← 직원정보 등
    """
    import requests

    base_url   = getattr(config, "API_BASE_URL", "")
    page_size  = getattr(config, "API_PAGE_SIZE", 200)
    verify_ssl = getattr(config, "API_VERIFY_SSL", False)
    headers    = _get_api_headers()
    url        = base_url + endpoint_path

    all_records = []
    page = 0

    while True:
        req_body = {**(payload or {}), "page": page, "size": page_size}
        try:
            if method.upper() == "POST":
                resp = requests.post(url, json=req_body, headers=headers,
                                     verify=verify_ssl, timeout=30)
            else:
                # GET: page/size를 query parameter로 전달
                params = {k: v for k, v in req_body.items()}
                resp = requests.get(url, params=params, headers=headers,
                                    verify=verify_ssl, timeout=30)

            if resp.status_code != 200:
                _msg = f"[{label}] API 오류 (HTTP {resp.status_code}) — {url}"
                print(_msg)
                try: st.warning(_msg)
                except: pass
                if _discord:
                    if resp.status_code == 401:
                        _discord.send_error(
                            f"API 인증 토큰이 만료되었습니다.\n엔드포인트: {url}\n\n"
                            "▶ .streamlit/secrets.toml [api] token 을 새 토큰으로 교체하세요.",
                            context=f"data.py — {label} 401 Unauthorized"
                        )
                    elif resp.status_code >= 500:
                        _discord.send_error(
                            f"API 서버 오류 (HTTP {resp.status_code})\n엔드포인트: {url}\n\n"
                            "▶ 서버 상태를 확인하세요.",
                            context=f"data.py — {label} {resp.status_code} Server Error"
                        )
                    else:
                        _discord.send_error(
                            f"API 오류 (HTTP {resp.status_code})\n엔드포인트: {url}",
                            context=f"data.py — {label}"
                        )
                break

            j = resp.json()

            # 응답 구조 A: data.list
            if isinstance(j, dict) and "data" in j and isinstance(j["data"], dict):
                inner    = j["data"]
                records  = inner.get("list", [])
                total    = inner.get("totalCount", len(records))
            # 응답 구조 B: list (최상위)
            elif isinstance(j, dict) and "list" in j:
                records  = j["list"]
                total    = j.get("totalCount", len(records))
            # 응답 구조 C: 단순 배열
            elif isinstance(j, list):
                records  = j
                total    = len(j)
            else:
                records  = []
                total    = 0

            all_records.extend(records)

            # 전체 데이터를 모두 받았거나 마지막 페이지면 종료
            if len(all_records) >= total or len(records) == 0:
                break

            page += 1

        except Exception as e:
            _msg = f"[{label}] API 호출 실패 (page={page}): {e}"
            print(_msg)
            try: st.warning(_msg)
            except: pass
            if _discord:
                import requests as _req
                if isinstance(e, (_req.exceptions.ConnectionError, _req.exceptions.Timeout)):
                    _discord.send_error(
                        f"API 서버에 접속할 수 없습니다.\n엔드포인트: {url}\n오류: {e}\n\n"
                        "▶ 서버 네트워크 상태를 확인하세요.",
                        context=f"data.py — {label} 접속 불가"
                    )
                else:
                    _discord.send_error(
                        f"API 호출 중 예외 발생\n엔드포인트: {url}\n오류: {e}",
                        context=f"data.py — {label}"
                    )
            break

    return all_records


# ──────────────────────────────────────────────
#  데이터 타입별 빌더 (API 레코드 → DataFrame)
# ──────────────────────────────────────────────

def _build_users_df(records: list) -> pd.DataFrame:
    """
    직원정보 API 레코드 → df_users (Google Sheets 컬럼명 규격으로 변환)

    API 필드 매핑:
        userNo          → UserNo          (3자리 zero-pad는 map_all에서 처리)
        userNm          → 임직원명
        prsId           → PRS ID
        hireDt          → 입사일자
        history[year].deptNm         → {year}_부서명
        history[year].hqNm           → {year}_본부/실
        history[year].divisionNm     → {year}_사업부
        history[year].statPositionNm → {year}_통계 직급
    """
    rows = []
    for r in records:
        retire_dt = r.get("retireDt") or ""
        row = {
            "UserNo":   str(r.get("userNo", "")),
            "임직원명":  r.get("userNm", ""),
            "PRS ID":   str(r.get("prsId", "")).strip().lower(),
            "입사일자":  r.get("hireDt", ""),
            "퇴사일자":  retire_dt,                          # 재직 중이면 ""
            # 퇴사일이 오늘 이전(당일 포함)일 때만 퇴사 처리
            # → 미래 날짜가 입력된 예정자는 퇴사일 당일까지 재직자로 표시
            "재직상태":  "퇴사" if retire_dt and retire_dt <= _date.today().isoformat() else "재직",
        }

        # history[] 평탄화: 연도별 소속·직급 이력 → {year}_컬럼명
        history_by_year: dict[int, dict] = {}
        for h in r.get("history", []):
            year = str(h.get("year", "")).strip()
            if not year:
                continue
            row[f"{year}_부서명"]    = h.get("deptNm", "")
            row[f"{year}_본부/실"]   = h.get("hqNm", "")
            row[f"{year}_사업부"]    = h.get("divisionNm", "")
            row[f"{year}_통계 직급"] = h.get("statPositionNm", "")
            try:
                history_by_year[int(year)] = h
            except ValueError:
                pass

        # ── 유효 연도(effective year) 결정 ─────────────────────────────
        # 퇴사자: 퇴사년도 이하 최근 history → 마지막 소속 기준 부서·직급 표시
        # 재직자: CURRENT_YEAR 이하 최근 history (통상 CURRENT_YEAR)
        # ※ 이 _eff_* 컬럼은 명부 표시 전용 — 로그 조인에는 사용하지 않음
        if retire_dt:
            try:
                eff_cap = min(int(retire_dt[:4]), config.CURRENT_YEAR)
            except (ValueError, IndexError):
                eff_cap = config.CURRENT_YEAR
        else:
            eff_cap = config.CURRENT_YEAR

        _valid = [y for y in history_by_year if y <= eff_cap]
        # 부서 정보가 있는 연도 우선 선택 (2026 데이터가 있어도 모두 None이면 이전 연도로 fallback)
        def _has_dept(h):
            return any(h.get(k) for k in ('deptNm', 'hqNm', 'divisionNm'))
        _valid_with_dept = [y for y in _valid if _has_dept(history_by_year[y])]
        _eff_year = max(_valid_with_dept) if _valid_with_dept else (max(_valid) if _valid else None)
        eff_h  = history_by_year[_eff_year] if _eff_year else {}
        row['_eff_deptNm'] = (eff_h.get('deptNm')         or '').strip()
        row['_eff_hqNm']   = (eff_h.get('hqNm')           or '').strip()
        row['_eff_divNm']  = (eff_h.get('divisionNm')     or '').strip()
        row['_eff_rankNm'] = (eff_h.get('statPositionNm') or '').strip()

        rows.append(row)

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _build_login_df(records: list) -> pd.DataFrame:
    """
    로그인 이력 API 레코드 → df_login

    API 필드 매핑:
        userNo     → UserNo
        createdDt  → 로그인 일자 (YYYY-MM-DD) + 로그인 시간 (HH:MM:SS)
          ※ createdDt 형식: ISO 8601 (예: "2026-04-17T09:24:35+09:00")
    """
    rows = []
    for r in records:
        date_str = time_str = ""
        raw_dt = r.get("createdDt") or r.get("loginDt") or ""
        if raw_dt:
            try:
                dt = pd.to_datetime(raw_dt, utc=True).tz_convert("Asia/Seoul")
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                pass

        rows.append({
            "UserNo":    str(r.get("userNo", "")),
            "로그인 일자": date_str,
            "로그인 시간": time_str,
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _build_download_df(records: list) -> pd.DataFrame:
    """
    다운로드 이력 API 레코드 → df_download

    API 필드 매핑:
        userNo      → UserNo
        createDt    → 다운로드 일자 + 다운로드 시간
        filePath    → 경로 메뉴명  (URL 키워드로 카테고리 분류)
          manage-file    → 운영자료
          project-search → 프로젝트
          support        → 서포트
          그 외           → 기타
    """
    cat_map = getattr(config, "DOWNLOAD_PATH_CATEGORIES", {
        "manage-file":    "운영자료",
        "project-search": "프로젝트",
        "support":        "서포트",
    })

    rows = []
    for r in records:
        date_str = time_str = ""
        raw_dt = r.get("createDt") or r.get("downloadDt") or ""
        if raw_dt:
            try:
                dt = pd.to_datetime(raw_dt, utc=True).tz_convert("Asia/Seoul")
                date_str = dt.strftime("%Y-%m-%d")
                time_str = dt.strftime("%H:%M:%S")
            except Exception:
                pass

        # filePath → 경로 메뉴명
        file_path = str(r.get("filePath", ""))
        category = "기타"
        for keyword, label in cat_map.items():
            if keyword in file_path:
                category = label
                break

        rows.append({
            "UserNo":    str(r.get("userNo", "")),
            "다운로드 일자": date_str,
            "다운로드 시간": time_str,
            "경로 메뉴명":  category,
            "파일명":      r.get("fileNm", ""),   # 실제 파일명 (Top10 분석용)
        })

    return pd.DataFrame(rows) if rows else pd.DataFrame()


def _build_proposal_df(records: list) -> pd.DataFrame:
    """
    제안서(ezPDF DRM) 열람 로그 API 레코드 → df_proposal

    API 필드 매핑:
        prsId    → PRS ID   (UserNo 역매핑 브릿지)
        openDate → 등록일    ("2026. 4. 29" → "2026-04-29" 정규화)
        openTime → 등록시간  ("HH:MM:SS")
    """
    import re

    def _normalize_date(raw: str) -> str:
        """"2026. 4. 29" 형식 → "2026-04-29" 표준 변환"""
        m = re.match(r"(\d{4})\.\s*(\d{1,2})\.\s*(\d{1,2})", str(raw).strip())
        if m:
            y, mo, d = m.groups()
            return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
        return raw  # 이미 표준 형식이면 그대로

    # 제외 계정 목록 (config.PROPOSAL_EXCLUDE_ACCOUNTS)
    exclude_accounts = set(
        a.strip().lower()
        for a in getattr(config, "PROPOSAL_EXCLUDE_ACCOUNTS", [])
    )

    rows = []
    for r in records:
        prs_id  = str(r.get("prsId",  "")).strip().lower()
        user_nm = str(r.get("userNm", "")).strip().lower()

        # userNm 또는 prsId 가 제외 목록에 있으면 스킵
        if prs_id in exclude_accounts or user_nm in exclude_accounts:
            continue

        # TODO: API가 send 타입 반환 시 아래 주석 해제
        if r.get("type") != "send":
            continue
        if r.get("resultYn") != "성공":
            continue
        if not prs_id:
            continue

        rows.append({
            "PRS ID":   prs_id,
            "등록일":    _normalize_date(r.get("openDate", "")),
            "등록시간":  r.get("openTime", ""),
            "문서경로":  r.get("itemId", ""),
        })

    if rows:
        return pd.DataFrame(rows)
    return pd.DataFrame(columns=["PRS ID", "등록일", "등록시간", "문서경로"])


@st.cache_data(ttl=600)
def load_from_api():
    """
    사내 REST API에서 모든 데이터를 로드하고 DataFrame으로 반환합니다.
    반환 컬럼 규격은 Google Sheets 버전과 동일 → 하위 map/preprocess 로직 재사용.
    """
    # 1. 직원정보
    users_records = _paginate(
        config.API_ENDPOINT_USERS, method="GET", label="직원정보"
    )
    df_users = _build_users_df(users_records)

    # 2. 로그인 이력
    login_records = _paginate(
        config.API_ENDPOINT_LOGIN, method="POST", payload={}, label="로그인"
    )
    df_login = _build_login_df(login_records)

    # 3. 다운로드 이력
    download_records = _paginate(
        config.API_ENDPOINT_DOWNLOAD, method="POST", payload={}, label="다운로드"
    )
    df_download = _build_download_df(download_records)

    # 4. 제안서(ezPDF DRM) 열람 로그
    proposal_records = _paginate(
        config.API_ENDPOINT_PROPOSAL, method="POST", payload={}, label="제안서"
    )
    df_proposal = _build_proposal_df(proposal_records)

    return df_users, df_login, df_download, df_proposal

@st.cache_data(ttl=600)
def load_all():
    """
    설정된 소스 모드(DATA_SOURCE_MODE)에 따라 데이터를 로드합니다.
    Google Sheets 또는 REST API에서 모든 데이터를 원본 그대로 로드하고,
    직원정보의 병합 헤더를 평탄화합니다.
    """
    mode = getattr(config, "DATA_SOURCE_MODE", "GSPREAD")
    if mode == "REST_API":
        return load_from_api()
        
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        
        # 1. Streamlit Secrets 확인 (대시보드 실행 시)
        if hasattr(st, "secrets") and "gcp_service_account" in st.secrets:
            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
            sheet_url = st.secrets["gcp_sheet_url"]
        else:
            # 2. 로컬 secrets.toml 직접 로드 (스케줄러/배치 등 일반 실행 시)
            import os
            import tomllib
            secrets_path = os.path.join(".streamlit", "secrets.toml")
            if not os.path.exists(secrets_path):
                raise FileNotFoundError(f"인증 정보 파일을 찾을 수 없습니다: {secrets_path}")
                
            with open(secrets_path, "rb") as f:
                secrets = tomllib.load(f)
                creds = Credentials.from_service_account_info(secrets["gcp_service_account"], scopes=scope)
                sheet_url = secrets.get("gcp_sheet_url", "https://docs.google.com/spreadsheets/d/1N0UUF2Qroqbukd37WRgur2FpjzxEXLevT79EB_GutEk/edit?usp=sharing")
        
        client = gspread.authorize(creds)
        sh = client.open_by_url(sheet_url)
    except Exception as e:
        print(f"Google Sheets 연결 실패: {e}")
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    def get_df_safe(sheet_name):
        try:
            ws = sh.worksheet(sheet_name)
            data = ws.get_all_values()
            if not data:
                return pd.DataFrame()
            
            # 중복 컬럼명 처리
            headers = data[0]
            from collections import Counter
            col_counts = Counter(headers)
            running_counts = {}
            new_headers = []
            for col in headers:
                if col_counts[col] > 1:
                    running_counts[col] = running_counts.get(col, 0) + 1
                    new_headers.append(f"{col}{running_counts[col]}")
                else:
                    new_headers.append(col)
            
            df = pd.DataFrame(data[1:], columns=new_headers)
            
            # [추가] 고유 번호 기반 중복 제거 (방어 로직)
            pk_cols = ['NO', 'No', '번호']
            actual_pk = [c for c in pk_cols if c in df.columns]
            if actual_pk:
                df = df.drop_duplicates(subset=actual_pk, keep='last')
            
            # 숫자 자동 변환
            for col in df.columns:
                try:
                    df[col] = pd.to_numeric(df[col])
                except (ValueError, TypeError):
                    pass
            return df
        except gspread.exceptions.WorksheetNotFound:
            return pd.DataFrame()

    # 일반 로그 시트 로드
    df_login = get_df_safe(config.SHEET_NAME_LOGIN)
    df_download = get_df_safe(config.SHEET_NAME_DOWNLOAD)
    df_proposal = get_df_safe(config.SHEET_NAME_PROPOSAL)

    # 직원정보 시트 헤더 평탄화
    df_users = pd.DataFrame()
    try:
        ws_users = sh.worksheet(config.SHEET_NAME_USERS)
        raw_users = ws_users.get_all_values()
        if len(raw_users) >= 2:
            row0 = raw_users[0]  # 연도 행
            row1 = raw_users[1]  # 컬럼명 행
            
            # forward fill for years
            current_year_val = ""
            flattened_headers = []
            # 고정 컬럼에서 config.COL_NAME_EMAIL(PRS ID) 사용
            fixed_cols = ["UserNo", "임직원명", config.COL_NAME_EMAIL, "입사일자"]
            
            for y, c in zip(row0, row1):
                y_str = str(y).strip()
                c_str = str(c).strip()
                
                if y_str:
                    current_year_val = y_str
                
                if c_str in fixed_cols or not current_year_val:
                    flattened_headers.append(c_str)
                else:
                    flattened_headers.append(f"{current_year_val}_{c_str}")
            
            df_users = pd.DataFrame(raw_users[2:], columns=flattened_headers)
            # No 컬럼 제외
            if "No" in df_users.columns:
                df_users = df_users.drop(columns=["No"])
    except Exception as e:
        _msg = f"직원정보 로드 실패: {e}"
        print(_msg)
        try: st.warning(_msg)
        except: pass

    return df_users, df_login, df_download, df_proposal

# --- [map 블록] ---

def map_all(df_users, df_login, df_download, df_proposal):
    """
    UserNo 정규화, 이메일 매핑, 마스터 정보 조인을 수행합니다.
    """
    if df_users.empty:
        return df_users, df_login, df_download, df_proposal

    # 1. UserNo 정규화 (3자리 zero-padding)
    def normalize_userno(val):
        if pd.isna(val) or str(val).strip() == "" or str(val).lower() == 'nan':
            return ""
        # 소수점 제거 및 공백 제거
        s = str(val).strip().replace('.0', '')
        # 숫자인 경우 3자리 자릿수 맞춤
        if s.isdigit():
            return s.zfill(3)
        return s

    if 'UserNo' in df_users.columns:
        df_users['UserNo'] = df_users['UserNo'].apply(normalize_userno)

    # 2. PRS ID -> UserNo 역매핑 브릿지 (직원정보 마스터 활용)
    email_to_userno = {}
    if config.COL_NAME_EMAIL in df_users.columns:
        # 이메일 앞뒤 공백 제거 및 소문자 통일하여 매핑 사전 생성
        temp_df = df_users.copy()
        temp_df[config.COL_NAME_EMAIL] = temp_df[config.COL_NAME_EMAIL].astype(str).str.strip().str.lower()
        email_to_userno = temp_df[temp_df[config.COL_NAME_EMAIL] != ""].set_index(config.COL_NAME_EMAIL)['UserNo'].to_dict()

    # 3. 각 시트 조인 처리
    def join_master_info(df, master):
        if df.empty: return df
        df = df.copy()
        
        # UserNo 정규화
        u_col = 'userNo' if 'userNo' in df.columns else 'UserNo' if 'UserNo' in df.columns else None
        if u_col:
            df[u_col] = df[u_col].apply(normalize_userno)
        
        # PRS ID (이메일) 컬럼이 있고 UserNo가 없는 경우 매핑 (제안서 등)
        if config.COL_NAME_EMAIL in df.columns and (not u_col or (df[u_col] == "").all()):
            # 로그의 이메일도 동일하게 공백 제거 및 소문자 정규화 수행
            df[config.COL_NAME_EMAIL] = df[config.COL_NAME_EMAIL].astype(str).str.strip().str.lower()
            df['UserNo_mapped'] = df[config.COL_NAME_EMAIL].map(email_to_userno)
            u_col = 'UserNo_mapped'
        
        if not u_col: return df

        # 기존 이름/부서/직급 등 컬럼 삭제
        cols_to_drop = [c for c in ['이름', '부서', '직급', '부서명', '직급그룹'] if c in df.columns]
        df.drop(columns=cols_to_drop, inplace=True)

        # 마스터 조인 (UserNo 기준)
        # 양쪽 UserNo 컬럼 정규화 (유저 요청 스펙 반영)
        df[u_col] = df[u_col].astype(str).str.strip().str.replace(r'\.0$', '', regex=True).str.zfill(3)
        master['UserNo'] = master['UserNo'].astype(str).str.strip().str.replace(r'\.0$', '', regex=True).str.zfill(3)
        
        # 중복 컬럼 확인 (디버깅)
        # print("df 중복 컬럼:", df.columns[df.columns.duplicated()].tolist())
        # print("master 중복 컬럼:", master.columns[master.columns.duplicated()].tolist())

        # 중복 컬럼 제거 후 merge
        df = df.loc[:, ~df.columns.duplicated()]
        master = master.loc[:, ~master.columns.duplicated()]
        master = master.drop_duplicates(subset=['UserNo'], keep='first')
        
        df = pd.merge(df, master, left_on=u_col, right_on='UserNo', how='left', suffixes=('', '_master'))
        
        # merge로 생긴 중복 컬럼 제거
        master_cols = [c for c in df.columns if c.endswith('_master')]
        df = df.drop(columns=master_cols)
        df = df.reset_index(drop=True)

        # [최적화] apply(axis=1) 루프 제거 및 벡터화 연산 일괄 처리
        if 'year' not in df.columns:
            df['year'] = config.CURRENT_YEAR
        else:
            df['year'] = pd.to_numeric(df['year'], errors='coerce').fillna(config.CURRENT_YEAR).astype(int)
            
        df['부서'] = ""
        df['사업부'] = "정보미등록"
        df['직급'] = ""
        df['부서_그룹'] = "M-Level"
        df['이름'] = df['임직원명'].fillna("").astype(str).str.strip() if '임직원명' in df.columns else ""

        unique_years = df['year'].unique()
        for y in unique_years:
            y_str = str(int(y))
            dept_col = config.YEAR_COL_DEPT.format(year=y_str)
            hq_col = config.YEAR_COL_HQ.format(year=y_str)
            div_col = config.YEAR_COL_DIVISION.format(year=y_str)
            rank_col = config.YEAR_COL_RANK.format(year=y_str)
            
            mask = df['year'] == y
            if not mask.any():
                continue
                
            # 1. 직급 매핑
            if rank_col in df.columns:
                df.loc[mask, '직급'] = df.loc[mask, rank_col].astype(str).str.strip().fillna("")
                
            # 2. 사업부 매핑 (DEPT_SHOW_AS_HQ 그룹은 hqNm 우선 — MICE부문 내 컨벤션/E&E 분리)
            _null_vals = ['nan', 'NaN', 'None', '']
            if div_col in df.columns:
                _div_s = df.loc[mask, div_col].astype(str).str.strip().replace(_null_vals, '')
                _hq_s  = df.loc[mask, hq_col].astype(str).str.strip().replace(_null_vals, '') if hq_col in df.columns else pd.Series('', index=df.loc[mask].index)
                _hq_ov = _hq_s.isin(config.DEPT_SHOW_AS_HQ)
                _div_f = _div_s.where(~_hq_ov, _hq_s)
                df.loc[mask, '사업부'] = _div_f.replace('', '정보미등록').fillna('정보미등록')

            # 3. 부서 Fallback 일괄 계산 (dept -> hq -> div)
            dept_val = df.loc[mask, dept_col].astype(str).str.strip().replace(_null_vals, None) if dept_col in df.columns else pd.Series(None, index=df[mask].index)
            hq_val   = df.loc[mask, hq_col].astype(str).str.strip().replace(_null_vals, None) if hq_col in df.columns else pd.Series(None, index=df[mask].index)
            div_val  = df.loc[mask, div_col].astype(str).str.strip().replace(_null_vals, None) if div_col in df.columns else pd.Series(None, index=df[mask].index)

            fallback_dept = dept_val.combine_first(hq_val).combine_first(div_val).fillna("")
            df.loc[mask, '부서'] = fallback_dept

            # 4. 부서_그룹 일괄 계산
            dept_series_g = df.loc[mask, dept_col].astype(str).str.strip().replace(_null_vals, '') if dept_col in df.columns else pd.Series("", index=df[mask].index)
            hq_series  = df.loc[mask, hq_col].astype(str).str.strip().replace(_null_vals, '') if hq_col in df.columns else pd.Series("", index=df[mask].index)
            div_series = df.loc[mask, div_col].astype(str).str.strip().replace(_null_vals, '') if div_col in df.columns else pd.Series("", index=df[mask].index)

            # 팀 단위 직접 표시 (DEPT_SHOW_AS_TEAM — deptNm 우선, hqNm보다 앞서 처리)
            _show_as_team = getattr(config, 'DEPT_SHOW_AS_TEAM', [])
            team_mask = dept_series_g.isin(_show_as_team)
            df.loc[mask & team_mask, '부서_그룹'] = dept_series_g[team_mask]

            # CP실 / 주최사업실 등 본부명 유지
            hq_mask = (~team_mask) & hq_series.isin(config.DEPT_SHOW_AS_HQ)
            df.loc[mask & hq_mask, '부서_그룹'] = hq_series[hq_mask]

            # 그 외 사업부명 사용
            div_mask = (~team_mask) & (~hq_mask) & (div_series != "")
            df.loc[mask & div_mask, '부서_그룹'] = div_series[div_mask]

            # 둘 다 아닌 경우 본부명 fallback (없으면 M-Level)
            fallback_mask = (~team_mask) & (~hq_mask) & (div_series == "")
            df.loc[mask & fallback_mask, '부서_그룹'] = hq_series[fallback_mask].replace('', 'M-Level')

        # 임원·총괄대표·대표이사는 부서 무관하게 M-Level 처리 (부서별 분석에서 제외)
        _exec_ranks = {'임원', '총괄대표', '대표이사'}
        if '직급' in df.columns:
            df.loc[df['직급'].isin(_exec_ranks), '부서_그룹'] = 'M-Level'

        return df

    # 로그 조인용 마스터: 전체 직원(재직+퇴사) 사용
    # → 퇴사자가 재직 당시 남긴 로그 기록도 집계에 포함되어야 함
    # → join_master_info 내부에서 로그 연도 기준 {year}_부서명 컬럼을 사용하므로
    #    2026년 퇴사자의 2026년 로그는 2026 데이터로 정확히 매핑됨
    df_login    = join_master_info(df_login,    df_users)
    df_download = join_master_info(df_download, df_users)
    df_proposal = join_master_info(df_proposal, df_users)

    # 4. 마스터(df_users) 자체에도 현재 연도 기준 표준 컬럼 추가 (apply 루프 제거)
    if not df_users.empty:
        y_str = str(config.CURRENT_YEAR)
        dept_col = config.YEAR_COL_DEPT.format(year=y_str)
        hq_col = config.YEAR_COL_HQ.format(year=y_str)
        div_col = config.YEAR_COL_DIVISION.format(year=y_str)
        rank_col = config.YEAR_COL_RANK.format(year=y_str)

        df_users['year'] = config.CURRENT_YEAR
        df_users['이름'] = df_users['임직원명'].fillna("").astype(str).str.strip()
        df_users['부서'] = ""
        df_users['사업부'] = "정보미등록"
        df_users['직급'] = ""
        df_users['부서_그룹'] = "M-Level"

        _null_vals = ['nan', 'NaN', 'None', '']

        if rank_col in df_users.columns:
            df_users['직급'] = df_users[rank_col].astype(str).str.strip().replace(_null_vals, '').fillna("")

        if div_col in df_users.columns:
            # DEPT_SHOW_AS_HQ 그룹은 hqNm 우선 — MICE부문 내 컨벤션/E&E 분리
            _div = df_users[div_col].astype(str).str.strip().replace(_null_vals, '')
            _hq  = df_users[hq_col].astype(str).str.strip().replace(_null_vals, '') if hq_col in df_users.columns else pd.Series('', index=df_users.index)
            _hq_override = _hq.isin(config.DEPT_SHOW_AS_HQ)
            _div_final   = _div.where(~_hq_override, _hq)
            df_users['사업부'] = _div_final.replace('', '정보미등록').fillna('정보미등록')

        dept_val = df_users[dept_col].astype(str).str.strip().replace(_null_vals, None) if dept_col in df_users.columns else pd.Series(None, index=df_users.index)
        hq_val   = df_users[hq_col].astype(str).str.strip().replace(_null_vals, None) if hq_col in df_users.columns else pd.Series(None, index=df_users.index)
        div_val  = df_users[div_col].astype(str).str.strip().replace(_null_vals, None) if div_col in df_users.columns else pd.Series(None, index=df_users.index)

        df_users['부서'] = dept_val.combine_first(hq_val).combine_first(div_val).fillna("")

        dept_series_g = df_users[dept_col].astype(str).str.strip().replace(_null_vals, '') if dept_col in df_users.columns else pd.Series("", index=df_users.index)
        hq_series  = df_users[hq_col].astype(str).str.strip().replace(_null_vals, '') if hq_col in df_users.columns else pd.Series("", index=df_users.index)
        div_series = df_users[div_col].astype(str).str.strip().replace(_null_vals, '') if div_col in df_users.columns else pd.Series("", index=df_users.index)

        # 팀 단위 직접 표시 (DEPT_SHOW_AS_TEAM — deptNm 우선)
        _show_as_team = getattr(config, 'DEPT_SHOW_AS_TEAM', [])
        team_mask = dept_series_g.isin(_show_as_team)
        df_users.loc[team_mask, '부서_그룹'] = dept_series_g[team_mask]

        hq_mask = (~team_mask) & hq_series.isin(config.DEPT_SHOW_AS_HQ)
        df_users.loc[hq_mask, '부서_그룹'] = hq_series[hq_mask]

        div_mask = (~team_mask) & (~hq_mask) & (div_series != "")
        df_users.loc[div_mask, '부서_그룹'] = div_series[div_mask]

        fallback_mask = (~team_mask) & (~hq_mask) & (div_series == "")
        df_users.loc[fallback_mask, '부서_그룹'] = hq_series[fallback_mask].replace('', 'M-Level')

        # 임원·총괄대표·대표이사는 부서 무관하게 M-Level 처리 (부서별 분석·명부 표시에서 제외)
        _exec_ranks = {'임원', '총괄대표', '대표이사'}
        exec_mask = df_users['직급'].isin(_exec_ranks)
        df_users.loc[exec_mask, '부서_그룹'] = 'M-Level'

        df_users['_ui_dept'] = df_users['부서'].replace('', 'M-Level')
        # 임원 직급은 명부에서도 M-Level로 표시
        df_users.loc[exec_mask, '_ui_dept'] = 'M-Level'

        # 테스트/관리자 계정은 부서_그룹·_ui_dept 모두 'Test'로 표시
        _test_unos_map = set(str(u).zfill(3) for u in getattr(config, 'TEST_ACCOUNT_USERNOS', []))
        if _test_unos_map and 'UserNo' in df_users.columns:
            _test_mask = df_users['UserNo'].isin(_test_unos_map)
            df_users.loc[_test_mask, '부서_그룹'] = 'Test'
            df_users.loc[_test_mask, '_ui_dept']  = 'Test'

        # ── 퇴사자 부서·직급 fallback ────────────────────────────────────
        # CURRENT_YEAR history가 없는 퇴사자(전년도 이전 퇴사)는 부서='' → M-Level이 됨
        # _eff_* 컬럼(퇴사년도 기준 가장 최근 history)으로 부서·직급 재계산
        # ※ 로그 조인은 active_users(재직자) 기준이므로 퇴사자 로그 기록에는 영향 없음
        if '_eff_deptNm' in df_users.columns:
            _null_set   = {'', 'nan', 'NaN', 'None'}
            _rank_norm  = getattr(config, 'RANK_NORMALIZE', {})
            _show_team  = set(getattr(config, 'DEPT_SHOW_AS_TEAM', []))
            _show_hq_s  = set(config.DEPT_SHOW_AS_HQ)
            _test_unos_fb = set(str(u).zfill(3) for u in getattr(config, 'TEST_ACCOUNT_USERNOS', []))

            # 부서가 비어있는 행 전체 (재직·퇴사 무관) — 2026 데이터 없는 경우 _eff_로 복원
            # Test 계정·임원 제외
            _fb_mask = (
                (df_users['부서'].isin(_null_set) | df_users['부서'].isna()) &
                ~df_users['직급'].isin(_exec_ranks) &
                ~df_users['UserNo'].isin(_test_unos_fb)
            )

            for _idx in df_users.index[_fb_mask]:
                _ed = (df_users.at[_idx, '_eff_deptNm'] or '').strip()
                _eh = (df_users.at[_idx, '_eff_hqNm']   or '').strip()
                _ev = (df_users.at[_idx, '_eff_divNm']  or '').strip()
                _er = (df_users.at[_idx, '_eff_rankNm'] or '').strip()
                _er = _rank_norm.get(_er, _er)  # RANK_NORMALIZE 적용

                df_users.at[_idx, '직급'] = _er

                # 임원 직급이면 M-Level 유지
                if _er in _exec_ranks:
                    df_users.at[_idx, '부서_그룹'] = 'M-Level'
                    df_users.at[_idx, '_ui_dept']  = 'M-Level'
                    continue

                # 부서 (deptNm → hqNm → divisionNm fallback)
                _dept_val = _ed or _eh or _ev
                df_users.at[_idx, '부서'] = _dept_val

                # 부서_그룹 재계산 (DEPT_SHOW_AS_TEAM > DEPT_SHOW_AS_HQ > div > hq > M-Level)
                if _ed in _show_team:
                    _grp = _ed
                elif _eh in _show_hq_s:
                    _grp = _eh
                elif _ev:
                    _grp = _ev
                elif _eh:
                    _grp = _eh
                else:
                    _grp = ''  # API에 history 데이터 없는 퇴사자 → M-Level 대신 빈 값

                df_users.at[_idx, '부서_그룹'] = _grp
                df_users.at[_idx, '_ui_dept']  = _dept_val or _grp or ''

    # 비표준 직급 → 표준 직급 정규화 (config.RANK_NORMALIZE)
    # df_users·로그 전체에 일괄 적용 → 피벗·직급그룹·명부 모두 반영
    _rank_normalize = getattr(config, 'RANK_NORMALIZE', {})
    if _rank_normalize:
        for _df in [df_users, df_login, df_download, df_proposal]:
            if not _df.empty and '직급' in _df.columns:
                _df['직급'] = _df['직급'].replace(_rank_normalize)

    return df_users, df_login, df_download, df_proposal

# --- [preprocess 블록] ---

def preprocess_all(df_users, df_login, df_download, df_proposal):
    """
    날짜 통일, 연도 추출, 직급 그룹화를 수행합니다.
    """
    def process_df(df):
        if df.empty:
            date_time_pairs_check = [('등록일', '등록시간'), ('다운로드 일자', '다운로드 시간'), ('로그인 일자', '로그인 시간')]
            if any(d_col in df.columns for d_col, _ in date_time_pairs_check):
                df = df.copy()
                df['date'] = pd.Series(dtype='datetime64[ns]')
                df['year'] = pd.Series(dtype='Int64')
            return df
        df = df.copy()

        # 1. 날짜 및 시간 컬럼 통합 (유효한 데이터가 있는 컬럼 우선 탐색)
        date_time_pairs = [
            ('등록일', '등록시간'),
            ('다운로드 일자', '다운로드 시간'),
            ('로그인 일자', '로그인 시간')
        ]

        best_date_series = None
        max_valid_dates = -1

        for d_col, t_col in date_time_pairs:
            if d_col in df.columns:
                if t_col in df.columns:
                    temp_date = pd.to_datetime(df[d_col].astype(str) + ' ' + df[t_col].astype(str), errors='coerce')
                else:
                    temp_date = pd.to_datetime(df[d_col], errors='coerce')

                valid_count = temp_date.notna().sum()
                if valid_count > max_valid_dates:
                    max_valid_dates = valid_count
                    best_date_series = temp_date

                # 모든 행이 유효하면 즉시 중단 (최적화)
                if valid_count == len(df):
                    break

        if best_date_series is not None:
            df['date'] = best_date_series
            df['year'] = df['date'].dt.year

        return df

    df_login = process_df(df_login)
    df_download = process_df(df_download)
    df_proposal = process_df(df_proposal)

    return df_users, df_login, df_download, df_proposal

def add_rank_group(df):
    if df.empty or '직급' not in df.columns: return df
    def group_rank(rank):
        if pd.isna(rank): return '기타'
        rank_str = str(rank).strip()
        if rank_str in ['사원', '대리']: return '실무자(사원/대리)'
        if rank_str in ['차장', '팀장', '부장', '본부장']: return '관리자(차장↑)'
        if rank_str in ['임원']: return '임원'
        return '기타'
    df['직급그룹'] = df['직급'].apply(group_rank)
    return df

def run_all():
    """
    데이터 로드부터 전처리까지 전체 프로세스를 실행합니다.
    """
    df_users, df_login, df_download, df_proposal = load_all()
    
    # UserNo 정규화 함수
    def _norm_uno(s): return str(s).strip().replace('.0', '').zfill(3)

    # 테스트 계정 UserNo (config + status_overrides.json의 Test 상태) → 로그 제외
    _test_unos = set(_norm_uno(u) for u in getattr(config, 'TEST_ACCOUNT_USERNOS', []))
    try:
        import json as _json, os as _os
        _ov_path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "status_overrides.json")
        if _os.path.exists(_ov_path):
            with open(_ov_path, 'r', encoding='utf-8') as _f:
                _ov = _json.load(_f)
            _test_unos |= {_norm_uno(k) for k, v in _ov.items() if v == 'Test'}
    except Exception:
        pass
    # 완전 제외 대상 → df_users + 로그 모두 제거 (명부에도 안 보임)
    _exclude_unos = set(_norm_uno(u) for u in getattr(config, 'DEFAULT_EXCLUDE_USERNO', []))
    # 로그 전용 제외 → df_users 유지 (명부에 보임), 사용 카운팅만 제외
    _log_exclude_unos = set(_norm_uno(u) for u in getattr(config, 'LOG_EXCLUDE_USERNOS', []))

    # 로그 데이터에서 테스트 계정 + 완전 제외 + 로그 전용 제외 모두 제거
    def exclude_from_logs(df):
        if df.empty or 'UserNo' not in df.columns: return df
        remove = _test_unos | _exclude_unos | _log_exclude_unos
        return df[~df['UserNo'].apply(_norm_uno).isin(remove)]

    # df_users에서는 완전 제외 계정만 제거 (테스트·로그 전용 제외는 명부에 유지)
    def exclude_from_users(df):
        if df.empty or 'UserNo' not in df.columns: return df
        return df[~df['UserNo'].apply(_norm_uno).isin(_exclude_unos)]

    df_users   = exclude_from_users(df_users)
    df_login   = exclude_from_logs(df_login)
    df_download = exclude_from_logs(df_download)
    df_proposal = exclude_from_logs(df_proposal)
    
    # Preprocess (날짜/연도 추출)
    df_users, df_login, df_download, df_proposal = preprocess_all(df_users, df_login, df_download, df_proposal)
    
    # Map (연도 기반 조인 & Fallback)
    df_users, df_login, df_download, df_proposal = map_all(df_users, df_login, df_download, df_proposal)
    
    # Post-process (직급 그룹화)
    df_users = add_rank_group(df_users)
    df_login = add_rank_group(df_login)
    df_download = add_rank_group(df_download)
    df_proposal = add_rank_group(df_proposal)

    # 데이터 0건 감지 — 평일 업무 시간(9~18시)에 전부 비어있으면 경보
    if _discord:
        from datetime import datetime as _dt
        _now = _dt.now()
        _is_weekday_hours = _now.weekday() < 5 and 9 <= _now.hour < 18
        if _is_weekday_hours:
            _empty = {
                "직원정보": df_users.empty,
                "로그인": df_login.empty,
                "다운로드": df_download.empty,
            }
            _empty_list = [k for k, v in _empty.items() if v]
            if _empty_list:
                _discord.send_error(
                    f"API는 응답했지만 데이터가 0건입니다.\n비어있는 항목: {', '.join(_empty_list)}\n\n"
                    "▶ API 서버 데이터 상태를 확인하세요.",
                    context="data.py — run_all() 0건 감지"
                )

    return df_users, df_login, df_download, df_proposal
