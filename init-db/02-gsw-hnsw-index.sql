-- init-db/02-gsw-hnsw-index.sql
-- HNSW index for memory retrieval on gsw_eternal_echoes (cosine; matches <=> in queries).
--
-- On first Docker init the ORM table may not exist yet (app creates schema later).
-- This block is idempotent: no-op with NOTICE if the table is missing.
-- App startup (DatabaseManager._ensure_gsw_hnsw_index) also ensures the index.

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'gsw_eternal_echoes'
    ) THEN
        DROP INDEX IF EXISTS idx_gsw_embedding;

        IF NOT EXISTS (
            SELECT 1
            FROM pg_indexes
            WHERE schemaname = 'public'
              AND tablename = 'gsw_eternal_echoes'
              AND indexname = 'idx_gsw_embedding_hnsw'
        ) THEN
            CREATE INDEX idx_gsw_embedding_hnsw
            ON gsw_eternal_echoes
            USING hnsw (embedding vector_cosine_ops)
            WITH (m = 16, ef_construction = 200)
            WHERE embedding IS NOT NULL;

            RAISE NOTICE 'Created idx_gsw_embedding_hnsw on gsw_eternal_echoes';
        ELSE
            RAISE NOTICE 'idx_gsw_embedding_hnsw already exists';
        END IF;
    ELSE
        RAISE NOTICE 'gsw_eternal_echoes not found; HNSW index deferred to app bootstrap';
    END IF;
END $$;
