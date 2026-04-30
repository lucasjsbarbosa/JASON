-- migration 002: handle resolver cache. apply via `jason db init`.
-- Avoids burning YouTube Data API quota re-resolving the same @handles.

CREATE TABLE IF NOT EXISTS handle_cache (
    handle      VARCHAR PRIMARY KEY,    -- lowercased, sem '@', ex: 'horadoterror'
    channel_id  VARCHAR,                -- UC... ou NULL se a API não reconheceu o handle
    resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
