
-- public.users definition

-- Drop table

-- DROP TABLE public.users;

CREATE TABLE public.users (
	id varchar(36) NOT NULL,
	email varchar(255) NOT NULL,
	hashed_password varchar(255) NOT NULL,
	display_name varchar(100) NULL,
	is_active bool NOT NULL,
	is_superuser bool NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT users_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_users_email ON public.users USING btree (email);

-- public.alembic_version definition

-- Drop table

-- DROP TABLE public.alembic_version;

CREATE TABLE public.alembic_version (
	version_num varchar(128) NOT NULL,
	CONSTRAINT alembic_version_pkey PRIMARY KEY (version_num)
);



-- public.audit_logs definition

-- Drop table

-- DROP TABLE public.audit_logs;

CREATE TABLE public.audit_logs (
	id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	"action" varchar(64) NOT NULL,
	resource_type varchar(64) NOT NULL,
	resource_id varchar(64) NULL,
	payload_json text NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT audit_logs_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_audit_logs_action ON public.audit_logs USING btree (action);
CREATE INDEX ix_audit_logs_resource_type ON public.audit_logs USING btree (resource_type);
CREATE INDEX ix_audit_logs_user_id ON public.audit_logs USING btree (user_id);



-- public.chat_sessions definition

-- Drop table

-- DROP TABLE public.chat_sessions;

CREATE TABLE public.chat_sessions (
	id varchar(36) NOT NULL,
	user_id varchar(36) NULL,
	title varchar(255) NULL,
	turn_count int4 NOT NULL,
	last_decision_type varchar(50) NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	last_active timestamptz DEFAULT now() NOT NULL,
	display_title varchar(255) NULL,
	archived_at timestamptz NULL,
	CONSTRAINT chat_sessions_pkey PRIMARY KEY (id),
	CONSTRAINT chat_sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE
);
CREATE INDEX ix_chat_sessions_archived_at ON public.chat_sessions USING btree (archived_at);
CREATE INDEX ix_chat_sessions_user_id ON public.chat_sessions USING btree (user_id);

-- public.document_chunks definition

-- Drop table

-- DROP TABLE public.document_chunks;

CREATE TABLE public.document_chunks (
	id varchar(36) NOT NULL,
	document_id varchar(36) NOT NULL,
	chunk_index int4 NOT NULL,
	"content" text NOT NULL,
	embedding_json text NULL,
	chunk_metadata text NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT document_chunks_pkey PRIMARY KEY (id),
	CONSTRAINT document_chunks_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE
);
CREATE INDEX ix_document_chunks_document_id ON public.document_chunks USING btree (document_id);

-- public.documents definition

-- Drop table

-- DROP TABLE public.documents;

CREATE TABLE public.documents (
	id varchar(36) NOT NULL,
	owner_id varchar(36) NOT NULL,
	title varchar(255) NOT NULL,
	file_type varchar(20) NOT NULL,
	file_size int4 NOT NULL,
	"content" text NULL,
	chunk_count int4 NOT NULL,
	"version" int4 NOT NULL,
	status varchar(20) NOT NULL,
	doc_metadata text NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT documents_pkey PRIMARY KEY (id),
	CONSTRAINT documents_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES public.users(id) ON DELETE CASCADE
);
CREATE INDEX ix_documents_owner_id ON public.documents USING btree (owner_id);

-- public.feedback definition

-- Drop table

-- DROP TABLE public.feedback;

CREATE TABLE public.feedback (
	id varchar(36) NOT NULL,
	session_id varchar(36) NOT NULL,
	query text NOT NULL,
	response text NULL,
	feedback_type varchar(30) NOT NULL,
	score float8 NULL,
	correction text NULL,
	feedback_metadata text NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT feedback_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_feedback_feedback_type ON public.feedback USING btree (feedback_type);
CREATE INDEX ix_feedback_session_id ON public.feedback USING btree (session_id);

-- public.reasoning_traces definition

-- Drop table

-- DROP TABLE public.reasoning_traces;

CREATE TABLE public.reasoning_traces (
	id varchar(36) NOT NULL,
	session_id varchar(36) NOT NULL,
	trace_id varchar(64) NULL,
	phase varchar(50) NOT NULL,
	"content" text NULL,
	score float8 NULL,
	iteration int4 NOT NULL,
	phase_metadata text NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT reasoning_traces_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_reasoning_traces_phase ON public.reasoning_traces USING btree (phase);
CREATE INDEX ix_reasoning_traces_session_id ON public.reasoning_traces USING btree (session_id);
CREATE INDEX ix_reasoning_traces_trace_id ON public.reasoning_traces USING btree (trace_id);

-- public.redis_shadow_kv definition

-- Drop table

-- DROP TABLE public.redis_shadow_kv;

CREATE TABLE public.redis_shadow_kv (
	id varchar(36) NOT NULL,
	redis_db int4 NOT NULL,
	redis_key varchar(255) NOT NULL,
	data_type varchar(20) NOT NULL,
	payload_json text NOT NULL,
	expire_at_ts float8 NULL,
	is_deleted bool NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT redis_shadow_kv_pkey PRIMARY KEY (id),
	CONSTRAINT uq_redis_shadow_db_key UNIQUE (redis_db, redis_key)
);
CREATE INDEX ix_redis_shadow_kv_redis_db ON public.redis_shadow_kv USING btree (redis_db);
CREATE INDEX ix_redis_shadow_kv_redis_key ON public.redis_shadow_kv USING btree (redis_key);

-- public.system_settings definition

-- Drop table

-- DROP TABLE public.system_settings;

CREATE TABLE public.system_settings (
	"key" varchar(128) NOT NULL,
	value text NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT system_settings_pkey PRIMARY KEY (key)
);

-- public.task_definitions definition

-- Drop table

-- DROP TABLE public.task_definitions;

CREATE TABLE public.task_definitions (
	id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	title varchar(255) NOT NULL,
	description text NOT NULL,
	trigger_type varchar(20) NOT NULL,
	trigger_config_json text NOT NULL,
	status varchar(20) NOT NULL,
	last_run_at timestamptz NULL,
	next_run_at timestamptz NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT task_definitions_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_task_definitions_user_id ON public.task_definitions USING btree (user_id);

-- public.task_notifications definition

-- Drop table

-- DROP TABLE public.task_notifications;

CREATE TABLE public.task_notifications (
	id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	task_id varchar(36) NOT NULL,
	run_id varchar(36) NULL,
	"level" varchar(20) NOT NULL,
	title varchar(255) NOT NULL,
	body text NULL,
	"read" bool NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT task_notifications_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_task_notifications_task_id ON public.task_notifications USING btree (task_id);
CREATE INDEX ix_task_notifications_user_id ON public.task_notifications USING btree (user_id);

-- public.task_runs definition

-- Drop table

-- DROP TABLE public.task_runs;

CREATE TABLE public.task_runs (
	id varchar(36) NOT NULL,
	task_id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	status varchar(20) NOT NULL,
	"output" text NULL,
	"error" text NULL,
	started_at timestamptz DEFAULT now() NOT NULL,
	finished_at timestamptz NULL,
	CONSTRAINT task_runs_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_task_runs_task_id ON public.task_runs USING btree (task_id);
CREATE INDEX ix_task_runs_user_id ON public.task_runs USING btree (user_id);

-- public.tool_stats definition

-- Drop table

-- DROP TABLE public.tool_stats;

CREATE TABLE public.tool_stats (
	id varchar(36) NOT NULL,
	tool_name varchar(100) NOT NULL,
	session_id varchar(36) NULL,
	success_count int4 NOT NULL,
	failure_count int4 NOT NULL,
	avg_latency_ms float8 NOT NULL,
	last_error text NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT tool_stats_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_tool_stats_session_id ON public.tool_stats USING btree (session_id);
CREATE INDEX ix_tool_stats_tool_name ON public.tool_stats USING btree (tool_name);

-- public.trace_logs definition

-- Drop table

-- DROP TABLE public.trace_logs;

CREATE TABLE public.trace_logs (
	id varchar(36) NOT NULL,
	session_id varchar(36) NULL,
	trace_id varchar(64) NULL,
	span_id varchar(32) NULL,
	query text NOT NULL,
	response text NULL,
	decision_type varchar(50) NULL,
	validation_score float8 NULL,
	latency_ms int4 NULL,
	model varchar(100) NULL,
	prompt_tokens int4 NOT NULL,
	completion_tokens int4 NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	reasoning_steps_json text NULL,
	execution_graph_json text NULL,
	CONSTRAINT trace_logs_pkey PRIMARY KEY (id),
	CONSTRAINT trace_logs_session_id_fkey FOREIGN KEY (session_id) REFERENCES public.chat_sessions(id) ON DELETE CASCADE
);
CREATE INDEX ix_trace_logs_session_id ON public.trace_logs USING btree (session_id);
CREATE INDEX ix_trace_logs_trace_id ON public.trace_logs USING btree (trace_id);

-- public.user_memories definition

-- Drop table

-- DROP TABLE public.user_memories;

CREATE TABLE public.user_memories (
	id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	memory_type varchar(20) NOT NULL,
	kind varchar(30) NOT NULL,
	title varchar(255) NULL,
	"content" text NOT NULL,
	tags_json text NULL,
	metadata_json text NULL,
	enabled bool NOT NULL,
	pinned bool NOT NULL,
	access_count int4 NOT NULL,
	last_accessed_at timestamptz NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT user_memories_pkey PRIMARY KEY (id)
);
CREATE INDEX ix_user_memories_memory_type ON public.user_memories USING btree (memory_type);
CREATE INDEX ix_user_memories_user_id ON public.user_memories USING btree (user_id);

-- public.user_memory_settings definition

-- Drop table

-- DROP TABLE public.user_memory_settings;

CREATE TABLE public.user_memory_settings (
	id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	memory_learning_enabled bool NOT NULL,
	preference_learning_enabled bool NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT user_memory_settings_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_user_memory_settings_user_id ON public.user_memory_settings USING btree (user_id);

-- public.user_ui_settings definition

-- Drop table

-- DROP TABLE public.user_ui_settings;

CREATE TABLE public.user_ui_settings (
	id varchar(36) NOT NULL,
	user_id varchar(36) NOT NULL,
	reasoning_default_expanded bool NOT NULL,
	graph_default_expanded bool NOT NULL,
	updated_at timestamptz DEFAULT now() NOT NULL,
	created_at timestamptz DEFAULT now() NOT NULL,
	CONSTRAINT user_ui_settings_pkey PRIMARY KEY (id)
);
CREATE UNIQUE INDEX ix_user_ui_settings_user_id ON public.user_ui_settings USING btree (user_id);



INSERT INTO public.users (id,email,hashed_password,display_name,is_active,is_superuser,created_at,updated_at) VALUES
	 ('10d9b603-0555-4200-9b2e-2abd79708d73','songts@tuwan.com','$2b$12$XonsQFiSGVEFX7bd7yYZOutSvkuk6Q6st47G9ciIuqtLSdo6kl1zW','Song TS',true,true,'2026-03-30 20:34:49.391731+08','2026-03-30 20:34:49.391731+08');

