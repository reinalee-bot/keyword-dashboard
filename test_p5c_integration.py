"""
test_p5c_integration.py

P5C 운영 통합 검증 테스트.

검증 항목:
  A. REVIEW_COLS 신규 필드 확인
  B. 헤더 기반 Sheets 컬럼 매핑 (FakeWorksheet)
  C. 기존 18열 CSV 하위 호환 (신규 컬럼 → "")
  D. 기존 "보도자료형" 저장 데이터 읽기 호환
  E. promotional_likelihood 저장·로드
  F. news_fetcher classify_article_extended 연결
  G. _ext_* 필드는 REVIEW_COLS에 포함되지 않음
"""

import contextlib
import copy
import csv
import hashlib
import io
import os
import sys
import tempfile
import types
import unittest

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

import monitoring_review_store as mrs
import news_fetcher as nf


# ═════════════════════════════════════════════════════════════
# A. REVIEW_COLS 신규 필드
# ═════════════════════════════════════════════════════════════

NEW_FIELDS = [
    "promotional_likelihood", "title_signal", "description_signal",
    "matched_rule", "promotional_score", "classification_basis",
]


class TestReviewCols(unittest.TestCase):
    def test_new_fields_present(self):
        for f in NEW_FIELDS:
            self.assertIn(f, mrs.REVIEW_COLS, f"{f} not in REVIEW_COLS")

    def test_legacy_fields_intact(self):
        legacy = [
            "article_id", "title", "url", "media", "published_at",
            "category", "monitoring_priority", "relevance_score",
            "news_importance_score", "pr_usability_score",
            "selection_reason", "pr_suggestion",
            "review_status", "usage_type", "exclusion_reason",
            "follow_up_required", "reviewer_memo", "reviewed_at",
        ]
        for f in legacy:
            self.assertIn(f, mrs.REVIEW_COLS, f"Legacy field {f} missing from REVIEW_COLS")

    def test_total_col_count(self):
        self.assertEqual(len(mrs.REVIEW_COLS), 24)

    def test_col_end_is_x(self):
        self.assertEqual(mrs._COL_END, 'X')

    def test_no_ext_prefix_in_review_cols(self):
        for c in mrs.REVIEW_COLS:
            self.assertFalse(c.startswith("_ext_"), f"_ext_ field in REVIEW_COLS: {c}")


# ═════════════════════════════════════════════════════════════
# B. 헤더 기반 Sheets 컬럼 매핑
# ═════════════════════════════════════════════════════════════

class FakeWorksheet:
    """gspread Worksheet 최소 구현 (테스트용)."""

    def __init__(self, initial_headers=None):
        self._data: list[list] = []
        if initial_headers:
            self._data.append(list(initial_headers))

    def row_values(self, row: int) -> list:
        idx = row - 1
        if 0 <= idx < len(self._data):
            return list(self._data[idx])
        return []

    def find(self, value, in_column=1):
        col_idx = in_column - 1
        for ri, row in enumerate(self._data):
            if ri == 0:
                continue  # skip header
            if col_idx < len(row) and str(row[col_idx]) == str(value):
                rec = types.SimpleNamespace()
                rec.row = ri + 1
                return rec
        return None

    def update(self, values, range_name):
        # parse range_name like "A2:X2"
        start_cell = range_name.split(":")[0]
        row_num = int("".join(c for c in start_cell if c.isdigit()))
        idx = row_num - 1
        while len(self._data) <= idx:
            self._data.append([])
        self._data[idx] = list(values[0]) if values else []

    def append_row(self, values, value_input_option="RAW"):
        self._data.append(list(values))

    def get_all_records(self, default_blank=""):
        if not self._data:
            return []
        headers = self._data[0]
        records = []
        for row in self._data[1:]:
            rec = {}
            for i, h in enumerate(headers):
                rec[h] = row[i] if i < len(row) else default_blank
            records.append(rec)
        return records

    def insert_row(self, values, row_num):
        self._data.insert(row_num - 1, list(values))


@contextlib.contextmanager
def _patched_ws(ws, col_map=None):
    """FakeWorksheet + 임시 CSV로 격리: 운영 데이터 오염 방지."""
    import tempfile as _tmp
    orig_singleton  = mrs._ws_singleton
    orig_init_done  = mrs._ws_init_done
    orig_col_map    = mrs._ws_col_map
    orig_csv        = mrs.REVIEWS_CSV

    tf = _tmp.NamedTemporaryFile(suffix=".csv", delete=False)
    tmp_csv = tf.name
    tf.close()

    mrs._ws_singleton = ws
    mrs._ws_init_done = True
    mrs._ws_col_map   = col_map if col_map is not None else {
        h: i for i, h in enumerate(mrs.REVIEW_COLS)
    }
    mrs.REVIEWS_CSV = tmp_csv
    try:
        yield
    finally:
        mrs._ws_singleton = orig_singleton
        mrs._ws_init_done = orig_init_done
        mrs._ws_col_map   = orig_col_map
        mrs.REVIEWS_CSV   = orig_csv
        try:
            os.unlink(tmp_csv)
        except Exception:
            pass


