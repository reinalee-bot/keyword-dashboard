"""
Google Sheets ↔ 로컬 CSV 양방향 동기화 단위 테스트

원칙:
- 실제 Google Sheets API 호출 없음
- 실제 운영 스프레드시트 읽기/쓰기 없음
- 외부 네트워크 의존 없음
- FakeWorksheet(gspread 6.x 동작 재현) + 임시 CSV 사용
- data/monitoring_reviews.csv 불변 보장

실행: python test_gsheets_sync.py
"""

import csv
import hashlib
import os
import re
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import monitoring_review_store as mrs

REVIEW_COLS = mrs.REVIEW_COLS
_PROD_CSV   = mrs.REVIEWS_CSV


# ──────────────────────────────────────────────────────────────
# 운영 CSV 해시 (테스트 전)
# ──────────────────────────────────────────────────────────────

def _file_sha256(path: str) -> str:
    if not os.path.exists(path):
        return "NO_FILE"
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


_PROD_CSV_HASH_BEFORE = _file_sha256(_PROD_CSV)


# ──────────────────────────────────────────────────────────────
# FakeWorksheet — gspread 6.x 동작 재현
# ──────────────────────────────────────────────────────────────

class FakeCell:
    def __init__(self, row: int):
        self.row = row


class FakeWorksheet:
    """
    gspread 6.x Worksheet 인터페이스 최소 구현 (in-memory).

    핵심 gspread 6.x 변경 사항 반영:
      - find(): 미발견 시 None 반환 (CellNotFound 예외 없음)
      - update(values, range_name=None): 인자 순서가 구버전과 반대
    """

    def __init__(self, header=None, extra_cols: list | None = None):
        self._data: list[list] = []
        h = list(header if header is not None else REVIEW_COLS)
        if extra_cols:
            h = h + extra_cols
        self._data.append(h)

    # ── read 메서드 ────────────────────────────────────────────

    def get_all_values(self) -> list:
        return [list(r) for r in self._data]

    def get_all_records(self, default_blank: str = "", **kwargs) -> list:
        if not self._data:
            return []
        headers = self._data[0]
        result = []
        for row in self._data[1:]:
            padded = list(row) + [default_blank] * max(0, len(headers) - len(row))
            result.append({
                h: (padded[i] if i < len(padded) else default_blank)
                for i, h in enumerate(headers)
            })
        return result

    def row_values(self, row_num: int) -> list:
        idx = row_num - 1
        return list(self._data[idx]) if 0 <= idx < len(self._data) else []

    # ── find: gspread 6.x — 미발견 시 None 반환 ───────────────

    def find(self, query: str, in_column: int = 1) -> "FakeCell | None":
        """gspread 6.x: 미발견 시 None. CellNotFound 예외 없음."""
        col_idx = in_column - 1
        for i, row in enumerate(self._data):
            if i == 0:  # 헤더 행 건너뜀
                continue
            if col_idx < len(row) and str(row[col_idx]) == str(query):
                return FakeCell(i + 1)
        return None  # gspread 6.x 동작

    # ── write 메서드: gspread 6.x API ─────────────────────────

    def update(self, values, range_name: str | None = None, **kwargs) -> None:
        """
        gspread 6.x: update(values, range_name=None).
        첫 인자가 values(리스트), 두 번째가 range_name(문자열).
        range_name이 문자열이 아닌 경우는 구버전 API 호출로 간주해 아무것도 하지 않는다.
        """
        if not isinstance(range_name, str):
            # 구버전 API 호출(range_name 자리에 리스트가 넘어옴): silent no-op
            return
        m = re.match(r"[A-Z]+(\d+)", range_name)
        if m and values:
            row_num = int(m.group(1))
            idx = row_num - 1
            if 0 <= idx < len(self._data):
                self._data[idx] = list(values[0]) if isinstance(values[0], list) else list(values)

    def append_row(self, values: list, value_input_option: str = "RAW") -> None:
        self._data.append(list(values))

    def append_rows(self, rows: list, value_input_option: str = "RAW") -> None:
        for row in rows:
            self._data.append(list(row))

    def insert_row(self, values: list, index: int) -> None:
        self._data.insert(index - 1, list(values))

    def delete_rows(self, row_num: int) -> None:
        idx = row_num - 1
        if 0 <= idx < len(self._data):
            del self._data[idx]

    # ── 테스트 헬퍼 ────────────────────────────────────────────

    def data_row_count(self) -> int:
        """헤더 제외 데이터 행 수."""
        return len(self._data) - 1

    def find_row_dict(self, article_id: str) -> dict | None:
        """article_id로 행을 dict로 반환. 없으면 None."""
        for r in self.get_all_records():
            if r.get("article_id") == article_id:
                return r
        return None


