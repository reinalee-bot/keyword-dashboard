"""
Tab4 헬퍼 함수 단위 테스트 (Streamlit 의존 없음)
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(__file__))

from monitoring_tab_helpers import (
    apply_category_filter,
    count_by_category,
    make_widget_key,
    monitoring_config_version,
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


if __name__ == "__main__":
    unittest.main()