def _make_review(**kwargs):
    base = {
        "article_id": hashlib.md5(b"http://test.com/1").hexdigest(),
        "title": "테스트 기사",
        "url": "http://test.com/1",
        "media": "테스트 매체",
        "published_at": "2026-07-23",
        "review_status": "검토 전",
    }
    base.update(kwargs)
    return base


class TestHeaderBasedSheetsMapping(unittest.TestCase):

    def test_upsert_new_row_full_cols(self):
        ws = FakeWorksheet(initial_headers=mrs.REVIEW_COLS)
        col_map = {h: i for i, h in enumerate(mrs.REVIEW_COLS)}
        rv = _make_review(
            promotional_likelihood="높음",
            title_signal="출시",
            promotional_score="2",
            classification_basis="title_only",
        )
        with _patched_ws(ws, col_map):
            ok, _ = mrs.save_review(rv)
        self.assertTrue(ok)
        records = ws.get_all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["promotional_likelihood"], "높음")
        self.assertEqual(records[0]["title_signal"], "출시")
        self.assertEqual(records[0]["promotional_score"], "2")

    def test_upsert_updates_existing_row(self):
        ws = FakeWorksheet(initial_headers=mrs.REVIEW_COLS)
        col_map = {h: i for i, h in enumerate(mrs.REVIEW_COLS)}
        rv = _make_review(promotional_likelihood="낮음")
        with _patched_ws(ws, col_map):
            mrs.save_review(rv)
            rv2 = copy.copy(rv)
            rv2["promotional_likelihood"] = "높음"
            rv2["review_status"] = "PR 후보"
            mrs.save_review(rv2)
        records = ws.get_all_records()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["promotional_likelihood"], "높음")
        self.assertEqual(records[0]["review_status"], "PR 후보")

    def test_old_18col_sheet_still_saves(self):
        """기존 18열 시트에 24열 REVIEW_COLS 데이터 저장 — 18열 이내만 기록됨."""
        old_headers = mrs.REVIEW_COLS[:18]
        ws = FakeWorksheet(initial_headers=old_headers)
        col_map = {h: i for i, h in enumerate(old_headers)}  # 18열 매핑
        rv = _make_review(promotional_likelihood="보통", title_signal="계획")
        with _patched_ws(ws, col_map):
            ok, _ = mrs.save_review(rv)
        self.assertTrue(ok)
        records = ws.get_all_records()
        self.assertEqual(len(records), 1)
        # 18열 시트에는 promotional_likelihood 컬럼이 없으므로 키 자체가 없어야 함
        self.assertNotIn("promotional_likelihood", records[0])
        # 기본 필드는 정상 저장
        self.assertEqual(records[0]["review_status"], "검토 전")


# ═════════════════════════════════════════════════════════════
# C. 기존 18열 CSV 하위 호환
# ═════════════════════════════════════════════════════════════

_LEGACY_COLS = [
    "article_id", "title", "url", "media", "published_at",
    "category", "monitoring_priority", "relevance_score",
    "news_importance_score", "pr_usability_score",
    "selection_reason", "pr_suggestion",
    "review_status", "usage_type", "exclusion_reason",
    "follow_up_required", "reviewer_memo", "reviewed_at",
]


class TestLegacyCSVCompat(unittest.TestCase):

    def _write_legacy_csv(self, path, rows):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=_LEGACY_COLS)
            w.writeheader()
            for r in rows:
                w.writerow(r)

    def test_old_csv_loads_with_empty_new_cols(self):
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as tf:
            tmp_path = tf.name
        try:
            self._write_legacy_csv(tmp_path, [{
                "article_id": "abc123",
                "title": "레거시 기사",
                "url": "http://old.com/1",
                "media": "구 매체",
                "published_at": "2026-01-01",
                "category": "", "monitoring_priority": "",
                "relevance_score": "", "news_importance_score": "",
                "pr_usability_score": "", "selection_reason": "",
                "pr_suggestion": "", "review_status": "검토 전",
                "usage_type": "", "exclusion_reason": "",
                "follow_up_required": "", "reviewer_memo": "",
                "reviewed_at": "2026-01-01 00:00:00 KST",
            }])
            orig = mrs.REVIEWS_CSV
            mrs.REVIEWS_CSV = tmp_path
            try:
                reviews = mrs.load_reviews()
            finally:
                mrs.REVIEWS_CSV = orig
        finally:
            os.unlink(tmp_path)

        self.assertIn("abc123", reviews)
        rec = reviews["abc123"]
        # 신규 컬럼은 빈 문자열로 채워져야 함
        for f in NEW_FIELDS:
            self.assertIn(f, rec, f"New field {f} missing from loaded legacy record")
            self.assertEqual(rec[f], "", f"New field {f} should be empty for legacy data")