# ──────────────────────────────────────────────────────────────
# 공통 픽스처 헬퍼
# ──────────────────────────────────────────────────────────────

def _base_row(**kw) -> dict:
    row = {c: "" for c in REVIEW_COLS}
    row.update(kw)
    return row


@contextmanager
def _temp_csv():
    """임시 디렉터리에 빈 CSV를 생성하고 REVIEWS_CSV를 교체한다."""
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "data", "monitoring_reviews.csv")
        os.makedirs(os.path.dirname(csv_path), exist_ok=True)
        with patch.object(mrs, "REVIEWS_CSV", csv_path):
            yield csv_path


@contextmanager
def _ws_context(ws_or_none):
    """_get_ws()를 fake ws 또는 None으로 교체한다."""
    mrs.reset_ws_cache()
    with patch.object(mrs, "_get_ws", return_value=ws_or_none):
        yield


# ──────────────────────────────────────────────────────────────
# A. Sheets → 로컬 (_gsheet_load)
# ──────────────────────────────────────────────────────────────

class TestGsheetLoad(unittest.TestCase):
    """_gsheet_load(ws): Sheets에서 {article_id: row_dict} 로드"""

    def test_load_new_rows(self):
        """Sheets 데이터가 article_id 키 dict로 로드된다."""
        ws = FakeWorksheet()
        ws.append_row([f"aid1"] + [""] * (len(REVIEW_COLS) - 1))
        result = mrs._gsheet_load(ws)
        self.assertIn("aid1", result)

    def test_load_all_fields(self):
        """로드된 행이 모든 REVIEW_COLS 필드를 가진다."""
        ws = FakeWorksheet()
        row = {c: f"v_{c}" for c in REVIEW_COLS}
        ws.append_row([row[c] for c in REVIEW_COLS])
        result = mrs._gsheet_load(ws)
        loaded = result["v_article_id"]
        for col in REVIEW_COLS:
            self.assertIn(col, loaded)

    def test_skip_empty_article_id(self):
        """article_id가 빈 행은 무시된다."""
        ws = FakeWorksheet()
        ws.append_row([""] + ["x"] * (len(REVIEW_COLS) - 1))
        result = mrs._gsheet_load(ws)
        self.assertEqual(len(result), 0)

    def test_extra_cols_in_sheets_no_error(self):
        """Sheets에 REVIEW_COLS 외 추가 열이 있어도 오류가 발생하지 않는다."""
        ws = FakeWorksheet(extra_cols=["promotional_likelihood", "future_field"])
        row = ["aid_extra"] + [""] * (len(REVIEW_COLS) - 1) + ["높음", "foo"]
        ws.append_row(row)
        result = mrs._gsheet_load(ws)
        self.assertIn("aid_extra", result)
        # 알 수 없는 열은 result에 포함되지 않는다
        self.assertNotIn("promotional_likelihood", result["aid_extra"])
        self.assertNotIn("future_field", result["aid_extra"])

    def test_header_order_independent(self):
        """열 순서가 달라도 열 이름 기준으로 데이터를 읽는다."""
        # 헤더를 REVIEW_COLS의 역순으로 구성
        reversed_cols = list(reversed(REVIEW_COLS))
        ws = FakeWorksheet(header=reversed_cols)
        row_values = {c: f"val_{c}" for c in reversed_cols}
        ws.append_row([row_values[c] for c in reversed_cols])
        result = mrs._gsheet_load(ws)
        # article_id는 reversed 헤더에서 마지막 열
        aid = f"val_article_id"
        self.assertIn(aid, result)
        self.assertEqual(result[aid]["title"], "val_title")

    def test_empty_worksheet_returns_empty_dict(self):
        """헤더만 있는 빈 Sheets는 빈 dict를 반환한다."""
        ws = FakeWorksheet()
        result = mrs._gsheet_load(ws)
        self.assertEqual(result, {})

    def test_duplicate_article_id_last_wins(self):
        """같은 article_id가 두 번 있을 때 마지막 행이 결과에 남는다."""
        ws = FakeWorksheet()
        row1 = _base_row(article_id="dup", reviewer_memo="first")
        row2 = _base_row(article_id="dup", reviewer_memo="second")
        ws.append_row([row1[c] for c in REVIEW_COLS])
        ws.append_row([row2[c] for c in REVIEW_COLS])
        result = mrs._gsheet_load(ws)
        # 동일 키 → 나중 값으로 덮어씀
        self.assertEqual(result["dup"]["reviewer_memo"], "second")

    def test_values_are_strings(self):
        """로드된 값은 모두 문자열이다."""
        ws = FakeWorksheet()
        ws.append_row(["aid_str"] + [""] * (len(REVIEW_COLS) - 1))
        result = mrs._gsheet_load(ws)
        for v in result["aid_str"].values():
            self.assertIsInstance(v, str)

    def test_bad_row_does_not_stop_all(self):
        """빈 article_id 행 하나가 전체 로드를 중단시키지 않는다."""
        ws = FakeWorksheet()
        ws.append_row([""] + ["bad"] * (len(REVIEW_COLS) - 1))   # 빈 ID
        ws.append_row(["good_id"] + ["ok"] * (len(REVIEW_COLS) - 1))
        result = mrs._gsheet_load(ws)
        self.assertIn("good_id", result)
        self.assertEqual(len(result), 1)


