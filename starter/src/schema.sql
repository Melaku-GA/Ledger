-- src/schema.sql
-- PostgreSQL Event Store Schema for The Ledger
-- Phase 1: Event Store Core

-- ============================================================================
-- EVENTS TABLE
-- The append-only event log - the source of truth for all domain events
-- ============================================================================
CREATE TABLE IF NOT EXISTS events (
    event_id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    stream_id        TEXT NOT NULL,
    stream_position  BIGINT NOT NULL,
    global_position  BIGINT GENERATED ALWAYS AS IDENTITY,
    event_type       TEXT NOT NULL,
    event_version    SMALLINT NOT NULL DEFAULT 1,
    payload          JSONB NOT NULL,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb,
    recorded_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    -- Ensure each stream position is unique within a stream
    CONSTRAINT uq_stream_position UNIQUE (stream_id, stream_position)
);

-- Index for loading streams efficiently (primary query pattern)
CREATE INDEX IF NOT EXISTS idx_events_stream_id 
    ON events (stream_id, stream_position);

-- Index for global event ordering (projection daemon)
CREATE INDEX IF NOT EXISTS idx_events_global_pos 
    ON events (global_position);

-- Index for filtering by event type
CREATE INDEX IF NOT EXISTS idx_events_type 
    ON events (event_type);

-- Index for time-based queries
CREATE INDEX IF NOT EXISTS idx_events_recorded 
    ON events (recorded_at);

-- ============================================================================
-- EVENT_STREAMS TABLE
-- Tracks metadata about each event stream (aggregate)
-- ============================================================================
CREATE TABLE IF NOT EXISTS event_streams (
    stream_id        TEXT PRIMARY KEY,
    aggregate_type   TEXT NOT NULL,
    current_version  BIGINT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    archived_at      TIMESTAMPTZ,
    metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
);

-- ============================================================================
-- PROJECTION_CHECKPOINTS TABLE
-- Tracks the last processed global_position for each projection
-- Enables resumable projection updates
-- ============================================================================
CREATE TABLE IF NOT EXISTS projection_checkpoints (
    projection_name  TEXT PRIMARY KEY,
    last_position    BIGINT NOT NULL DEFAULT 0,
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- OUTBOX TABLE
-- Implements the Outbox Pattern for reliable event publishing
-- Events are written to this table in the same transaction as the event,
-- then published asynchronously by a separate process
-- ============================================================================
CREATE TABLE IF NOT EXISTS outbox (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_id         UUID NOT NULL,
    destination      TEXT NOT NULL,
    payload          JSONB NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    published_at     TIMESTAMPTZ,
    attempts         SMALLINT NOT NULL DEFAULT 0,
    -- Store the event_id as text since we can't reference events in same transaction easily
    CONSTRAINT fk_event_id FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
);

-- Index for finding unpublished events
CREATE INDEX IF NOT EXISTS idx_outbox_unpublished 
    ON outbox (created_at) 
    WHERE published_at IS NULL;

-- Index for retry logic
CREATE INDEX IF NOT EXISTS idx_outbox_attempts 
    ON outbox (attempts) 
    WHERE published_at IS NULL;
