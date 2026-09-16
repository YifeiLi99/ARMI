-- Attention owns scheduling and request admission, never a duplicate cost ledger.
CREATE TABLE armi.autonomy_plans (
    subject_id uuid PRIMARY KEY REFERENCES armi.subjects(subject_id),
    plan_version bigint NOT NULL CHECK (plan_version > 0),
    policy jsonb NOT NULL CHECK (jsonb_typeof(policy) = 'object'),
    observed_state_epoch bigint NOT NULL CHECK (observed_state_epoch >= 0),
    outlet_state text CHECK (outlet_state IN ('ready','disabled','unbound','unavailable')),
    outlet_reason_code text,
    outlet_observed_at timestamptz,
    CONSTRAINT autonomy_outlet_observation_check CHECK ((outlet_state IS NULL) = (outlet_observed_at IS NULL)),
    next_consideration_at timestamptz NOT NULL,
    source_episode_id uuid REFERENCES armi.cognitive_episodes(cognitive_episode_id),
    opportunity_id uuid REFERENCES armi.opportunities(opportunity_id),
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp()
);

CREATE TABLE armi.autonomy_request_admissions (
    call_id text PRIMARY KEY,
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    root_opportunity_id uuid REFERENCES armi.opportunities(opportunity_id),
    quota_date date NOT NULL,
    registered_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    CONSTRAINT autonomy_request_admissions_call_id_check CHECK (length(call_id) BETWEEN 1 AND 128)
);
CREATE INDEX autonomy_request_admissions_day_idx
    ON armi.autonomy_request_admissions(subject_id, quota_date);
