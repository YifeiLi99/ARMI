-- Current ARMI schema tables owned by this baseline module.

--
-- Name: life_material_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.life_material_revisions (
    life_material_revision_id uuid NOT NULL,
    life_material_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    artifact_id uuid NOT NULL,
    title text NOT NULL,
    metadata jsonb NOT NULL,
    revision_kind text NOT NULL,
    privacy_status text NOT NULL,
    material_status text NOT NULL,
    source_kind text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT life_material_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL) AND (revision_kind = 'created'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL) AND (revision_kind = ANY (ARRAY['updated'::text, 'privacy_changed'::text, 'deleted'::text]))))),
    CONSTRAINT life_material_revisions_check1 CHECK ((((revision_kind = 'created'::text) AND (privacy_status = 'creator_visible'::text)) OR ((revision_kind = 'updated'::text) AND (privacy_status = ANY (ARRAY['creator_visible'::text, 'private'::text]))) OR ((revision_kind = 'privacy_changed'::text) AND (privacy_status = ANY (ARRAY['creator_visible'::text, 'private'::text]))) OR ((revision_kind = 'deleted'::text) AND (privacy_status = 'restricted'::text)))),
    CONSTRAINT life_material_revisions_life_material_revision_id_check CHECK ((uuid_extract_version(life_material_revision_id) = 7)),
    CONSTRAINT life_material_revisions_material_status_check CHECK ((material_status = ANY (ARRAY['active'::text, 'archived'::text]))),
    CONSTRAINT life_material_revisions_metadata_check CHECK (((jsonb_typeof(metadata) = 'object'::text) AND (jsonb_array_length(jsonb_path_query_array(metadata, '$.keyvalue()'::jsonpath)) <= 32))),
    CONSTRAINT life_material_revisions_privacy_status_check CHECK ((privacy_status = ANY (ARRAY['creator_visible'::text, 'private'::text, 'shared'::text, 'restricted'::text]))),
    CONSTRAINT life_material_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT life_material_revisions_revision_kind_check CHECK ((revision_kind = ANY (ARRAY['created'::text, 'updated'::text, 'privacy_changed'::text, 'deleted'::text]))),
    CONSTRAINT life_material_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT life_material_revisions_source_kind_check CHECK ((source_kind = 'subject_cognition'::text)),
    CONSTRAINT life_material_revisions_title_check CHECK (((length(title) >= 1) AND (length(title) <= 256)))
);

--
-- Name: life_materials; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.life_materials (
    life_material_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    material_kind text NOT NULL,
    owner_party_id uuid NOT NULL,
    current_revision_id uuid NOT NULL,
    head_version bigint NOT NULL,
    deleted_at timestamp(6) with time zone,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    updated_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT life_materials_current_revision_id_check CHECK ((uuid_extract_version(current_revision_id) = 7)),
    CONSTRAINT life_materials_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT life_materials_life_material_id_check CHECK ((uuid_extract_version(life_material_id) = 7)),
    CONSTRAINT life_materials_material_kind_check CHECK ((material_kind = ANY (ARRAY['diary'::text, 'work'::text, 'collection'::text, 'draft'::text])))
);

--
-- Name: memory_relations; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.memory_relations (
    memory_relation_id uuid NOT NULL,
    from_memory_id uuid NOT NULL,
    from_memory_revision_id uuid NOT NULL,
    to_memory_id uuid NOT NULL,
    relation_kind text NOT NULL,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT memory_relations_check CHECK ((from_memory_id <> to_memory_id)),
    CONSTRAINT memory_relations_memory_relation_id_check CHECK ((uuid_extract_version(memory_relation_id) = 7)),
    CONSTRAINT memory_relations_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT memory_relations_relation_kind_check CHECK ((relation_kind = ANY (ARRAY['supports'::text, 'contradicts'::text, 'reinterprets'::text])))
);

--
-- Name: relationship_experience_links; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.relationship_experience_links (
    relationship_revision_id uuid NOT NULL,
    experience_id uuid NOT NULL,
    link_kind text NOT NULL,
    ordinal smallint NOT NULL,
    CONSTRAINT relationship_experience_links_link_kind_check CHECK ((link_kind = ANY (ARRAY['supports_relationship_change'::text, 'supports_commitment_event'::text]))),
    CONSTRAINT relationship_experience_links_ordinal_check CHECK ((ordinal > 0))
);

