"""
기존 trends.db 데이터를 구글 시트로 한 번에 이전하는 스크립트.
구글 연결 설정(credentials.json + GOOGLE_SHEET_ID)이 완료된 뒤에 실행하세요.
"""
import os
import sys

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DB_PATH = os.path.join(os.path.dirname(__file__), "trends.db")


def main():
    print("=" * 54)
    print("  trends.db  →  구글 시트 데이터 이전")
    print("=" * 54)

    from sheets_sync import sync_all_from_db, is_configured

    if not is_configured():
        print()
        print("❌ 구글 시트 연결 설정이 아직 완료되지 않았습니다.")
        print()
        print("아래 두 가지가 모두 있어야 합니다:")
        print("  1. 이 폴더 안에  credentials.json  파일")
        print("  2. .env 파일 안에  GOOGLE_SHEET_ID=...")
        print()
        print("가이드를 따라 설정을 마친 후 다시 실행해 주세요.")
        return

    if not os.path.exists(DB_PATH):
        print(f"\n❌ trends.db 파일이 없습니다: {DB_PATH}")
        return

    print(f"\n  DB 파일: {DB_PATH}")
    print("  구글 시트로 업로드 중... (잠시 기다려 주세요)")

    try:
        count = sync_all_from_db(DB_PATH)
        print(f"\n  ✅ 완료!  {count}건이 구글 시트에 저장됐습니다.")
        print()
        print("  이제 구글 시트를 열어서 'trends' 탭을 확인해 보세요.")
        print("  앞으로 collector.py 를 실행하면 새 데이터가 자동으로 추가됩니다.")
    except FileNotFoundError as e:
        print(f"\n❌ {e}")
    except ValueError as e:
        print(f"\n❌ {e}")
    except Exception as e:
        print(f"\n❌ 예상치 못한 오류 — Claude 에게 아래 내용을 알려주세요:")
        print(f"   {e}")


if __name__ == "__main__":
    main()
