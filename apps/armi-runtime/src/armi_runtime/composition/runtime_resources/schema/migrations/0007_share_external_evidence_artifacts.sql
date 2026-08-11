-- Allow distinct accepted inputs with identical content to share one artifact.

ALTER TABLE armi.external_evidence
    DROP CONSTRAINT external_evidence_artifact_key;
