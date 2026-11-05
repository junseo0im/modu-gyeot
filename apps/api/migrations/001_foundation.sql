CREATE TABLE IF NOT EXISTS sessions (
    token_hash text PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '7 days'
);
CREATE TABLE IF NOT EXISTS jobs (
    id uuid PRIMARY KEY,
    owner_hash text NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,
    request_key text NOT NULL,
    request_hash text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('SEARCH','COMPARE')),
    status text NOT NULL CHECK (status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
    payload jsonb NOT NULL,
    result jsonb,
    error_code text,
    attempts integer NOT NULL DEFAULT 0,
    lease_token uuid,
    lease_until timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT now() + interval '24 hours',
    UNIQUE(owner_hash, request_key)
);
CREATE INDEX IF NOT EXISTS jobs_queue ON jobs(created_at) WHERE status='QUEUED';
CREATE INDEX IF NOT EXISTS jobs_owner ON jobs(owner_hash, created_at DESC);
CREATE TABLE IF NOT EXISTS call_budget (
    id bigserial PRIMARY KEY,
    kind text NOT NULL,
    units integer NOT NULL,
    reserved_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS call_budget_time ON call_budget(reserved_at);