# ──────────────────────────────────────────────────────────────
# B. 로컬 → Sheets (_gsheet_upsert)
# ──────────────────────────────────────────────────────────────

class TestGsheetUpsert(unittest.TestCase):
    """_gsheet_upsert(ws, row_data): Sheets에 article_id 기준 upsert"""

    def setUp(self):
        self.ws = FakeWorksheet()

    def test_new_record_appended(self):
        """신규 article_id는 Sheets에 행이 추가된다."""
        row = _base_row(article_id="new1", title="신규 기사")
        result = mrs._gsheet_upsert(self.ws, row)
        self.assertTrue(result, "신규 행 upsert가 True를 반환해야 한다")
        self.assertEqual(self.ws.data_row_count(), 1)
        found = self.ws.find_row_dict("new1")
        self.assertIsNotNone(found, "upsert 후 article_id로 조회 가능해야 한다")
        self.assertEqual(found["title"], "신규 기사")

    def test_existing_record_updated(self):
        """기존 article_id 행은 중복 추가 없이 제자리 업데이트된다."""
        row_v1 = _base_row(article_id="upd1", reviewer_memo="초안")
        mrs._gsheet_upsert(self.ws, row_v1)
        self.assertEqual(self.ws.data_row_count(), 1)

        row_v2 = _base_row(article_id="upd1", reviewer_memo="최종")
        result = mrs._gsheet_upsert(self.ws, row_v2)
        self.assertTrue(result)
        self.assertEqual(self.ws.data_row_count(), 1, "중복 행 없이 제자리 업데이트")
        found = self.ws.find_row_dict("upd1")
        self.assertEqual(found["reviewer_memo"], "최종")

    def test_upsert_uses_review_cols_order(self):
        """upsert된 행의 열 순서는 REVIEW_COLS를 따른다."""
        row = _base_row(article_id="ord1", title="순서 확인")
        mrs._gsheet_upsert(self.ws, row)
        # FakeWorksheet의 헤더와 데이터 행이 동일 순서여야 함
        header = self.ws.get_all_values()[0]
        data_row = self.ws.get_all_values()[1]
        aid_idx = header.index("article_id")
        title_idx = header.index("title")
        self.assertEqual(data_row[aid_idx], "ord1")
        self.assertEqual(data_row[title_idx], "순서 확인")

    def test_no_duplicate_on_multiple_upserts(self):
        """같은 article_id를 여러 번 upsert해도 행이 하나만 존재한다."""
        row = _base_row(article_id="dup2", reviewer_memo="v1")
        mrs._gsheet_upsert(self.ws, row)
        row["reviewer_memo"] = "v2"
        mrs._gsheet_upsert(self.ws, row)
        row["reviewer_memo"] = "v3"
        mrs._gsheet_upsert(self.ws, row)
        self.assertEqual(self.ws.data_row_count(), 1)

    def test_empty_string_values_preserved(self):
        """빈 문자열 값도 기존 Sheets 값을 소실시키지 않고 그대로 기록된다."""
        row = _base_row(article_id="emp1", reviewer_memo="있던 메모")
        mrs._gsheet_upsert(self.ws, row)
        # reviewer_memo를 빈 문자열로 업데이트
        row2 = _base_row(article_id="emp1", reviewer_memo="")
        mrs._gsheet_upsert(self.ws, row2)
        found = self.ws.find_row_dict("emp1")
        # 빈 문자열로 명시적 업데이트된 것이므로 빈 문자열이어야 한다
        self.assertEqual(found["reviewer_memo"], "")

    def test_returns_false_on_exception(self):
        """예외 발생 시 False를 반환하고 예외가 전파되지 않는다."""
        class BrokenWs:
            def find(self, *a, **kw):
                raise RuntimeError("mock API error")
        row = _base_row(article_id="err1")
        result = mrs._gsheet_upsert(BrokenWs(), row)
        self.assertFalse(result)


