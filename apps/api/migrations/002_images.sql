ALTER TABLE jobs DROP CONSTRAINT jobs_kind_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_kind_check CHECK (kind IN ('SEARCH','COMPARE','OCR'));
CREATE TABLE job_images (
    job_id uuid PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
    image_bytes bytea NOT NULL,
    sha256 text NOT NULL,
    width integer NOT NULL,
    height integer NOT NULL,
    expires_at timestamptz NOT NULL DEFAULT now() + interval '1 hour'
);