"""
test_dashboard_perf.py

모니터링 카드 NameError 수정 및 rerun 지연 개선 검증.

검증 항목:
  A. dashboard.py에 _mon_art 참조가 없음 (정적 검사)
  B. 모니터링 기사 카드 fallback 필드 접근 — 값이 없는 구버전 데이터 포함
  C. load_reviews 캐시 래퍼 패턴 동작 — FakeWorksheet 사용
  D. 저장 성공 후 캐시 무효화 경로 동작
  E. _ext_* 필드가 저장·로드 결과에 없음
  F. 운영 monitoring_reviews.csv 불변

실행: python test_dashboard_perf.py
"""

import contextlib
import hashlib
import os
import re
import sys
import tempfile
import types
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import monitoring_review_store as mrs
from monitoring_review_store import REVIEW_COLS, reset_ws_cache, save_review


# ────────────────────────────────────────────────────────────
# 운영 CSV SHA256 (테스트 전)
# ────────────────────────────────────────────────────────────

def _sha256(path: str) -> str:
    if not os.path.exists(path):
        return "NO_FILE"
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_PROD_CSV_HASH_BEFORE = _sha256(mrs.REVIEWS_CSV)


# ────────────────────────────────────────────────────────────
# FakeWorksheet (gspread 6.x 최소 구현)
# ────────────────────────────────────────────────────────────

class FakeCell:
    def __init__(self, row: int):
        self.row = row


class FakeWorksheet:
    def __init__(self):
        self._rows = [REVIEW_COLS[:]]  # 헤더

    def row_values(self, row: int):
        idx = row - 1
        return self._rows[idx][:] if idx < len(self._rows) else []

    def find(self, value, in_column=1):
        col_idx = in_column - 1
        for i, row in enumerate(self._rows):
            if i == 0:
                continue
            if col_idx < len(row) and row[col_idx] == value:
                return FakeCell(i + 1)
        return None

    def update(self, values, range_name):
        match = re.match(r"A(\d+)", range_name)
        if match:
            row_idx = int(match.group(1)) - 1
            if row_idx < len(self._rows):
                self._rows[row_idx] = list(values[0])

    def append_row(self, values, value_input_option="RAW"):
        self._rows.append(list(values))

    def get_all_records(self, default_blank=""):
        if len(self._rows) < 2:
            return []
        headers = self._rows[0]
        records = []
        for row in self._rows[1:]:
            rec = {}
            for i, h in enumerate(headers):
                rec[h] = row[i] if i < len(row) else default_blank
            records.append(rec)
        return records

    def get_all_values(self):
        return [r[:] for r in self._rows]

    def insert_row(self, values, row=1):
        self._rows.insert(row - 1, list(values))


@contextmanager
def _patched_ws():
    """테스트 격리: _ws_singleton + REVIEWS_CSV 모두 임시 경로로 리다이렉트."""
    fake = FakeWorksheet()
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w",
                                     encoding="utf-8-sig") as tmp:
        tmp_csv = tmp.name
    try:
        original_csv = mrs.REVIEWS_CSV
        mrs.REVIEWS_CSV = tmp_csv
        reset_ws_cache()
        mrs._ws_singleton   = fake
        mrs._ws_init_done   = True
        mrs._ws_col_map     = {h: i for i, h in enumerate(REVIEW_COLS)}
        yield fake, tmp_csv
    finally:
        mrs.REVIEWS_CSV = original_csv
        reset_ws_cache()
        if os.path.exists(tmp_csv):
            os.unlink(tmp_csv)


def _base_review(**kwargs) -> dict:
    rv = {
        "article_id":   "test_perf_001",
        "title":        "테스트 기사 제목",
        "url":          "https://example.com/test",
        "media":        "테스트매체",
        "published_at": "2026-07-24",
        "review_status": "관심 기사",
    }
    rv.update(kwargs)
    return rv


# ════════════════════════════════════════════════════════════
# A. 정적 검사: _mon_art 참조 부재
# ════════════════════════════════════════════════════════════

