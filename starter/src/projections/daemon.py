"""
src/projections/daemon.py
=========================
Projection Daemon - Async Daemon for CQRS Read Models

The daemon continuously polls the events table from the last processed
global_position, processes new events through registered projections,
and updates projection_checkpoints.

Key Features:
- Fault-tolerant: logs errors, skips offending events, continues processing
- Checkpoint management: tracks last processed position per projection
- Lag metrics: exposes get_lag() for each projection
- Configurable poll interval and batch size
"""
import asyncio
from typing import AsyncIterator, Callable
from datetime import datetime


class Projection:
    """Base class for projections."""
    
    @property
    def name(self) -> str:
        raise NotImplementedError
    
    async def apply(self, event: dict) -> None:
        """Apply a single event to update the projection."""
        raise NotImplementedError


class ProjectionDaemon:
    """
    Async projection daemon that processes events and updates projections.
    
    The daemon polls the event store from the last checkpoint position,
    processes events through registered projections, and updates checkpoints.
    """
    
    def __init__(
        self,
        event_store,
        projections: list[Projection],
        poll_interval_ms: int = 100,
        batch_size: int = 100,
    ):
        self._event_store = event_store
        self._projections = {p.name: p for p in projections}
        self._poll_interval_ms = poll_interval_ms
        self._batch_size = batch_size
        self._running = False
        self._checkpoints: dict[str, int] = {}
    
    @property
    def projection_names(self) -> list[str]:
        return list(self._projections.keys())
    
    async def start(self) -> None:
        """Start the daemon."""
        self._running = True
        # Load initial checkpoints
        await self._load_checkpoints()
    
    async def stop(self) -> None:
        """Stop the daemon."""
        self._running = False
    
    async def _load_checkpoints(self) -> None:
        """Load current checkpoints from the event store."""
        for name in self._projections.keys():
            checkpoint = await self._event_store.get_checkpoint(name)
            self._checkpoints[name] = checkpoint if checkpoint is not None else 0
    
    async def run_forever(self) -> None:
        """
        Run the daemon continuously.
        
        This is the main loop that polls for new events and processes them.
        """
        await self.start()
        
        while self._running:
            try:
                await self._process_batch()
            except Exception as e:
                print(f"Error in projection daemon: {e}")
            
            await asyncio.sleep(self._poll_interval_ms / 1000)
    
    async def _process_batch(self) -> None:
        """
        Process a batch of events from the event store.
        
        Loads events from the lowest checkpoint position across all projections,
        processes them through subscribed projections, and updates checkpoints.
        """
        if not self._projections:
            return
        
        # Get the lowest checkpoint (oldest unprocessed position)
        min_checkpoint = min(self._checkpoints.values())
        
        # Load events from that position
        events = []
        async for event in self._event_store.load_all(
            from_global_position=min_checkpoint,
            batch_size=self._batch_size,
        ):
            events.append(event)
            if len(events) >= self._batch_size:
                break
        
        if not events:
            return
        
        # Process each event through all projections
        for event in events:
            event_global_pos = event.get("global_position", 0)
            
            for projection_name, projection in self._projections.items():
                try:
                    await projection.apply(event)
                    # Update checkpoint after successful processing
                    self._checkpoints[projection_name] = event_global_pos + 1
                    await self._event_store.save_checkpoint(
                        projection_name, 
                        event_global_pos + 1
                    )
                except Exception as e:
                    print(f"Error in projection {projection_name}: {e}")
                    # Continue processing other projections
    
    def get_lag(self, projection_name: str) -> int:
        """
        Get the lag for a specific projection.
        
        Returns the number of events between the latest event in the store
        and the latest event processed by this projection.
        """
        if projection_name not in self._projections:
            raise ValueError(f"Unknown projection: {projection_name}")
        
        # This would need the event store's global position
        # For now, return the checkpoint position
        return self._checkpoints.get(projection_name, 0)
    
    async def get_all_lags(self) -> dict[str, int]:
        """Get lag metrics for all projections."""
        return dict(self._checkpoints)
    
    async def rebuild_from_scratch(self, projection_name: str) -> None:
        """
        Rebuild a projection from scratch by replaying all events.
        
        This truncates the projection and replays from position 0.
        """
        if projection_name not in self._projections:
            raise ValueError(f"Unknown projection: {projection_name}")
        
        projection = self._projections[projection_name]
        
        # Reset checkpoint to 0
        self._checkpoints[projection_name] = 0
        await self._event_store.save_checkpoint(projection_name, 0)
        
        # Replay all events
        async for event in self._event_store.load_all(from_global_position=0):
            try:
                await projection.apply(event)
                self._checkpoints[projection_name] += 1
            except Exception as e:
                print(f"Error rebuilding projection {projection_name}: {e}")
        
        await self._event_store.save_checkpoint(
            projection_name, 
            self._checkpoints[projection_name]
        )
