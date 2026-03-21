"""
src/event_store.py
==================
PostgreSQL-backed Event Store for The Ledger

Phase 1: Event Store Core Implementation

This module provides the EventStore class - an async PostgreSQL implementation
of an append-only event store with optimistic concurrency control.

Key Features:
- Append-only event storage with ACID guarantees
- Optimistic concurrency control via expected_version
- Stream metadata management
- Projection checkpoint support
- Outbox pattern support for event publishing

Usage:
    store = EventStore("postgresql://user:pass@localhost/dbname")
    await store.connect()
    try:
        await store.append("loan-001", events, expected_version=0)
    finally:
        await store.close()
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import AsyncGenerator, Optional
from uuid import UUID
import asyncio

import asyncpg

from src.models.events import (
    OptimisticConcurrencyError,
    DomainError,
    StreamNotFoundError,
    StoredEvent,
    StreamMetadata,
)


class EventStore:
    """
    PostgreSQL-backed append-only event store.
    
    This is the core infrastructure component that all other components
    write to and read from. It implements:
    - Optimistic concurrency control (OCC)
    - Stream-based event organization
    - Global event ordering
    - Projection checkpoint management
    
    The event store is the source of truth - every decision made by
    AI agents is recorded here as an immutable event.
    """

    def __init__(
        self,
        db_url: str,
        upcaster_registry: Optional[object] = None,
    ):
        """
        Initialize the event store.
        
        Args:
            db_url: PostgreSQL connection string
            upcaster_registry: Optional registry for schema evolution
        """
        self.db_url = db_url
        self.upcasters = upcaster_registry
        self._pool: Optional[asyncpg.Pool] = None

    async def connect(self) -> None:
        """Create connection pool to PostgreSQL."""
        self._pool = await asyncpg.create_pool(
            self.db_url,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def initialize_schema(self) -> None:
        """
        Initialize the database schema.
        
        Creates all required tables if they don't exist.
        Should be called once during application startup.
        """
        schema_sql = """
        -- Events table - the append-only log
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
            CONSTRAINT uq_stream_position UNIQUE (stream_id, stream_position)
        );

        -- Indexes for efficient querying
        CREATE INDEX IF NOT EXISTS idx_events_stream_id 
            ON events (stream_id, stream_position);
        CREATE INDEX IF NOT EXISTS idx_events_global_pos 
            ON events (global_position);
        CREATE INDEX IF NOT EXISTS idx_events_type 
            ON events (event_type);
        CREATE INDEX IF NOT EXISTS idx_events_recorded 
            ON events (recorded_at);

        -- Event streams metadata
        CREATE TABLE IF NOT EXISTS event_streams (
            stream_id        TEXT PRIMARY KEY,
            aggregate_type   TEXT NOT NULL,
            current_version  BIGINT NOT NULL DEFAULT 0,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            archived_at      TIMESTAMPTZ,
            metadata         JSONB NOT NULL DEFAULT '{}'::jsonb
        );

        -- Projection checkpoints
        CREATE TABLE IF NOT EXISTS projection_checkpoints (
            projection_name  TEXT PRIMARY KEY,
            last_position    BIGINT NOT NULL DEFAULT 0,
            updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );

        -- Outbox for reliable event publishing
        CREATE TABLE IF NOT EXISTS outbox (
            id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            event_id         UUID NOT NULL,
            destination      TEXT NOT NULL,
            payload          JSONB NOT NULL,
            created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            published_at     TIMESTAMPTZ,
            attempts         SMALLINT NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_outbox_unpublished 
            ON outbox (created_at) 
            WHERE published_at IS NULL;
        """
        
        async with self._pool.acquire() as conn:
            await conn.execute(schema_sql)

    # ─── STREAM OPERATIONS ─────────────────────────────────────────────────────

    async def stream_version(self, stream_id: str) -> int:
        """
        Get the current version of a stream.
        
        Returns -1 if the stream doesn't exist yet.
        
        Args:
            stream_id: The stream identifier (e.g., "loan-APP-001")
            
        Returns:
            Current stream version (position of last event), or -1 if stream is new
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT current_version FROM event_streams WHERE stream_id = $1",
                stream_id
            )
            return row["current_version"] if row else -1

    async def append(
        self,
        stream_id: str,
        events: list[dict],
        expected_version: int,
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> list[int]:
        """
        Append events to a stream with optimistic concurrency control.
        
        This is the core write operation. It uses expected_version to ensure
        that no two concurrent writes can corrupt the stream state.
        
        Args:
            stream_id: The stream to append to (e.g., "loan-APP-001")
            events: List of event dicts to append
            expected_version: The version expected (-1 for new stream, N for existing)
            correlation_id: Optional correlation ID for tracking related events
            causation_id: Optional causation ID for causal chains
            metadata: Optional metadata to attach to all events
            
        Returns:
            List of stream positions assigned to each event
            
        Raises:
            OptimisticConcurrencyError: If expected_version doesn't match actual version
        """
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                # 1. Get current stream version with row lock
                row = await conn.fetchrow(
                    "SELECT current_version, aggregate_type FROM event_streams "
                    "WHERE stream_id = $1 FOR UPDATE",
                    stream_id
                )
                
                current = row["current_version"] if row else -1
                
                # 2. OCC Check
                if current != expected_version:
                    raise OptimisticConcurrencyError(
                        stream_id, expected_version, current
                    )
                
                # 3. Create stream if new
                if row is None:
                    aggregate_type = stream_id.split("-")[0] if "-" in stream_id else "unknown"
                    await conn.execute(
                        "INSERT INTO event_streams(stream_id, aggregate_type, current_version) "
                        "VALUES($1, $2, 0)",
                        stream_id, aggregate_type
                    )
                
                # 4. Build metadata
                meta = {**(metadata or {})}
                if correlation_id:
                    meta["correlation_id"] = correlation_id
                if causation_id:
                    meta["causation_id"] = causation_id
                
                # 5. Insert each event
                positions = []
                new_version = current
                
                for i, event in enumerate(events):
                    new_version = current + 1 + i
                    event_id = await conn.fetchval(
                        "INSERT INTO events(stream_id, stream_position, event_type, "
                        "event_version, payload, metadata, recorded_at) "
                        "VALUES($1, $2, $3, $4, $5::jsonb, $6::jsonb, $7) "
                        "RETURNING event_id",
                        stream_id,
                        new_version,
                        event.get("event_type", "Unknown"),
                        event.get("event_version", 1),
                        json.dumps(event.get("payload", {})),
                        json.dumps(meta),
                        datetime.utcnow()
                    )
                    positions.append(new_version)
                    
                    # Add to outbox (Outbox Pattern)
                    await conn.execute(
                        "INSERT INTO outbox(event_id, destination, payload) "
                        "VALUES($1, $2, $3::jsonb)",
                        event_id,
                        "event-bus",  # Default destination
                        json.dumps({
                            "stream_id": stream_id,
                            "event_type": event.get("event_type"),
                            "event_id": str(event_id),
                            "payload": event.get("payload", {}),
                        })
                    )
                
                # 6. Update stream version
                await conn.execute(
                    "UPDATE event_streams SET current_version = $1 WHERE stream_id = $2",
                    new_version,
                    stream_id
                )
                
                return positions

    async def load_stream(
        self,
        stream_id: str,
        from_position: int = 0,
        to_position: Optional[int] = None,
    ) -> list[StoredEvent]:
        """
        Load events from a specific stream.
        
        Events are returned in stream_position order (chronological for that stream).
        Applies upcasters if configured.
        
        Args:
            stream_id: The stream to load
            from_position: Starting position (inclusive), default 0
            to_position: Ending position (inclusive), None means all remaining
            
        Returns:
            List of StoredEvent objects in order
        """
        async with self._pool.acquire() as conn:
            query = (
                "SELECT event_id, stream_id, stream_position, global_position, "
                "event_type, event_version, payload, metadata, recorded_at "
                "FROM events WHERE stream_id = $1 AND stream_position >= $2"
            )
            params = [stream_id, from_position]
            
            if to_position is not None:
                query += " AND stream_position <= $3"
                params.append(to_position)
            
            query += " ORDER BY stream_position ASC"
            
            rows = await conn.fetch(query, *params)
            
            events = []
            for row in rows:
                event = StoredEvent(
                    event_id=row["event_id"],
                    stream_id=row["stream_id"],
                    stream_position=row["stream_position"],
                    global_position=row["global_position"],
                    event_type=row["event_type"],
                    event_version=row["event_version"],
                    payload=dict(row["payload"]),
                    metadata=dict(row["metadata"]),
                    recorded_at=row["recorded_at"],
                )
                
                # Apply upcasters if configured
                if self.upcasters:
                    event = self._apply_upcasters(event)
                
                events.append(event)
            
            return events

    async def load_all(
        self,
        from_global_position: int = 0,
        event_types: Optional[list[str]] = None,
        batch_size: int = 500,
    ) -> AsyncGenerator[StoredEvent, None]:
        """
        Load all events from the store in global position order.
        
        This is an async generator - it yields events in batches for efficiency.
        Used by the projection daemon to process events.
        
        Args:
            from_global_position: Starting global position
            event_types: Optional filter by event types
            batch_size: Number of events per batch
            
        Yields:
            StoredEvent objects in global order
        """
        async with self._pool.acquire() as conn:
            pos = from_global_position - 1  # Start before first position
            
            while True:
                # Build query
                query = (
                    "SELECT event_id, stream_id, stream_position, global_position, "
                    "event_type, event_version, payload, metadata, recorded_at "
                    "FROM events WHERE global_position > $1"
                )
                params: list = [pos]
                
                if event_types:
                    query += f" AND event_type = ANY(${len(params) + 1})"
                    params.append(event_types)
                
                query += f" ORDER BY global_position ASC LIMIT ${len(params) + 1}"
                params.append(batch_size)
                
                rows = await conn.fetch(query, *params)
                
                if not rows:
                    break
                
                for row in rows:
                    event = StoredEvent(
                        event_id=row["event_id"],
                        stream_id=row["stream_id"],
                        stream_position=row["stream_position"],
                        global_position=row["global_position"],
                        event_type=row["event_type"],
                        event_version=row["event_version"],
                        payload=dict(row["payload"]),
                        metadata=dict(row["metadata"]),
                        recorded_at=row["recorded_at"],
                    )
                    
                    # Apply upcasters if configured
                    if self.upcasters:
                        event = self._apply_upcasters(event)
                    
                    yield event
                
                pos = rows[-1]["global_position"]
                
                if len(rows) < batch_size:
                    break

    async def get_event(self, event_id: UUID) -> Optional[StoredEvent]:
        """
        Load a single event by its ID.
        
        Used for causation chain lookups and debugging.
        
        Args:
            event_id: The UUID of the event
            
        Returns:
            StoredEvent if found, None otherwise
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT event_id, stream_id, stream_position, global_position, "
                "event_type, event_version, payload, metadata, recorded_at "
                "FROM events WHERE event_id = $1",
                event_id
            )
            
            if not row:
                return None
            
            event = StoredEvent(
                event_id=row["event_id"],
                stream_id=row["stream_id"],
                stream_position=row["stream_position"],
                global_position=row["global_position"],
                event_type=row["event_type"],
                event_version=row["event_version"],
                payload=dict(row["payload"]),
                metadata=dict(row["metadata"]),
                recorded_at=row["recorded_at"],
            )
            
            if self.upcasters:
                event = self._apply_upcasters(event)
            
            return event

    async def archive_stream(self, stream_id: str) -> None:
        """
        Archive a stream.
        
        Marking a stream as archived prevents new events from being appended
        but keeps all existing events for audit purposes.
        
        Args:
            stream_id: The stream to archive
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                "UPDATE event_streams SET archived_at = NOW() WHERE stream_id = $1",
                stream_id
            )

    async def get_stream_metadata(self, stream_id: str) -> StreamMetadata:
        """
        Get metadata about a stream.
        
        Args:
            stream_id: The stream to query
            
        Returns:
            StreamMetadata object
            
        Raises:
            StreamNotFoundError: If stream doesn't exist
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT stream_id, aggregate_type, current_version, created_at, "
                "archived_at, metadata FROM event_streams WHERE stream_id = $1",
                stream_id
            )
            
            if not row:
                raise StreamNotFoundError(stream_id)
            
            return StreamMetadata(
                stream_id=row["stream_id"],
                aggregate_type=row["aggregate_type"],
                current_version=row["current_version"],
                created_at=row["created_at"],
                archived_at=row["archived_at"],
                metadata=dict(row["metadata"]),
            )

    # ─── PROJECTION CHECKPOINT OPERATIONS ─────────────────────────────────────

    async def save_checkpoint(
        self,
        projection_name: str,
        position: int,
    ) -> None:
        """
        Save the current processing position for a projection.
        
        Args:
            projection_name: Name of the projection
            position: Global position that has been processed
        """
        async with self._pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO projection_checkpoints (projection_name, last_position, updated_at)
                VALUES ($1, $2, NOW())
                ON CONFLICT (projection_name) 
                DO UPDATE SET last_position = $2, updated_at = NOW()
                """,
                projection_name,
                position,
            )

    async def load_checkpoint(self, projection_name: str) -> int:
        """
        Load the last processed position for a projection.
        
        Args:
            projection_name: Name of the projection
            
        Returns:
            Last processed global position, or 0 if never checkpointed
        """
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT last_position FROM projection_checkpoints "
                "WHERE projection_name = $1",
                projection_name,
            )
            return row["last_position"] if row else 0

    # ─── HELPERS ─────────────────────────────────────────────────────────────

    def _apply_upcasters(self, event: StoredEvent) -> StoredEvent:
        """Apply registered upcasters to an event."""
        if not self.upcasters:
            return event
        
        # Convert to dict for upcaster
        event_dict = event.model_dump()
        upcasted = self.upcasters.upcast(event_dict)
        
        # Convert back to StoredEvent
        return StoredEvent(**upcasted)


# ─── FACTORY FUNCTION ─────────────────────────────────────────────────────────

async def create_event_store(
    db_url: str,
    upcaster_registry: Optional[object] = None,
    auto_initialize: bool = True,
) -> EventStore:
    """
    Factory function to create and initialize an EventStore.
    
    Args:
        db_url: PostgreSQL connection string
        upcaster_registry: Optional upcaster registry
        auto_initialize: If True, creates tables automatically
        
    Returns:
        Connected and initialized EventStore
    """
    store = EventStore(db_url, upcaster_registry)
    await store.connect()
    
    if auto_initialize:
        await store.initialize_schema()
    
    return store
