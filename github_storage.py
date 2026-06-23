"""
GitHub API를 통해 CSV 파일을 읽고 쓰는 모듈.
Streamlit Cloud에서 derived_keywords.csv의 영구 보존에 사용됩니다.

- GITHUB_TOKEN : 개인 액세스 토큰 (repo 권한)
- GITHUB_REPO  : "사용자명/저장소명"  예) "reinalee-bot/keyword-dashboard"

위 두 값이 없으면 자동으로 로컬 CSV 파일을 사용합니다.
"""

import os
import base64
import requests
import pandas as pd
from io import StringIO

GITHUB_API = "https://api.github.com"


def _get_config() -> tuple:
    """Streamlit secrets 또는 환경변수에서 토큰·저장소 이름을 가져옵니다."""
    try:
        import streamlit as st
        token = st.secrets.get("GITHUB_TOKEN", os.getenv("GITHUB_TOKEN", ""))
        repo  = st.secrets.get("GITHUB_REPO",  os.getenv("GITHUB_REPO",  ""))
    except Exception:
        token = os.getenv("GITHUB_TOKEN", "")
        repo  = os.getenv("GITHUB_REPO",  "")
    return token.strip(), repo.strip()


def is_configured() -> bool:
    """GitHub 연동이 설정됐는지 확인합니다."""
    token, repo = _get_config()
    return bool(token) and bool(repo)


def read_csv(file_path: str) -> pd.DataFrame | None:
    """
    GitHub에서 CSV 파일을 읽습니다.
    file_path 예: "data/derived_keywords.csv"
    실패 시 None 반환.
    """
    token, repo = _get_config()
    if not token or not repo:
        return None

    url = f"{GITHUB_API}/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }
    try:
        r = requests.get(url, headers=headers, timeout=10)
        if r.status_code != 200:
            return None
        raw = base64.b64decode(r.json()["content"]).decode("utf-8-sig")
        return pd.read_csv(StringIO(raw), dtype=str)
    except Exception:
        return None


def write_csv(df: pd.DataFrame, file_path: str, message: str) -> bool:
    """
    DataFrame을 GitHub에 CSV로 저장(커밋)합니다.
    file_path 예: "data/derived_keywords.csv"
    성공 시 True 반환.
    """
    token, repo = _get_config()
    if not token or not repo:
        return False

    url = f"{GITHUB_API}/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json",
    }

    # 현재 파일의 SHA 조회 (업데이트에 필요)
    try:
        r = requests.get(url, headers=headers, timeout=10)
        sha = r.json().get("sha", "") if r.status_code == 200 else ""
    except Exception:
        sha = ""

    # CSV → base64 인코딩
    csv_bytes  = df.to_csv(index=False).encode("utf-8")
    encoded    = base64.b64encode(csv_bytes).decode()

    payload = {"message": message, "content": encoded}
    if sha:
        payload["sha"] = sha

    try:
        r = requests.put(url, headers=headers, json=payload, timeout=20)
        return r.status_code in [200, 201]
    except Exception:
        return False
