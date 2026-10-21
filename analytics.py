"""
analytics.py — GA4 통합 모듈

구조:
- 브라우저 측: components.html() 안의 iframe에서 gtag.js를 직접 초기화
  → window.parent 의존 없이 DebugView 등록 보장
  → page_view, UTM 세션 어트리뷰션, 탭 전환 자동 추적
- 서버 측: Measurement Protocol (/mp/collect) 로 커스텀 이벤트 전송

GA4 설정 필요 항목 (.streamlit/secrets.toml):
  GA4_MEASUREMENT_ID = "G-XXXXXXXXXX"
  GA4_API_SECRET     = "xxxxxxxxxxxx"  (Measurement Protocol API secret)

debug 모드:
  ?ga_debug_mode=1 → Python st.query_params가 판별 → JS 리터럴로 삽입
  iframe 내부에서 window.location을 읽지 않음
"""

import os
import uuid
import threading
from urllib.parse import urlencode

import requests
import streamlit as st
import streamlit.components.v1 as components

_MP_ENDPOINT       = "https://www.google-analytics.com/mp/collect"
_MP_DEBUG_ENDPOINT = "https://www.google-analytics.com/debug/mp/collect"

# 배포 URL — page_location 파라미터에 사용 (secrets로 override 가능)
_DEFAULT_APP_URL = "https://keyword-dashboard-4dqkm8snau6crfozatwbcg.streamlit.app/"


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


def _page_url() -> str:
    """현재 페이지 URL을 쿼리 파라미터 포함하여 재구성합니다."""
    try:
        base = (
            st.secrets.get("GA4_APP_URL", None)
            or os.getenv("GA4_APP_URL", "")
            or _DEFAULT_APP_URL
        )
    except Exception:
        base = _DEFAULT_APP_URL
    base = base.rstrip("/") + "/"
    try:
        qp = {k: v for k, v in st.query_params.items()
              if k != "ga_debug_mode"}          # debug param은 URL에 노출 안 함
        return (base + "?" + urlencode(qp)) if qp else base
    except Exception:
        return base


# ── 브라우저 측: gtag.js를 iframe 내부에서 직접 초기화 ──────
def inject_ga4_tag() -> None:
    """
    GA4 gtag.js를 components.html() iframe 내부에서 직접 초기화합니다.
    window.parent 의존 없이 안정적으로 동작합니다.

    debug 모드(ga_debug_mode=1):
    - Python이 st.query_params로 감지
    - JS 리터럴(true/false)을 HTML에 직접 삽입
    - gtag('set','debug_mode',true) 후 config → GA4 DebugView에 기기 등록

    session_state로 중복 주입을 방지하되,
    debug 모드가 바뀌면 재주입합니다.
    """
    if not _enabled():
        return

    mid, _ = _cfg()
    debug = _is_debug()
    js_debug = "true" if debug else "false"

    # 같은 debug 모드로 이미 주입했으면 건너뜀
    if (st.session_state.get("_ga4_injected")
            and st.session_state.get("_ga4_debug_mode") == debug):
        return

    page_url = _page_url()

    components.html(f"""<!DOCTYPE html>
<html>
<head>
<script async src="https://www.googletagmanager.com/gtag/js?id={mid}"></script>
<script>
(function() {{
  var MID   = '{mid}';
  var DEBUG = {js_debug};
  var PAGE  = '{page_url}';

  window.dataLayer = window.dataLayer || [];
  function gtag() {{ dataLayer.push(arguments); }}
  window.gtag = gtag;

  // debug 모드: 'set' 먼저, 그 다음 'js', 마지막 'config'
  if (DEBUG) gtag('set', 'debug_mode', true);
  gtag('js', new Date());
  gtag('config', MID, {{
    'debug_mode'               : DEBUG,
    'send_page_view'           : true,
    'page_location'            : PAGE,
    'anonymize_ip'             : true,
    'allow_enhanced_measurement': true
  }});

  // 부모 창에도 gtag / 디버그 플래그 노출 (tab_view 등에 사용)
  // window.parent 접근이 불가한 환경에선 조용히 실패
  try {{
    window.parent.gtag        = gtag;
    window.parent.dataLayer   = window.dataLayer;
    window.parent._ga4_debug  = DEBUG;
  }} catch(e) {{}}
}})();
</script>
</head>
<body></body>
</html>
""", height=0, scrolling=False)

    st.session_state["_ga4_injected"]   = True
    st.session_state["_ga4_debug_mode"] = debug


# ── 브라우저 측: 탭 전환 감지 ─────────────────────────────
def track_active_tab() -> None:
    """
    DOM에서 활성 탭 이름을 읽어 탭이 바뀔 때만 gtag 이벤트를 전송합니다.
    부모 창의 gtag 함수를 사용하며, 없으면 아무것도 하지 않습니다.
    """
    if not _enabled():
        return

    components.html("""<script>
(function() {
  // inject_ga4_tag() 가 parent.gtag를 노출했을 때만 동작
  function tryTrack() {
    var gtagFn;
    try { gtagFn = window.parent.gtag; } catch(e) { return; }
    if (typeof gtagFn !== 'function') return;

    function check() {
      var doc;
      try { doc = window.parent.document; } catch(e) { return; }

      var el = doc.querySelector('[role="tab"][aria-selected="true"]');
      if (!el) return;

      // 이모지·공백 제거 후 순수 탭 이름 추출
      var name = el.innerText.trim().replace(/^[\\s\\S]{1,3}\\s/, '').trim();
      var last;
      try { last = window.parent._ga4_last_tab; } catch(e) { return; }
      if (!name || name === last) return;
      try { window.parent._ga4_last_tab = name; } catch(e) {}

      var params = { tab_name: name };
      try { if (window.parent._ga4_debug) params.debug_mode = true; } catch(e) {}
      gtagFn('event', 'tab_view', params);
    }

    setTimeout(check, 80);
    setTimeout(check, 450);
  }

  // gtag가 아직 설정 안 됐을 수 있으므로 약간 지연 후 시도
  setTimeout(tryTrack, 200);
  setTimeout(tryTrack, 700);
})();
</script>
""", height=0, scrolling=False)


