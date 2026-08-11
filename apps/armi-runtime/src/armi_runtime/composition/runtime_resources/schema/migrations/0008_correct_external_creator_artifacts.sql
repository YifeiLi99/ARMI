-- Align existing external Creator inputs with the Creator context contract.

UPDATE armi.artifacts
SET privacy_scope = 'creator_visible'
WHERE logical_kind = 'creator.input.text'
  AND privacy_scope = 'private';
