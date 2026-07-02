# check_db.py
from sqlalchemy import inspect, text
from app.services.db_manager import sync_engine as engine, Base

def run_deep_diagnostics():
    print("\n" + "═"*60)
    print(" 🏥 VITA 系統資料庫深度診斷報告 (Deep Diagnostics)")
    print("═"*60)

    # 初始化檢查器
    inspector = inspect(engine)
    db_tables = set(inspector.get_table_names())
    model_tables = set(Base.metadata.tables.keys())
    
    missing_in_db = model_tables - db_tables
    unmapped_in_db = db_tables - model_tables

    # ==========================================
    # 1. 映射對齊檢查
    # ==========================================
    print("\n 🗄️ [第一階段] ORM 模型與資料庫對齊檢查")
    print("-" * 60)
    print(f" 📝 程式碼定義了 {len(model_tables)} 張表")
    print(f" 📦 資料庫實際有 {len(db_tables)} 張表")

    if missing_in_db:
        print(f"\n ❌ [警告] 以下表格在程式碼有定義，但資料庫還沒建立：")
        for t in missing_in_db:
            print(f"    - {t}")
    else:
        print("\n ✅ 基礎對齊：程式碼定義的表格，資料庫裡全部都有！")

    # ==========================================
    # 2. 核心記憶與向量欄位檢查 (pgvector)
    # ==========================================
    print("\n 🧬 [第二階段] 核心記憶與 Vector 向量結構檢查")
    print("-" * 60)
    
    # 需要檢查向量的關鍵表格
    vector_tables = ['gsw_eternal_echoes', 'turns', 'risk_assessments']
    
    for table in vector_tables:
        if table in db_tables:
            columns = inspector.get_columns(table)
            has_vector = False
            print(f" [CHECK] table [{table}]:")
            for col in columns:
                col_type = str(col['type'])
                if 'VECTOR' in col_type.upper() or 'EMBEDDING' in col['name'].upper():
                    print(f"    field: {col['name']:<15} | type: {col_type}")
                    if 'VECTOR' in col_type.upper():
                        has_vector = True

            if has_vector:
                print("    status: OK (pgvector column present)")
            else:
                print("    status: FAIL (no VECTOR column)")

            if table == 'gsw_eternal_echoes':
                indexes = inspector.get_indexes(table)
                index_names = {idx['name'] for idx in indexes}
                if 'idx_gsw_embedding_hnsw' in index_names:
                    print("    index:  OK (idx_gsw_embedding_hnsw HNSW)")
                elif 'idx_gsw_embedding' in index_names:
                    print("    index:  WARN (legacy IVFFlat idx_gsw_embedding; restart app to migrate)")
                else:
                    print("    index:  WARN (no vector index; restart app to create HNSW)")
        else:
            print(f" [CHECK] missing table [{table}]")

    print("\n [PHASE 2b] PostgreSQL extensions (vector / age / pg_cron)")
    print("-" * 60)
    with engine.connect() as conn:
        ext_rows = conn.execute(
            text(
                "SELECT extname, extversion FROM pg_extension "
                "WHERE extname IN ('vector', 'age', 'pg_cron') ORDER BY extname"
            )
        ).fetchall()
    installed = {row[0]: row[1] for row in ext_rows}
    for ext_name in ("vector", "age", "pg_cron"):
        if ext_name in installed:
            print(f" [OK]   {ext_name}: v{installed[ext_name]}")
        else:
            level = "FAIL" if ext_name == "vector" else "WARN"
            hint = " (rebuild: docker compose build postgres && docker compose up -d postgres)"
            print(f" [{level}]  {ext_name}: not installed{hint if ext_name != 'vector' else ''}")

    if "age" in installed:
        try:
            with engine.connect() as conn:
                graph_rows = conn.execute(
                    text("SELECT name FROM ag_catalog.ag_graph WHERE name = 'vita_memory_graph'")
                ).fetchall()
            if graph_rows:
                print(" [OK]   AGE graph vita_memory_graph present")
            else:
                print(" [WARN] AGE graph vita_memory_graph missing (restart app to create)")
        except Exception as exc:
            print(f" [WARN] AGE graph check failed: {exc}")

    # ==========================================
    # 3. 資料庫內容掃描與清理建議
    # ==========================================
    print("\n 📊 [第三階段] 資料筆數透視與舊表清理建議")
    print("-" * 60)
    
    with engine.connect() as conn:
        print(" 【使用中的核心表 (Mapped Tables)】")
        for table in sorted(model_tables.intersection(db_tables)):
            try:
                count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                print(f"  🟢 {table:<25} : {count:>5} 筆")
            except Exception:
                print(f"  🔴 {table:<25} : 無法讀取")

        print("\n 【未映射的舊表格 (Unmapped Tables)】")
        if not unmapped_in_db:
            print("  ✅ 沒有多餘的垃圾表格，資料庫非常乾淨！")
        else:
            for table in sorted(unmapped_in_db):
                # 如果是你特別需要保留的，可以略過警告
                if table == 'gsw_eternal_echoes':
                    try:
                        count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                        print(f"  🔵 {table:<25} : {count:>5} 筆 (GSW 記憶表，請保留)")
                    except Exception:
                        pass
                    continue
                    
                try:
                    count = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar()
                    if count == 0:
                        print(f"  ⚪ {table:<25} : {count:>5} 筆 🗑️ (空表，建議 DROP)")
                    else:
                        print(f"  🟡 {table:<25} : {count:>5} 筆 ⚠️ (有舊資料！請確認是否要 DROP)")
                except Exception:
                    print(f"  🔴 {table:<25} : 無法讀取")

    print("\n" + "═"*60)
    print(" 🏁 診斷結束")
    print("═"*60 + "\n")

if __name__ == "__main__":
    run_deep_diagnostics()