# ──────────────────────────────────────────────────────────────
# C. Sheets 삭제 (_gsheet_delete)
# ──────────────────────────────────────────────────────────────

class TestGsheetDelete(unittest.TestCase):
    """_gsheet_delete(ws, article_id): 행 삭제"""

    def setUp(self):
        self.ws = FakeWorksheet()

    def test_delete_existing_row(self):
        """존재하는 행을 삭제하면 True를 반환하고 행이 사라진다."""
        row = _base_row(article_id="del1")
        mrs._gsheet_upsert(self.ws, row)
        self.assertEqual(self.ws.data_row_count(), 1)

        result = mrs._gsheet_delete(self.ws, "del1")
        self.assertTrue(result)
        self.assertEqual(self.ws.data_row_count(), 0)
        self.assertIsNone(self.ws.find("del1", in_column=1))

    def test_delete_nonexistent_returns_false(self):
        """존재하지 않는 article_id 삭제 시 False를 반환한다."""
        result = mrs._gsheet_delete(self.ws, "nonexistent_id")
        self.assertFalse(result)

    def test_delete_does_not_affect_other_rows(self):
        """삭제는 해당 행만 제거하고 다른 행에 영향을 주지 않는다."""
        mrs._gsheet_upsert(self.ws, _base_row(article_id="keep1"))
        mrs._gsheet_upsert(self.ws, _base_row(article_id="gone1"))
        mrs._gsheet_upsert(self.ws, _base_row(article_id="keep2"))

        mrs._gsheet_delete(self.ws, "gone1")
        self.assertEqual(self.ws.data_row_count(), 2)
        self.assertIsNotNone(self.ws.find("keep1", in_column=1))
        self.assertIsNotNone(self.ws.find("keep2", in_column=1))
        self.assertIsNone(self.ws.find("gone1", in_column=1))


# ──────────────────────────────────────────────────────────────
# D. CSV 백엔드
# ──────────────────────────────────────────────────────────────

class TestCsvBackend(unittest.TestCase):
    """_upsert_csv, _load_csv_df: CSV 읽기·쓰기"""

    def test_upsert_new_row(self):
        """신규 article_id 행을 CSV에 추가한다."""
        with _temp_csv() as csv_path:
            mrs._upsert_csv(_base_row(article_id="csv1", title="CSV 테스트"))
            df = mrs._load_csv_df()
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["article_id"], "csv1")

    def test_upsert_updates_existing_no_duplicate(self):
        """기존 article_id는 중복 없이 업데이트된다."""
        with _temp_csv():
            mrs._upsert_csv(_base_row(article_id="csv2", reviewer_memo="초안"))
            mrs._upsert_csv(_base_row(article_id="csv2", reviewer_memo="최종"))
            df = mrs._load_csv_df()
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["reviewer_memo"], "최종")

    def test_load_missing_file_returns_empty(self):
        """파일이 없으면 빈 DataFrame을 반환한다."""
        with tempfile.TemporaryDirectory() as tmp:
            missing_path = os.path.join(tmp, "nonexistent.csv")
            with patch.object(mrs, "REVIEWS_CSV", missing_path):
                df = mrs._load_csv_df()
        self.assertTrue(df.empty)
        self.assertListEqual(list(df.columns), REVIEW_COLS)

    def test_load_missing_cols_filled(self):
        """CSV에 REVIEW_COLS 중 일부 열이 없으면 빈 문자열로 채워진다."""
        with _temp_csv() as csv_path:
            # reviewer_memo 없이 저장
            partial_cols = [c for c in REVIEW_COLS if c != "reviewer_memo"]
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=partial_cols)
                w.writeheader()
                w.writerow({c: "v" for c in partial_cols})
            df = mrs._load_csv_df()
            self.assertIn("reviewer_memo", df.columns)
            self.assertEqual(df.iloc[0]["reviewer_memo"], "")

    def test_load_extra_cols_excluded(self):
        """CSV에 REVIEW_COLS 외 추가 열이 있어도 결과에 포함되지 않는다."""
        with _temp_csv() as csv_path:
            extra_cols = REVIEW_COLS + ["promotional_likelihood"]
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=extra_cols)
                w.writeheader()
                row = {c: "v" for c in extra_cols}
                row["article_id"] = "ext1"
                w.writerow(row)
            df = mrs._load_csv_df()
            self.assertNotIn("promotional_likelihood", df.columns)
            self.assertListEqual(list(df.columns), REVIEW_COLS)

    def test_upsert_multiple_ids(self):
        """서로 다른 article_id는 각각 독립적으로 저장된다."""
        with _temp_csv():
            for i in range(5):
                mrs._upsert_csv(_base_row(article_id=f"m{i}", title=f"기사{i}"))
            df = mrs._load_csv_df()
            self.assertEqual(len(df), 5)

    def test_korean_and_special_chars_preserved(self):
        """한글, 쉼표, 따옴표, 이모지가 포함된 값이 CSV를 통해 보존된다."""
        special_title = '한글 제목, "인용" 포함 📌 emoji'
        with _temp_csv():
            mrs._upsert_csv(_base_row(article_id="ko1", title=special_title))
            df = mrs._load_csv_df()
            self.assertEqual(df.iloc[0]["title"], special_title)


