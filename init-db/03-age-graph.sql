-- init-db/03-age-graph.sql
-- Apache AGE graph shell (read-only reserve per ADR-002).
-- Primary app memory writes: gsw_eternal_echoes (pgvector) + memory_graph table.
-- No runtime cypher writes until a future ADR re-opens AGE as a write path.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'age') THEN
        RAISE NOTICE 'AGE extension not installed; skip graph creation';
        RETURN;
    END IF;

    LOAD 'age';
    PERFORM set_config('search_path', 'ag_catalog, "$user", public', false);

    IF EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'vita_memory_graph'
    ) THEN
        RAISE NOTICE 'AGE graph vita_memory_graph already exists';
    ELSE
        PERFORM create_graph('vita_memory_graph');
        RAISE NOTICE 'Created AGE graph vita_memory_graph';
    END IF;
EXCEPTION
    WHEN undefined_table THEN
        RAISE NOTICE 'AGE catalog unavailable; graph creation deferred to app bootstrap';
    WHEN duplicate_object THEN
        RAISE NOTICE 'AGE graph vita_memory_graph already exists (duplicate_object)';
    WHEN OTHERS THEN
        RAISE NOTICE 'AGE graph setup skipped: %', SQLERRM;
END $$;
