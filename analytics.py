"""
analytics.py — GA4 통합 모듈

구조:
- 브라우저 측: 0-height 컴포넌트로 gtag.js를 부모 윈도우에 주입
  → page_view, UTM 세션 어트리뷰션, 탭 전환 자동 추적
- 서버 측: Measurement Protocol로 커스텀 이벤트 전송 (버튼·필터 등)

GA4 설정 필요 항목 (.streamlit/secrets.toml):
  GA4_MEASUREMENT_ID = "G-XXXXXXXXXX"
  GA4_API_SECRET     = "xxxxxxxxxxxx"  (Measurement Protocol API secret)

디버그 모드:
  ?ga_debug_mode=1 쿼리 파라미터 → Python이 감지 → JS에 직접 주입
  (iframe 내부에서 window.location을 읽지 않음)
"""

import os
import uuid
import threading

import requests
import streamlit as st
import streamlit.components.v1 as components

_MP_ENDPOINT      = "https://www.google-analytics.com/mp/collect"
_MP_DEBUG_ENDPOINT = "https://www.google-analytics.com/debug/mp/collect"


# ── 설정 읽기 ─────────────────────────────────────────────
def _cfg() -> tuple[str, str]:
    """(measurement_id, api_secret) — 없으면 빈 문자열."""
    mid = sec = ""
    try:
        mid = st.secrets.get("GA4_MEASUREMENT_ID", "") or ""
        sec = st.secrets.get("GA4_API_SECRET", "") or ""
    except Exception:
        pass
    mid = mid or os.getenv("GA4_MEASUREMENT_ID", "")
    sec = sec or os.getenv("GA4_API_SECRET", "")
    return str(mid).strip(), str(sec).strip()


def _enabled() -> bool:
    mid, _ = _cfg()
    return bool(mid)


def _client_id() -> str:
    """세션당 고정 익명 UUID (GA4 client_id 대용)."""
    if "_ga4_cid" not in st.session_state:
        st.session_state["_ga4_cid"] = str(uuid.uuid4())
    return st.session_state["_ga4_cid"]


def _is_debug() -> bool:
    """
    Python 서버 측에서 ga_debug_mode 쿼리 파라미터를 판별합니다.
    iframe 내부 JS에서 window.location을 읽지 않습니다.
    """
    try:
        return st.query_params.get("ga_debug_mode", "") == "1"
    except Exception:
        return False


# ── 브라우저 측: gtag.js 주입 ─────────────────────────────
def inject_ga4_tag() -> None:
    """
    gtag.js를 Streamlit 부모 윈도우에 1회 주입합니다.
    Measurement ID가 없으면 아무것도 하지 않습니다.
    debug 모드 여부는 Python이 st.query_params로 판별해 JS에 직접 삽입합니다.
    """
    if not _enabled():
        return
    if st.session_state.get("_ga4_injected"):
        return

    mid, _ = _cfg()
    debug = _is_debug()
    # Python bool → JS literal
    js_debug = "true" if debug else "false"

    components.html(f"""
<script>
(function() {{
  var w = window.parent;
  if (w._ga4_injected) return;
  w._ga4_injected = true;

  var MID   = '{mid}';
  var DEBUG = {js_debug};

  // dataLayer + gtag 초기화 (스크립트 로드 전에 미리 설정)
  w.dataLayer = w.dataLayer || [];
  w.gtag = function() {{ w.dataLayer.push(arguments); }};

  if (DEBUG) {{
    // DebugView 활성화: 'set' 호출을 config 이전에
    w.gtag('set', 'debug_mode', true);
  }}

  w.gtag('js', new Date());
  w.gtag('config', MID, {{
    'anonymize_ip': true,
    'allow_enhanced_measurement': true,
    'send_page_view': true,
    'debug_mode': DEBUG
  }});

  // gtag.js 스크립트 삽입
  var s = w.document.createElement('script');
  s.async = true;
  s.src = 'https://www.googletagmanager.com/gtag/js?id=' + MID;
  w.document.head.insertBefore(s, w.document.head.firstChild);

  // debug 모드 플래그를 부모 창에 노출 (track_active_tab 등에서 참조)
  w._ga4_debug = DEBUG;
}})();
</script>
""", height=0, scrolling=False)

    st.session_state["_ga4_injected"] = True