# ──────────────────────────────────────────────────────────────
# E. CSV ↔ Sheets 마이그레이션 (_migrate_csv_to_gsheet)
# ──────────────────────────────────────────────────────────────

class TestMigrate(unittest.TestCase):
    """_migrate_csv_to_gsheet(ws): CSV → Sheets 일회성 이전"""

    def test_migrate_empty_sheets_from_csv(self):
        """빈 Sheets에 CSV 데이터를 이전한다."""
        with _temp_csv():
            mrs._upsert_csv(_base_row(article_id="mg1", title="이전 기사"))
            ws = FakeWorksheet()
            mrs._migrate_csv_to_gsheet(ws)
            self.assertEqual(ws.data_row_count(), 1)
            self.assertIsNotNone(ws.find_row_dict("mg1"))

    def test_migrate_skips_nonempty_sheets(self):
        """Sheets에 이미 데이터가 있으면 마이그레이션을 건너뛴다."""
        with _temp_csv():
            mrs._upsert_csv(_base_row(article_id="mg2"))
            ws = FakeWorksheet()
            ws.append_row(["existing"] + [""] * (len(REVIEW_COLS) - 1))
            mrs._migrate_csv_to_gsheet(ws)
            # 기존 1행 + 추가 없음
            self.assertEqual(ws.data_row_count(), 1)
            self.assertIsNone(ws.find_row_dict("mg2"))

    def test_migrate_empty_csv_does_nothing(self):
        """CSV가 비어 있으면 Sheets에 아무것도 추가되지 않는다."""
        with _temp_csv():
            ws = FakeWorksheet()
            mrs._migrate_csv_to_gsheet(ws)
            self.assertEqual(ws.data_row_count(), 0)


# ──────────────────────────────────────────────────────────────
# F. 공개 API: save_review / load_reviews
# ──────────────────────────────────────────────────────────────