--
-- Name: relationship_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.relationship_revisions (
    relationship_revision_id uuid NOT NULL,
    relationship_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    facts jsonb NOT NULL,
    interpretation text NOT NULL,
    boundaries jsonb NOT NULL,
    commitments jsonb NOT NULL,
    open_issues jsonb NOT NULL,
    commitment_event jsonb,
    relationship_status text NOT NULL,
    mechanism_identity text NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    issue_resolution jsonb,
    CONSTRAINT relationship_revisions_boundaries_check CHECK (((jsonb_typeof(boundaries) = 'array'::text) AND (jsonb_array_length(boundaries) <= 16))),
    CONSTRAINT relationship_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL)))),
    CONSTRAINT relationship_revisions_commitment_event_check CHECK (((commitment_event IS NULL) OR (jsonb_typeof(commitment_event) = 'object'::text))),
    CONSTRAINT relationship_revisions_commitments_check CHECK (((jsonb_typeof(commitments) = 'array'::text) AND (jsonb_array_length(commitments) <= 16))),
    CONSTRAINT relationship_revisions_facts_check CHECK (((jsonb_typeof(facts) = 'array'::text) AND ((jsonb_array_length(facts) >= 1) AND (jsonb_array_length(facts) <= 64)))),
    CONSTRAINT relationship_revisions_interpretation_check CHECK (((length(interpretation) >= 1) AND (length(interpretation) <= 1024))),
    CONSTRAINT relationship_revisions_issue_resolution_check CHECK (((issue_resolution IS NULL) OR ((jsonb_typeof(issue_resolution) = 'object'::text) AND (issue_resolution ?& ARRAY['issue_id'::text, 'resolution_summary'::text, 'status'::text]) AND ((issue_resolution - ARRAY['issue_id'::text, 'resolution_summary'::text, 'status'::text]) = '{}'::jsonb) AND ((issue_resolution ->> 'status'::text) = 'resolved'::text) AND (((issue_resolution ->> 'issue_id'::text))::uuid IS NOT NULL) AND (uuid_extract_version(((issue_resolution ->> 'issue_id'::text))::uuid) = 7) AND ((length((issue_resolution ->> 'resolution_summary'::text)) >= 1) AND (length((issue_resolution ->> 'resolution_summary'::text)) <= 512))))),
    CONSTRAINT relationship_revisions_mechanism_identity_check CHECK ((mechanism_identity = ANY (ARRAY['armi.relationship.contextual-v1'::text, 'armi.relationship.lifecycle-v2'::text]))),
    CONSTRAINT relationship_revisions_open_issues_check CHECK (((jsonb_typeof(open_issues) = 'array'::text) AND (jsonb_array_length(open_issues) <= 32))),
    CONSTRAINT relationship_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT relationship_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT relationship_revisions_relationship_revision_id_check CHECK ((uuid_extract_version(relationship_revision_id) = 7)),
    CONSTRAINT relationship_revisions_relationship_status_check CHECK ((relationship_status = ANY (ARRAY['active'::text, 'ended'::text]))),
    CONSTRAINT relationship_revisions_revision_no_check CHECK ((revision_no > 0))
);

--
-- Name: relationships; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.relationships (
    relationship_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    subject_party_id uuid NOT NULL,
    other_party_id uuid NOT NULL,
    scope text NOT NULL,
    current_revision_id uuid NOT NULL,
    head_version bigint NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    tombstoned_at timestamp(6) with time zone,
    tombstone_order_id uuid,
    CONSTRAINT relationships_check CHECK ((subject_party_id <> other_party_id)),
    CONSTRAINT relationships_current_revision_id_check CHECK ((uuid_extract_version(current_revision_id) = 7)),
    CONSTRAINT relationships_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT relationships_relationship_id_check CHECK ((uuid_extract_version(relationship_id) = 7)),
    CONSTRAINT relationships_scope_check CHECK ((scope = ANY (ARRAY['creator_social'::text, 'other_human_social'::text]))),
    CONSTRAINT relationships_tombstone_order_id_check CHECK (((tombstone_order_id IS NULL) OR (uuid_extract_version(tombstone_order_id) = 7))),
    CONSTRAINT relationships_tombstone_pair_check CHECK (((tombstoned_at IS NULL) = (tombstone_order_id IS NULL)))
);

--
-- Name: subjective_memories; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subjective_memories (
    memory_id uuid NOT NULL,
    subject_id uuid NOT NULL,
    life_generation_id uuid NOT NULL,
    current_revision_id uuid NOT NULL,
    head_version bigint NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT subjective_memories_current_revision_id_check CHECK ((uuid_extract_version(current_revision_id) = 7)),
    CONSTRAINT subjective_memories_head_version_check CHECK ((head_version > 0)),
    CONSTRAINT subjective_memories_memory_id_check CHECK ((uuid_extract_version(memory_id) = 7))
);

--
-- Name: subjective_memory_revisions; Type: TABLE; Schema: armi; Owner: -
--