# ── 브라우저 측: 탭 전환 감지 ────────────────────────────
def track_active_tab() -> None:
    """
    DOM에서 활성 탭 이름을 읽어 탭이 바뀔 때만 gtag 이벤트를 전송합니다.
    debug_mode 파라미터는 부모 창의 w._ga4_debug 플래그로 전달합니다.
    """
    if not _enabled():
        return

    components.html("""
<script>
(function() {
  var w = window.parent;
  if (typeof w.gtag !== 'function') {
    setTimeout(arguments.callee, 500);
    return;
  }
  function check() {
    var el = w.document.querySelector('[role="tab"][aria-selected="true"]');
    if (!el) return;
    var name = el.innerText.trim().replace(/^[\\s\\S]{1,3}\\s/, '').trim();
    if (!name || name === w._ga4_last_tab) return;
    w._ga4_last_tab = name;
    var params = { tab_name: name };
    if (w._ga4_debug) params.debug_mode = true;
    w.gtag('event', 'tab_view', params);
  }
  setTimeout(check, 80);
  setTimeout(check, 400);
})();
</script>
""", height=0, scrolling=False)


# ── 서버 측: Measurement Protocol 전송 (비동기) ──────────
def _mp(event_name: str, params: dict) -> None:
    """
    GA4 Measurement Protocol로 이벤트를 비동기 전송합니다.
    debug 모드일 때는 /debug/mp/collect 엔드포인트로 보냅니다.
    API Secret이 없거나 전송에 실패해도 앱 동작에 영향을 주지 않습니다.
    """
    mid, sec = _cfg()
    if not mid or not sec:
        return

    debug = _is_debug()
    if debug:
        params = dict(params, debug_mode=True)

    endpoint = _MP_DEBUG_ENDPOINT if debug else _MP_ENDPOINT
    payload = {
        "client_id": _client_id(),
        "events": [{"name": event_name, "params": params}],
    }
    url = f"{endpoint}?measurement_id={mid}&api_secret={sec}"

    def _post():
        try:
            requests.post(url, json=payload, timeout=3)
        except Exception:
            pass

    threading.Thread(target=_post, daemon=True).start()


# ── 공개 이벤트 함수 ───────────────────────────────────────

def event_dashboard_view(utm_source: str = "", utm_campaign: str = "",
                         utm_content: str = "") -> None:
    """앱 첫 진입 시 1회 기록."""
    if st.session_state.get("_ga4_dv_sent"):
        return
    st.session_state["_ga4_dv_sent"] = True
    _mp("dashboard_view", {
        "page_name": "keyword_dashboard",
        "utm_source": utm_source[:50],
        "utm_campaign": utm_campaign[:50],
        "utm_content": utm_content[:100],
    })


def event_keyword_search(keyword: str, search_type: str = "trend") -> None:
    """특정 키워드 선택·조회 시 기록."""
    if not keyword:
        return
    _mp("keyword_search", {
        "keyword": str(keyword)[:50],
        "search_type": search_type,
    })


def event_filter_change(filter_name: str, filter_value: str) -> None:
    """필터 값이 실제로 변경됐을 때만 기록."""
    key = f"_ga4_flt_{filter_name}"
    prev = st.session_state.get(key, "__unset__")
    val_str = str(filter_value)[:50]
    if prev == val_str:
        return
    st.session_state[key] = val_str
    _mp("filter_change", {"filter_name": filter_name, "filter_value": val_str})


def event_news_open(news_source: str, news_category: str = "") -> None:
    """뉴스 원문 또는 관련 링크 클릭 시 기록."""
    _mp("news_open", {
        "news_source": str(news_source)[:50],
        "news_category": str(news_category)[:50],
    })


def event_export_download(export_type: str, tab_name: str) -> None:
    """내보내기 실행 시 기록."""
    _mp("export_download", {
        "export_type": export_type,
        "tab_name": tab_name,
    })


def event_pr_action(action_type: str, content_type: str = "") -> None:
    """PR 활용 관리 탭의 핵심 액션 기록."""
    _mp("pr_action", {
        "action_type": action_type,
        "content_type": str(content_type)[:50],
    })