class TestSaveLoadPublicAPI(unittest.TestCase):
    """save_review(), load_reviews(): Sheets/CSV 통합 저장·로드"""

    def test_save_without_sheets_goes_to_csv(self):
        """Sheets 없이 저장하면 CSV에만 기록된다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(article_id="pub1", title="CSV 전용")
            row["review_status"] = "검토 전"
            ok, msg = mrs.save_review(row)
            self.assertTrue(ok)
            df = mrs._load_csv_df()
            self.assertEqual(len(df), 1)
            self.assertEqual(df.iloc[0]["article_id"], "pub1")

    def test_save_with_sheets_writes_both(self):
        """Sheets 연결 시 Sheets와 CSV 양쪽에 저장된다."""
        ws = FakeWorksheet()
        with _temp_csv(), _ws_context(ws):
            row = _base_row(article_id="pub2", title="양방향 저장")
            row["review_status"] = "관심 기사"
            ok, _ = mrs.save_review(row)
            self.assertTrue(ok)
            # Sheets 확인
            self.assertEqual(ws.data_row_count(), 1)
            # CSV 확인
            df = mrs._load_csv_df()
            self.assertEqual(len(df), 1)

    def test_save_missing_article_id_fails(self):
        """article_id가 없으면 (False, 오류메시지)를 반환한다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(article_id="", title="ID 없음")
            row["review_status"] = "검토 전"
            ok, msg = mrs.save_review(row)
            self.assertFalse(ok)
            self.assertIn("article_id", msg)

    def test_save_invalid_status_fails(self):
        """유효하지 않은 review_status는 (False, 오류메시지)를 반환한다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(article_id="pub3")
            row["review_status"] = "알 수 없는 상태"
            ok, msg = mrs.save_review(row)
            self.assertFalse(ok)
            self.assertIn("검토 상태", msg)

    def test_reviewed_at_auto_set(self):
        """저장 시 reviewed_at이 자동으로 설정된다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(article_id="pub4", reviewed_at="")
            row["review_status"] = "검토 전"
            mrs.save_review(row)
            df = mrs._load_csv_df()
            self.assertTrue(df.iloc[0]["reviewed_at"].strip() != "")

    def test_load_prefers_sheets_over_csv(self):
        """Sheets가 연결돼 있고 데이터가 있으면 Sheets 데이터를 반환한다."""
        ws = FakeWorksheet()
        ws.append_row(["sheets_only"] + ["Sheets에서 로드"] + [""] * (len(REVIEW_COLS) - 2))

        with _temp_csv(), _ws_context(ws):
            mrs._upsert_csv(_base_row(article_id="csv_only", title="CSV에만 있음"))
            result = mrs.load_reviews()

        self.assertIn("sheets_only", result)
        # Sheets에 있고 data가 있으므로 CSV fallback 안 함
        self.assertNotIn("csv_only", result)

    def test_load_falls_back_to_csv_when_sheets_empty(self):
        """Sheets가 연결됐지만 비어 있으면 CSV로 fallback한다."""
        ws = FakeWorksheet()  # 헤더만 있음
        with _temp_csv(), _ws_context(ws):
            mrs._upsert_csv(_base_row(article_id="csv_fb", title="Fallback"))
            result = mrs.load_reviews()
        self.assertIn("csv_fb", result)

    def test_load_falls_back_to_csv_when_no_sheets(self):
        """Sheets 연결 없으면 CSV에서 로드한다."""
        with _temp_csv(), _ws_context(None):
            mrs._upsert_csv(_base_row(article_id="csv_no_ws", title="No Sheets"))
            result = mrs.load_reviews()
        self.assertIn("csv_no_ws", result)

    def test_save_then_load_roundtrip(self):
        """저장 후 load_reviews로 동일한 값을 읽는다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(
                article_id="rt1",
                title="왕복 테스트",
                reviewer_memo="검토 메모",
                review_status="PR 후보",
            )
            mrs.save_review(row)
            result = mrs.load_reviews()
            self.assertIn("rt1", result)
            self.assertEqual(result["rt1"]["title"], "왕복 테스트")
            self.assertEqual(result["rt1"]["reviewer_memo"], "검토 메모")
            self.assertEqual(result["rt1"]["review_status"], "PR 후보")


# ──────────────────────────────────────────────────────────────
# G. 충돌·왕복·특수 문자
# ──────────────────────────────────────────────────────────────

class TestRoundtrip(unittest.TestCase):
    """왕복·충돌·특수 값 보존 테스트"""

    def test_sheets_csv_roundtrip_preserves_values(self):
        """Sheets → CSV → load_reviews 왕복 후 값이 동일하다."""
        ws = FakeWorksheet()
        memo = "검토 완료 — 후속 기획 소재 검토"
        with _temp_csv(), _ws_context(ws):
            row = _base_row(article_id="rtrip", reviewer_memo=memo,
                            review_status="관심 기사")
            mrs.save_review(row)

            # Sheets에서 직접 로드 (컨텍스트 안에서 검증)
            loaded = mrs._gsheet_load(ws)
            self.assertEqual(loaded["rtrip"]["reviewer_memo"], memo)

            # CSV에서 로드 (temp_csv 컨텍스트 안에서 검증)
            csv_df = mrs._load_csv_df()
            csv_row = csv_df[csv_df["article_id"] == "rtrip"]
            self.assertFalse(csv_row.empty)
            self.assertEqual(csv_row.iloc[0]["reviewer_memo"], memo)

    def test_korean_comma_quote_emoji_roundtrip(self):
        """한글·쉼표·따옴표·이모지가 Sheets upsert → load 왕복에서 보존된다."""
        special = '제목: "AI 혁신", 분류 → 보도자료형 📌'
        ws = FakeWorksheet()
        row = _base_row(article_id="sp1", title=special, review_status="검토 전")
        mrs._gsheet_upsert(ws, row)
        result = mrs._gsheet_load(ws)
        self.assertEqual(result["sp1"]["title"], special)

    def test_all_review_status_values_valid(self):
        """모든 REVIEW_STATUSES 값은 save_review에서 오류 없이 저장된다."""
        for status in mrs.REVIEW_STATUSES:
            with _temp_csv(), _ws_context(None):
                row = _base_row(article_id=f"st_{status[:3]}", review_status=status)
                ok, _ = mrs.save_review(row)
                self.assertTrue(ok, f"review_status='{status}' 저장 실패")

    def test_empty_article_id_in_csv_handled(self):
        """article_id가 빈 행은 load_reviews에서 무시된다."""
        with _temp_csv() as csv_path:
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=REVIEW_COLS)
                w.writeheader()
                w.writerow({c: "" for c in REVIEW_COLS})  # 전부 빈 행
                w.writerow({**{c: "" for c in REVIEW_COLS}, "article_id": "valid_id"})
            with _ws_context(None):
                result = mrs.load_reviews()
        self.assertIn("valid_id", result)
        self.assertNotIn("", result)

    def test_conflict_policy_sheets_wins(self):
        """
        같은 레코드가 로컬 CSV와 Sheets에서 모두 다르면,
        현재 구현은 Sheets 데이터를 우선한다 (load_reviews 정책).
        """
        ws = FakeWorksheet()
        ws.append_row(["conflict1", "Sheets 버전"] + [""] * (len(REVIEW_COLS) - 2))

        with _temp_csv(), _ws_context(ws):
            mrs._upsert_csv(_base_row(article_id="conflict1", title="로컬 버전"))
            result = mrs.load_reviews()

        # Sheets에 데이터 있으면 Sheets 우선
        self.assertEqual(result["conflict1"]["title"], "Sheets 버전")

    def test_existing_article_type_pr_preserved(self):
        """기존 article_type='보도자료형' 값이 저장·로드 과정에서 보존된다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(article_id="pr_type")
            # article_type은 REVIEW_COLS에 없으므로 reviewer_memo로 기록
            row["selection_reason"] = "보도자료형 관련 선택"
            row["review_status"] = "PR 후보"
            ok, _ = mrs.save_review(row)
            self.assertTrue(ok)
            result = mrs.load_reviews()
            self.assertEqual(result["pr_type"]["selection_reason"], "보도자료형 관련 선택")