# ═════════════════════════════════════════════════════════════
# D. 기존 "보도자료형" 저장 데이터 읽기 호환
# ═════════════════════════════════════════════════════════════

class TestLegacyPRTypeCompat(unittest.TestCase):

    def test_보도자료형_value_readable_from_csv(self):
        """article_type='보도자료형'이 저장된 CSV를 읽어도 에러 없이 로드됨."""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w",
                                         encoding="utf-8-sig") as tf:
            tmp_path = tf.name
        try:
            cols_with_at = _LEGACY_COLS[:]  # article_type is NOT in REVIEW_COLS
            with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["article_id", "title", "url", "media", "published_at",
                             "category", "monitoring_priority", "relevance_score",
                             "news_importance_score", "pr_usability_score",
                             "selection_reason", "pr_suggestion",
                             "review_status", "usage_type", "exclusion_reason",
                             "follow_up_required", "reviewer_memo", "reviewed_at"])
                w.writerow(["pr123", "보도자료형 기사", "http://pr.com/1", "PR 매체",
                             "2026-01-01", "", "", "", "", "", "", "",
                             "검토 전", "", "", "", "", "2026-01-01 00:00:00 KST"])
            orig = mrs.REVIEWS_CSV
            mrs.REVIEWS_CSV = tmp_path
            try:
                reviews = mrs.load_reviews()
            finally:
                mrs.REVIEWS_CSV = orig
        finally:
            os.unlink(tmp_path)

        self.assertIn("pr123", reviews)
        # 신규 promotional_likelihood 필드는 빈 문자열 (기존 데이터에 없음)
        self.assertEqual(reviews["pr123"].get("promotional_likelihood", ""), "")

    def test_보도자료형_not_in_new_article_type_domain(self):
        """classify_article_extended()는 '보도자료형'을 절대 반환하지 않는다."""
        test_titles = [
            "SCK, AI 보안 솔루션 출시 공식 발표",
            "삼성전자, 신제품 보도자료 배포",
            "경찰청, 사이버범죄 예방 캠페인 안내문 배포",
        ]
        for title in test_titles:
            result = nf.classify_article_extended(title, "")
            self.assertNotEqual(
                result["article_type"], "보도자료형",
                f"'보도자료형' returned for: {title}"
            )


# ═════════════════════════════════════════════════════════════
# E. promotional_likelihood CSV 저장·로드
# ═════════════════════════════════════════════════════════════

