"""
fetch_daily_monitoring_candidates() 단위 테스트
네트워크 호출은 unittest.mock으로 처리한다.
실행: python test_monitoring.py
"""

import os
import sys
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import monitoring as mon

# ── 테스트용 최소 설정 ────────────────────────────────────────
_MINIMAL_CFG = {
    "groups": {
        "company": {
            "enabled": True,
            "queries": [
                {"text": "SCK",   "enabled": True},
                {"text": "STK",   "enabled": False},   # 비활성 쿼리
            ],
        },
        "competitor": {
            "enabled": True,
            "queries": [{"text": "디모아", "enabled": True}],
        },
        "inactive_group": {
            "enabled": False,
            "queries": [{"text": "DISABLED", "enabled": True}],  # 비활성 그룹
        },
    }
}

START = datetime(2026, 7, 13, tzinfo=timezone.utc)
END   = datetime(2026, 7, 20, tzinfo=timezone.utc)


# ── 픽스처 헬퍼 ──────────────────────────────────────────────
def _make_article(url, title, group="company", query="SCK"):
    return {
        "title":               title,
        "description":         "본문 내용 샘플",
        "url":                 url,
        "domain":              "test.com",
        "media_name":          "테스트매체",
        "pub_date":            "2026-07-20",
        "pub_datetime":        "2026-07-20 10:00",
        "_dt":                 datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc),
        "_media_tier":         3,
        "_in_whitelist":       False,
        "search_keyword":      query,
        "article_type":        "일반 기사",
        "_multi_kw_count":     1,
        "_kw_title_score":     1,
        "_filter_reason":      "",
        "_relevance_score":    35,
        "_relevance_level":    "보통",
        "_relevance_type":     "시장동향",
        "_relevance_reasons":  ["검색 주제 제목 포함"],
        "_low_relevance_reason": "",
        "_foreign_language":   False,
    }


def _mock_fetch(results_map):
    """keyword → articles 매핑을 사용하는 mock side_effect 반환."""
    def _side_effect(*args, **kwargs):
        kw   = kwargs.get("keyword") or (args[0] if args else "")
        arts = results_map.get(kw, [])
        return {"articles": arts, "raw_count": len(arts),
                "filtered_count": len(arts), "status": "success",
                "error": None, "foreign_count": 0}
    return _side_effect


# ══════════════════════════════════════════════════════════════
class TestLoadActiveQueries(unittest.TestCase):

    def test_only_enabled_queries_returned(self):
        active  = mon.load_active_queries(_MINIMAL_CFG)
        queries = [a["query"] for a in active]
        self.assertIn("SCK",   queries)
        self.assertIn("디모아", queries)
        self.assertNotIn("STK",      queries)   # 비활성 쿼리
        self.assertNotIn("DISABLED", queries)   # 비활성 그룹

    def test_group_field_set_correctly(self):
        active = mon.load_active_queries(_MINIMAL_CFG)
        groups = {a["group"] for a in active}
        self.assertIn("company",    groups)
        self.assertIn("competitor", groups)
        self.assertNotIn("inactive_group", groups)

    def test_active_count(self):
        active = mon.load_active_queries(_MINIMAL_CFG)
        self.assertEqual(len(active), 2)   # SCK + 디모아


