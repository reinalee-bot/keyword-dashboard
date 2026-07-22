"""
7단계 단위 테스트 (22개)
- monitoring_review_store 핵심 로직
- monitoring_tab_helpers 필터/집계
- 운영 CSV 비접촉 (임시 디렉터리 사용)
"""
import os
import sys
import hashlib
import tempfile
import shutil
import unittest

# ── 경로 설정 ──────────────────────────────────────────
_BASE = os.path.dirname(__file__)
if _BASE not in sys.path:
    sys.path.insert(0, _BASE)

# monitoring_review_store를 임시 디렉터리로 격리
import monitoring_review_store as mrs


def _tmp_reviews_csv(tmp_dir: str) -> str:
    return os.path.join(tmp_dir, "monitoring_reviews.csv")


def _patch_csv(tmp_dir: str):
    """mrs.REVIEWS_CSV를 임시 경로로 교체한다."""
    mrs.REVIEWS_CSV = _tmp_reviews_csv(tmp_dir)


# ══════════════════════════════════════════════════════
# 1~2  article_id 일관성
# ══════════════════════════════════════════════════════
class TestArticleId(unittest.TestCase):

    def test_01_same_url_same_id(self):
        """동일 URL → 동일 article_id"""
        url = "https://example.com/news/123"
        id1 = mrs.make_article_id(url)
        id2 = mrs.make_article_id(url)
        self.assertEqual(id1, id2)

    def test_02_different_url_different_id(self):
        """다른 URL → 다른 article_id"""
        id1 = mrs.make_article_id("https://example.com/a")
        id2 = mrs.make_article_id("https://example.com/b")
        self.assertNotEqual(id1, id2)

    def test_02b_no_url_fallback(self):
        """URL 없을 때 제목+매체+날짜 조합으로 MD5 생성"""
        aid = mrs.make_article_id("", "테스트 기사", "한겨레", "2026-07-22")
        expected = hashlib.md5("테스트 기사|한겨레|2026-07-22".encode("utf-8")).hexdigest()
        self.assertEqual(aid, expected)