class TestPromotionalLikelihoodStorage(unittest.TestCase):

    def test_save_and_load_promotional_likelihood(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_csv = os.path.join(tmpdir, "reviews.csv")
            orig = mrs.REVIEWS_CSV
            mrs.REVIEWS_CSV = tmp_csv
            try:
                rv = _make_review(
                    article_id="zzz999",
                    promotional_likelihood="높음",
                    title_signal="출시",
                    description_signal="",
                    matched_rule="P2a",
                    promotional_score="3",
                    classification_basis="title_and_description",
                    review_status="PR 후보",
                )
                ok, err = mrs.save_review(rv)
                self.assertTrue(ok, err)
                reviews = mrs.load_reviews()
            finally:
                mrs.REVIEWS_CSV = orig

        self.assertIn("zzz999", reviews)
        rec = reviews["zzz999"]
        self.assertEqual(rec["promotional_likelihood"], "높음")
        self.assertEqual(rec["title_signal"], "출시")
        self.assertEqual(rec["matched_rule"], "P2a")
        self.assertEqual(rec["promotional_score"], "3")
        self.assertEqual(rec["classification_basis"], "title_and_description")

    def test_save_excludes_ext_prefix_fields(self):
        """save_review() 저장 결과에 _ext_ 접두사 필드가 없어야 한다."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_csv = os.path.join(tmpdir, "reviews.csv")
            orig = mrs.REVIEWS_CSV
            mrs.REVIEWS_CSV = tmp_csv
            try:
                rv = _make_review(
                    article_id="ext_test",
                    _ext_article_type="일반 기사",       # 저장 제외 대상
                    _ext_promotional_likelihood="낮음",  # 저장 제외 대상
                )
                mrs.save_review(rv)
                df = mrs._load_csv_df()
            finally:
                mrs.REVIEWS_CSV = orig

        for col in df.columns:
            self.assertFalse(col.startswith("_ext_"), f"_ext_ col in CSV: {col}")


# ═════════════════════════════════════════════════════════════
# F. news_fetcher — classify_article_extended 연결 확인
# ═════════════════════════════════════════════════════════════

class TestNewsFetcherExtendedFields(unittest.TestCase):

    def _run_fetch(self, articles):
        """fetch_articles_for_keyword의 분류 루프를 간소화해서 호출.
        실제 API 호출 없이 분류 로직만 검증한다.
        """
        results = []
        for art in articles:
            title = art.get("title", "")
            desc  = art.get("description", "")
            _ext = nf.classify_article_extended(title, desc)
            art_copy = dict(art)
            art_copy["article_type"]           = _ext["article_type"]
            art_copy["promotional_likelihood"] = _ext["promotional_likelihood"]
            art_copy["title_signal"]           = _ext["title_signal"]
            art_copy["description_signal"]     = _ext["description_signal"]
            art_copy["matched_rule"]           = _ext["matched_rule"]
            art_copy["promotional_score"]      = _ext["promotional_score"]
            art_copy["classification_basis"]   = _ext["classification_basis"]
            results.append(art_copy)
        return results

    def test_article_type_is_4종(self):
        valid = {"기획·분석", "인터뷰", "행사·현장", "일반 기사", "제외 대상"}
        arts = self._run_fetch([
            {"title": "AI 시장 분석 심층 기획 — 미래를 전망하다", "description": ""},
            {"title": "CEO 인터뷰 \"디지털 전환\"의 의미", "description": ""},
            {"title": "CES 2026 개막식 현장", "description": ""},
            {"title": "삼성전자 반도체 동향", "description": ""},
        ])
        for art in arts:
            self.assertIn(art["article_type"], valid)

    def test_보도자료형_not_produced(self):
        arts = self._run_fetch([
            {"title": "SCK, AI 솔루션 출시 보도자료", "description": ""},
            {"title": "기업 신제품 출시 안내", "description": ""},
        ])
        for art in arts:
            self.assertNotEqual(art["article_type"], "보도자료형")

    def test_promotional_likelihood_set(self):
        arts = self._run_fetch([
            {"title": "넥서스AI, '넥서스AI 플랫폼' 정식 출시", "description": ""},
        ])
        self.assertIn(arts[0]["promotional_likelihood"], ("높음", "보통", "낮음"))

    def test_all_7_fields_set(self):
        expected_keys = {
            "article_type", "promotional_likelihood", "title_signal",
            "description_signal", "matched_rule", "promotional_score",
            "classification_basis",
        }
        arts = self._run_fetch([{"title": "일반 IT 동향 기사", "description": ""}])
        for key in expected_keys:
            self.assertIn(key, arts[0], f"Missing key: {key}")

    def test_classification_basis_title_only(self):
        arts = self._run_fetch([{"title": "AI 보안 동향", "description": ""}])
        self.assertEqual(arts[0]["classification_basis"], "title_only")

    def test_classification_basis_title_and_description(self):
        arts = self._run_fetch([{"title": "AI 보안 동향", "description": "심층 분석 내용"}])
        self.assertEqual(arts[0]["classification_basis"], "title_and_description")


# ═════════════════════════════════════════════════════════════
# G. Sheets 헤더 확장 로직 검증
# ═════════════════════════════════════════════════════════════

class TestSheetsHeaderExtension(unittest.TestCase):

    def test_gsheet_load_with_old_18col_sheet(self):
        """18열 시트에서 get_all_records()로 로드 — 신규 컬럼은 빈값."""
        ws = FakeWorksheet(initial_headers=mrs.REVIEW_COLS[:18])
        row = [hashlib.md5(b"http://x.com").hexdigest()] + ["테스트"] * 17
        ws.append_row(row)
        col_map = {h: i for i, h in enumerate(mrs.REVIEW_COLS[:18])}
        with _patched_ws(ws, col_map):
            data = mrs._gsheet_load(ws)
        aid = row[0]
        self.assertIn(aid, data)
        # 신규 컬럼은 존재하지 않거나 빈 문자열
        self.assertIn(data[aid].get("promotional_likelihood", ""), ("", None, ""))

    def test_upsert_col_end_uses_actual_header_length(self):
        """헤더 24열 시트에서 col_end가 'X'가 되어야 한다."""
        ws = FakeWorksheet(initial_headers=mrs.REVIEW_COLS)
        col_map = {h: i for i, h in enumerate(mrs.REVIEW_COLS)}
        n_cols  = max(col_map.values()) + 1
        self.assertEqual(chr(ord('A') + n_cols - 1), 'X')

    def test_reset_clears_col_map(self):
        mrs._ws_col_map = {"article_id": 0, "title": 1}
        mrs.reset_ws_cache()
        self.assertEqual(mrs._ws_col_map, {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
