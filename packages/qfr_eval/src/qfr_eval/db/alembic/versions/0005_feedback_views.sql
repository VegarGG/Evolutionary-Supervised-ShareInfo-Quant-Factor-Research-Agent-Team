ALTER TABLE eval.released_reports
 ADD COLUMN release_seq bigint GENERATED ALWAYS AS IDENTITY UNIQUE;
GRANT USAGE ON SEQUENCE eval.released_reports_release_seq_seq TO eval_rw;
CREATE OR REPLACE VIEW feedback.released_reports_v WITH(security_barrier=true) AS
 SELECT r.id,r.artifact_version_id,r.content_hash,r.protocol_version,r.dataset_version_id,
 r.evaluator_version,r.payload AS released_content,r.created_at,r.release_seq
 FROM eval.released_reports r JOIN eval.release_publications p ON p.id=r.id
 JOIN eval.release_queue q ON q.id=p.queue_id AND q.published_report_id=r.id
 WHERE q.state='published' AND q.eligible_at<=clock_timestamp() AND r.payload->>'program_id'=ANY(string_to_array(
   coalesce(current_setting('qfr.program_ids',true),''),','));
CREATE OR REPLACE VIEW feedback.artifact_status_v WITH(security_barrier=true) AS
 SELECT DISTINCT ON (r.artifact_version_id) r.id,r.artifact_version_id,
 r.payload->'content'->>'type' AS status,r.created_at
 FROM eval.released_reports r JOIN eval.release_publications p ON p.id=r.id
 JOIN eval.release_queue q ON q.id=p.queue_id AND q.published_report_id=r.id
 WHERE q.state='published' AND q.eligible_at<=clock_timestamp() AND r.payload->>'program_id'=ANY(string_to_array(
   coalesce(current_setting('qfr.program_ids',true),''),','))
 ORDER BY r.artifact_version_id,r.release_seq DESC;
CREATE OR REPLACE VIEW feedback.library_v WITH(security_barrier=true) AS
 SELECT r.id,r.payload->'identity'->>'artifact_version_id' AS artifact_version_id,
 r.payload->'content'->>'membership' AS membership
 FROM eval.released_reports r JOIN eval.release_publications p ON p.id=r.id
 JOIN eval.release_queue q ON q.id=p.queue_id AND q.published_report_id=r.id
 WHERE q.state='published' AND q.eligible_at<=clock_timestamp() AND r.payload->'content'->>'type'='library'
 AND r.payload->>'program_id'=ANY(string_to_array(
   coalesce(current_setting('qfr.program_ids',true),''),','));
ALTER TABLE eval.public_policy_cards ADD COLUMN card_ref text UNIQUE,
 ADD COLUMN content_sha256 text,
 ADD CONSTRAINT policy_card_metadata CHECK(card_ref IS NOT NULL AND length(card_ref)>0
  AND content_sha256 IS NOT NULL AND content_sha256 ~ '^[0-9a-f]{64}$') NOT VALID;
ALTER TABLE eval.public_protocol_cards ADD COLUMN card_ref text UNIQUE,
 ADD COLUMN content_sha256 text,
 ADD CONSTRAINT protocol_card_metadata CHECK(card_ref IS NOT NULL AND length(card_ref)>0
  AND content_sha256 IS NOT NULL AND content_sha256 ~ '^[0-9a-f]{64}$') NOT VALID;
CREATE OR REPLACE VIEW feedback.policy_card_v WITH(security_barrier=true) AS
 SELECT id,payload,card_ref,content_sha256 FROM eval.public_policy_cards WHERE card_ref IS NOT NULL;
CREATE OR REPLACE VIEW feedback.protocol_card_v WITH(security_barrier=true) AS
 SELECT id,payload,card_ref,content_sha256 FROM eval.public_protocol_cards WHERE card_ref IS NOT NULL;