# ══════════════════════════════════════════════════════════════
class TestFetchCandidates(unittest.TestCase):

    @patch("monitoring.fetch_articles_for_keyword")
    def test_url_dedup_merges_matched_queries(self, mock_fetch):
        """동일 URL이 두 검색어에서 발견되면 _matched_queries를 병합한다."""
        art_a = _make_article("http://ex.com/1", "SCK 기사")
        art_b = _make_article("http://ex.com/1", "SCK 기사", "competitor", "디모아")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art_a], "디모아": [art_b]})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        self.assertEqual(len(results), 1)
        mq = results[0]["_matched_queries"]
        self.assertIn("company/SCK",      mq)
        self.assertIn("competitor/디모아", mq)

    @patch("monitoring.fetch_articles_for_keyword")
    def test_title_dedup_merges_matched_queries(self, mock_fetch):
        """유사 제목(≥90%) 기사는 1건으로 통합하고 _matched_queries를 병합한다."""
        art_a = _make_article("http://ex.com/2", "삼성SDS AI 인프라 구축 발표")
        art_b = _make_article("http://ex.com/3", "삼성SDS AI 인프라 구축 발표",
                              "competitor", "디모아")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art_a], "디모아": [art_b]})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        self.assertEqual(len(results), 1)
        self.assertEqual(len(results[0]["_matched_queries"]), 2)

    @patch("monitoring.fetch_articles_for_keyword")
    def test_distinct_articles_kept_separately(self, mock_fetch):
        """서로 다른 기사는 각각 유지된다."""
        art_a = _make_article("http://ex.com/4", "SCK 파트너십 체결")
        art_b = _make_article("http://ex.com/5", "디모아 연간 실적 발표",
                              "competitor", "디모아")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art_a], "디모아": [art_b]})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        self.assertEqual(len(results), 2)

    @patch("monitoring.fetch_articles_for_keyword")
    def test_relevance_fields_preserved(self, mock_fetch):
        """기존 relevance 필드가 그대로 유지된다."""
        art = _make_article("http://ex.com/6", "SCK AI 솔루션 발표")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art], "디모아": []})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r["_relevance_score"],  35)
        self.assertEqual(r["_relevance_level"],  "보통")
        self.assertEqual(r["_relevance_type"],   "시장동향")
        self.assertEqual(r["_relevance_reasons"], ["검색 주제 제목 포함"])

    @patch("monitoring.fetch_articles_for_keyword")
    def test_monitoring_meta_fields_added(self, mock_fetch):
        """_monitoring_group, _source_query, _matched_queries 필드가 추가된다."""
        art = _make_article("http://ex.com/7", "SCK 공시 내용")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art], "디모아": []})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        r = results[0]
        self.assertIn("_monitoring_group", r)
        self.assertIn("_source_query",     r)
        self.assertIn("_matched_queries",  r)
        self.assertEqual(r["_monitoring_group"], "company")
        self.assertEqual(r["_source_query"],     "SCK")
        self.assertIsInstance(r["_matched_queries"], list)
        self.assertEqual(r["_matched_queries"], ["company/SCK"])

    @patch("monitoring.fetch_articles_for_keyword")
    def test_disabled_queries_not_called(self, mock_fetch):
        """비활성 쿼리(STK) 및 비활성 그룹(DISABLED)에 API가 호출되지 않는다."""
        mock_fetch.side_effect = _mock_fetch({})

        mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        called = [c.kwargs["keyword"] for c in mock_fetch.call_args_list]
        self.assertNotIn("STK",      called)
        self.assertNotIn("DISABLED", called)
        self.assertIn("SCK",   called)
        self.assertIn("디모아", called)

    @patch("monitoring.fetch_articles_for_keyword")
    def test_matched_queries_no_duplicates(self, mock_fetch):
        """동일 검색어가 _matched_queries에 중복 추가되지 않는다."""
        art_a = _make_article("http://ex.com/8", "중복 테스트 기사")
        art_b = _make_article("http://ex.com/8", "중복 테스트 기사")  # 동일 URL
        mock_fetch.side_effect = _mock_fetch({"SCK": [art_a, art_b], "디모아": []})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        mq = results[0]["_matched_queries"]
        self.assertEqual(mq.count("company/SCK"), 1)


# ══════════════════════════════════════════════════════════════
class TestRealConfig(unittest.TestCase):

    def setUp(self):
        mon._load_monitoring_config.cache_clear()

    def test_config_file_loads(self):
        """실제 monitoring_queries.yaml이 로드되고 groups 키를 포함한다."""
        cfg = mon._load_monitoring_config()
        self.assertIn("groups", cfg)
        self.assertGreater(len(cfg["groups"]), 0)

    def test_real_config_active_query_count(self):
        """활성 쿼리 수: company 6 + competitor 1 + ai_ax 7 + cloud_security 5 + vendor 6 = 25"""
        cfg    = mon._load_monitoring_config()
        active = mon.load_active_queries(cfg)
        self.assertEqual(len(active), 25)

    def test_real_config_all_groups_present(self):
        """5개 그룹이 모두 존재한다."""
        cfg    = mon._load_monitoring_config()
        groups = set(cfg["groups"].keys())
        for expected in ("company", "competitor", "ai_ax", "cloud_security", "vendor"):
            self.assertIn(expected, groups)


# ══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(sys.modules[__name__])
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    print()
    n = result.testsRun
    f = len(result.failures) + len(result.errors)
    print(f"결과: {n - f}/{n} PASS,  {f} FAIL")
    sys.exit(0 if result.wasSuccessful() else 1)
