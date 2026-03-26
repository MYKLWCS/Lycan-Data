-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "age";
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- ── Apache AGE: OSINT Knowledge Graph ────────────────────────────────────────
-- Create the graph if it doesn't already exist.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM ag_catalog.ag_graph WHERE name = 'osint_graph'
    ) THEN
        PERFORM ag_catalog.create_graph('osint_graph');
    END IF;
END $$;

-- Vertex and edge labels are created lazily by AGE on first Cypher use.