CREATE TABLE armi.subjective_memory_revisions (
    memory_revision_id uuid NOT NULL,
    memory_id uuid NOT NULL,
    revision_no bigint NOT NULL,
    previous_revision_id uuid,
    subject_commit_id uuid NOT NULL,
    candidate_validation_id uuid NOT NULL,
    proposal_ref text NOT NULL,
    source_experience_id uuid NOT NULL,
    source_kind text NOT NULL,
    source_fact_class text NOT NULL,
    summary text NOT NULL,
    uncertainty text,
    revision_kind text NOT NULL,
    accessibility text NOT NULL,
    mechanism_identity text NOT NULL,
    mechanism_config_identity text NOT NULL,
    privacy_scope text NOT NULL,
    created_at timestamp(6) with time zone DEFAULT statement_timestamp() NOT NULL,
    CONSTRAINT subjective_memory_revisions_accessibility_check CHECK ((accessibility = ANY (ARRAY['available'::text, 'faded'::text, 'forgotten'::text]))),
    CONSTRAINT subjective_memory_revisions_check CHECK ((((revision_no = 1) AND (previous_revision_id IS NULL) AND (revision_kind = 'formed'::text) AND (accessibility = 'available'::text) AND (mechanism_identity = 'armi.memory-formation.contextual-v1'::text) AND (mechanism_config_identity = 'formation-v1'::text)) OR ((revision_no > 1) AND (previous_revision_id IS NOT NULL) AND (revision_kind <> 'formed'::text) AND (mechanism_identity = 'armi.memory-revision.contextual-v1'::text) AND (mechanism_config_identity = ANY (ARRAY['natural-dialogue-v1'::text, 'sleep-maintenance-v1'::text]))))),
    CONSTRAINT subjective_memory_revisions_check1 CHECK ((((revision_kind = ANY (ARRAY['formed'::text, 'recalled'::text])) AND (accessibility = 'available'::text)) OR ((revision_kind = 'faded'::text) AND (accessibility = 'faded'::text)) OR ((revision_kind = 'forgotten'::text) AND (accessibility = 'forgotten'::text)) OR ((revision_kind = 'reinterpreted'::text) AND (accessibility = ANY (ARRAY['available'::text, 'faded'::text]))))),
    CONSTRAINT subjective_memory_revisions_check2 CHECK ((((source_kind = 'reported'::text) AND (source_fact_class = 'external_claim'::text)) OR ((source_kind = 'inferred'::text) AND (source_fact_class = 'inference'::text)) OR ((source_kind = 'queried'::text) AND (source_fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text]))) OR ((source_kind = 'unknown'::text) AND (source_fact_class = 'unknown'::text)) OR ((source_kind = 'experienced'::text) AND (source_fact_class = ANY (ARRAY['objective_fact'::text, 'subjective_understanding'::text]))))),
    CONSTRAINT subjective_memory_revisions_mechanism_config_identity_check CHECK ((mechanism_config_identity = ANY (ARRAY['formation-v1'::text, 'natural-dialogue-v1'::text, 'sleep-maintenance-v1'::text]))),
    CONSTRAINT subjective_memory_revisions_mechanism_identity_check CHECK ((mechanism_identity = ANY (ARRAY['armi.memory-formation.contextual-v1'::text, 'armi.memory-revision.contextual-v1'::text]))),
    CONSTRAINT subjective_memory_revisions_memory_revision_id_check CHECK ((uuid_extract_version(memory_revision_id) = 7)),
    CONSTRAINT subjective_memory_revisions_privacy_scope_check CHECK ((privacy_scope = 'private'::text)),
    CONSTRAINT subjective_memory_revisions_proposal_ref_check CHECK ((proposal_ref ~ '^proposal:[1-9][0-9]{0,2}$'::text)),
    CONSTRAINT subjective_memory_revisions_revision_kind_check CHECK ((revision_kind = ANY (ARRAY['formed'::text, 'recalled'::text, 'faded'::text, 'forgotten'::text, 'reinterpreted'::text]))),
    CONSTRAINT subjective_memory_revisions_revision_no_check CHECK ((revision_no > 0)),
    CONSTRAINT subjective_memory_revisions_source_fact_class_check CHECK ((source_fact_class = ANY (ARRAY['objective_fact'::text, 'external_claim'::text, 'subjective_understanding'::text, 'inference'::text, 'unknown'::text]))),
    CONSTRAINT subjective_memory_revisions_source_kind_check CHECK ((source_kind = ANY (ARRAY['experienced'::text, 'reported'::text, 'inferred'::text, 'queried'::text, 'unknown'::text]))),
    CONSTRAINT subjective_memory_revisions_summary_check CHECK (((length(summary) >= 1) AND (length(summary) <= 512))),
    CONSTRAINT subjective_memory_revisions_uncertainty_check CHECK (((uncertainty IS NULL) OR ((length(uncertainty) >= 1) AND (length(uncertainty) <= 512))))
);
