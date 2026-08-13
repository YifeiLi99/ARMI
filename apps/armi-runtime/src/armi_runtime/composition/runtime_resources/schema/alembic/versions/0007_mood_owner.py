"""Extract mood from Mind into an independent owner."""

from __future__ import annotations

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_OLD_BIRTH_CONTRACT = (
    "sha256:deba3fecb2391c4d24852b9fba27ae3492c261bc559a26058a349611c7522c6b"
)
_NEW_BIRTH_CONTRACT = (
    "sha256:d173571d23ce4295c9706e71988d0463c89439f5c22feb0a63da11da58fa70d2"
)


def upgrade() -> None:
    op.execute(
        f"""
        DO $validation$
        BEGIN
          IF EXISTS (
            SELECT 1
            FROM armi.subject_component_heads AS head
            JOIN armi.subject_component_revisions AS revision
              ON revision.component_revision_id=head.current_revision_id
            WHERE head.component_kind='mind'
              AND (
                jsonb_typeof(revision.semantic_payload) IS DISTINCT FROM 'object'
                OR revision.semantic_payload->>'schema_version'
                   IS DISTINCT FROM 'armi.mind.v1'
                OR (SELECT array_agg(key ORDER BY key)
                    FROM jsonb_object_keys(revision.semantic_payload) AS key)
                   IS DISTINCT FROM ARRAY[
                     'attention','emotions','mood','motivations','schema_version',
                     'thoughts','understanding','wishes'
                   ]::text[]
                OR jsonb_typeof(revision.semantic_payload->'emotions')
                   IS DISTINCT FROM 'array'
                OR jsonb_typeof(revision.semantic_payload->'understanding')
                   IS DISTINCT FROM 'array'
                OR jsonb_typeof(revision.semantic_payload->'attention')
                   IS DISTINCT FROM 'array'
                OR jsonb_typeof(revision.semantic_payload->'thoughts')
                   IS DISTINCT FROM 'array'
                OR jsonb_typeof(revision.semantic_payload->'wishes')
                   IS DISTINCT FROM 'array'
                OR jsonb_typeof(revision.semantic_payload->'motivations')
                   IS DISTINCT FROM 'array'
                OR jsonb_typeof(revision.semantic_payload->'mood')
                   NOT IN ('string','null')
              )
          ) THEN
            RAISE EXCEPTION 'invalid current Mind payload for mood extraction';
          END IF;
          IF EXISTS (
            SELECT 1 FROM armi.runtime_bundle_activations
            WHERE fixed_policy_digest <> '{_OLD_BIRTH_CONTRACT}'
          ) THEN
            RAISE EXCEPTION 'unexpected birth contract digest before mood extraction';
          END IF;
        END
        $validation$;

        CREATE TABLE armi.mood_revisions (
          mood_revision_id uuid PRIMARY KEY,
          subject_id uuid NOT NULL REFERENCES armi.subjects(subject_id),
          mood_version bigint NOT NULL CHECK (mood_version > 0),
          previous_revision_id uuid,
          origin_kind text NOT NULL CHECK (
            origin_kind IN (
              'bootstrap','module_migration','subject_commit','admin_correction'
            )
          ),
          origin_ref uuid NOT NULL CHECK (uuid_extract_version(origin_ref)=7),
          subject_commit_id uuid REFERENCES armi.subject_commits(subject_commit_id),
          proposal_ref text CHECK (
            proposal_ref IS NULL OR proposal_ref ~ '^proposal:[1-9][0-9]{{0,2}}$'
          ),
          semantic_payload jsonb NOT NULL CHECK (
            jsonb_typeof(semantic_payload)='object'
          ),
          privacy_scope text NOT NULL CHECK (privacy_scope='private'),
          created_at timestamp(6) with time zone NOT NULL DEFAULT statement_timestamp(),
          CONSTRAINT mood_revisions_id_check
            CHECK (uuid_extract_version(mood_revision_id)=7),
          CONSTRAINT mood_revisions_subject_version_key
            UNIQUE (subject_id,mood_version),
          CONSTRAINT mood_revisions_owner_key
            UNIQUE (mood_revision_id,subject_id),
          CONSTRAINT mood_revisions_origin_check CHECK (
            (origin_kind IN ('bootstrap','module_migration')
             AND mood_version=1 AND previous_revision_id IS NULL
             AND subject_commit_id IS NULL AND proposal_ref IS NULL)
            OR
            (origin_kind='subject_commit' AND mood_version>1
             AND previous_revision_id IS NOT NULL
             AND subject_commit_id IS NOT NULL AND proposal_ref IS NOT NULL)
            OR
            (origin_kind='admin_correction' AND mood_version>1
             AND previous_revision_id IS NOT NULL
             AND subject_commit_id IS NULL AND proposal_ref IS NULL)
          ),
          CONSTRAINT mood_revisions_payload_check CHECK (
            semantic_payload->>'schema_version'='armi.mood.v1'
            AND semantic_payload ?& ARRAY['emotions','mood','schema_version']
            AND semantic_payload
                - ARRAY['emotions','mood','schema_version']::text[] = '{{}}'::jsonb
            AND jsonb_typeof(semantic_payload->'emotions')='array'
            AND jsonb_typeof(semantic_payload->'mood') IN ('string','null')
          )
        );

        ALTER TABLE armi.mood_revisions
          ADD CONSTRAINT mood_revisions_previous_owner_fkey
          FOREIGN KEY (previous_revision_id,subject_id)
          REFERENCES armi.mood_revisions(mood_revision_id,subject_id);

        CREATE TABLE armi.mood_heads (
          subject_id uuid PRIMARY KEY REFERENCES armi.subjects(subject_id),
          current_revision_id uuid NOT NULL,
          mood_version bigint NOT NULL CHECK (mood_version > 0),
          CONSTRAINT mood_heads_current_owner_fkey
            FOREIGN KEY (current_revision_id,subject_id)
            REFERENCES armi.mood_revisions(mood_revision_id,subject_id)
        );

        CREATE TABLE armi.mood_extract_0007 AS
        SELECT head.subject_id,
               head.current_revision_id AS old_mind_revision_id,
               head.component_version AS old_mind_version,
               uuidv7() AS new_mind_revision_id,
               uuidv7() AS mood_revision_id,
               revision.semantic_payload
        FROM armi.subject_component_heads AS head
        JOIN armi.subject_component_revisions AS revision
          ON revision.component_revision_id=head.current_revision_id
        WHERE head.component_kind='mind';

        INSERT INTO armi.mood_revisions
          (mood_revision_id,subject_id,mood_version,origin_kind,origin_ref,
           semantic_payload,privacy_scope)
        SELECT mood_revision_id,subject_id,1,'module_migration',
               old_mind_revision_id,
               jsonb_build_object(
                 'schema_version','armi.mood.v1',
                 'emotions',semantic_payload->'emotions',
                 'mood',semantic_payload->'mood'
               ),
               'private'
        FROM armi.mood_extract_0007;

        INSERT INTO armi.mood_heads
          (subject_id,current_revision_id,mood_version)
        SELECT subject_id,mood_revision_id,1 FROM armi.mood_extract_0007;

        ALTER TABLE armi.subject_component_revisions
          DROP CONSTRAINT subject_component_revisions_origin_check,
          DROP CONSTRAINT subject_component_revisions_origin_kind_check,
          ADD CONSTRAINT subject_component_revisions_origin_kind_check
            CHECK (origin_kind IN (
              'bootstrap','subject_commit','admin_correction','module_migration'
            )),
          ADD CONSTRAINT subject_component_revisions_origin_check CHECK (
            (origin_kind='bootstrap' AND component_version=1
             AND previous_revision_id IS NULL AND subject_commit_id IS NULL
             AND proposal_ref IS NULL)
            OR
            (origin_kind='subject_commit' AND component_version>1
             AND previous_revision_id IS NOT NULL AND subject_commit_id IS NOT NULL
             AND proposal_ref IS NOT NULL)
            OR
            (origin_kind='admin_correction' AND component_version>1
             AND previous_revision_id IS NOT NULL AND subject_commit_id IS NULL
             AND proposal_ref IS NULL)
            OR
            (origin_kind='module_migration' AND component_version>1
             AND previous_revision_id IS NOT NULL AND subject_commit_id IS NULL
             AND proposal_ref IS NULL)
          );

        INSERT INTO armi.subject_component_revisions
          (component_revision_id,subject_id,component_kind,component_version,
           previous_revision_id,origin_kind,origin_ref,semantic_payload,
           privacy_scope)
        SELECT new_mind_revision_id,subject_id,'mind',old_mind_version+1,
               old_mind_revision_id,'module_migration',old_mind_revision_id,
               (semantic_payload - 'emotions' - 'mood') ||
                 '{{"schema_version":"armi.mind.v2"}}'::jsonb,
               'private'
        FROM armi.mood_extract_0007;

        UPDATE armi.subject_component_heads AS head
        SET current_revision_id=source.new_mind_revision_id,
            component_version=source.old_mind_version+1
        FROM armi.mood_extract_0007 AS source
        WHERE head.subject_id=source.subject_id AND head.component_kind='mind';

        DROP TABLE armi.mood_extract_0007;

        ALTER TABLE armi.cognitive_context_items
          DROP CONSTRAINT cognitive_context_items_section_check,
          ADD CONSTRAINT cognitive_context_items_section_check CHECK (
            section IN (
              'runtime_truth','purpose','self','mind','mood','life_mode','scene',
              'relationship','memory','activity','material','evidence',
              'capability','prompt'
            )
          );

        ALTER TABLE armi.cognitive_candidate_validation_items
          DROP CONSTRAINT cognitive_candidate_validation_items_owner_kind_check,
          ADD CONSTRAINT cognitive_candidate_validation_items_owner_kind_check CHECK (
            owner_kind IN (
              'experience','self','mind','mood','life_mode','memory',
              'relationship','activity','capability','action','web_research',
              'codex_delegation','sleep','material','prompt','exact_life_query',
              'maintenance'
            )
          );

        UPDATE armi.runtime_bundle_activations
        SET fixed_policy_digest='{_NEW_BIRTH_CONTRACT}'
        WHERE fixed_policy_digest='{_OLD_BIRTH_CONTRACT}';

        CREATE INDEX mood_revisions_subject_created_idx
          ON armi.mood_revisions(subject_id,created_at DESC,mood_revision_id DESC);

        GRANT SELECT ON TABLE armi.mood_heads, armi.mood_revisions
          TO armi_runtime, armi_admin;
        GRANT INSERT, UPDATE ON TABLE armi.mood_heads TO armi_runtime;
        GRANT INSERT ON TABLE armi.mood_revisions TO armi_runtime;
        GRANT UPDATE ON TABLE armi.mood_heads TO armi_admin;
        GRANT INSERT ON TABLE armi.mood_revisions TO armi_admin;
        """
    )


def downgrade() -> None:
    raise RuntimeError("ARMI database revisions are forward-only")
