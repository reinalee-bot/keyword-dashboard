"""
Tab4 헬퍼 함수 단위 테스트 (Streamlit 의존 없음)
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

import monitoring as mon

from monitoring_tab_helpers import (
    apply_category_filter,
    apply_urgency_filter,
    count_by_category,
    make_widget_key,
    monitoring_config_version,
    sort_monitoring_articles,
    today_kst,
)


class TestTodayKst(unittest.TestCase):
    def test_format(self):
        result = today_kst()
        self.assertRegex(result, r"^\d{4}-\d{2}-\d{2}$")

    def test_is_string(self):
        self.assertIsInstance(today_kst(), str)


class TestMonitoringConfigVersion(unittest.TestCase):
    def test_stability(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"key: value\n")
            path = f.name
        try:
            v1 = monitoring_config_version(path)
            v2 = monitoring_config_version(path)
            self.assertEqual(v1, v2)
        finally:
            os.unlink(path)

    def test_missing_file_returns_default(self):
        result = monitoring_config_version("/nonexistent/path.yaml")
        self.assertEqual(result, "default")

    def test_hash_length(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f:
            f.write(b"test: 1\n")
            path = f.name
        try:
            result = monitoring_config_version(path)
            self.assertEqual(len(result), 8)
        finally:
            os.unlink(path)

    def test_different_content_different_hash(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f1:
            f1.write(b"version: 1\n")
            p1 = f1.name
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as f2:
            f2.write(b"version: 2\n")
            p2 = f2.name
        try:
            self.assertNotEqual(
                monitoring_config_version(p1),
                monitoring_config_version(p2),
            )
        finally:
            os.unlink(p1)
            os.unlink(p2)


def _make_article(url, category):
    return {"url": url, "_monitoring_category": category, "title": f"기사 {url}"}


class TestApplyCategoryFilter(unittest.TestCase):
    def setUp(self):
        self.articles = [
            _make_article("url1", "리스크"),
            _make_article("url2", "AI·AX 시장동향"),
            _make_article("url3", "주요 벤더"),
            _make_article("url4", "리스크"),
        ]

    def test_all_returns_all(self):
        result = apply_category_filter(self.articles, "전체")
        self.assertEqual(len(result), 4)

    def test_category_filter(self):
        result = apply_category_filter(self.articles, "리스크")
        self.assertEqual(len(result), 2)
        self.assertTrue(all(art.get("_monitoring_category") == "리스크"
                            for _, art in result))

    def test_global_rank_preserved_through_filter(self):
        result = apply_category_filter(self.articles, "리스크")
        ranks = [r for r, _ in result]
        # url1 is rank 1, url4 is rank 4 — both are 리스크
        self.assertIn(1, ranks)
        self.assertIn(4, ranks)

    def test_full_returns_tuples_with_rank(self):
        result = apply_category_filter(self.articles, "전체")
        for i, (rank, art) in enumerate(result):
            self.assertEqual(rank, i + 1)

    def test_empty_category_returns_empty(self):
        result = apply_category_filter(self.articles, "자사·관계사")
        self.assertEqual(result, [])

    def test_empty_articles(self):
        result = apply_category_filter([], "전체")
        self.assertEqual(result, [])


class TestCountByCategory(unittest.TestCase):
    def test_counts(self):
        articles = [
            _make_article("u1", "리스크"),
            _make_article("u2", "리스크"),
            _make_article("u3", "주요 벤더"),
        ]
        counts = count_by_category(articles)
        self.assertEqual(counts["리스크"], 2)
        self.assertEqual(counts["주요 벤더"], 1)

    def test_zero_count_category_not_included(self):
        articles = [_make_article("u1", "기타")]
        counts = count_by_category(articles)
        self.assertNotIn("리스크", counts)

    def test_empty_list(self):
        self.assertEqual(count_by_category([]), {})

    def test_missing_category_defaults_to_기타(self):
        articles = [{"url": "u1", "title": "t"}]
        counts = count_by_category(articles)
        self.assertEqual(counts.get("기타", 0), 1)


class TestMakeWidgetKey(unittest.TestCase):
    def test_monitoring_prefix(self):
        key = make_widget_key("monitoring_util", "https://example.com")
        self.assertTrue(key.startswith("monitoring_util_"))

    def test_manual_prefix(self):
        key = make_widget_key("manual_util", "https://example.com")
        self.assertTrue(key.startswith("manual_util_"))

    def test_no_collision_between_prefixes(self):
        url = "https://news.example.com/article/123"
        k_mon = make_widget_key("monitoring_util", url)
        k_man = make_widget_key("manual_util", url)
        self.assertNotEqual(k_mon, k_man)

    def test_same_url_same_prefix_same_key(self):
        url = "https://news.naver.com/article/001"
        k1 = make_widget_key("monitoring_util", url)
        k2 = make_widget_key("monitoring_util", url)
        self.assertEqual(k1, k2)

    def test_different_urls_different_keys(self):
        k1 = make_widget_key("monitoring_util", "https://a.com/1")
        k2 = make_widget_key("monitoring_util", "https://a.com/2")
        self.assertNotEqual(k1, k2)


# ── 6단계 신규 테스트 ─────────────────────────────────────────────────────────

def _make_mon_art(url, category, is_risk_priority=False, pr_score=50, buzz_score=40):
    """6단계 테스트용 모니터링 기사 딕셔너리를 반환한다."""
    return {
        "url": url,
        "title": f"테스트 기사 {url}",
        "media_name": "테스트매체",
        "_monitoring_category": category,
        "_is_risk_priority": is_risk_priority,
        "_pr_value_score": pr_score,
        "score": buzz_score,
    }


class TestApplyUrgencyFilter(unittest.TestCase):
    """긴급 리스크 필터 테스트."""

    def setUp(self):
        arts = [
            _make_mon_art("u1", "리스크", is_risk_priority=True),
            _make_mon_art("u2", "리스크", is_risk_priority=False),
            _make_mon_art("u3", "AI·AX 시장동향", is_risk_priority=False),
        ]
        self.ranked = [(i + 1, a) for i, a in enumerate(arts)]

    def test_no_filter_returns_all(self):
        result = apply_urgency_filter(self.ranked, risk_only=False)
        self.assertEqual(len(result), 3)

    def test_risk_only_returns_urgent_only(self):
        result = apply_urgency_filter(self.ranked, risk_only=True)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0][1]["_is_risk_priority"])

    def test_empty_list_returns_empty(self):
        self.assertEqual(apply_urgency_filter([], risk_only=True), [])

    def test_no_urgent_articles_returns_empty_when_filtered(self):
        arts = [_make_mon_art("u1", "기타", is_risk_priority=False)]
        ranked = [(1, arts[0])]
        result = apply_urgency_filter(ranked, risk_only=True)
        self.assertEqual(result, [])


class TestSortMonitoringArticles(unittest.TestCase):
    """정렬 기능 테스트."""

    def setUp(self):
        arts = [
            _make_mon_art("u1", "리스크", pr_score=30),
            _make_mon_art("u2", "기타",   pr_score=80),
            _make_mon_art("u3", "기타",   pr_score=50),
        ]
        # 전달 순서: 1, 2, 3 (우선순위순)
        self.ranked = [(1, arts[0]), (2, arts[1]), (3, arts[2])]

    def test_default_order_preserved(self):
        result = sort_monitoring_articles(self.ranked, "우선순위순")
        ranks = [r for r, _ in result]
        self.assertEqual(ranks, [1, 2, 3])

    def test_pr_score_sort_descending(self):
        result = sort_monitoring_articles(self.ranked, "PR 활용도순")
        scores = [a["_pr_value_score"] for _, a in result]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_empty_list_returns_empty(self):
        self.assertEqual(sort_monitoring_articles([], "PR 활용도순"), [])


class TestMonitoringDataFields(unittest.TestCase):
    """monitoring.py 출력 필드가 UI에서 읽는 필드명과 일치하는지 검증한다."""

    def _make_scored(self, url, title, group="cloud_security", relevance_type="리스크"):
        art = {
            "url": url, "title": title, "description": "테스트",
            "media_name": "테스트매체", "pub_datetime": "2026-07-21 12:00",
            "pub_date": "2026-07-21", "article_type": "일반 기사",
            "_monitoring_group": group, "_source_query": "사이버 공격 기업",
            "_matched_queries": ["사이버 공격 기업"], "_matched_groups": [group],
            "_relevance_type": relevance_type, "_relevance_level": "높음",
            "_relevance_score": 70, "_relevance_reasons": ["테스트"],
            "_in_whitelist": False, "score": 45,
        }
        return art

    def test_score_monitoring_sets_required_ui_fields(self):
        """score_monitoring_candidate()가 UI에서 읽는 필드를 모두 설정한다."""
        art = self._make_scored("http://ex.com/t1", "사이버 공격 피해 기업 발생")
        mon.score_monitoring_candidate(art)
        for field in ["_monitoring_category", "_monitoring_priority",
                      "_is_risk_priority", "_pr_value_score", "_monitoring_reason"]:
            self.assertIn(field, art, f"필드 {field}가 없음")

    def test_sck_company_not_classified_as_own_company(self):
        """SCK컴퍼니(스타벅스코리아) 기사가 자사·관계사로 분류되지 않는다."""
        art = self._make_scored(
            "http://ex.com/t2", "SCK컴퍼니 스타벅스 노조 출범 소식",
            group="company", relevance_type="자사·관계사")
        art["_matched_groups"] = ["company"]
        mon.score_monitoring_candidate(art)
        self.assertNotEqual(art["_monitoring_category"], "자사·관계사")

    def test_urgent_incident_has_is_risk_priority_true(self):
        """급 리스크(urgent_incident) 기사는 _is_risk_priority=True여야 한다."""
        art = self._make_scored(
            "http://ex.com/t3", "기업 고객 데이터 유출 사건 발생",
            group="cloud_security", relevance_type="리스크")
        mon.score_monitoring_candidate(art)
        self.assertTrue(art.get("_is_risk_priority"),
                        "_is_risk_priority가 True여야 함")

    def test_security_trend_has_is_risk_priority_false(self):
        """보안 트렌드 기사(security_trend)는 _is_risk_priority=False여야 한다."""
        art = self._make_scored(
            "http://ex.com/t4", "AI 시대 사이버 위협 특강 개최",
            group="cloud_security", relevance_type="리스크")
        art["article_type"] = "행사·현장"
        mon.score_monitoring_candidate(art)
        self.assertFalse(art.get("_is_risk_priority"),
                         "_is_risk_priority가 False여야 함")

    def test_missing_optional_fields_dont_crash(self):
        """필수 필드 없는 기사도 score_monitoring_candidate가 정상 동작한다."""
        art = {
            "url": "http://ex.com/t5", "title": "필드 없는 테스트",
            "_monitoring_group": "cloud_security",
            "_source_query": "테스트", "_matched_queries": [],
            "_matched_groups": [], "_relevance_type": "리스크",
            "_relevance_level": "높음", "_relevance_score": 70,
            "_relevance_reasons": [], "_in_whitelist": False, "score": 30,
            # media_name, pub_datetime, description 등 선택 필드 없음
        }
        try:
            mon.score_monitoring_candidate(art)
        except Exception as e:
            self.fail(f"예외 발생: {e}")
        self.assertIn("_monitoring_category", art)


class TestNoUrlArticleHandling(unittest.TestCase):
    """URL 없는 기사 처리 테스트."""

    def test_no_url_article_in_filter(self):
        """URL이 없어도 카테고리 필터가 정상 동작한다."""
        arts = [
            {"title": "제목 없는 URL", "_monitoring_category": "리스크"},
            {"title": "정상 URL", "url": "http://ex.com", "_monitoring_category": "기타"},
        ]
        result = apply_category_filter(arts, "리스크")
        self.assertEqual(len(result), 1)

    def test_no_url_article_in_urgency_filter(self):
        """URL 없이 _is_risk_priority만 있는 기사도 필터가 정상 동작한다."""
        ranked = [
            (1, {"title": "긴급", "_is_risk_priority": True}),
            (2, {"title": "일반", "_is_risk_priority": False}),
        ]
        result = apply_urgency_filter(ranked, risk_only=True)
        self.assertEqual(len(result), 1)

    def test_empty_article_list_returns_empty(self):
        """빈 목록에도 모든 헬퍼 함수가 오류 없이 동작한다."""
        self.assertEqual(apply_category_filter([], "전체"), [])
        self.assertEqual(apply_urgency_filter([], risk_only=True), [])
        self.assertEqual(sort_monitoring_articles([], "PR 활용도순"), [])
        self.assertEqual(count_by_category([]), {})


class TestNoDuplicatesInSelection(unittest.TestCase):
    """동일 URL이 최종 선정 목록에 중복 포함되지 않는지 확인한다."""

    def test_apply_category_filter_preserves_uniqueness(self):
        """동일 URL이 있어도 apply_category_filter는 중복 없이 반환한다."""
        arts = [
            {"url": "http://ex.com/1", "_monitoring_category": "리스크"},
            {"url": "http://ex.com/2", "_monitoring_category": "기타"},
        ]
        result = apply_category_filter(arts, "전체")
        urls = [a.get("url") for _, a in result]
        self.assertEqual(len(urls), len(set(urls)), "URL 중복이 있음")

    def test_select_daily_does_not_produce_duplicates(self):
        """select_daily_monitoring_articles 결과에 URL 중복이 없다."""
        from unittest.mock import patch
        from datetime import datetime, timezone

        def _make_art(i):
            return {
                "url": f"http://ex.com/{i}", "title": f"기사 {i}",
                "media_name": f"매체{i % 3}", "pub_date": "2026-07-21",
                "pub_datetime": "2026-07-21 12:00", "article_type": "일반 기사",
                "_monitoring_group": "cloud_security",
                "_source_query": "사이버 공격 기업",
                "_matched_queries": ["사이버 공격 기업"],
                "_matched_groups": ["cloud_security"],
                "_relevance_type": "리스크", "_relevance_level": "높음",
                "_relevance_score": 70, "_relevance_reasons": [],
                "_in_whitelist": False, "score": 40,
                "_dt": datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
            }

        arts = [_make_art(i) for i in range(20)]
        with patch("monitoring.calculate_article_score", return_value=40), \
             patch("monitoring.load_media_config", return_value={}), \
             patch("monitoring.cluster_articles",
                   side_effect=lambda a, **kw: [{"rep": x, "cluster": [x], "size": 1} for x in a]):
            result = mon.select_daily_monitoring_articles(
                arts, target_count=10, max_count=20)
        urls = [a.get("url") for a in result]
        self.assertEqual(len(urls), len(set(urls)), "URL 중복이 있음")


if __name__ == "__main__":
    unittest.main()
