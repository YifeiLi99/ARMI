-- Attention owns two-stage scheduling. Provider owners retain physical call usage.
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
    updated_at timestamptz NOT NULL DEFAULT statement_timestamp(),
    phase text NOT NULL DEFAULT 'waiting' CHECK (phase IN ('waiting','check','execute','blocked')),
    idle_streak integer NOT NULL DEFAULT 0 CHECK (idle_streak BETWEEN 0 AND 2),
    failure_streak integer NOT NULL DEFAULT 0 CHECK (failure_streak BETWEEN 0 AND 3),
    last_check_started_at timestamptz,
    last_event_at timestamptz,
    last_engage boolean,
    blocked_reason_code text,
    model_configuration_revision text
);