# ══════════════════════════════════════════════════════
# 3~12  save_review / load_reviews
# ══════════════════════════════════════════════════════
class TestSaveLoad(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _patch_csv(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _base_data(self, status="검토 전", usage="", follow="", memo=""):
        url = "https://example.com/news/test"
        aid = mrs.make_article_id(url)
        return {
            "article_id": aid,
            "title": "테스트 기사",
            "url": url,
            "media": "테스트매체",
            "published_at": "2026-07-22",
            "review_status": status,
            "usage_type": usage,
            "follow_up_required": follow,
            "reviewer_memo": memo,
        }

    def test_03_new_review_save(self):
        """신규 저장 성공"""
        ok, err = mrs.save_review(self._base_data())
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_04_upsert_no_duplicate(self):
        """같은 article_id 재저장 시 행이 1개만 존재"""
        data = self._base_data(status="관심 기사")
        mrs.save_review(data)
        data["review_status"] = "PR 후보"
        mrs.save_review(data)
        reviews = mrs.load_reviews()
        self.assertEqual(len(reviews), 1)
        self.assertEqual(list(reviews.values())[0]["review_status"], "PR 후보")

    def test_05_load_saved_review(self):
        """저장 후 load_reviews에서 반환"""
        data = self._base_data(status="관심 기사")
        mrs.save_review(data)
        reviews = mrs.load_reviews()
        self.assertIn(data["article_id"], reviews)

    def test_06_status_검토전(self):
        """'검토 전' 상태 저장 가능"""
        ok, _ = mrs.save_review(self._base_data(status="검토 전"))
        self.assertTrue(ok)

    def test_07_status_관심기사(self):
        """'관심 기사' 상태 저장 가능"""
        ok, _ = mrs.save_review(self._base_data(status="관심 기사"))
        self.assertTrue(ok)

    def test_08_status_PR후보(self):
        """'PR 후보' 상태 저장 가능"""
        ok, _ = mrs.save_review(self._base_data(status="PR 후보"))
        self.assertTrue(ok)

    def test_09_status_제외(self):
        """'제외' 상태 저장 가능"""
        ok, _ = mrs.save_review(self._base_data(status="제외"))
        self.assertTrue(ok)

    def test_10_pr_usage_type_saved(self):
        """PR 후보 + 활용 형태 저장"""
        data = self._base_data(status="PR 후보", usage="기획기사")
        mrs.save_review(data)
        rv = mrs.load_reviews()[data["article_id"]]
        self.assertEqual(rv["usage_type"], "기획기사")

    def test_11_follow_up_saved(self):
        """후속 확인 사항 저장"""
        data = self._base_data(status="PR 후보", follow="현업 인터뷰 필요")
        mrs.save_review(data)
        rv = mrs.load_reviews()[data["article_id"]]
        self.assertEqual(rv["follow_up_required"], "현업 인터뷰 필요")

    def test_12_empty_memo_no_crash(self):
        """메모 빈 문자열로 저장 — 예외 없음"""
        data = self._base_data(memo="")
        ok, err = mrs.save_review(data)
        self.assertTrue(ok)
        self.assertEqual(err, "")

    def test_13_missing_optional_fields_default(self):
        """선택 필드 누락 시 기본값(빈 문자열) 처리"""
        minimal = {
            "article_id": mrs.make_article_id("https://example.com/min"),
            "review_status": "검토 전",
        }
        ok, _ = mrs.save_review(minimal)
        self.assertTrue(ok)
        rv = mrs.load_reviews()[minimal["article_id"]]
        self.assertEqual(rv.get("reviewer_memo", ""), "")

    def test_21_invalid_article_id_returns_false(self):
        """article_id 없는 데이터 → 실패 반환, 예외 미발생"""
        ok, err = mrs.save_review({"review_status": "검토 전"})
        self.assertFalse(ok)
        self.assertIn("article_id", err)

    def test_22_existing_review_default_values(self):
        """기존 저장 데이터 로드 시 widget 기본값 복원 가능"""
        data = self._base_data(status="PR 후보", usage="보도자료", memo="확인 필요")
        mrs.save_review(data)
        loaded = mrs.load_reviews()
        rv = loaded[data["article_id"]]
        self.assertEqual(rv["review_status"], "PR 후보")
        self.assertEqual(rv["usage_type"], "보도자료")
        self.assertEqual(rv["reviewer_memo"], "확인 필요")


# ══════════════════════════════════════════════════════
# 14~15  count_by_review_status / 검토완료
# ══════════════════════════════════════════════════════
class TestCountByStatus(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _patch_csv(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _save(self, url_suffix, status):
        aid = mrs.make_article_id(f"https://example.com/{url_suffix}")
        mrs.save_review({"article_id": aid, "review_status": status})

    def test_14_count_by_review_status(self):
        """상태별 건수 집계"""
        self._save("a", "관심 기사")
        self._save("b", "PR 후보")
        self._save("c", "PR 후보")
        self._save("d", "제외")
        reviews = mrs.load_reviews()
        counts = mrs.count_by_review_status(reviews)
        self.assertEqual(counts.get("관심 기사", 0), 1)
        self.assertEqual(counts.get("PR 후보", 0), 2)
        self.assertEqual(counts.get("제외", 0), 1)

    def test_15_검토완료_count(self):
        """count_review_summary에서 검토완료 = 관심+PR후보+제외"""
        from monitoring_tab_helpers import count_review_summary
        articles = [
            {"url": "https://example.com/a", "title": "A", "media_name": "", "pub_date": ""},
            {"url": "https://example.com/b", "title": "B", "media_name": "", "pub_date": ""},
            {"url": "https://example.com/c", "title": "C", "media_name": "", "pub_date": ""},
            {"url": "https://example.com/d", "title": "D", "media_name": "", "pub_date": ""},
        ]
        self._save("a", "관심 기사")
        self._save("b", "PR 후보")
        self._save("d", "제외")
        reviews = mrs.load_reviews()
        summary = count_review_summary(articles, reviews)
        self.assertEqual(summary["전체"], 4)
        self.assertEqual(summary["검토완료"], 3)
        self.assertEqual(summary["검토 전"], 1)


# ══════════════════════════════════════════════════════
# 16~20  apply_review_filter 및 복합 필터
# ══════════════════════════════════════════════════════
class TestApplyReviewFilter(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        _patch_csv(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_art(self, url, cat="기타", risk=False):
        return {
            "url": url, "title": f"기사 {url}", "media_name": "매체",
            "pub_date": "2026-07-22",
            "_monitoring_category": cat,
            "_is_risk_priority": risk,
        }

    def _save_status(self, url, status):
        aid = mrs.make_article_id(url)
        mrs.save_review({"article_id": aid, "review_status": status})

    def test_16_apply_review_filter_전체(self):
        """'전체' 필터는 모든 기사 통과"""
        from monitoring_tab_helpers import apply_review_filter
        arts = [self._make_art(f"https://example.com/{i}") for i in range(3)]
        ranked = [(i + 1, a) for i, a in enumerate(arts)]
        result = apply_review_filter(ranked, "전체", {})
        self.assertEqual(len(result), 3)

    def test_16b_apply_review_filter_pr후보(self):
        """'PR 후보' 필터는 해당 상태 기사만 반환"""
        from monitoring_tab_helpers import apply_review_filter
        arts = [self._make_art(f"https://example.com/{i}") for i in range(3)]
        self._save_status("https://example.com/1", "PR 후보")
        reviews = mrs.load_reviews()
        ranked = [(i + 1, a) for i, a in enumerate(arts)]
        result = apply_review_filter(ranked, "PR 후보", reviews)
        self.assertEqual(len(result), 1)

    def test_17_category_and_review_filter(self):
        """카테고리 필터 + 검토 상태 필터 조합"""
        from monitoring_tab_helpers import apply_category_filter, apply_review_filter
        arts = [
            self._make_art("https://example.com/a", cat="리스크"),
            self._make_art("https://example.com/b", cat="기술"),
            self._make_art("https://example.com/c", cat="리스크"),
        ]
        self._save_status("https://example.com/a", "관심 기사")
        reviews = mrs.load_reviews()
        ranked = apply_category_filter(arts, "리스크")
        result = apply_review_filter(ranked, "관심 기사", reviews)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["url"], "https://example.com/a")

    def test_18_urgency_and_review_filter(self):
        """긴급 리스크 필터 + 검토 상태 필터 조합"""
        from monitoring_tab_helpers import apply_urgency_filter, apply_review_filter
        arts = [
            self._make_art("https://example.com/r1", risk=True),
            self._make_art("https://example.com/r2", risk=True),
            self._make_art("https://example.com/n1", risk=False),
        ]
        self._save_status("https://example.com/r1", "PR 후보")
        reviews = mrs.load_reviews()
        ranked = [(i + 1, a) for i, a in enumerate(arts)]
        ranked = apply_urgency_filter(ranked, risk_only=True)
        result = apply_review_filter(ranked, "PR 후보", reviews)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1]["url"], "https://example.com/r1")

    def test_19_filter_zero_results(self):
        """조건에 맞는 기사 0건"""
        from monitoring_tab_helpers import apply_review_filter
        arts = [self._make_art("https://example.com/x")]
        ranked = [(1, arts[0])]
        result = apply_review_filter(ranked, "PR 후보", {})
        self.assertEqual(len(result), 0)

    def test_20_scores_unchanged_after_save(self):
        """저장 전후 기사 점수 필드 변경 없음"""
        from monitoring_tab_helpers import apply_review_filter
        art = {
            "url": "https://example.com/score",
            "title": "점수 기사",
            "media_name": "",
            "pub_date": "2026-07-22",
            "score": 85,
            "_pr_value_score": 90,
            "_relevance_score": 75,
        }
        ranked_before = [(1, dict(art))]
        self._save_status("https://example.com/score", "관심 기사")
        reviews = mrs.load_reviews()
        result = apply_review_filter(ranked_before, "전체", reviews)
        self.assertEqual(result[0][1]["score"], 85)
        self.assertEqual(result[0][1]["_pr_value_score"], 90)
        self.assertEqual(result[0][1]["_relevance_score"], 75)


if __name__ == "__main__":
    unittest.main(verbosity=2)
