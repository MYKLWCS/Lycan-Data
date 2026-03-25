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

-- Vertex labels (node types)
DO $$
DECLARE
    lbl TEXT;
BEGIN
    FOREACH lbl IN ARRAY ARRAY[
        'Person', 'Company', 'Address', 'Phone', 'Email',
        'Property', 'Vehicle', 'Court_Case', 'Social_Profile',
        'Domain', 'Crypto_Wallet'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM ag_catalog.ag_label
            WHERE graph = (SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'osint_graph')
              AND name = lbl
              AND kind = 'v'
        ) THEN
            PERFORM ag_catalog.create_vlabel('osint_graph', lbl);
        END IF;
    END LOOP;
END $$;

-- Edge labels (relationship types)
DO $$
DECLARE
    lbl TEXT;
BEGIN
    FOREACH lbl IN ARRAY ARRAY[
        'OFFICER_OF', 'DIRECTOR_OF', 'OWNS', 'SHAREHOLDER_OF',
        'RELATIVE_OF', 'ASSOCIATE_OF', 'SPOUSE_OF',
        'LIVES_AT', 'LOCATED_AT', 'REGISTERED_AT',
        'HAS_PHONE', 'HAS_EMAIL', 'HAS_DOMAIN',
        'OWNS_PROPERTY', 'OWNS_VEHICLE', 'OWNS_WALLET',
        'PARTY_TO', 'FILED_AGAINST',
        'HAS_PROFILE', 'EMPLOYED_BY', 'SUBSIDIARY_OF',
        'LINKED_TO'
    ] LOOP
        IF NOT EXISTS (
            SELECT 1 FROM ag_catalog.ag_label
            WHERE graph = (SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'osint_graph')
              AND name = lbl
              AND kind = 'e'
        ) THEN
            PERFORM ag_catalog.create_elabel('osint_graph', lbl);
        END IF;
    END LOOP;
END $$;
