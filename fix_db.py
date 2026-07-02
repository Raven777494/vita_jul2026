
import os
import sys
from sqlalchemy import create_engine, text

# Add project root to path
sys.path.insert(0, os.getcwd())
try:
    from app.config import config
except ImportError:
    # Fallback if app module not found
    sys.path.insert(0, os.path.join(os.getcwd(), 'app'))
    from app.config import config

def fix_db():
    print("="*60)
    print("Vita DB Schema Fixer")
    print("="*60)
    print(f"Target Database: {config.DATABASE_URL}")
    
    try:
        engine = create_engine(config.DATABASE_URL)
        with engine.connect() as conn:
            conn = conn.execution_options(isolation_level="AUTOCOMMIT")
            
            # 1. Check if 'users' table exists
            try:
                conn.execute(text("SELECT 1 FROM users LIMIT 1"))
                print("[OK] 'users' table exists")
            except Exception:
                print("[INFO] 'users' table does not exist. It will be created by SQLAlchemy on app start.")
                # We can trigger creation by importing db_manager
                try:
                    from app.services.db_manager import Base, engine as db_engine
                    Base.metadata.create_all(bind=db_engine)
                    print("[FIX] Tables created via SQLAlchemy.")
                except Exception as e:
                    print(f"[ERROR] Failed to create tables: {e}")
                return

            # 2. Check for 'id' vs 'user_id' column mismatch
            has_id = False
            try:
                conn.execute(text("SELECT id FROM users LIMIT 1"))
                has_id = True
                print("[OK] 'id' column exists")
            except Exception:
                print("[WARN] 'id' column missing.")

            if not has_id:
                try:
                    # Check if user_id exists
                    conn.execute(text("SELECT user_id FROM users LIMIT 1"))
                    print("[INFO] Found old 'user_id' column. Renaming to 'id'...")
                    conn.execute(text("ALTER TABLE users RENAME COLUMN user_id TO id"))
                    print("[FIX] Renamed 'user_id' to 'id'")
                except Exception as e:
                    print(f"[ERROR] Could not find 'user_id' to rename: {e}")
                    print("You may need to drop the table or check schema manually.")

            # 3. Add missing columns
            columns_to_check = [
                ("session_metadata", "JSONB DEFAULT '{}'::jsonb"),
                ("intimacy", "FLOAT DEFAULT 0.0"),
                ("total_turns", "INTEGER DEFAULT 0"),
                ("total_sessions", "INTEGER DEFAULT 0"),
                ("trust_score", "FLOAT DEFAULT 0.0"),
                ("thought_fingerprint", "JSONB DEFAULT '{}'::jsonb"),
                ("dark_triad_scores", "JSONB DEFAULT '{}'::jsonb")
            ]
            
            for col_name, col_def in columns_to_check:
                try:
                    conn.execute(text(f"SELECT {col_name} FROM users LIMIT 1"))
                    print(f"[OK] Column '{col_name}' exists")
                except Exception:
                    print(f"[FIX] Adding missing column: '{col_name}'")
                    try:
                        conn.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                    except Exception as e:
                        print(f"[ERROR] Failed to add {col_name}: {e}")

            print("\n[SUCCESS] Database schema fix completed.")

    except Exception as e:
        print(f"\n[CRITICAL ERROR] Database connection failed: {e}")
        print("Please ensure PostgreSQL is running and credentials in .env are correct.")

if __name__ == "__main__":
    fix_db()