# ── 서버 측: Measurement Protocol 전송 (비동기) ──────────
def _mp(event_name: str, params: dict) -> None:
    """
    GA4 Measurement Protocol(/mp/collect)로 이벤트를 비동기 전송합니다.
    debug 모드일 때 params에 debug_mode:true 를 추가해 DebugView에 이벤트를 표시합니다.
    (/debug/mp/collect 는 검증 전용으로 GA4에 이벤트를 저장하지 않으므로 사용하지 않음)

    API Secret이 없거나 전송에 실패해도 앱 동작에 영향을 주지 않습니다.
    """
    mid, sec = _cfg()
    if not mid or not sec:
        return

    # engagement_time_msec: GA4가 활성 세션으로 인식하는 데 필요
    final_params = {"engagement_time_msec": 1, **params}
    if _is_debug():
        final_params["debug_mode"] = True

    payload = {
        "client_id": _client_id(),
        "events": [{"name": event_name, "params": final_params}],
    }
    url = f"{_MP_ENDPOINT}?measurement_id={mid}&api_secret={sec}"

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
        "page_name"    : "keyword_dashboard",
        "utm_source"   : utm_source[:50],
        "utm_campaign" : utm_campaign[:50],
        "utm_content"  : utm_content[:100],
    })


def event_keyword_search(keyword: str, search_type: str = "trend") -> None:
    """특정 키워드 선택·조회 시 기록."""
    if not keyword:
        return
    _mp("keyword_search", {
        "keyword"     : str(keyword)[:50],
        "search_type" : search_type,
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
        "news_source"    : str(news_source)[:50],
        "news_category"  : str(news_category)[:50],
    })


def event_export_download(export_type: str, tab_name: str) -> None:
    """내보내기 실행 시 기록."""
    _mp("export_download", {
        "export_type" : export_type,
        "tab_name"    : tab_name,
    })


def event_pr_action(action_type: str, content_type: str = "") -> None:
    """PR 활용 관리 탭의 핵심 액션 기록."""
    _mp("pr_action", {
        "action_type"  : action_type,
        "content_type" : str(content_type)[:50],
    })


# ── 디버그 패널 (ga_debug_mode=1 에서만 표시) ─────────────
def show_debug_panel() -> None:
    """
    ?ga_debug_mode=1 접속 시 Streamlit 화면 상단에 GA4 MP 검증 결과를 표시합니다.
    - GA4 credentials 정상 여부
    - 테스트 이벤트 MP 검증 응답 (오류 메시지 포함)
    - DebugView가 동작하지 않는 환경에서 대체 진단 수단
    """
    if not _is_debug():
        return

    mid, sec = _cfg()

    with st.expander("🔧 GA4 디버그 패널 (ga_debug_mode=1)", expanded=True):
        st.caption("이 패널은 ?ga_debug_mode=1 접속 시에만 표시됩니다.")

        col1, col2 = st.columns(2)
        with col1:
            st.metric("Measurement ID", mid if mid else "❌ 미설정")
        with col2:
            st.metric("API Secret", "✅ 설정됨" if sec else "❌ 미설정")

        if not mid or not sec:
            st.error("GA4_MEASUREMENT_ID 또는 GA4_API_SECRET 이 설정되지 않았습니다.")
            return

        st.divider()
        if st.button("📡 MP 검증 이벤트 전송 (debug endpoint)"):
            payload = {
                "client_id": _client_id(),
                "events": [{
                    "name": "ga4_debug_test",
                    "params": {
                        "debug_mode"         : True,
                        "engagement_time_msec": 1,
                        "test_note"          : "analytics.py debug panel",
                    }
                }]
            }
            url = f"{_MP_DEBUG_ENDPOINT}?measurement_id={mid}&api_secret={sec}"
            try:
                resp = requests.post(url, json=payload, timeout=5)
                data = resp.json()
                if data.get("validationMessages"):
                    st.warning("⚠️ 검증 오류:")
                    for msg in data["validationMessages"]:
                        st.code(f"{msg.get('validationCode')}: {msg.get('description')}")
                else:
                    st.success("✅ MP 검증 성공! 이벤트 형식 이상 없음")
                    st.caption("→ GA4 실시간 보고서에서 'ga4_debug_test' 이벤트 확인 가능")
                with st.expander("원본 응답"):
                    st.json(data)
            except Exception as e:
                st.error(f"요청 실패: {e}")

        st.divider()
        st.info(
            "**DebugView '디버그 기기 0' 이유:**\n"
            "GA4 DebugView의 '기기' 카운터는 브라우저에서 gtag.js SDK가 직접 실행될 때만 증가합니다. "
            "Streamlit의 srcdoc iframe에서는 Streamlit Cloud 보안 정책으로 외부 스크립트 로딩이 제한될 수 있습니다.\n\n"
            "**대안:** GA4 > 보고서 > **실시간** 에서 dashboard_view, keyword_search 등 이벤트를 실시간 확인하세요."
        )