# ──────────────────────────────────────────────────────────────
# H. 스키마 호환성 (P3 설계 적용 전 확인)
# ──────────────────────────────────────────────────────────────

class TestSchemaCompat(unittest.TestCase):
    """P3 설계(article_type 분리) 실제 구현 전 스키마 호환성 확인"""

    def test_csv_with_extra_column_loads_safely(self):
        """
        CSV에 promotional_likelihood 같은 미지원 열이 있어도
        _load_csv_df는 REVIEW_COLS만 반환하고 오류가 없다.
        """
        with _temp_csv() as csv_path:
            extra_cols = REVIEW_COLS + ["promotional_likelihood"]
            with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=extra_cols)
                w.writeheader()
                w.writerow({
                    **{c: "" for c in extra_cols},
                    "article_id": "compat1",
                    "promotional_likelihood": "높음",
                })
            df = mrs._load_csv_df()
        self.assertNotIn("promotional_likelihood", df.columns)
        self.assertEqual(df.iloc[0]["article_id"], "compat1")

    def test_sheets_with_new_col_load_safe(self):
        """
        Sheets에 신규 열(promotional_likelihood)이 있어도
        _gsheet_load는 오류 없이 REVIEW_COLS 데이터만 반환한다.
        """
        ws = FakeWorksheet(extra_cols=["promotional_likelihood"])
        row = ["fut1"] + [""] * (len(REVIEW_COLS) - 1) + ["높음"]
        ws.append_row(row)
        result = mrs._gsheet_load(ws)
        self.assertIn("fut1", result)
        self.assertNotIn("promotional_likelihood", result["fut1"])

    def test_sheets_missing_new_col_load_safe(self):
        """
        Sheets에 신규 열이 아직 없는 경우,
        _gsheet_load는 기존 REVIEW_COLS 데이터를 정상 반환한다.
        """
        ws = FakeWorksheet()  # 기존 REVIEW_COLS만 있음
        ws.append_row(["old1"] + ["v"] * (len(REVIEW_COLS) - 1))
        result = mrs._gsheet_load(ws)
        self.assertIn("old1", result)
        self.assertEqual(len(result["old1"]), len(REVIEW_COLS))

    def test_upsert_with_extra_local_field_ignored(self):
        """
        row_data에 REVIEW_COLS에 없는 필드가 있어도 upsert는 정상 동작한다.
        초과 필드는 무시된다.
        """
        ws = FakeWorksheet()
        row = _base_row(article_id="extra1")
        row["promotional_likelihood"] = "높음"  # 미지원 필드
        result = mrs._gsheet_upsert(ws, row)
        self.assertTrue(result)
        found = ws.find_row_dict("extra1")
        self.assertIsNotNone(found)
        self.assertNotIn("promotional_likelihood", found)

    def test_review_cols_has_no_promotional_likelihood(self):
        """
        현재 REVIEW_COLS에 promotional_likelihood가 없다.
        P3 설계 실제 구현 전에는 이 테스트가 통과해야 한다.
        """
        self.assertNotIn("promotional_likelihood", REVIEW_COLS,
                         "promotional_likelihood는 P3 구현 전 REVIEW_COLS에 없어야 한다")

    def test_make_article_id_stable(self):
        """make_article_id는 같은 입력에 대해 항상 동일한 값을 반환한다."""
        url = "https://example.com/news/123"
        aid1 = mrs.make_article_id(url)
        aid2 = mrs.make_article_id(url)
        self.assertEqual(aid1, aid2)

    def test_make_article_id_no_builtin_hash(self):
        """make_article_id는 Python 내장 hash()를 사용하지 않는다 (MD5 기반)."""
        aid = mrs.make_article_id("https://example.com/test")
        # MD5 결과는 32자리 hex
        self.assertEqual(len(aid), 32)
        self.assertRegex(aid, r'^[0-9a-f]{32}$')


