"""
모니터링 모듈 단위·통합 테스트
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
# 2단계: 점수 계산·선정 테스트 (T14–T28)
# ══════════════════════════════════════════════════════════════

def _make_scored_article(url, title, group="ai_ax", query="기업 AI",
                          relevance_score=65, relevance_level="높음",
                          relevance_type="시장동향", article_type="일반 기사",
                          media_name="테스트매체", media_tier=3, buzz=50):
    """score(화제성)까지 포함된 2단계용 테스트 기사."""
    art = _make_article(url, title, group, query)
    art["_relevance_score"] = relevance_score
    art["_relevance_level"] = relevance_level
    art["_relevance_type"]  = relevance_type
    art["article_type"]     = article_type
    art["media_name"]       = media_name
    art["_media_tier"]      = media_tier
    art["_matched_groups"]  = [group]
    art["score"]            = buzz
    return art


class TestScoreCandidate(unittest.TestCase):
    """score_monitoring_candidate() 단위 테스트"""

    def test_formula_accuracy(self):
        """우선순위 = round(rscore*0.45 + buzz*0.30 + pr*0.25), 0-100 클램프."""
        art = _make_scored_article("http://ex.com/f1", "기업 AI 도입 사례",
                                   relevance_score=70, buzz=60)
        mon.score_monitoring_candidate(art)
        pr = art["_pr_value_score"]
        expected = round(70 * 0.45 + 60 * 0.30 + pr * 0.25)
        self.assertEqual(art["_monitoring_priority"], expected)

    def test_priority_clamped_0_100(self):
        """우선순위는 0-100 범위를 벗어나지 않는다."""
        # 매우 높은 점수 → 100 클램프
        art = _make_scored_article("http://ex.com/f2", "SCK 기사",
                                   group="company", query="SCK",
                                   relevance_score=100, relevance_level="높음",
                                   relevance_type="자사·관계사", buzz=100)
        art["_matched_groups"] = ["company"]
        mon.score_monitoring_candidate(art)
        self.assertLessEqual(art["_monitoring_priority"], 100)
        self.assertGreaterEqual(art["_monitoring_priority"], 0)

    def test_risk_articles_flagged(self):
        """_relevance_type=='리스크'이면 _is_risk_priority=True."""
        art = _make_scored_article("http://ex.com/f3", "기업 사이버 공격 피해",
                                   group="cloud_security", query="사이버 공격 기업",
                                   relevance_type="리스크", relevance_level="높음")
        art["_matched_groups"] = ["cloud_security"]
        mon.score_monitoring_candidate(art)
        self.assertTrue(art["_is_risk_priority"])

    def test_non_risk_not_flagged(self):
        """리스크 타입이 아닌 기사는 _is_risk_priority=False."""
        art = _make_scored_article("http://ex.com/f4", "AI 인프라 구축 동향")
        mon.score_monitoring_candidate(art)
        self.assertFalse(art["_is_risk_priority"])

    def test_existing_fields_preserved(self):
        """score_monitoring_candidate는 기존 relevance 필드를 변경하지 않는다."""
        art = _make_scored_article("http://ex.com/f5", "기업 AI 트렌드",
                                   relevance_score=55, relevance_level="보통",
                                   relevance_type="시장동향")
        orig_score = art["_relevance_score"]
        orig_level = art["_relevance_level"]
        orig_type  = art["_relevance_type"]
        mon.score_monitoring_candidate(art)
        self.assertEqual(art["_relevance_score"], orig_score)
        self.assertEqual(art["_relevance_level"], orig_level)
        self.assertEqual(art["_relevance_type"],  orig_type)

    def test_category_priority_multi_group(self):
        """리스크 타입은 다른 그룹보다 높은 카테고리 우선순위를 가진다."""
        art = _make_scored_article("http://ex.com/f6", "기업 클라우드 보안 사고",
                                   group="cloud_security", query="클라우드 보안",
                                   relevance_type="리스크", relevance_level="높음")
        art["_matched_groups"] = ["cloud_security", "ai_ax"]
        mon.score_monitoring_candidate(art)
        self.assertEqual(art["_monitoring_category"], "리스크")

    def test_company_category_requires_entity_in_text(self):
        """자사 그룹이어도 엔티티가 제목/설명에 없으면 자사·관계사 카테고리 미부여."""
        art = _make_scored_article("http://ex.com/f7", "기업 AI 채택 현황",
                                   group="company", query="SCK",
                                   relevance_type="시장동향")
        art["_matched_groups"] = ["company"]
        # title/description에 SCK 등 엔티티 없음
        mon.score_monitoring_candidate(art)
        self.assertNotEqual(art["_monitoring_category"], "자사·관계사")

    def test_company_category_assigned_when_entity_present(self):
        """확정 자사 엔티티(에쓰씨케이)가 있으면 자사·관계사 카테고리가 부여된다."""
        art = _make_scored_article("http://ex.com/f8", "에쓰씨케이 파트너십 체결 소식",
                                   group="company", query="SCK",
                                   relevance_type="자사·관계사", relevance_level="높음")
        art["_matched_groups"] = ["company"]
        mon.score_monitoring_candidate(art)
        self.assertEqual(art["_monitoring_category"], "자사·관계사")

    def test_monitoring_reason_is_string(self):
        """_monitoring_reason은 비어있지 않은 문자열이어야 한다."""
        art = _make_scored_article("http://ex.com/f9", "AI 인프라 기업 도입 증가")
        mon.score_monitoring_candidate(art)
        self.assertIsInstance(art["_monitoring_reason"], str)
        self.assertGreater(len(art["_monitoring_reason"]), 0)


class TestSelectArticles(unittest.TestCase):
    """select_daily_monitoring_articles() 단위 테스트"""

    def _make_pool(self, n, group="ai_ax", query="기업 AI",
                   relevance_level="높음", relevance_type="시장동향",
                   media_name="테스트매체", relevance_score=65):
        """n개의 서로 다른 기사 리스트를 만든다."""
        return [
            _make_scored_article(
                f"http://ex.com/p{i}", f"기업 AI 도입 기사 {i} 사례 보도",
                group=group, query=query,
                relevance_level=relevance_level,
                relevance_type=relevance_type,
                relevance_score=relevance_score,
                media_name=media_name,
            )
            for i in range(n)
        ]

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_low_relevance_not_selected(self, mock_cl, mock_score, mock_mc):
        """낮음 기사는 기본적으로 선정되지 않는다."""
        mock_mc.return_value = {}
        arts = self._make_pool(3, relevance_level="낮음", relevance_score=20)
        result = mon.select_daily_monitoring_articles(arts)
        self.assertEqual(len(result), 0)

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_no_fill_with_low_relevance(self, mock_cl, mock_score, mock_mc):
        """목표 수보다 적은 후보라도 낮음 기사로 채우지 않는다."""
        mock_mc.return_value = {}
        # 보통 2개 + 낮음 10개
        good = self._make_pool(2, relevance_level="보통", relevance_score=40)
        bad  = self._make_pool(10, relevance_level="낮음", relevance_score=15)
        result = mon.select_daily_monitoring_articles(good + bad, target_count=5)
        self.assertEqual(len(result), 2)

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_risk_articles_sorted_first(self, mock_cl, mock_score, mock_mc):
        """_is_risk_priority=True 기사가 목록 맨 앞에 온다."""
        mock_mc.return_value = {}
        normal = _make_scored_article("http://ex.com/r1", "기업 AI 도입 현황")
        risk   = _make_scored_article("http://ex.com/r2", "기업 사이버 공격 피해 사례",
                                      group="cloud_security", query="사이버 공격 기업",
                                      relevance_type="리스크")
        risk["_matched_groups"] = ["cloud_security"]
        result = mon.select_daily_monitoring_articles([normal, risk])
        self.assertTrue(result[0].get("_is_risk_priority", False))

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_same_category_max_5(self, mock_cl, mock_score, mock_mc):
        """같은 카테고리(기타 제외 일반) 기사는 최대 5개만 선정된다."""
        mock_mc.return_value = {}
        arts = [
            _make_scored_article(f"http://ex.com/c{i}",
                                 f"기업 AI 동향 기사 사례 분석 {i}",
                                 media_name=f"매체{i}")
            for i in range(8)
        ]
        result = mon.select_daily_monitoring_articles(arts, max_count=20)
        from collections import Counter
        cats = Counter(a["_monitoring_category"] for a in result)
        for cat, cnt in cats.items():
            if cat not in {"자사·관계사", "경쟁사"}:
                self.assertLessEqual(cnt, 5, f"카테고리 '{cat}' 초과: {cnt}")

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_same_media_max_3(self, mock_cl, mock_score, mock_mc):
        """같은 매체 기사는 최대 3개만 선정된다."""
        mock_mc.return_value = {}
        arts = [
            _make_scored_article(f"http://ex.com/m{i}",
                                 f"AI 뉴스 {i} 기업 도입 사례 분석",
                                 media_name="동일매체")
            for i in range(6)
        ]
        result = mon.select_daily_monitoring_articles(arts, max_count=20)
        media_counts = {}
        for a in result:
            m = a.get("media_name", "")
            media_counts[m] = media_counts.get(m, 0) + 1
        for m, cnt in media_counts.items():
            self.assertLessEqual(cnt, 3, f"매체 '{m}' 초과: {cnt}")

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_same_vendor_max_3(self, mock_cl, mock_score, mock_mc):
        """같은 벤더 기사는 최대 3개만 선정된다."""
        mock_mc.return_value = {}
        arts = []
        for i in range(5):
            a = _make_scored_article(
                f"http://ex.com/v{i}", f"Microsoft 엔터프라이즈 정책 변화 {i}",
                group="vendor", query="Microsoft", media_name=f"매체{i}",
            )
            a["_matched_groups"] = ["vendor"]
            a["_matched_queries"] = ["vendor/Microsoft"]
            arts.append(a)
        result = mon.select_daily_monitoring_articles(arts, max_count=20)
        vendor_counts = {}
        for a in result:
            v = mon._get_vendor_name(a)
            if v:
                vendor_counts[v] = vendor_counts.get(v, 0) + 1
        for v, cnt in vendor_counts.items():
            self.assertLessEqual(cnt, 3, f"벤더 '{v}' 초과: {cnt}")

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    def test_matched_queries_merged_into_cluster_rep(self, mock_score, mock_mc):
        """클러스터 멤버의 _matched_queries가 대표 기사에 병합된다."""
        mock_mc.return_value = {}
        rep    = _make_scored_article("http://ex.com/q1", "AI 인프라 구축 기업 동향")
        member = _make_scored_article("http://ex.com/q2", "AI 인프라 구축 기업 동향",
                                      group="vendor", query="Microsoft")
        rep["_matched_queries"]    = ["ai_ax/기업 AI"]
        member["_matched_queries"] = ["vendor/Microsoft"]
        rep["_matched_groups"]     = ["ai_ax"]
        member["_matched_groups"]  = ["vendor"]

        with patch("monitoring.cluster_articles", return_value=[
            {"rep": rep, "cluster": [rep, member], "size": 2}
        ]):
            result = mon.select_daily_monitoring_articles([rep, member])

        self.assertIn("vendor/Microsoft", result[0]["_matched_queries"])
        self.assertIn("ai_ax/기업 AI",   result[0]["_matched_queries"])

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    def test_matched_groups_merged_into_cluster_rep(self, mock_score, mock_mc):
        """클러스터 멤버의 _matched_groups가 대표 기사에 병합된다."""
        mock_mc.return_value = {}
        rep    = _make_scored_article("http://ex.com/g1", "클라우드 보안 기업 전략")
        member = _make_scored_article("http://ex.com/g2", "클라우드 보안 기업 전략",
                                      group="vendor", query="Microsoft")
        rep["_matched_groups"]    = ["cloud_security"]
        member["_matched_groups"] = ["vendor"]

        with patch("monitoring.cluster_articles", return_value=[
            {"rep": rep, "cluster": [rep, member], "size": 2}
        ]):
            result = mon.select_daily_monitoring_articles([rep, member])

        self.assertIn("cloud_security", result[0]["_matched_groups"])
        self.assertIn("vendor",         result[0]["_matched_groups"])


class TestFetchCandidates2(unittest.TestCase):
    """fetch_daily_monitoring_candidates() 2단계 관련 추가 테스트"""

    @patch("monitoring.fetch_articles_for_keyword")
    def test_matched_groups_field_added(self, mock_fetch):
        """_matched_groups 필드가 기사에 추가된다."""
        art = _make_article("http://ex.com/mg1", "SCK 뉴스")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art], "디모아": []})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        self.assertIn("_matched_groups", results[0])
        self.assertIsInstance(results[0]["_matched_groups"], list)
        self.assertIn("company", results[0]["_matched_groups"])

    @patch("monitoring.fetch_articles_for_keyword")
    def test_matched_groups_merged_on_dedup(self, mock_fetch):
        """동일 URL 기사의 _matched_groups가 병합된다."""
        art_a = _make_article("http://ex.com/mg2", "공통 기사 제목")
        art_b = _make_article("http://ex.com/mg2", "공통 기사 제목",
                              "competitor", "디모아")
        mock_fetch.side_effect = _mock_fetch({"SCK": [art_a], "디모아": [art_b]})

        results = mon.fetch_daily_monitoring_candidates(START, END, _cfg=_MINIMAL_CFG)

        self.assertEqual(len(results), 1)
        mg = results[0]["_matched_groups"]
        self.assertIn("company",    mg)
        self.assertIn("competitor", mg)


# ══════════════════════════════════════════════════════════════
# 통합 테스트 — 실제 cluster_articles / calculate_article_score / score_relevance 연결
# ══════════════════════════════════════════════════════════════

def _make_candidate(url, title, group, query,
                    matched_queries=None, matched_groups=None,
                    relevance_score=65, relevance_level="높음",
                    relevance_type="시장동향", article_type="일반 기사",
                    media_name="테스트매체", media_tier=3):
    """select_daily_monitoring_articles()에 직접 전달할 후보 기사 (fetch 단계 이후 상태)."""
    return {
        "title":               title,
        "description":         "기업 AI 인프라 관련 본문 내용",
        "url":                 url,
        "domain":              "test.com",
        "media_name":          media_name,
        "pub_date":            "2026-07-21",
        "pub_datetime":        "2026-07-21 10:00",
        "_dt":                 datetime(2026, 7, 21, 10, 0, tzinfo=timezone.utc),
        "_media_tier":         media_tier,
        "_in_whitelist":       False,
        "search_keyword":      query,
        "article_type":        article_type,
        "_multi_kw_count":     1,
        "_kw_title_score":     1,
        "_filter_reason":      "",
        "_relevance_score":    relevance_score,
        "_relevance_level":    relevance_level,
        "_relevance_type":     relevance_type,
        "_relevance_reasons":  ["검색 주제 제목 포함"],
        "_low_relevance_reason": "",
        "_foreign_language":   False,
        "_monitoring_group":   group,
        "_source_query":       query,
        "_matched_queries":    matched_queries if matched_queries is not None else [f"{group}/{query}"],
        "_matched_groups":     matched_groups if matched_groups is not None else [group],
    }


class TestMonitoringIntegration(unittest.TestCase):
    """실제 cluster_articles / calculate_article_score / score_relevance 연결 통합 테스트"""

    def test_score_field_set_by_real_cluster_scoring(self):
        """select_daily_monitoring_articles() 후 score가 실제 calculate_article_score 값으로 설정된다."""
        art = _make_candidate(
            "http://ex.com/int1", "기업 AI 인프라 구축 현황 보도",
            "ai_ax", "기업 AI", media_tier=2,
        )
        with patch("monitoring.load_media_config", return_value={}):
            result = mon.select_daily_monitoring_articles([art])
        self.assertEqual(len(result), 1)
        self.assertIn("score", result[0])
        # tier 2 → 매체 점수 15, 최신성 점수 ≥5 → score ≥ 20
        self.assertGreater(result[0]["score"], 0)

    def test_cluster_rep_single_returned_for_similar_titles(self):
        """유사 제목 3건은 cluster_articles()에 의해 대표 1건만 반환된다."""
        # 제목 유사도 ≥0.75 (80~90% 대) — 같은 제목의 다른 URL 기사
        same = "기업 AI 인프라 구축 활용 사례 현황"
        arts = [
            _make_candidate(f"http://ex.com/cl{i}", same,
                            "ai_ax", "기업 AI", media_name=f"매체{i}")
            for i in range(3)
        ]
        with patch("monitoring.load_media_config", return_value={}):
            result = mon.select_daily_monitoring_articles(arts)
        self.assertEqual(len(result), 1)

    def test_cluster_matched_queries_fully_merged(self):
        """클러스터로 묶인 3건의 _matched_queries가 대표 기사에 모두 병합된다."""
        same = "기업 AI 인프라 구축 활용 사례 현황"
        a = _make_candidate("http://ex.com/mq1", same, "ai_ax", "기업 AI",
                            matched_queries=["ai_ax/기업 AI"],    matched_groups=["ai_ax"])
        b = _make_candidate("http://ex.com/mq2", same, "ai_ax", "AI 인프라",
                            matched_queries=["ai_ax/AI 인프라"],  matched_groups=["ai_ax"])
        c = _make_candidate("http://ex.com/mq3", same, "vendor", "Microsoft",
                            matched_queries=["vendor/Microsoft"], matched_groups=["vendor"])
        with patch("monitoring.load_media_config", return_value={}):
            result = mon.select_daily_monitoring_articles([a, b, c])
        self.assertEqual(len(result), 1)
        mq = result[0]["_matched_queries"]
        self.assertIn("ai_ax/기업 AI",    mq)
        self.assertIn("ai_ax/AI 인프라",  mq)
        self.assertIn("vendor/Microsoft", mq)

    def test_cluster_matched_groups_fully_merged(self):
        """클러스터로 묶인 3건의 _matched_groups가 대표 기사에 모두 병합된다."""
        same = "기업 AI 인프라 구축 활용 사례 현황"
        a = _make_candidate("http://ex.com/mg1", same, "ai_ax",  "기업 AI",
                            matched_groups=["ai_ax"])
        b = _make_candidate("http://ex.com/mg2", same, "ai_ax",  "AI 인프라",
                            matched_groups=["ai_ax"])
        c = _make_candidate("http://ex.com/mg3", same, "vendor", "Microsoft",
                            matched_groups=["vendor"])
        with patch("monitoring.load_media_config", return_value={}):
            result = mon.select_daily_monitoring_articles([a, b, c])
        self.assertEqual(len(result), 1)
        mg = result[0]["_matched_groups"]
        self.assertIn("ai_ax",  mg)
        self.assertIn("vendor", mg)

    def test_cluster_size_reflected_in_buzz(self):
        """클러스터 크기 3이 화제성 점수(확산도 항목)에 반영된다."""
        same = "기업 AI 인프라 구축 활용 사례 현황"
        arts = [
            _make_candidate(f"http://ex.com/sz{i}", same,
                            "ai_ax", "기업 AI", media_name=f"매체{i}")
            for i in range(3)
        ]
        with patch("monitoring.load_media_config", return_value={}):
            result = mon.select_daily_monitoring_articles(arts)
        self.assertEqual(len(result), 1)
        # 클러스터 크기 3 → 확산도 min((3-1)*2.8, 25) = 5 → score ≥ 5
        self.assertGreaterEqual(result[0]["score"], 5)

    def test_real_risk_detection_from_relevance_scorer(self):
        """score_relevance()가 기업 해킹·유출 기사를 '리스크' 타입으로 판정하면 _is_risk_priority=True."""
        from relevance_scorer import score_relevance
        _title = "클라우드 서비스 해킹으로 고객 데이터 유출"
        _desc  = "국내 기업의 클라우드 시스템이 해킹 공격을 받아 고객 개인정보가 유출됐다. 피해 규모가 확산되고 있다."
        rel = score_relevance(title=_title, description=_desc, query_keyword="사이버 공격 기업")
        self.assertEqual(rel["_relevance_type"], "리스크",
                         "score_relevance가 해킹·유출 기사를 리스크로 판정해야 한다")
        # _classify_monitoring_risk()는 title/description으로 시그널을 확인하므로 필드를 보장한다
        rel.setdefault("title", _title)
        rel.setdefault("description", _desc)
        rel["_matched_queries"] = ["cloud_security/사이버 공격 기업"]
        rel["_matched_groups"]  = ["cloud_security"]
        rel["score"] = 50
        mon.score_monitoring_candidate(rel)
        self.assertTrue(rel["_is_risk_priority"])

    def test_disabled_person_context_not_risk(self):
        """장애인 맥락 기사는 score_relevance()가 리스크로 판정하지 않으며 _is_risk_priority=False."""
        from relevance_scorer import score_relevance
        rel = score_relevance(
            title="장애인 고용 의무 이행 기업 지원 정책 발표",
            description="정부가 장애인 고용 의무 이행 기업에 대한 지원 제도를 강화한다고 밝혔다.",
            query_keyword="사이버 공격 기업",
        )
        self.assertNotEqual(rel["_relevance_type"], "리스크",
                            "장애인 기사는 리스크 타입이 되면 안 된다")
        rel["_matched_queries"] = ["cloud_security/사이버 공격 기업"]
        rel["_matched_groups"]  = ["cloud_security"]
        rel["score"] = 50
        mon.score_monitoring_candidate(rel)
        self.assertFalse(rel["_is_risk_priority"])

    def test_full_pipeline_fields_complete(self):
        """select_daily_monitoring_articles() 반환 기사에 2단계 필드가 모두 존재한다."""
        art = _make_candidate(
            "http://ex.com/full1", "기업 AI 솔루션 도입 확산",
            "ai_ax", "기업 AI",
        )
        with patch("monitoring.load_media_config", return_value={}):
            result = mon.select_daily_monitoring_articles([art])
        self.assertEqual(len(result), 1)
        r = result[0]
        for field in ("score", "_pr_value_score", "_monitoring_priority",
                      "_is_risk_priority", "_monitoring_category", "_monitoring_reason"):
            self.assertIn(field, r, f"누락 필드: {field}")
        # score(buzz)가 공식에 실제로 반영됐는지 확인
        pr = r["_pr_value_score"]
        rscore = r["_relevance_score"]
        buzz   = r["score"]
        expected = max(0, min(100, round(rscore * 0.45 + buzz * 0.30 + pr * 0.25)))
        self.assertEqual(r["_monitoring_priority"], expected)


# ══════════════════════════════════════════════════════════════
# 5단계 신규 테스트 — _classify_monitoring_risk / 이벤트 클러스터링 / target_count
# ══════════════════════════════════════════════════════════════

def _make_risk_article(title, description="본문 내용 샘플", article_type="일반 기사"):
    """리스크 타입 기사 픽스처."""
    art = _make_scored_article(
        "http://ex.com/risk_cls", title,
        group="cloud_security", query="사이버 공격 기업",
        relevance_type="리스크", relevance_level="높음",
    )
    art["description"]  = description
    art["article_type"] = article_type
    return art


class TestClassifyMonitoringRisk(unittest.TestCase):
    """_classify_monitoring_risk() 단위 테스트"""

    def test_not_risk_when_relevance_type_not_risk(self):
        """_relevance_type이 '리스크'가 아니면 항상 'not_risk'를 반환한다."""
        art = _make_scored_article("http://ex.com/cr1", "AI 시장동향")
        self.assertEqual(mon._classify_monitoring_risk(art), "not_risk")

    def test_urgent_incident_data_breach(self):
        """'데이터 유출' 시그널 → 'urgent_incident'."""
        art = _make_risk_article("기업 고객 데이터 유출 사건 발생")
        self.assertEqual(mon._classify_monitoring_risk(art), "urgent_incident")

    def test_urgent_incident_ransomware(self):
        """'랜섬웨어 감염' 시그널 → 'urgent_incident'."""
        art = _make_risk_article("물류 기업 랜섬웨어 감염 피해 확산")
        self.assertEqual(mon._classify_monitoring_risk(art), "urgent_incident")

    def test_urgent_incident_침해사고(self):
        """'침해 사고' 시그널 → 'urgent_incident'."""
        art = _make_risk_article("국내 기업 침해 사고 신고 건수 급증")
        self.assertEqual(mon._classify_monitoring_risk(art), "urgent_incident")

    def test_urgent_incident_zero_day(self):
        """'제로데이 공격' 시그널 → 'urgent_incident'."""
        art = _make_risk_article("제로데이 공격 연쇄 발생 — 패치 적용 권고")
        self.assertEqual(mon._classify_monitoring_risk(art), "urgent_incident")

    def test_security_trend_no_signals(self):
        """리스크 타입이지만 시그널 없음 → 'security_trend'."""
        art = _make_risk_article("기업 보안 담당자 인터뷰 — 클라우드 전환 고민")
        self.assertEqual(mon._classify_monitoring_risk(art), "security_trend")

    def test_not_risk_product_launch(self):
        """'정식 출시' 비사건 시그널 → 'not_risk'."""
        art = _make_risk_article("보안 솔루션 정식 출시 — 엔터프라이즈 시장 공략")
        self.assertEqual(mon._classify_monitoring_risk(art), "not_risk")

    def test_not_risk_event_preview(self):
        """'isec' 비사건 시그널 → 'not_risk'."""
        art = _make_risk_article("isec 2026 미리보기 — 보안 트렌드 총정리")
        self.assertEqual(mon._classify_monitoring_risk(art), "not_risk")

    def test_not_risk_article_type_pr(self):
        """article_type '보도자료형' → 'not_risk'."""
        art = _make_risk_article("침해 사고 대응 솔루션 출시 보도자료",
                                 article_type="보도자료형")
        self.assertEqual(mon._classify_monitoring_risk(art), "not_risk")

    def test_is_risk_priority_false_for_security_trend(self):
        """security_trend 기사는 _is_risk_priority=False."""
        art = _make_risk_article("기업 보안 담당자 인터뷰 — 클라우드 전환 고민")
        art["score"] = 50
        mon.score_monitoring_candidate(art)
        self.assertFalse(art["_is_risk_priority"])


class TestEventClustering(unittest.TestCase):
    """이벤트 토큰·클러스터링 단위 테스트"""

    def _base_art(self, title, priority=50, dt=None):
        if dt is None:
            dt = datetime(2026, 7, 20, 10, 0, tzinfo=timezone.utc)
        art = _make_scored_article("http://ex.com/ev", title,
                                   group="cloud_security",
                                   query="사이버 공격 기업",
                                   relevance_type="리스크")
        art["_monitoring_priority"] = priority
        art["_dt"] = dt
        return art

    def test_event_tokens_basic(self):
        """기본 제목에서 의미 있는 토큰이 추출된다."""
        tokens = mon._event_tokens("SGA솔루션즈 보안 취약점 침해")
        self.assertIn("SGA솔루션즈", tokens)
        self.assertIn("보안", tokens)
        self.assertIn("취약점", tokens)
        self.assertIn("침해", tokens)

    def test_event_tokens_strip_particles(self):
        """한국어 조사가 제거된 형태로 토큰화된다."""
        tokens = mon._event_tokens("보안을 취약점에서 확인")
        self.assertIn("보안", tokens)
        self.assertIn("취약점", tokens)
        self.assertNotIn("보안을", tokens)
        self.assertNotIn("취약점에서", tokens)

    def test_same_monitoring_event_true(self):
        """공통 엔티티 토큰 3개 이상 → _same_monitoring_event True."""
        a = self._base_art("SGA솔루션즈 보안 취약점 침해 사고 발생")
        b = self._base_art("SGA솔루션즈 취약점 악용 보안 침해 사고")
        self.assertTrue(mon._same_monitoring_event(a, b))

    def test_different_events_not_same(self):
        """공통 토큰 없는 기사 → _same_monitoring_event False."""
        a = self._base_art("Microsoft 클라우드 서비스 업데이트 발표")
        b = self._base_art("금융권 랜섬웨어 피해 복구 진행 중")
        self.assertFalse(mon._same_monitoring_event(a, b))

    def test_merge_event_clusters_reduces_count(self):
        """같은 이벤트 2건 → _merge_monitoring_event_clusters 후 1건."""
        a = self._base_art("SGA솔루션즈 보안 취약점 침해 사고 발생", priority=70)
        b = self._base_art("SGA솔루션즈 취약점 악용 보안 침해 사고", priority=60)
        a["_matched_queries"] = ["cloud_security/사이버 공격 기업"]
        b["_matched_queries"] = ["cloud_security/사이버 보안"]
        a["_matched_groups"]  = ["cloud_security"]
        b["_matched_groups"]  = ["cloud_security"]
        result = mon._merge_monitoring_event_clusters([a, b])
        self.assertEqual(len(result), 1)

    def test_merge_keeps_higher_priority_rep(self):
        """_merge_monitoring_event_clusters는 우선순위 높은 기사를 대표로 선택한다."""
        a = self._base_art("SGA솔루션즈 보안 취약점 침해 사고 발생", priority=70)
        b = self._base_art("SGA솔루션즈 취약점 악용 보안 침해 사고", priority=40)
        a["_matched_queries"] = ["cloud_security/q1"]
        b["_matched_queries"] = ["cloud_security/q2"]
        a["_matched_groups"]  = ["cloud_security"]
        b["_matched_groups"]  = ["cloud_security"]
        result = mon._merge_monitoring_event_clusters([a, b])
        self.assertEqual(result[0]["_monitoring_priority"], 70)

    def test_merge_combines_matched_queries(self):
        """병합된 클러스터 대표 기사에 모든 _matched_queries가 합쳐진다."""
        a = self._base_art("SGA솔루션즈 보안 취약점 침해 사고 발생", priority=70)
        b = self._base_art("SGA솔루션즈 취약점 악용 보안 침해 사고", priority=40)
        a["_matched_queries"] = ["cloud_security/사이버 공격 기업"]
        b["_matched_queries"] = ["cloud_security/클라우드 보안"]
        a["_matched_groups"]  = ["cloud_security"]
        b["_matched_groups"]  = ["cloud_security"]
        result = mon._merge_monitoring_event_clusters([a, b])
        mq = result[0]["_matched_queries"]
        self.assertIn("cloud_security/사이버 공격 기업", mq)
        self.assertIn("cloud_security/클라우드 보안", mq)


class TestTargetCountAndRiskCap(unittest.TestCase):
    """target_count 준수 및 리스크 카테고리 상한 테스트"""

    def _make_pool(self, n, group, query, relevance_type="시장동향",
                   relevance_level="높음", description="본문 내용 샘플"):
        arts = []
        for i in range(n):
            a = _make_scored_article(
                f"http://ex.com/pool_{group}_{i}",
                f"{group} 동향 기사 사례 분석 보도 {i}",
                group=group, query=query,
                relevance_type=relevance_type,
                relevance_level=relevance_level,
                media_name=f"매체_{group}_{i}",
            )
            a["_matched_groups"] = [group]
            a["description"] = description
            arts.append(a)
        return arts

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_stops_at_target_count(self, mock_cl, mock_score, mock_mc):
        """target_count 도달 후 must-include 아닌 기사는 추가 선정하지 않는다."""
        mock_mc.return_value = {}
        arts = (
            self._make_pool(5, "ai_ax", "기업 AI")
            + self._make_pool(5, "cloud_security", "클라우드 보안")
            + self._make_pool(5, "vendor", "Microsoft")
            + self._make_pool(5, "ai_ax", "AI 인프라")
        )
        result = mon.select_daily_monitoring_articles(arts, target_count=3, max_count=20)
        self.assertEqual(len(result), 3)

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_risk_capped_at_max_risk_count(self, mock_cl, mock_score, mock_mc):
        """리스크 카테고리 기사는 최대 _MAX_RISK_COUNT(5)개만 선정된다."""
        mock_mc.return_value = {}
        arts = self._make_pool(
            10, "cloud_security", "사이버 공격 기업",
            relevance_type="리스크",
            description="침해 사고 발생",
        )
        result = mon.select_daily_monitoring_articles(arts, target_count=15, max_count=20)
        from collections import Counter
        cats = Counter(a["_monitoring_category"] for a in result)
        self.assertLessEqual(cats.get("리스크", 0), mon._MAX_RISK_COUNT)

    @patch("monitoring.load_media_config")
    @patch("monitoring.calculate_article_score", return_value=50)
    @patch("monitoring.cluster_articles", side_effect=lambda arts, **kw:
           [{"rep": a, "cluster": [a], "size": 1} for a in arts])
    def test_unlimited_cat_exceeds_target(self, mock_cl, mock_score, mock_mc):
        """자사·관계사 카테고리는 target_count를 초과해 선정될 수 있다."""
        mock_mc.return_value = {}
        # 제목을 충분히 다르게 해 2차 이벤트 클러스터링에 묶이지 않게 한다
        # 자사·관계사 확정을 위해 확정 엔티티(에쓰씨케이, SCK Corp)를 명시한다
        titles = [
            "에쓰씨케이 클라우드 인프라 구축 계약 체결",
            "에쓰씨케이 금융 고객 AX 전환 성과 발표",
            "에쓰씨케이 제조 부문 신규 수주 달성",
            "SCK Corp AI 도입 기업 증가 보고",
        ]
        arts = []
        for i, title in enumerate(titles):
            a = _make_scored_article(
                f"http://ex.com/co{i}", title,
                group="company", query="SCK",
                relevance_type="자사·관계사", relevance_level="높음",
                media_name=f"매체_{i}",
            )
            a["_matched_groups"] = ["company"]
            arts.append(a)
        result = mon.select_daily_monitoring_articles(arts, target_count=2, max_count=20)
        company_count = sum(
            1 for a in result if a["_monitoring_category"] == "자사·관계사"
        )
        self.assertGreater(company_count, 2)


# ══════════════════════════════════════════════════════════════
# 자사·관계사 동명이사 오탐 방지 회귀 테스트 (7개)
# ══════════════════════════════════════════════════════════════

def _make_company_art(url_suffix, title, description=""):
    """company 그룹, 자사·관계사 관련성 타입의 테스트 기사를 만든다."""
    art = _make_scored_article(
        f"http://ex.com/co_{url_suffix}", title,
        group="company", query="SCK",
        relevance_type="자사·관계사", relevance_level="높음",
    )
    art["_matched_groups"] = ["company"]
    if description:
        art["description"] = description
    return art


class TestCompanyDisambiguation(unittest.TestCase):
    """SCK vs SCK컴퍼니(스타벅스코리아) 동명이사 구분 회귀 테스트."""

    def test_sck_corp_강한_엔티티_총판(self):
        """[1] 'SCK Corp.' 확정 엔티티 포함 → 자사·관계사."""
        art = _make_company_art("cd1", "SCK Corp. 총판 계약 체결")
        mon.score_monitoring_candidate(art)
        self.assertEqual(art["_monitoring_category"], "자사·관계사")

    def test_에쓰씨케이_대표_선임(self):
        """[2] '에쓰씨케이' 확정 엔티티 포함 → 자사·관계사."""
        art = _make_company_art("cd2", "에쓰씨케이 대표이사 신규 선임")
        mon.score_monitoring_candidate(art)
        self.assertEqual(art["_monitoring_category"], "자사·관계사")

    def test_sck컴퍼니_스타벅스_노조_is_not_company(self):
        """[3] 'SCK컴퍼니 스타벅스 노조' → 동명이사 제외 → 자사 아님."""
        art = _make_company_art("cd3", "SCK컴퍼니 스타벅스 노조 출범")
        mon.score_monitoring_candidate(art)
        self.assertNotEqual(art["_monitoring_category"], "자사·관계사")

    def test_sck컴퍼니_실적_is_not_company(self):
        """[4] 'SCK컴퍼니 실적' → 동명이사 제외 → 자사 아님."""
        art = _make_company_art("cd4", "SCK컴퍼니 실적 발표 적자 전환")
        mon.score_monitoring_candidate(art)
        self.assertNotEqual(art["_monitoring_category"], "자사·관계사")

    def test_이마트_계열사_sck컴퍼니_is_not_company(self):
        """[5] '이마트 계열사 SCK컴퍼니' → 동명이사 제외 → 자사 아님."""
        art = _make_company_art("cd5", "이마트 계열사 SCK컴퍼니 현황")
        mon.score_monitoring_candidate(art)
        self.assertNotEqual(art["_monitoring_category"], "자사·관계사")

    def test_bare_sck_보조신호_없음_not_confirmed(self):
        """[6] bare 'SCK' + 당사 사업 보조 신호 없음 → 자사 확정 금지."""
        art = _make_company_art("cd6", "SCK 관련 뉴스 동향",
                                description="기업 전반의 동향을 살펴본다.")
        mon.score_monitoring_candidate(art)
        self.assertNotEqual(art["_monitoring_category"], "자사·관계사")

    def test_bare_sck_with_microsoft_총판_is_company_candidate(self):
        """[7] bare 'SCK' + Microsoft 총판 보조 신호 → 자사 후보 인정."""
        art = _make_company_art(
            "cd7", "SCK, Microsoft 소프트웨어 라이선스 총판 계약 체결"
        )
        mon.score_monitoring_candidate(art)
        self.assertEqual(art["_monitoring_category"], "자사·관계사")


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
