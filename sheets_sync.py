"""
구글 시트 동기화 모듈
- 처음 한 번: migrate_to_sheets.py 로 기존 데이터 전체 이전
- 이후: collector.py 실행 때마다 새 데이터만 추가
"""

import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

CRED_FILE = os.path.join(os.path.dirname(__file__), "credentials.json")
SHEET_ID  = os.getenv("GOOGLE_SHEET_ID", "").strip()
HEADER    = ["keyword", "date", "ratio", "source", "collected_at"]


def is_configured() -> bool:
    """credentials.json 과 GOOGLE_SHEET_ID 가 모두 준비됐는지 확인"""
    load_dotenv()
    sid = os.getenv("GOOGLE_SHEET_ID", "").strip()
    return os.path.exists(CRED_FILE) and bool(sid)


def _get_worksheet(tab: str = "trends"):
    load_dotenv()
    sid = os.getenv("GOOGLE_SHEET_ID", "").strip()

    if not os.path.exists(CRED_FILE):
        raise FileNotFoundError(
            "credentials.json 파일이 없습니다.\n"
            f"구글 클라우드 가이드를 따라 다운로드한 후\n"
            f"{os.path.dirname(CRED_FILE)} 폴더에 넣어주세요."
        )
    if not sid:
        raise ValueError(
            ".env 파일에 GOOGLE_SHEET_ID가 없습니다.\n"
            "구글 시트 URL 중간의 ID를 복사해서 .env 에 추가해 주세요."
        )

    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.file",
    ]
    creds = Credentials.from_service_account_file(CRED_FILE, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(sid)

    try:
        return sh.worksheet(tab)
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title=tab, rows=20000, cols=10)
        return ws


def sync_all_from_db(db_path: str) -> int:
    """
    SQLite trends.db 전체 데이터를 구글 시트 'trends' 탭에 덮어쓰기.
    처음 한 번 마이그레이션할 때 사용.
    반환: 업로드된 행 수
    """
    import sqlite3

    ws = _get_worksheet("trends")

    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT keyword, date, ratio, source, collected_at "
        "FROM trends ORDER BY date, source, keyword"
    ).fetchall()
    conn.close()

    if not rows:
        return 0

    ws.clear()
    all_data = [HEADER] + [list(r) for r in rows]
    # 한 번에 업로드 (API 횟수 절약)
    ws.update(all_data, value_input_option="RAW")
    return len(rows)


def append_new(inserted_records: list[tuple]) -> int:
    """
    collector.py 가 새로 저장한 records 를 구글 시트에 추가.
    inserted_records: [(keyword, date, ratio, source), ...]
    반환: 추가된 행 수
    """
    if not inserted_records:
        return 0

    ws = _get_worksheet("trends")

    # 헤더 확인 — 없으면 첫 행에 추가
    if ws.row_values(1) != HEADER:
        ws.clear()
        ws.append_row(HEADER)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_rows = [
        [kw, str(d)[:10], float(r), src, now]
        for kw, d, r, src in inserted_records
    ]
    ws.append_rows(new_rows, value_input_option="RAW")
    return len(new_rows)