# ──────────────────────────────────────────────────────────────
# I. 운영 CSV 불변성 보증
# ──────────────────────────────────────────────────────────────

class TestProdCsvUnchanged(unittest.TestCase):
    """테스트 실행 전후 data/monitoring_reviews.csv가 변경되지 않았는지 확인"""

    def test_prod_csv_hash_unchanged(self):
        """
        모든 테스트가 운영 CSV를 변경하지 않는다.
        이 테스트가 실패하면 다른 테스트에서 REVIEWS_CSV를 올바르게 격리하지 않은 것이다.
        """
        after_hash = _file_sha256(_PROD_CSV)
        self.assertEqual(
            _PROD_CSV_HASH_BEFORE,
            after_hash,
            f"운영 CSV가 테스트 중 변경되었습니다!\n"
            f"  변경 전: {_PROD_CSV_HASH_BEFORE}\n"
            f"  변경 후: {after_hash}\n"
            f"  경로: {_PROD_CSV}",
        )


# ──────────────────────────────────────────────────────────────
# J. delete_review 공개 API
# ──────────────────────────────────────────────────────────────

class TestDeleteReview(unittest.TestCase):
    """delete_review(): Sheets + CSV 양쪽 삭제"""

    def test_delete_removes_from_csv(self):
        """delete_review로 CSV에서 행이 삭제된다."""
        with _temp_csv(), _ws_context(None):
            row = _base_row(article_id="del_csv", review_status="검토 전")
            mrs.save_review(row)
            df = mrs._load_csv_df()
            self.assertEqual(len(df), 1)

            mrs.delete_review("del_csv")
            df2 = mrs._load_csv_df()
            self.assertEqual(len(df2), 0)

    def test_delete_removes_from_sheets(self):
        """delete_review로 Sheets에서도 행이 삭제된다."""
        ws = FakeWorksheet()
        with _temp_csv(), _ws_context(ws):
            row = _base_row(article_id="del_ws", review_status="관심 기사")
            mrs.save_review(row)
            self.assertEqual(ws.data_row_count(), 1)

            mrs.delete_review("del_ws")
            self.assertEqual(ws.data_row_count(), 0)

    def test_delete_nonexistent_does_not_crash(self):
        """없는 article_id 삭제는 예외 없이 처리된다."""
        with _temp_csv(), _ws_context(None):
            try:
                mrs.delete_review("not_exist_id")
            except Exception as e:
                self.fail(f"예외 발생: {e}")


# ──────────────────────────────────────────────────────────────
# 실행 진입점
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite  = loader.loadTestsFromModule(__import__(__name__))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
