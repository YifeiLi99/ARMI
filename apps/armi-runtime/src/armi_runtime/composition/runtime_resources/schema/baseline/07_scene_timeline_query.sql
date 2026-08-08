CREATE TABLE armi.interaction_scenes (
    scene_id uuid PRIMARY KEY CHECK (uuid_extract_version(scene_id) = 7),
    subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
    scene_key text NOT NULL
        CHECK (scene_key ~ '^[a-z0-9][a-z0-9._-]{0,63}$'),
    scene_kind text NOT NULL CHECK (scene_kind = 'creator_dialogue'),
    primary_party_id uuid NOT NULL REFERENCES armi.parties(party_id),
    audience_scope text NOT NULL CHECK (audience_scope = 'creator'),
    current_status text NOT NULL CHECK (current_status IN ('open', 'closed')),
    opened_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    closed_at timestamptz(6),
    recent_context_boundary uuid
        CHECK (
            recent_context_boundary IS NULL
            OR uuid_extract_version(recent_context_boundary) = 7
        ),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (subject_id, scene_key),
    CHECK (
        (current_status = 'open' AND closed_at IS NULL)
        OR (
            current_status = 'closed'
            AND closed_at IS NOT NULL
            AND closed_at >= opened_at
        )
    )
);

CREATE UNIQUE INDEX interaction_scenes_one_default_idx
    ON armi.interaction_scenes (subject_id)
    WHERE scene_key = 'default';

CREATE TABLE armi.scene_timeline_items (
    timeline_item_id uuid PRIMARY KEY
        CHECK (uuid_extract_version(timeline_item_id) = 7),
    scene_id uuid NOT NULL REFERENCES armi.interaction_scenes(scene_id),
    source_kind text NOT NULL
        CHECK (source_kind ~ '^[a-z][a-z0-9._-]{0,63}$'),
    source_ref uuid NOT NULL CHECK (uuid_extract_version(source_ref) = 7),
    source_event_no bigint NOT NULL CHECK (source_event_no > 0),
    result_status text NOT NULL
        CHECK (
            result_status IN (
                'accepted',
                'applied',
                'waiting',
                'rejected',
                'unavailable',
                'failed',
                'unknown',
                'completed'
            )
        ),
    occurred_at timestamptz(6) NOT NULL,
    recorded_at timestamptz(6) NOT NULL DEFAULT statement_timestamp(),
    schema_version smallint NOT NULL DEFAULT 1 CHECK (schema_version = 1),
    UNIQUE (scene_id, source_kind, source_ref, source_event_no)
);

CREATE INDEX scene_timeline_items_page_idx
    ON armi.scene_timeline_items (scene_id, occurred_at DESC, timeline_item_id DESC);

INSERT INTO armi.interaction_scenes (
    scene_id,
    subject_id,
    scene_key,
    scene_kind,
    primary_party_id,
    audience_scope,
    current_status,
    schema_version
)
SELECT
    uuidv7(),
    subject.subject_id,
    'default',
    'creator_dialogue',
    creator.party_id,
    'creator',
    'open',
    1
FROM armi.subjects AS subject
JOIN armi.parties AS creator
    ON creator.party_kind = 'creator'
   AND creator.creator_role = 'unique_primary_creator'
WHERE subject.singleton_key = 1
ON CONFLICT (subject_id, scene_key) DO NOTHING;

REVOKE ALL ON TABLE armi.interaction_scenes, armi.scene_timeline_items
FROM PUBLIC, armi_runtime, armi_admin, armi_migrator;

GRANT SELECT ON TABLE armi.interaction_scenes, armi.scene_timeline_items
TO armi_runtime;

GRANT INSERT (
    scene_id,
    subject_id,
    scene_key,
    scene_kind,
    primary_party_id,
    audience_scope,
    current_status,
    schema_version
) ON armi.interaction_scenes TO armi_runtime;

GRANT UPDATE (current_status, closed_at, recent_context_boundary)
ON armi.interaction_scenes TO armi_runtime;