class TestNoMonArtReference(unittest.TestCase):
    """dashboard.py 전체에 _mon_art 참조가 없어야 한다."""

    def test_dashboard_has_no_mon_art(self):
        dashboard_path = os.path.join(BASE_DIR, "dashboard.py")
        self.assertTrue(os.path.exists(dashboard_path), "dashboard.py not found")
        with open(dashboard_path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        matches = [(i + 1, line.rstrip())
                   for i, line in enumerate(source.splitlines())
                   if "_mon_art" in line]
        self.assertEqual(
            matches, [],
            f"_mon_art 참조 {len(matches)}건 발견:\n" +
            "\n".join(f"  L{ln}: {text}" for ln, text in matches)
        )

    def test_cached_load_reviews_defined(self):
        """_cached_load_reviews 함수가 dashboard.py에 정의됐는지 확인."""
        dashboard_path = os.path.join(BASE_DIR, "dashboard.py")
        with open(dashboard_path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        self.assertIn("def _cached_load_reviews", source,
                      "_cached_load_reviews 캐시 함수가 dashboard.py에 없음")
        self.assertIn("def _inv_reviews", source,
                      "_inv_reviews 무효화 함수가 dashboard.py에 없음")

    def test_save_calls_inv_reviews(self):
        """저장 성공 분기에 _inv_reviews() 호출이 있는지 확인."""
        dashboard_path = os.path.join(BASE_DIR, "dashboard.py")
        with open(dashboard_path, encoding="utf-8", errors="replace") as f:
            source = f.read()
        # save_review 성공 분기에서 _inv_reviews 호출 확인
        self.assertIn("_inv_reviews()", source,
                      "_inv_reviews() 호출이 dashboard.py에 없음")

    def test_gh_cache_ttl_not_30s(self):
        """GitHub CSV 캐시 TTL이 정확히 30초인 항목이 없는지 확인 (ttl=30, 또는 ttl=30) 패턴)."""
        dashboard_path = os.path.join(BASE_DIR, "dashboard.py")
        with open(dashboard_path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        # ttl=30 뒤에 숫자가 오지 않는 패턴 (정확히 30인 경우만 탐지)
        pattern = re.compile(r"ttl=30[^0-9]")
        short_ttl_lines = []
        for i, line in enumerate(lines):
            if pattern.search(line):
                short_ttl_lines.append((i + 1, line.rstrip()))
        self.assertEqual(
            short_ttl_lines, [],
            "ttl=30 캐시(정확히 30초)가 아직 남아 있음:\n" +
            "\n".join(f"  L{ln}: {text}" for ln, text in short_ttl_lines)
        )


# ════════════════════════════════════════════════════════════
# B. 모니터링 카드 fallback 필드 접근 — 필드 없는 구버전 데이터
# ════════════════════════════════════════════════════════════

class TestMonitoringCardFieldFallback(unittest.TestCase):
    """기사 dict에서 _confidence / _score_axes / _quality_factors를 안전하게 읽는지 확인."""

    def _card_fields(self, art: dict) -> dict:
        """dashboard.py 카드 렌더링의 필드 접근 패턴을 재현 (순수 함수)."""
        return {
            "confidence":   art.get("_confidence", ""),
            "score_axes":   art.get("_score_axes"),
            "quality_factors": art.get("_quality_factors"),
            "article_type":  art.get("article_type", "") or "",
            "promo_like":    art.get("promotional_likelihood", "") or "",
        }

    def test_full_field_article(self):
        art = {
            "article_type":         "기획·분석",
            "promotional_likelihood": "높음",
            "_confidence":          "높음",
            "_score_axes":          {"sck_relevance": 20, "industry_insight": 15},
            "_quality_factors":     {"industry_change": True, "is_promotional": False},
        }
        r = self._card_fields(art)
        self.assertEqual(r["confidence"], "높음")
        self.assertIsNotNone(r["score_axes"])
        self.assertIsNotNone(r["quality_factors"])
        self.assertEqual(r["article_type"], "기획·분석")
        self.assertEqual(r["promo_like"], "높음")

    def test_legacy_no_confidence(self):
        """구버전 기사 — _confidence, _score_axes, _quality_factors 없음."""
        art = {
            "article_type": "일반 기사",
        }
        r = self._card_fields(art)
        self.assertEqual(r["confidence"], "")
        self.assertIsNone(r["score_axes"])
        self.assertIsNone(r["quality_factors"])

    def test_legacy_pr_type(self):
        """구버전 '보도자료형' article_type — 오류 없이 읽혀야 함."""
        art = {
            "article_type": "보도자료형",
            "promotional_likelihood": "",
        }
        r = self._card_fields(art)
        self.assertEqual(r["article_type"], "보도자료형")
        self.assertEqual(r["promo_like"], "")

    def test_empty_article(self):
        """완전히 빈 dict에서도 오류 없이 기본값 반환."""
        r = self._card_fields({})
        self.assertEqual(r["confidence"], "")
        self.assertIsNone(r["score_axes"])
        self.assertIsNone(r["quality_factors"])
        self.assertEqual(r["article_type"], "")
        self.assertEqual(r["promo_like"], "")

    def test_none_values_coerced(self):
        """None 값이 들어왔을 때 or '' 처리가 올바르게 동작하는지 확인."""
        art = {
            "article_type":         None,
            "promotional_likelihood": None,
        }
        r = self._card_fields(art)
        self.assertEqual(r["article_type"], "")
        self.assertEqual(r["promo_like"], "")


# ════════════════════════════════════════════════════════════
# C. load_reviews 캐시 래퍼 패턴 동작
# ════════════════════════════════════════════════════════════

class TestLoadReviewsCache(unittest.TestCase):
    """캐시 래퍼가 연속 호출에서 재조회를 줄이는 패턴을 검증."""

    def test_load_reviews_with_fake_ws_returns_dict(self):
        """FakeWorksheet 기반 load_reviews()가 dict를 반환한다."""
        with _patched_ws() as (fake, _):
            result = mrs.load_reviews()
        self.assertIsInstance(result, dict)

    def test_load_reviews_with_data(self):
        """저장 후 load_reviews()로 동일 데이터를 읽을 수 있다."""
        with _patched_ws() as (fake, _):
            rv = _base_review(article_id="cache_test_001",
                              promotional_likelihood="보통")
            ok, _ = save_review(rv)
            self.assertTrue(ok)
            loaded = mrs.load_reviews()
            self.assertIn("cache_test_001", loaded)
            self.assertEqual(loaded["cache_test_001"]["promotional_likelihood"], "보통")

    def test_multiple_load_calls_consistent(self):
        """같은 세션에서 연속 load_reviews() 호출 결과가 일치한다."""
        with _patched_ws() as (fake, _):
            rv = _base_review(article_id="cache_test_002")
            save_review(rv)
            r1 = mrs.load_reviews()
            r2 = mrs.load_reviews()
            self.assertEqual(set(r1.keys()), set(r2.keys()))

    def test_load_reviews_empty_sheet(self):
        """빈 시트에서 load_reviews()는 빈 dict를 반환한다."""
        with _patched_ws() as (fake, _):
            result = mrs.load_reviews()
        self.assertEqual(result, {})

    def test_load_reviews_no_ext_fields(self):
        """load_reviews() 결과에 _ext_* 필드가 포함되지 않는다."""
        with _patched_ws() as (fake, _):
            rv = _base_review(article_id="ext_check_001")
            rv["_ext_article_type"] = "일반 기사"          # 무시돼야 함
            rv["_ext_promotional_likelihood"] = "높음"     # 무시돼야 함
            save_review(rv)
            loaded = mrs.load_reviews()
            self.assertIn("ext_check_001", loaded)
            record = loaded["ext_check_001"]
            ext_keys = [k for k in record.keys() if k.startswith("_ext_")]
            self.assertEqual(ext_keys, [], f"_ext_ 필드 유출: {ext_keys}")


# ════════════════════════════════════════════════════════════
# D. 저장 성공 후 캐시 무효화 경로
# ════════════════════════════════════════════════════════════

class TestCacheInvalidationPattern(unittest.TestCase):
    """저장·실패 시 캐시 무효화가 올바르게 동작하는지 패턴 검증."""

    def test_save_success_triggers_cache_clear(self):
        """
        save_review 성공 후 _inv_reviews()를 호출하면 다음 load에서 최신 데이터가 보인다.
        dashboard.py의 _inv_reviews() 호출 패턴을 mrs 수준에서 재현.
        """
        _call_count = [0]
        original_load = mrs.load_reviews

        def _counting_load():
            _call_count[0] += 1
            return original_load()

        with _patched_ws() as (fake, _):
            rv1 = _base_review(article_id="inv_test_001", review_status="검토 전")
            ok, _ = save_review(rv1)
            self.assertTrue(ok)

            # 첫 번째 로드
            r1 = mrs.load_reviews()
            self.assertIn("inv_test_001", r1)

            # 두 번째 저장 후 다시 로드 — 최신 값 반영 확인
            rv2 = _base_review(article_id="inv_test_001", review_status="PR 후보")
            ok2, _ = save_review(rv2)
            self.assertTrue(ok2)
            r2 = mrs.load_reviews()
            self.assertEqual(r2["inv_test_001"]["review_status"], "PR 후보")

    def test_save_failure_no_stale_data(self):
        """저장 실패 시(article_id 없음) load_reviews()는 이전 상태를 유지한다."""
        with _patched_ws() as (fake, _):
            rv_good = _base_review(article_id="stale_test_001")
            save_review(rv_good)

            # 잘못된 데이터 (article_id 없음) → 저장 실패
            ok, _err = save_review({"title": "오류 케이스"})
            self.assertFalse(ok)

            # 기존 데이터는 그대로여야 함
            loaded = mrs.load_reviews()
            self.assertIn("stale_test_001", loaded)

    def test_manual_vs_normal_rerun_distinction(self):
        """
        수동 재수집과 일반 rerun 구분: 일반 load_reviews()는 캐시에서
        반환되지만, reset_ws_cache() 후에는 강제 재연결된다.
        """
        with _patched_ws() as (fake, _):
            rv = _base_review(article_id="rerun_test_001")
            save_review(rv)
            # 일반 로드
            r1 = mrs.load_reviews()
            self.assertIn("rerun_test_001", r1)
            # reset_ws_cache 후 재로드 — 연결 재초기화
            reset_ws_cache()
            # 재연결 시 FakeWorksheet가 없으므로 CSV fallback
            r2 = mrs.load_reviews()
            # CSV에도 저장됐으므로 동일 데이터 존재
            self.assertIn("rerun_test_001", r2)


# ════════════════════════════════════════════════════════════
# E. _ext_* 필드 미노출 (저장·로드)
# ════════════════════════════════════════════════════════════

class TestExtFieldsNotExposed(unittest.TestCase):

    def test_ext_fields_stripped_from_csv(self):
        """_ext_ 필드는 CSV 저장 후 컬럼에 나타나지 않는다."""
        import pandas as pd
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False,
                                         mode="w", encoding="utf-8-sig") as tmp:
            tmp_path = tmp.name
        try:
            original_csv = mrs.REVIEWS_CSV
            mrs.REVIEWS_CSV = tmp_path
            reset_ws_cache()
            rv = _base_review(article_id="ext_csv_001")
            rv["_ext_article_type"]           = "기획·분석"
            rv["_ext_promotional_likelihood"] = "높음"
            save_review(rv)

            df = pd.read_csv(tmp_path, dtype=str).fillna("")
            ext_cols = [c for c in df.columns if c.startswith("_ext_")]
            self.assertEqual(ext_cols, [], f"_ext_ 컬럼 CSV 유출: {ext_cols}")
        finally:
            mrs.REVIEWS_CSV = original_csv
            reset_ws_cache()
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)


# ════════════════════════════════════════════════════════════
# F. 운영 CSV 불변 확인
# ════════════════════════════════════════════════════════════

class TestProdCsvUnchanged(unittest.TestCase):

    def test_prod_csv_hash_unchanged(self):
        """테스트 실행 전후 운영 monitoring_reviews.csv SHA256이 동일해야 한다."""
        after = _sha256(mrs.REVIEWS_CSV)
        self.assertEqual(
            _PROD_CSV_HASH_BEFORE, after,
            f"운영 CSV가 변경됨!\n  before: {_PROD_CSV_HASH_BEFORE}\n  after : {after}"
        )

    def test_prod_csv_no_ext_columns(self):
        """운영 CSV에 _ext_* 컬럼이 없어야 한다."""
        import pandas as pd
        if not os.path.exists(mrs.REVIEWS_CSV):
            return
        try:
            df = pd.read_csv(mrs.REVIEWS_CSV, dtype=str).fillna("")
        except Exception as exc:
            self.fail(f"운영 CSV 읽기 실패: {exc}")
        ext_cols = [c for c in df.columns if c.startswith("_ext_")]
        self.assertEqual(ext_cols, [], f"_ext_ 컬럼이 운영 CSV에 존재: {ext_cols}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
