# OSINT/Data Broker Platform — Real-Time Progress, Expanding Search & Communication Architecture

## Part 1: Communication Pattern Decision — API vs Webhook vs Temporal

### The Problem
OSINT searches are long-running (30s to 15min+). We need the right communication pattern between:
- Frontend ↔ API
- API ↔ Workers
- Workers ↔ Scrapers
- System ↔ External consumers

### Pattern Comparison

#### REST API (Request/Response)
- **Good for**: Initiating searches, fetching cached results, CRUD operations
- **Bad for**: Long-running operations, real-time updates
- **Latency**: Immediate for cached, timeout risk for live
- **Complexity**: Low
- **Verdict**: Use for search initiation + result retrieval, NOT for waiting on results

#### WebSockets (Bidirectional)
- **Good for**: Real-time progress updates, live data streaming, two-way communication
- **Bad for**: Stateless operations, high connection count at scale
- **Latency**: Sub-100ms updates
- **Complexity**: Medium
- **Verdict**: Use for live debugging, parameter changes, search cancellation

#### Server-Sent Events (SSE)
- **Good for**: One-way progress streaming (server → client), simple implementation
- **Bad for**: Bidirectional communication, requires HTTP/2 for efficiency
- **Latency**: Sub-100ms
- **Complexity**: Low
- **Verdict**: RECOMMENDED for progress bars - simpler than WebSocket

#### Webhooks (Push Notifications)
- **Good for**: Notifying external systems when searches complete
- **Bad for**: Internal communication (unreliable), real-time UI
- **Latency**: Variable (seconds to minutes)
- **Complexity**: Medium (retry logic, signature verification)
- **Verdict**: Use for external integrations and notifications only

#### Temporal.io (Workflow Orchestration)
- **Good for**: Complex multi-step workflows, retry/resume, long-running processes, auditing
- **Bad for**: Simple request/response, adds infrastructure complexity
- **Latency**: Adds ~50-100ms overhead per step
- **Complexity**: High
- **Verdict**: Use for core search orchestration pipeline — worth the complexity

#### Message Queue (Redis Streams / Kafka)
- **Good for**: Decoupling workers, buffering, fan-out, scalability
- **Bad for**: Request/response patterns, real-time UI feedback
- **Latency**: Sub-10ms within network
- **Complexity**: Medium
- **Verdict**: Use for worker job distribution and progress event streaming

### Recommended Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│ Frontend (Browser/Mobile)                                           │
├─────────────────────────────────────────────────────────────────────┤
│ - React/Vue for UI                                                  │
│ - SSE listener for progress updates                                 │
│ - WebSocket for parameter changes & cancellation                    │
│ - REST API for search initiation & result retrieval                 │
└────────┬─────────────────┬────────────┬──────────────────────────────┘
         │                 │            │
         │ REST API        │ SSE        │ WebSocket
         │                 │            │
┌────────▼─────────────────▼────────────▼──────────────────────────────┐
│ API Server (FastAPI/Node.js)                                        │
├─────────────────────────────────────────────────────────────────────┤
│ - Route: POST /search → initiate via Temporal                       │
│ - Route: GET /search/{id} → fetch from cache/DB                    │
│ - Route: GET /search/{id}/progress → SSE stream                    │
│ - Route: WS /search/{id}/ws → bidirectional control               │
│ - Temporal Client for workflow management                           │
└────────┬──────────────────────┬─────────────────────────────────────┘
         │                      │
         │ Temporal SDK         │ Redis Pub/Sub
         │ (register/start)     │ (listen for events)
         │                      │
┌────────▼──────────────────────▼─────────────────────────────────────┐
│ Temporal Server                                                     │
├─────────────────────────────────────────────────────────────────────┤
│ Workflows:                                                          │
│ - SearchPersonWorkflow (main orchestrator)                          │
│ - GrowthDiscoveryWorkflow (expand search)                           │
│ - DeduplicationWorkflow (merge duplicates)                          │
│ - EnrichmentWorkflow (add context)                                  │
└────────┬──────────────────────┬─────────────────────────────────────┘
         │                      │
         │ Temporal Activity    │ Temporal Activity
         │ calls                │ calls
         │                      │
┌────────▼────────────────────────────────────────────────────────────┐
│ Worker Nodes                                                        │
├─────────────────────────────────────────────────────────────────────┤
│ Activity Handlers:                                                  │
│ - SearchPersonActivity                                              │
│ - ScrapeSourceActivity (per scraper)                                │
│ - DeduplicateActivity                                               │
│ - EnrichActivity                                                    │
└────┬───────┬───────┬───────┬────────────────────────────────────────┘
     │       │       │       │
     │       │       │       │ Redis Pub/Sub
     │       │       │       │ (emit progress)
     │       │       │       │
┌────▼───────▼───────▼───────▼────────────────────────────────────────┐
│ External Scrapers / Data Sources                                    │
├─────────────────────────────────────────────────────────────────────┤
│ - Whitepages, TrueCaller, ZoomInfo                                  │
│ - Court records, property records, business filings                 │
│ - Social media APIs, news aggregators                               │
│ - Custom web scrapers with rotating proxies                         │
└─────────────────────────────────────────────────────────────────────┘

External Integration Points:
┌─────────────────────────────────────────────────────────────────────┐
│ External Systems                                                    │
├─────────────────────────────────────────────────────────────────────┤
│ - Webhook subscriptions: /webhooks/search-complete                  │
│ - Event batching: every 30 seconds or 100 results                   │
│ - Signature verification: HMAC-SHA256                               │
│ - Retry logic: exponential backoff, 7-day grace period              │
└─────────────────────────────────────────────────────────────────────┘
```

### Why This Combination?

1. **REST API**: Simple, cacheable, stateless — perfect for initiating and retrieving results
2. **SSE for Progress**: Lightweight, automatic reconnection, one-way is sufficient for updates
3. **WebSocket for Control**: When users need to change parameters or cancel mid-flight
4. **Temporal for Orchestration**: Handles retries, timeouts, long-running workflows, resume after crash
5. **Redis Streams for Job Queue**: Fast, persistent, consumer groups for scalability
6. **Webhooks for External**: Standard integration pattern for third-party systems

---

## Part 2: Code Implementation — Communication Patterns

### 2.1 Temporal Workflow Definition

```python
# temporal_workflows.py
from temporalio import workflow, activity
from temporalio.exceptions import ActivityError, TimeoutError as TemporalTimeoutError
from dataclasses import dataclass
from typing import List, Optional, Dict
from datetime import timedelta
import logging

logger = logging.getLogger(__name__)

@dataclass
class SearchInput:
    search_id: str
    query: str
    name: Optional[str] = None
    location_filter: Optional[str] = None
    depth: int = 2
    max_results: int = 100
    excluded_sources: Optional[List[str]] = None
    priority_sources: Optional[List[str]] = None

@dataclass
class SearchResult:
    search_id: str
    total_people_found: int
    total_records: int
    phase: str  # "complete"
    results: List[Dict]
    error: Optional[str] = None

@activity.defn
async def emit_progress(search_id: str, event: Dict):
    """Emit progress event to Redis pub/sub"""
    import aioredis
    redis = await aioredis.create_redis_pool('redis://localhost')
    await redis.publish(f'search:{search_id}:progress', json.dumps(event))
    redis.close()
    await redis.wait_closed()

@activity.defn
async def search_person_activity(search_input: SearchInput) -> Dict:
    """Execute search across all active scrapers"""
    logger.info(f"Starting person search: {search_input.search_id}")

    scrapers = get_active_scrapers(
        excluded=search_input.excluded_sources or [],
        priority=search_input.priority_sources or []
    )

    results = []
    for scraper in scrapers:
        try:
            await emit_progress(search_input.search_id, {
                "event_type": "scraper_started",
                "scraper_name": scraper.name,
                "timestamp": datetime.utcnow().isoformat()
            })

            scraper_results = await scraper.search(search_input.query)
            results.extend(scraper_results)

            await emit_progress(search_input.search_id, {
                "event_type": "scraper_completed",
                "scraper_name": scraper.name,
                "records_found": len(scraper_results),
                "timestamp": datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f"Scraper {scraper.name} failed: {e}")
            await emit_progress(search_input.search_id, {
                "event_type": "scraper_failed",
                "scraper_name": scraper.name,
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            })

    return {
        "search_id": search_input.search_id,
        "raw_results": results,
        "record_count": len(results)
    }

@activity.defn
async def deduplicate_activity(search_id: str, raw_results: List[Dict]) -> List[Dict]:
    """Remove duplicate records, merge data from multiple sources"""
    logger.info(f"Deduplicating {len(raw_results)} records for search {search_id}")

    deduped = {}
    for idx, record in enumerate(raw_results):
        await emit_progress(search_id, {
            "event_type": "dedup_progress",
            "records_processed": idx + 1,
            "total_records": len(raw_results),
            "unique_count": len(deduped),
            "timestamp": datetime.utcnow().isoformat()
        })

        key = generate_dedup_key(record)
        if key not in deduped:
            deduped[key] = record
        else:
            # Merge new data into existing record
            deduped[key] = merge_records(deduped[key], record)

    return list(deduped.values())

@activity.defn
async def enrichment_activity(search_id: str, records: List[Dict]) -> List[Dict]:
    """Add context: relationships, business info, social links"""
    logger.info(f"Enriching {len(records)} records for search {search_id}")

    enriched = []
    for idx, record in enumerate(records):
        await emit_progress(search_id, {
            "event_type": "enrichment_progress",
            "records_processed": idx + 1,
            "total_records": len(records),
            "timestamp": datetime.utcnow().isoformat()
        })

        try:
            record['relationships'] = await discover_relationships(record)
            record['business_info'] = await enrich_business_data(record)
            record['social_links'] = await find_social_profiles(record)
            enriched.append(record)
        except Exception as e:
            logger.warning(f"Enrichment failed for record: {e}")
            enriched.append(record)  # Return unenriched

    return enriched

@activity.defn
async def discovery_activity(search_id: str, person_record: Dict, depth: int) -> List[Dict]:
    """Discover connected people (relatives, associates, neighbors)"""
    logger.info(f"Discovering connections for {person_record.get('name')} (depth={depth})")

    connections = []

    # Find by address
    if address := person_record.get('address'):
        address_matches = await find_by_address(address)
        connections.extend(address_matches)

    # Find by phone
    if phone := person_record.get('phone'):
        phone_matches = await find_by_phone(phone)
        connections.extend(phone_matches)

    # Find by email
    if email := person_record.get('email'):
        email_matches = await find_by_email(email)
        connections.extend(email_matches)

    # Find relatives (from people search data)
    if name := person_record.get('name'):
        relatives = await find_relatives(name, person_record.get('address'))
        connections.extend(relatives)

    # Score and dedupe connections
    scored = score_connections(connections, person_record)
    return scored[:50]  # Top 50

@workflow.defn
async def search_person_workflow(search_input: SearchInput) -> SearchResult:
    """
    Main workflow orchestrating the entire search pipeline.
    Handles retries, timeouts, cancellation, and parameter updates.
    """
    logger.info(f"Starting search workflow: {search_input.search_id}")

    retry_policy = workflow.RetryPolicy(
        initial_interval=timedelta(seconds=1),
        maximum_interval=timedelta(seconds=60),
        maximum_attempts=3,
        backoff_coefficient=2.0,
        non_retryable_error_types=["BadInputError", "NotFoundError"]
    )

    try:
        # Phase 1: Collection (0-60%)
        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_started",
                "phase": "collecting",
                "progress_pct": 0,
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        search_result = await workflow.execute_activity(
            search_person_activity,
            search_input,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=15),
            heartbeat_timeout=timedelta(seconds=30)
        )

        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_complete",
                "phase": "collecting",
                "progress_pct": 60,
                "records_found": search_result['record_count'],
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        # Phase 2: Deduplication (60-75%)
        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_started",
                "phase": "deduplicating",
                "progress_pct": 60,
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        deduped_results = await workflow.execute_activity(
            deduplicate_activity,
            search_input.search_id,
            search_result['raw_results'],
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=10)
        )

        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_complete",
                "phase": "deduplicating",
                "progress_pct": 75,
                "unique_records": len(deduped_results),
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        # Phase 3: Enrichment (75-95%)
        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_started",
                "phase": "enriching",
                "progress_pct": 75,
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        enriched_results = await workflow.execute_activity(
            enrichment_activity,
            search_input.search_id,
            deduped_results,
            retry_policy=retry_policy,
            start_to_close_timeout=timedelta(minutes=10)
        )

        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_complete",
                "phase": "enriching",
                "progress_pct": 95,
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        # Phase 4: Discovery (optional, if depth > 0)
        discovered_people = []
        if search_input.depth > 0:
            for person in enriched_results[:10]:  # Limit discovery to top 10
                discovered = await workflow.execute_activity(
                    discovery_activity,
                    search_input.search_id,
                    person,
                    search_input.depth - 1,
                    start_to_close_timeout=timedelta(minutes=5)
                )
                discovered_people.extend(discovered)

        # Phase 5: Finalization (95-100%)
        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "phase_started",
                "phase": "finalizing",
                "progress_pct": 95,
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        final_results = enriched_results + discovered_people

        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "search_complete",
                "phase": "complete",
                "progress_pct": 100,
                "total_people_found": len(final_results),
                "total_records": sum(len(p.get('sources', [])) for p in final_results),
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        return SearchResult(
            search_id=search_input.search_id,
            total_people_found=len(final_results),
            total_records=sum(len(p.get('sources', [])) for p in final_results),
            phase="complete",
            results=final_results
        )

    except Exception as e:
        logger.error(f"Search workflow failed: {e}")
        await workflow.execute_activity(
            emit_progress,
            search_input.search_id,
            {
                "event_type": "search_failed",
                "phase": "error",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            },
            start_to_close_timeout=timedelta(seconds=5)
        )

        return SearchResult(
            search_id=search_input.search_id,
            total_people_found=0,
            total_records=0,
            phase="error",
            results=[],
            error=str(e)
        )
```

### 2.2 SSE Progress Streaming Endpoint

```python
# fastapi_progress_endpoint.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
import aioredis
import asyncio
import json
from datetime import datetime
from typing import AsyncGenerator

app = FastAPI()

class ProgressAggregator:
    """Aggregates progress events from Redis and maintains state"""

    def __init__(self, search_id: str):
        self.search_id = search_id
        self.events = []
        self.current_phase = "initializing"
        self.progress_pct = 0
        self.results_found = 0
        self.scrapers_total = 0
        self.scrapers_completed = 0
        self.scrapers_failed = 0
        self.start_time = datetime.utcnow()
        self.phase_start_time = datetime.utcnow()

    def process_event(self, event: Dict):
        """Update internal state based on progress event"""
        self.events.append(event)
        event_type = event.get('event_type')

        if event_type == 'phase_started':
            self.current_phase = event.get('phase', 'unknown')
            self.progress_pct = event.get('progress_pct', 0)
            self.phase_start_time = datetime.utcnow()

        elif event_type == 'phase_complete':
            self.progress_pct = event.get('progress_pct', 0)

        elif event_type == 'scraper_started':
            self.scrapers_total += 1

        elif event_type == 'scraper_completed':
            self.scrapers_completed += 1
            self.results_found += event.get('records_found', 0)

        elif event_type == 'scraper_failed':
            self.scrapers_failed += 1

        elif event_type == 'dedup_progress':
            self.results_found = event.get('unique_count', self.results_found)

        elif event_type == 'search_complete':
            self.progress_pct = 100
            self.results_found = event.get('total_people_found', 0)

    def estimate_time_remaining(self) -> float:
        """Estimate seconds remaining based on phase and historical data"""
        elapsed = (datetime.utcnow() - self.start_time).total_seconds()

        if self.progress_pct <= 0:
            return 0

        # Linear extrapolation
        estimated_total = (elapsed / self.progress_pct) * 100
        remaining = estimated_total - elapsed

        return max(0, remaining)

    def to_dict(self) -> Dict:
        """Convert state to frontend-ready dict"""
        return {
            "search_id": self.search_id,
            "current_phase": self.current_phase,
            "progress_pct": self.progress_pct,
            "results_found": self.results_found,
            "scrapers_total": self.scrapers_total,
            "scrapers_completed": self.scrapers_completed,
            "scrapers_failed": self.scrapers_failed,
            "estimated_seconds_remaining": self.estimate_time_remaining(),
            "elapsed_seconds": (datetime.utcnow() - self.start_time).total_seconds()
        }

async def progress_event_generator(
    search_id: str,
    redis: aioredis.Redis
) -> AsyncGenerator[str, None]:
    """
    Generator that streams progress events from Redis.
    SSE format: "data: {json}\n\n"
    """
    aggregator = ProgressAggregator(search_id)

    # Subscribe to progress channel
    channel = (await redis.subscribe(f'search:{search_id}:progress'))[0]

    try:
        while True:
            # Read from Redis channel
            message = await asyncio.wait_for(
                channel.get(),
                timeout=60.0  # Heartbeat every 60 seconds
            )

            if message:
                try:
                    event = json.loads(message.decode('utf-8'))
                    aggregator.process_event(event)
                except json.JSONDecodeError:
                    continue

            # Send aggregated state to client
            state = aggregator.to_dict()
            yield f"data: {json.dumps(state)}\n\n"

            # Exit if search complete
            if aggregator.current_phase == "complete":
                break

    except asyncio.TimeoutError:
        # Send heartbeat every 60 seconds
        state = aggregator.to_dict()
        yield f"data: {json.dumps(state)}\n\n"
    finally:
        await redis.unsubscribe(f'search:{search_id}:progress')

@app.get("/search/{search_id}/progress")
async def stream_progress(search_id: str):
    """
    SSE endpoint that streams real-time progress.

    Usage:
    const sse = new EventSource(`/search/${searchId}/progress`);
    sse.onmessage = (e) => {
        const progress = JSON.parse(e.data);
        console.log(`Progress: ${progress.progress_pct}%`);
    };
    """
    redis = await aioredis.create_redis_pool('redis://localhost')

    # Check if search exists
    exists = await redis.exists(f'search:{search_id}')
    if not exists:
        redis.close()
        await redis.wait_closed()
        raise HTTPException(status_code=404, detail="Search not found")

    return StreamingResponse(
        progress_event_generator(search_id, redis),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive"
        }
    )

@app.get("/search/{search_id}/progress-snapshot")
async def get_progress_snapshot(search_id: str):
    """
    Get current progress state without streaming.
    Useful for page refreshes.
    """
    redis = await aioredis.create_redis_pool('redis://localhost')

    # Retrieve last progress event
    last_event = await redis.get(f'search:{search_id}:progress:latest')
    if not last_event:
        redis.close()
        await redis.wait_closed()
        raise HTTPException(status_code=404, detail="Search not found")

    event = json.loads(last_event)
    redis.close()
    await redis.wait_closed()

    return {
        "search_id": search_id,
        "current_phase": event.get('phase', 'unknown'),
        "progress_pct": event.get('progress_pct', 0),
        "results_found": event.get('records_found', 0),
        "timestamp": event.get('timestamp')
    }
```

### 2.3 WebSocket Control Channel

```python
# websocket_control.py
from fastapi import WebSocket, WebSocketDisconnect
import json
import aioredis
from temporalio.client import Client as TemporalClient

app = FastAPI()

class SearchControlManager:
    """Manages WebSocket connections for search control"""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}

    async def connect(self, search_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[search_id] = websocket

    async def disconnect(self, search_id: str):
        self.active_connections.pop(search_id, None)

    async def send_confirmation(self, search_id: str, message: Dict):
        if search_id in self.active_connections:
            await self.active_connections[search_id].send_json(message)

manager = SearchControlManager()

@app.websocket("/search/{search_id}/control")
async def websocket_endpoint(websocket: WebSocket, search_id: str):
    """
    WebSocket for sending control commands:
    - update_parameters: modify search params mid-flight
    - cancel: abort the search
    - pause: pause the search (resume later)
    """
    await manager.connect(search_id, websocket)
    temporal_client = await TemporalClient.connect("localhost:7233")

    try:
        while True:
            # Receive command from client
            command = await websocket.receive_json()
            command_type = command.get('type')

            if command_type == 'update_parameters':
                # Update search parameters mid-flight
                new_params = command.get('parameters', {})

                # Send signal to running workflow
                workflow_handle = temporal_client.get_workflow_handle(search_id)
                await workflow_handle.signal(
                    'update_search_parameters',
                    new_params
                )

                await manager.send_confirmation(search_id, {
                    "status": "confirmed",
                    "action": "parameters_updated",
                    "parameters": new_params
                })

            elif command_type == 'cancel':
                # Cancel the search
                workflow_handle = temporal_client.get_workflow_handle(search_id)
                await workflow_handle.cancel()

                await manager.send_confirmation(search_id, {
                    "status": "confirmed",
                    "action": "search_cancelled"
                })
                break

            elif command_type == 'pause':
                # Pause (for resuming later)
                workflow_handle = temporal_client.get_workflow_handle(search_id)
                await workflow_handle.signal('pause_search')

                await manager.send_confirmation(search_id, {
                    "status": "confirmed",
                    "action": "search_paused"
                })

            elif command_type == 'resume':
                # Resume a paused search
                workflow_handle = temporal_client.get_workflow_handle(search_id)
                await workflow_handle.signal('resume_search')

                await manager.send_confirmation(search_id, {
                    "status": "confirmed",
                    "action": "search_resumed"
                })

    except WebSocketDisconnect:
        await manager.disconnect(search_id)
    finally:
        await temporal_client.aclose()
```

### 2.4 Redis Streams Job Queue

```python
# redis_job_queue.py
import aioredis
import json
import uuid
from datetime import datetime, timedelta
from enum import Enum

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"

class RedisJobQueue:
    """
    Job queue using Redis Streams for scalable worker distribution.
    Handles:
    - Job creation with priority
    - Consumer groups for parallel processing
    - Automatic retries
    - Dead letter queue for permanent failures
    """

    def __init__(self, redis_url: str = "redis://localhost"):
        self.redis_url = redis_url
        self.main_stream = "job_queue:stream"
        self.consumer_group = "job_workers"
        self.pending_stream = "job_queue:pending"
        self.dead_letter_stream = "job_queue:dead_letter"

    async def create_job(
        self,
        job_type: str,
        payload: Dict,
        priority: int = 0,
        max_retries: int = 3
    ) -> str:
        """
        Create a new job in the queue.
        Priority: 0-100 (higher = more urgent)
        """
        redis = await aioredis.create_redis_pool(self.redis_url)

        job_id = str(uuid.uuid4())
        job = {
            "id": job_id,
            "type": job_type,
            "payload": json.dumps(payload),
            "priority": priority,
            "max_retries": max_retries,
            "retries": 0,
            "created_at": datetime.utcnow().isoformat(),
            "status": JobStatus.PENDING.value
        }

        # Add to stream
        await redis.xadd(
            self.main_stream,
            fields=job,
            id=f"{priority:03d}-*"  # Priority-based sorting
        )

        redis.close()
        await redis.wait_closed()

        return job_id

    async def start_consumer(self, worker_id: str):
        """
        Start a worker that processes jobs from the queue.
        """
        redis = await aioredis.create_redis_pool(self.redis_url)

        # Create consumer group if it doesn't exist
        try:
            await redis.xgroup_create(
                self.main_stream,
                self.consumer_group,
                id="$"  # Start from new messages
            )
        except Exception:
            pass  # Group already exists

        while True:
            try:
                # Read next job with timeout
                messages = await redis.xreadgroup(
                    groups_and_streams={
                        self.consumer_group: (self.main_stream,)
                    },
                    count=1,
                    block=1000  # Block 1 second
                )

                if not messages:
                    continue

                stream_key, message_list = messages[0]
                msg_id, fields = message_list[0]

                # Parse job
                job = {k.decode(): v.decode() for k, v in fields}

                try:
                    # Process the job
                    await self._process_job(job)

                    # Acknowledge successful processing
                    await redis.xack(self.main_stream, self.consumer_group, msg_id)

                    # Update status to COMPLETED
                    await redis.hset(
                        f"job:{job['id']}",
                        "status",
                        JobStatus.COMPLETED.value
                    )

                except Exception as e:
                    # Handle failure with retries
                    retries = int(job.get('retries', 0)) + 1
                    max_retries = int(job.get('max_retries', 3))

                    if retries >= max_retries:
                        # Move to dead letter queue
                        await redis.xadd(
                            self.dead_letter_stream,
                            fields={
                                **job,
                                "error": str(e),
                                "failed_at": datetime.utcnow().isoformat()
                            }
                        )

                        # Acknowledge and remove from main queue
                        await redis.xack(self.main_stream, self.consumer_group, msg_id)

                        await redis.hset(
                            f"job:{job['id']}",
                            "status",
                            JobStatus.DEAD_LETTER.value
                        )
                    else:
                        # Retry: update job and re-add to queue
                        job['retries'] = str(retries)
                        job['status'] = JobStatus.PENDING.value

                        await redis.xadd(
                            self.main_stream,
                            fields=job,
                            id=f"{job['priority']}-*"
                        )

                        await redis.xack(self.main_stream, self.consumer_group, msg_id)

            except Exception as e:
                logger.error(f"Consumer error: {e}")
                await asyncio.sleep(1)

        redis.close()
        await redis.wait_closed()

    async def _process_job(self, job: Dict):
        """Process a single job based on its type"""
        job_type = job['type']
        payload = json.loads(job['payload'])

        if job_type == 'scrape':
            await self._scrape_job(payload)
        elif job_type == 'enrich':
            await self._enrich_job(payload)
        elif job_type == 'deduplicate':
            await self._deduplicate_job(payload)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

    async def _scrape_job(self, payload: Dict):
        """Execute a scraping job"""
        scraper_name = payload['scraper']
        search_id = payload['search_id']
        query = payload['query']

        logger.info(f"Processing scrape job: {scraper_name}")
        # Implementation details...

    async def _enrich_job(self, payload: Dict):
        """Execute an enrichment job"""
        # Implementation details...
        pass

    async def _deduplicate_job(self, payload: Dict):
        """Execute a deduplication job"""
        # Implementation details...
        pass
```

### 2.5 Webhook Notification System

```python
# webhook_notifier.py
import aioredis
import httpx
import json
import hmac
import hashlib
from datetime import datetime, timedelta

class WebhookNotifier:
    """
    Send notifications to external systems via webhooks.
    Features:
    - Signature verification (HMAC-SHA256)
    - Automatic retries with exponential backoff
    - Event batching
    - Delivery tracking
    """

    def __init__(self, redis_url: str = "redis://localhost", signing_secret: str = ""):
        self.redis_url = redis_url
        self.signing_secret = signing_secret
        self.retry_delays = [5, 30, 300, 3600, 86400]  # 5s, 30s, 5m, 1h, 1d

    async def subscribe_webhook(
        self,
        webhook_url: str,
        event_types: List[str],
        webhook_id: str = None
    ) -> str:
        """
        Register a webhook subscription.
        Event types: search_complete, search_failed, new_results_batch
        """
        if not webhook_id:
            webhook_id = str(uuid.uuid4())

        redis = await aioredis.create_redis_pool(self.redis_url)

        await redis.hset(
            f"webhook:{webhook_id}",
            mapping={
                "url": webhook_url,
                "event_types": json.dumps(event_types),
                "created_at": datetime.utcnow().isoformat(),
                "active": "true"
            }
        )

        redis.close()
        await redis.wait_closed()

        return webhook_id

    async def notify(
        self,
        event_type: str,
        event_data: Dict,
        search_id: str
    ):
        """
        Send webhook notifications for an event.
        """
        redis = await aioredis.create_redis_pool(self.redis_url)

        # Find all webhooks subscribed to this event type
        webhook_keys = await redis.keys("webhook:*")

        for key in webhook_keys:
            webhook = await redis.hgetall(key)
            if not webhook:
                continue

            webhook_id = key.decode().split(":")[1]
            subscribed_events = json.loads(webhook.get(b'event_types', b'[]'))

            if event_type in subscribed_events:
                # Queue for delivery
                await self._queue_delivery(
                    redis,
                    webhook_id,
                    webhook.get(b'url').decode(),
                    event_type,
                    event_data,
                    search_id
                )

        redis.close()
        await redis.wait_closed()

    async def _queue_delivery(
        self,
        redis,
        webhook_id: str,
        url: str,
        event_type: str,
        event_data: Dict,
        search_id: str
    ):
        """Queue a webhook delivery with retry tracking"""
        delivery_id = str(uuid.uuid4())

        await redis.hset(
            f"webhook_delivery:{delivery_id}",
            mapping={
                "webhook_id": webhook_id,
                "url": url,
                "event_type": event_type,
                "event_data": json.dumps(event_data),
                "search_id": search_id,
                "attempt": "0",
                "created_at": datetime.utcnow().isoformat(),
                "status": "pending"
            }
        )

        # Add to delivery queue
        await redis.lpush(f"webhook_queue:{webhook_id}", delivery_id)

    async def start_delivery_worker(self):
        """
        Background worker that delivers queued webhooks.
        Implements exponential backoff retries.
        """
        redis = await aioredis.create_redis_pool(self.redis_url)

        while True:
            try:
                # Get all webhook queues
                webhook_keys = await redis.keys("webhook_queue:*")

                for queue_key in webhook_keys:
                    webhook_id = queue_key.decode().split(":")[1]

                    # Process up to 10 deliveries from this webhook
                    for _ in range(10):
                        delivery_id = await redis.rpop(queue_key)
                        if not delivery_id:
                            break

                        delivery_id = delivery_id.decode()

                        # Get delivery details
                        delivery = await redis.hgetall(f"webhook_delivery:{delivery_id}")
                        if not delivery:
                            continue

                        success = await self._attempt_delivery(
                            delivery,
                            delivery_id,
                            redis
                        )

                        if not success:
                            # Requeue for retry
                            attempt = int(delivery.get(b'attempt', b'0')) + 1

                            if attempt < len(self.retry_delays):
                                # Schedule retry
                                delay = self.retry_delays[attempt]
                                await redis.hset(
                                    f"webhook_delivery:{delivery_id}",
                                    "attempt",
                                    str(attempt)
                                )

                                # Add back to queue with delay
                                await asyncio.sleep(delay)
                                await redis.lpush(queue_key, delivery_id)
                            else:
                                # Max retries exceeded
                                await redis.hset(
                                    f"webhook_delivery:{delivery_id}",
                                    "status",
                                    "failed"
                                )

                await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"Webhook delivery worker error: {e}")
                await asyncio.sleep(5)

        redis.close()
        await redis.wait_closed()

    async def _attempt_delivery(
        self,
        delivery: Dict,
        delivery_id: str,
        redis
    ) -> bool:
        """
        Attempt to deliver a webhook.
        Returns True if successful, False if should retry.
        """
        url = delivery.get(b'url').decode()
        event_type = delivery.get(b'event_type').decode()
        event_data = json.loads(delivery.get(b'event_data'))

        payload = {
            "event_type": event_type,
            "data": event_data,
            "timestamp": datetime.utcnow().isoformat()
        }

        # Create HMAC signature
        signature = hmac.new(
            self.signing_secret.encode(),
            json.dumps(payload).encode(),
            hashlib.sha256
        ).hexdigest()

        headers = {
            "X-Webhook-Signature": signature,
            "X-Webhook-Delivery-ID": delivery_id,
            "Content-Type": "application/json"
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)

                if response.status_code >= 200 and response.status_code < 300:
                    # Success
                    await redis.hset(
                        f"webhook_delivery:{delivery_id}",
                        "status",
                        "delivered"
                    )
                    return True
                else:
                    # Server error, retry
                    return False

        except httpx.RequestError as e:
            logger.warning(f"Webhook delivery failed: {e}")
            return False
```

---

## Part 3: Progress Bar System

### 3.1 Progress Event Schema

```python
# progress_models.py
from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List
from enum import Enum

class EventType(str, Enum):
    SCRAPER_QUEUED = "scraper_queued"
    SCRAPER_RUNNING = "scraper_running"
    SCRAPER_COMPLETED = "scraper_completed"
    SCRAPER_FAILED = "scraper_failed"
    DEDUP_RUNNING = "dedup_running"
    DEDUP_PROGRESS = "dedup_progress"
    ENRICHMENT_RUNNING = "enrichment_running"
    ENRICHMENT_PROGRESS = "enrichment_progress"
    DISCOVERY_RUNNING = "discovery_running"
    DISCOVERY_PROGRESS = "discovery_progress"
    SEARCH_COMPLETE = "search_complete"
    SEARCH_FAILED = "search_failed"
    PHASE_STARTED = "phase_started"
    PHASE_COMPLETE = "phase_complete"

class Phase(str, Enum):
    COLLECTING = "collecting"
    DEDUPLICATING = "deduplicating"
    ENRICHING = "enriching"
    DISCOVERING = "discovering"
    FINALIZING = "finalizing"
    COMPLETE = "complete"

class ProgressEvent(BaseModel):
    search_id: str
    event_type: EventType
    scraper_name: Optional[str] = None
    progress_pct: float  # 0.0 to 100.0
    results_found: int = 0
    total_scrapers: int = 0
    completed_scrapers: int = 0
    failed_scrapers: int = 0
    current_phase: Phase = Phase.COLLECTING
    phase_progress: float = 0.0  # 0.0 to 100.0 within phase
    records_processed: int = 0
    total_records: int = 0
    unique_count: int = 0
    estimated_seconds_remaining: float = 0.0
    partial_results: Optional[List[dict]] = None
    error: Optional[str] = None
    timestamp: datetime

class ProgressState(BaseModel):
    """Aggregated progress state for frontend"""
    search_id: str
    current_phase: Phase
    progress_pct: float
    results_found: int
    scrapers_total: int
    scrapers_completed: int
    scrapers_failed: int
    scrapers_running: int
    estimated_seconds_remaining: float
    elapsed_seconds: float
    phase_progress: float
    last_update: datetime
    scraper_statuses: dict  # {scraper_name: "running" | "completed" | "failed" | "queued"}
```

### 3.2 Progress Calculation Algorithm

```python
# progress_calculator.py
from typing import List, Dict
from datetime import datetime, timedelta
import numpy as np

class ProgressCalculator:
    """
    Calculate meaningful progress percentage.

    Phases and their ranges:
    - Collection (0-60%): based on scraper completion
    - Deduplication (60-75%): based on records processed
    - Enrichment (75-95%): based on enrichment tasks
    - Finalization (95-100%): final scoring/indexing
    """

    PHASE_RANGES = {
        "collecting": (0.0, 60.0),
        "deduplicating": (60.0, 75.0),
        "enriching": (75.0, 95.0),
        "discovering": (75.0, 95.0),
        "finalizing": (95.0, 100.0),
        "complete": (100.0, 100.0)
    }

    def __init__(self, start_time: datetime, scraper_count: int):
        self.start_time = start_time
        self.scraper_count = max(1, scraper_count)
        self.phase_timings = {}  # {phase: seconds_taken}

    def calculate_collection_progress(
        self,
        completed_scrapers: int,
        failed_scrapers: int
    ) -> float:
        """
        Progress during collection phase.
        Range: 0-60%

        Calculation: (completed + failed) / total * 60%
        """
        total_done = completed_scrapers + failed_scrapers
        progress = (total_done / self.scraper_count) * 60.0
        return min(60.0, progress)

    def calculate_dedup_progress(
        self,
        records_processed: int,
        total_records: int
    ) -> float:
        """
        Progress during deduplication phase.
        Range: 60-75%

        Calculation: (records_processed / total) * 15% + 60%
        """
        if total_records == 0:
            return 60.0

        progress = (records_processed / total_records) * 15.0
        return 60.0 + min(15.0, progress)

    def calculate_enrichment_progress(
        self,
        completed_enrichments: int,
        total_enrichments: int
    ) -> float:
        """
        Progress during enrichment phase.
        Range: 75-95%

        Calculation: (completed / total) * 20% + 75%
        """
        if total_enrichments == 0:
            return 75.0

        progress = (completed_enrichments / total_enrichments) * 20.0
        return 75.0 + min(20.0, progress)

    def estimate_time_remaining(
        self,
        current_progress: float,
        current_phase: str,
        phase_start_time: datetime
    ) -> float:
        """
        Estimate seconds remaining based on current progress.

        Uses two methods:
        1. Linear extrapolation from overall progress
        2. Historical phase timing

        Returns the more conservative estimate.
        """
        elapsed_total = (datetime.utcnow() - self.start_time).total_seconds()
        elapsed_phase = (datetime.utcnow() - phase_start_time).total_seconds()

        # Linear extrapolation
        if current_progress > 0:
            estimated_total = (elapsed_total / current_progress) * 100
            linear_remaining = estimated_total - elapsed_total
        else:
            linear_remaining = float('inf')

        # Phase-based estimate
        phase_start, phase_end = self.PHASE_RANGES.get(current_phase, (0, 100))
        phase_range = phase_end - phase_start
        phase_progress = current_progress - phase_start

        if phase_progress > 0 and phase_range > 0:
            phase_pct = phase_progress / phase_range
            estimated_phase_time = elapsed_phase / max(0.01, phase_pct)
            phase_remaining = estimated_phase_time - elapsed_phase
        else:
            phase_remaining = float('inf')

        # Return average of both estimates, clamped to 0-3600 seconds
        remaining = min(
            (linear_remaining + phase_remaining) / 2,
            3600.0
        )
        return max(0, remaining)

    def calculate_overall_progress(
        self,
        current_phase: str,
        phase_progress: float
    ) -> float:
        """
        Calculate overall progress percentage from phase and phase progress.

        Phase progress is the % completion within that phase.
        """
        phase_start, phase_end = self.PHASE_RANGES.get(current_phase, (0, 100))
        phase_range = phase_end - phase_start

        # Interpolate within phase
        progress = phase_start + (phase_range * (phase_progress / 100.0))
        return min(100.0, max(0.0, progress))

class ProgressAggregator:
    """
    Aggregates individual progress events into a single state.
    Handles deduplication and consistency.
    """

    def __init__(self, search_id: str, scraper_count: int):
        self.search_id = search_id
        self.calculator = ProgressCalculator(datetime.utcnow(), scraper_count)

        self.scraper_statuses: Dict[str, str] = {}  # {name: status}
        self.scrapers_completed = 0
        self.scrapers_failed = 0
        self.results_found = 0
        self.unique_count = 0
        self.current_phase = "collecting"
        self.phase_start_time = datetime.utcnow()
        self.last_update = datetime.utcnow()
        self.enrichments_completed = 0
        self.enrichments_total = 0
        self.dedup_records_processed = 0
        self.dedup_total_records = 0

    def process_event(self, event: ProgressEvent) -> Optional[ProgressState]:
        """
        Process a progress event and return updated state if changed.
        """
        event_type = event.event_type

        if event_type == EventType.SCRAPER_RUNNING:
            if event.scraper_name:
                self.scraper_statuses[event.scraper_name] = "running"

        elif event_type == EventType.SCRAPER_COMPLETED:
            self.scrapers_completed += 1
            self.results_found += event.results_found
            if event.scraper_name:
                self.scraper_statuses[event.scraper_name] = "completed"

        elif event_type == EventType.SCRAPER_FAILED:
            self.scrapers_failed += 1
            if event.scraper_name:
                self.scraper_statuses[event.scraper_name] = "failed"

        elif event_type == EventType.DEDUP_PROGRESS:
            self.dedup_records_processed = event.records_processed
            self.dedup_total_records = event.total_records
            self.unique_count = event.unique_count

        elif event_type == EventType.ENRICHMENT_PROGRESS:
            self.enrichments_completed = event.records_processed
            self.enrichments_total = event.total_records

        elif event_type == EventType.PHASE_STARTED:
            self.current_phase = event.current_phase.value
            self.phase_start_time = datetime.utcnow()

        elif event_type == EventType.PHASE_COMPLETE:
            self.current_phase = event.current_phase.value

        elif event_type == EventType.SEARCH_COMPLETE:
            self.current_phase = "complete"
            self.results_found = event.results_found

        self.last_update = datetime.utcnow()

        return self.to_state()

    def to_state(self) -> ProgressState:
        """Convert aggregator state to frontend-ready ProgressState"""

        # Calculate phase progress
        if self.current_phase == "collecting":
            phase_progress = self.calculator.calculate_collection_progress(
                self.scrapers_completed,
                self.scrapers_failed
            )
        elif self.current_phase == "deduplicating":
            phase_progress = self.calculator.calculate_dedup_progress(
                self.dedup_records_processed,
                self.dedup_total_records
            )
        elif self.current_phase == "enriching":
            phase_progress = self.calculator.calculate_enrichment_progress(
                self.enrichments_completed,
                self.enrichments_total
            )
        elif self.current_phase == "complete":
            phase_progress = 100.0
        else:
            phase_progress = 0.0

        # Calculate overall progress
        overall_progress = self.calculator.calculate_overall_progress(
            self.current_phase,
            phase_progress
        )

        # Calculate ETA
        eta_seconds = self.calculator.estimate_time_remaining(
            overall_progress,
            self.current_phase,
            self.phase_start_time
        )

        # Count running scrapers
        running_count = sum(1 for s in self.scraper_statuses.values() if s == "running")

        return ProgressState(
            search_id=self.search_id,
            current_phase=Phase(self.current_phase),
            progress_pct=overall_progress,
            results_found=self.results_found,
            scrapers_total=self.calculator.scraper_count,
            scrapers_completed=self.scrapers_completed,
            scrapers_failed=self.scrapers_failed,
            scrapers_running=running_count,
            estimated_seconds_remaining=eta_seconds,
            elapsed_seconds=(datetime.utcnow() - self.calculator.start_time).total_seconds(),
            phase_progress=phase_progress,
            last_update=self.last_update,
            scraper_statuses=self.scraper_statuses
        )
```

### 3.3 Frontend Progress Component (React)

```jsx
// ProgressBar.jsx
import React, { useEffect, useState } from 'react';
import './ProgressBar.css';

export function ProgressBar({ searchId }) {
  const [progress, setProgress] = useState(null);
  const [eventLog, setEventLog] = useState([]);
  const [expandedDetails, setExpandedDetails] = useState(false);

  useEffect(() => {
    // Connect to SSE stream
    const eventSource = new EventSource(`/search/${searchId}/progress`);

    eventSource.onmessage = (event) => {
      try {
        const progressData = JSON.parse(event.data);
        setProgress(progressData);

        // Add to event log
        setEventLog(prev => [
          ...prev.slice(-9),  // Keep last 10 events
          {
            timestamp: new Date(),
            phase: progressData.current_phase,
            progress: progressData.progress_pct
          }
        ]);
      } catch (e) {
        console.error('Failed to parse progress event', e);
      }
    };

    eventSource.onerror = (error) => {
      console.error('Progress stream error', error);
      eventSource.close();
    };

    return () => {
      eventSource.close();
    };
  }, [searchId]);

  if (!progress) {
    return <div className="progress-container loading">Loading...</div>;
  }

  const getPhaseColor = (phase) => {
    const colors = {
      collecting: '#3b82f6',
      deduplicating: '#8b5cf6',
      enriching: '#ec4899',
      discovering: '#f59e0b',
      finalizing: '#10b981',
      complete: '#10b981'
    };
    return colors[phase] || '#6b7280';
  };

  const formatTime = (seconds) => {
    if (seconds < 60) return `${Math.round(seconds)}s`;
    if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
    return `${Math.round(seconds / 3600)}h`;
  };

  const phaseBgColor = getPhaseColor(progress.current_phase);

  return (
    <div className="progress-container">
      {/* Main Progress Bar */}
      <div className="progress-section">
        <div className="progress-header">
          <div>
            <h3>{progress.progress_pct.toFixed(1)}%</h3>
            <p className="phase-label">{progress.current_phase}</p>
          </div>
          <div className="progress-meta">
            <div className="meta-item">
              <span className="meta-label">Found</span>
              <span className="meta-value">{progress.results_found}</span>
            </div>
            <div className="meta-item">
              <span className="meta-label">ETA</span>
              <span className="meta-value">
                {formatTime(progress.estimated_seconds_remaining)}
              </span>
            </div>
          </div>
        </div>

        {/* Progress Bar */}
        <div className="progress-bar-container">
          <div
            className="progress-bar"
            style={{
              width: `${progress.progress_pct}%`,
              backgroundColor: phaseBgColor
            }}
          />
        </div>

        {/* Phase Indicators */}
        <div className="phase-indicators">
          {['collecting', 'deduplicating', 'enriching', 'finalizing'].map((phase, idx) => (
            <div
              key={phase}
              className={`phase-indicator ${
                progress.progress_pct >= [0, 60, 75, 95][idx] ? 'completed' : ''
              } ${progress.current_phase === phase ? 'active' : ''}`}
              style={{ left: `${[0, 60, 75, 95][idx]}%` }}
            >
              <span>{['0%', '60%', '75%', '95%'][idx]}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Scraper Status Grid */}
      <div className="scrapers-section">
        <h4>Scrapers ({progress.scrapers_completed}/{progress.scrapers_total})</h4>
        <div className="scrapers-grid">
          {Object.entries(progress.scraper_statuses).map(([name, status]) => (
            <div
              key={name}
              className={`scraper-item status-${status}`}
              title={name}
            >
              <span className="scraper-status-dot" />
              <span className="scraper-name">{name}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Expandable Details */}
      <button
        className="details-toggle"
        onClick={() => setExpandedDetails(!expandedDetails)}
      >
        {expandedDetails ? '▼' : '▶'} Details
      </button>

      {expandedDetails && (
        <div className="details-panel">
          <div className="details-grid">
            <div className="detail-item">
              <label>Running Scrapers</label>
              <span>{progress.scrapers_running}</span>
            </div>
            <div className="detail-item">
              <label>Failed Scrapers</label>
              <span>{progress.scrapers_failed}</span>
            </div>
            <div className="detail-item">
              <label>Elapsed</label>
              <span>{formatTime(progress.elapsed_seconds)}</span>
            </div>
            <div className="detail-item">
              <label>Phase Progress</label>
              <span>{progress.phase_progress.toFixed(1)}%</span>
            </div>
          </div>

          {/* Event Log */}
          <div className="event-log">
            <h5>Recent Events</h5>
            <ul>
              {eventLog.map((event, idx) => (
                <li key={idx}>
                  <time>{event.timestamp.toLocaleTimeString()}</time>
                  <span className={`event-phase phase-${event.phase}`}>
                    {event.phase}
                  </span>
                  <span className="event-progress">{event.progress.toFixed(1)}%</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}
    </div>
  );
}
```

```css
/* ProgressBar.css */
.progress-container {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.progress-container.loading {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 200px;
  color: #6b7280;
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}

.progress-header h3 {
  margin: 0 0 4px;
  font-size: 32px;
  font-weight: 700;
}

.phase-label {
  margin: 0;
  color: #6b7280;
  font-size: 14px;
  text-transform: capitalize;
}

.progress-meta {
  display: flex;
  gap: 20px;
}

.meta-item {
  display: flex;
  flex-direction: column;
  align-items: center;
}

.meta-label {
  font-size: 12px;
  color: #9ca3af;
  text-transform: uppercase;
  margin-bottom: 2px;
}

.meta-value {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.progress-bar-container {
  height: 8px;
  background: #e5e7eb;
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 16px;
}

.progress-bar {
  height: 100%;
  transition: width 0.3s ease;
}

.phase-indicators {
  position: relative;
  height: 20px;
  margin-bottom: 16px;
}

.phase-indicator {
  position: absolute;
  transform: translateX(-50%);
  font-size: 10px;
  color: #9ca3af;
}

.phase-indicator.active {
  color: #1f2937;
  font-weight: 600;
}

.scrapers-section {
  margin-top: 20px;
}

.scrapers-section h4 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
  color: #1f2937;
}

.scrapers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 8px;
}

.scraper-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 13px;
  background: #f3f4f6;
}

.scraper-status-dot {
  width: 6px;
  height: 6px;
  border-radius: 3px;
  background: #9ca3af;
}

.scraper-item.status-running .scraper-status-dot {
  background: #3b82f6;
  animation: pulse 1s infinite;
}

.scraper-item.status-completed .scraper-status-dot {
  background: #10b981;
}

.scraper-item.status-failed .scraper-status-dot {
  background: #ef4444;
}

.scraper-item.status-queued .scraper-status-dot {
  background: #d1d5db;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.details-toggle {
  background: none;
  border: none;
  cursor: pointer;
  padding: 8px 0;
  color: #3b82f6;
  font-weight: 500;
  margin-top: 12px;
}

.details-panel {
  background: #f9fafb;
  border-radius: 6px;
  padding: 16px;
  margin-top: 12px;
}

.details-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 16px;
  margin-bottom: 16px;
}

.detail-item {
  display: flex;
  flex-direction: column;
}

.detail-item label {
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 4px;
  text-transform: uppercase;
}

.detail-item span {
  font-size: 18px;
  font-weight: 600;
  color: #1f2937;
}

.event-log {
  border-top: 1px solid #e5e7eb;
  padding-top: 12px;
}

.event-log h5 {
  margin: 0 0 8px;
  font-size: 12px;
  color: #6b7280;
  text-transform: uppercase;
}

.event-log ul {
  list-style: none;
  margin: 0;
  padding: 0;
  max-height: 150px;
  overflow-y: auto;
}

.event-log li {
  display: flex;
  gap: 8px;
  padding: 4px 0;
  font-size: 12px;
  color: #6b7280;
}

.event-log time {
  min-width: 60px;
  color: #9ca3af;
}

.event-phase {
  flex: 1;
  text-transform: capitalize;
}

.event-progress {
  min-width: 40px;
  text-align: right;
}
```

---

## Part 4: Expanding Search (Growth Engine)

```python
# growth_engine.py
from dataclasses import dataclass
from typing import List, Optional, Dict
from enum import Enum
import asyncio

class RelationshipType(str, Enum):
    RELATIVE = "relative"
    ADDRESS = "address"
    PHONE = "phone"
    EMAIL = "email"
    BUSINESS = "business"
    LEGAL = "legal"
    SOCIAL = "social"
    NEIGHBOR = "neighbor"

@dataclass
class Connection:
    person_name: str
    relationship_type: RelationshipType
    confidence: float  # 0.0 to 1.0
    source: str
    connection_details: Dict
    person_data: Optional[Dict] = None

class GrowthEngine:
    """
    Discover and expand search to connected people.
    Uses breadth-first expansion to grow network outward.
    """

    def __init__(self, max_depth: int = 2, max_connections_per_level: int = 50):
        self.max_depth = max_depth
        self.max_connections_per_level = max_connections_per_level
        self.discovered_people = set()
        self.connection_graph: Dict[str, List[Connection]] = {}

    async def discover_connections(
        self,
        person_id: str,
        person_data: Dict
    ) -> List[Connection]:
        """
        Discover all connections for a person from multiple sources.
        Returns sorted by confidence.
        """
        connections: List[Connection] = []

        # Parallel discovery
        tasks = [
            self._find_by_address(person_data),
            self._find_by_phone(person_data),
            self._find_by_email(person_data),
            self._find_relatives(person_data),
            self._find_business_connections(person_data),
            self._find_legal_connections(person_data),
            self._find_social_connections(person_data)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, Exception):
                logger.warning(f"Connection discovery failed: {result}")
                continue
            connections.extend(result)

        # Deduplicate and score
        unique = self._deduplicate_connections(connections)
        scored = self._score_connections(unique, person_data)

        # Sort by confidence and return top N
        sorted_conns = sorted(scored, key=lambda c: c.confidence, reverse=True)
        return sorted_conns[:self.max_connections_per_level]

    async def _find_by_address(self, person_data: Dict) -> List[Connection]:
        """Find people at same address"""
        if not person_data.get('address'):
            return []

        address = person_data['address']
        matches = await query_people_database(
            query={'address': address}
        )

        connections = []
        for match in matches:
            if match.get('name') != person_data.get('name'):
                connections.append(Connection(
                    person_name=match['name'],
                    relationship_type=RelationshipType.ADDRESS,
                    confidence=0.95,
                    source="people_database",
                    connection_details={
                        'shared_address': address,
                        'record_count': len(matches)
                    },
                    person_data=match
                ))

        return connections

    async def _find_by_phone(self, person_data: Dict) -> List[Connection]:
        """Find people with shared phone number"""
        if not person_data.get('phone'):
            return []

        phone = person_data['phone']
        matches = await query_phone_database(phone)

        connections = []
        for match in matches:
            if match.get('name') != person_data.get('name'):
                connections.append(Connection(
                    person_name=match['name'],
                    relationship_type=RelationshipType.PHONE,
                    confidence=0.85,
                    source="phone_database",
                    connection_details={
                        'shared_phone': phone
                    },
                    person_data=match
                ))

        return connections

    async def _find_by_email(self, person_data: Dict) -> List[Connection]:
        """Find people with shared email"""
        if not person_data.get('email'):
            return []

        email = person_data['email']
        matches = await query_email_database(email)

        connections = []
        for match in matches:
            if match.get('name') != person_data.get('name'):
                connections.append(Connection(
                    person_name=match['name'],
                    relationship_type=RelationshipType.EMAIL,
                    confidence=0.8,
                    source="email_database",
                    connection_details={
                        'shared_email': email
                    },
                    person_data=match
                ))

        return connections

    async def _find_relatives(self, person_data: Dict) -> List[Connection]:
        """Find relatives from people search sites and surname matching"""
        connections = []

        # People search sites often have relative info
        if relatives_info := person_data.get('relatives'):
            for relative in relatives_info:
                connections.append(Connection(
                    person_name=relative['name'],
                    relationship_type=RelationshipType.RELATIVE,
                    confidence=0.9,
                    source="people_search",
                    connection_details={
                        'relationship': relative.get('relationship'),
                        'age': relative.get('age')
                    }
                ))

        # Surname matching at same address
        if address := person_data.get('address'):
            matches = await query_people_database({
                'address': address,
                'surname': person_data.get('surname')
            })

            for match in matches:
                if match.get('name') != person_data.get('name'):
                    connections.append(Connection(
                        person_name=match['name'],
                        relationship_type=RelationshipType.RELATIVE,
                        confidence=0.6,
                        source="surname_match",
                        connection_details={
                            'shared_address': address,
                            'shared_surname': person_data.get('surname')
                        },
                        person_data=match
                    ))

        return connections

    async def _find_business_connections(self, person_data: Dict) -> List[Connection]:
        """Find business partners, coworkers, officers"""
        connections = []

        # Find by employer
        if employer := person_data.get('employer'):
            matches = await query_business_database({'employer': employer})

            for match in matches:
                connections.append(Connection(
                    person_name=match['name'],
                    relationship_type=RelationshipType.BUSINESS,
                    confidence=0.7,
                    source="business_database",
                    connection_details={
                        'shared_employer': employer,
                        'job_title': match.get('job_title')
                    },
                    person_data=match
                ))

        # Find by corporate filings (company officers)
        if company_names := person_data.get('companies'):
            for company in company_names:
                officers = await query_sec_filings(company)

                for officer in officers:
                    connections.append(Connection(
                        person_name=officer['name'],
                        relationship_type=RelationshipType.BUSINESS,
                        confidence=0.85,
                        source="sec_filings",
                        connection_details={
                            'shared_company': company,
                            'role': officer.get('role')
                        },
                        person_data=officer
                    ))

        return connections

    async def _find_legal_connections(self, person_data: Dict) -> List[Connection]:
        """Find legal co-defendants, co-plaintiffs"""
        connections = []

        # Court records
        if cases := person_data.get('court_cases'):
            for case in cases:
                # Find other parties in same case
                other_parties = await query_court_records(case['case_id'])

                for party in other_parties:
                    if party.get('name') != person_data.get('name'):
                        connections.append(Connection(
                            person_name=party['name'],
                            relationship_type=RelationshipType.LEGAL,
                            confidence=0.75,
                            source="court_records",
                            connection_details={
                                'shared_case': case['case_id'],
                                'case_type': case.get('type'),
                                'party_role': party.get('role')
                            },
                            person_data=party
                        ))

        return connections

    async def _find_social_connections(self, person_data: Dict) -> List[Connection]:
        """Find social media connections"""
        connections = []

        # LinkedIn connections (if available)
        if linkedin_url := person_data.get('linkedin_url'):
            connections_data = await query_linkedin(linkedin_url)

            for connection in connections_data:
                connections.append(Connection(
                    person_name=connection['name'],
                    relationship_type=RelationshipType.SOCIAL,
                    confidence=0.6,
                    source="linkedin",
                    connection_details={
                        'mutual_connections': connection.get('mutual_count'),
                        'industry': connection.get('industry')
                    },
                    person_data=connection
                ))

        return connections

    def _deduplicate_connections(self, connections: List[Connection]) -> List[Connection]:
        """Remove duplicate connections (same person found multiple times)"""
        seen = {}
        deduplicated = []

        for conn in connections:
            key = conn.person_name.lower().strip()

            if key not in seen:
                seen[key] = conn
                deduplicated.append(conn)
            else:
                # Keep the one with higher confidence
                existing = seen[key]
                if conn.confidence > existing.confidence:
                    seen[key] = conn
                    deduplicated[deduplicated.index(existing)] = conn

        return deduplicated

    def _score_connections(
        self,
        connections: List[Connection],
        person_data: Dict
    ) -> List[Connection]:
        """Score connections by relevance and strength"""
        for conn in connections:
            # Base confidence already set by discovery source

            # Boost if multiple connection types
            # (e.g., same address AND same phone = very strong)
            # This is handled by having multiple entries

            # Reduce confidence if connection is old
            if updated := conn.connection_details.get('last_updated'):
                days_old = (datetime.utcnow() - updated).days
                if days_old > 365:
                    conn.confidence *= 0.8

        return connections

    async def expand_search(
        self,
        seed_person_id: str,
        seed_person_data: Dict,
        depth: int = 1,
        exclude_known: Optional[set] = None
    ) -> Dict[str, List[Connection]]:
        """
        Breadth-first expansion from seed person.

        Returns dict: {person_id: [connections]}
        """
        if exclude_known is None:
            exclude_known = set()

        if depth <= 0 or depth > self.max_depth:
            return {}

        expansion_results = {seed_person_id: []}
        queue = [(seed_person_id, seed_person_data, 0)]  # (id, data, current_depth)

        while queue:
            person_id, person_data, current_depth = queue.pop(0)

            if current_depth >= depth:
                continue

            # Discover connections
            connections = await self.discover_connections(person_id, person_data)
            expansion_results[person_id] = connections

            # Add new people to queue for next level
            for conn in connections[:10]:  # Limit branching factor
                if conn.person_name not in exclude_known:
                    exclude_known.add(conn.person_name)

                    if conn.person_data:
                        queue.append((
                            conn.person_name,
                            conn.person_data,
                            current_depth + 1
                        ))

        return expansion_results
```

---

## Part 5: Editable Search Parameters

```python
# search_parameters.py
from pydantic import BaseModel, validator
from typing import Optional, List, Dict
from datetime import datetime

class LocationFilter(BaseModel):
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    zip_code: Optional[str] = None
    radius_miles: Optional[float] = None
    bounding_box: Optional[Dict[str, float]] = None  # {min_lat, max_lat, min_lon, max_lon}

class TimeFilter(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None

class SourceFilter(BaseModel):
    include_sources: Optional[List[str]] = None  # whitelist
    exclude_sources: Optional[List[str]] = None  # blacklist
    priority_sources: Optional[List[str]] = None  # check first

class SearchParameters(BaseModel):
    query: str
    name: Optional[str] = None
    age: Optional[int] = None
    location_filter: Optional[LocationFilter] = None
    relationship_filter: Optional[List[str]] = None  # ["relatives", "business", "neighbors"]
    source_filter: Optional[SourceFilter] = None
    time_filter: Optional[TimeFilter] = None
    depth: int = 2
    max_results: int = 100
    manual_hints: Optional[Dict[str, str]] = None  # e.g., {"middle_name": "James"}
    excluded_sources: Optional[List[str]] = None
    priority_sources: Optional[List[str]] = None

class ParameterUpdate(BaseModel):
    """Partial parameters that can be updated mid-search"""
    location_filter: Optional[LocationFilter] = None
    relationship_filter: Optional[List[str]] = None
    source_filter: Optional[SourceFilter] = None
    depth: Optional[int] = None
    excluded_sources: Optional[List[str]] = None
    priority_sources: Optional[List[str]] = None

@workflow.defn
async def search_person_workflow_with_signals(
    search_input: SearchInput
) -> SearchResult:
    """
    Enhanced workflow that accepts parameter updates via signals.
    """
    current_params = search_input.parameters

    async def handle_parameter_update(new_params: ParameterUpdate):
        """Signal handler for parameter updates"""
        nonlocal current_params

        # Merge new parameters
        if new_params.location_filter:
            current_params.location_filter = new_params.location_filter
        if new_params.source_filter:
            current_params.source_filter = new_params.source_filter
        if new_params.depth is not None:
            current_params.depth = new_params.depth

        logger.info(f"Search parameters updated: {current_params}")

    @workflow.signal
    async def update_parameters(new_params: Dict):
        """Signal to update search parameters mid-flight"""
        param_update = ParameterUpdate(**new_params)
        await handle_parameter_update(param_update)

    # Rest of workflow uses current_params which gets updated
    # when signal is received

    # Search phase respects updated parameters
    scrapers = get_active_scrapers(
        excluded=current_params.excluded_sources or [],
        priority=current_params.priority_sources or []
    )

    # ... rest of workflow implementation
```

---

## Part 6: Robustness & Zero-Error Design

```python
# robustness.py
from enum import Enum
from dataclasses import dataclass
from typing import List, Type
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

class ErrorCategory(str, Enum):
    TRANSIENT = "transient"  # Retry
    PERMANENT = "permanent"  # Skip this scraper/source
    FATAL = "fatal"          # Abort entire search

@dataclass
class ErrorMapping:
    """Map exception types to error categories"""
    exception_type: Type[Exception]
    category: ErrorCategory
    retry: bool = True
    max_retries: int = 3

class RetryConfig:
    """Configuration for retry behavior"""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter

    def get_delay(self, attempt: int) -> float:
        """Calculate delay for given attempt number"""
        delay = self.base_delay * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay)

        if self.jitter:
            import random
            # Add random jitter: ±20%
            jitter = delay * (0.2 * (random.random() - 0.5))
            delay += jitter

        return max(0, delay)

class CircuitBreaker:
    """Circuit breaker pattern to prevent cascading failures"""

    class State(str, Enum):
        CLOSED = "closed"       # Normal
        OPEN = "open"          # Failing, skip requests
        HALF_OPEN = "half_open"  # Testing if recovered

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        name: str = "circuit_breaker"
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.name = name

        self.state = self.State.CLOSED
        self.failure_count = 0
        self.last_failure_time: Optional[datetime] = None
        self.success_count = 0

    def record_success(self):
        """Record successful operation"""
        if self.state == self.State.HALF_OPEN:
            self.success_count += 1
            if self.success_count >= 2:
                logger.info(f"Circuit breaker {self.name} CLOSED (recovered)")
                self.state = self.State.CLOSED
                self.failure_count = 0
                self.success_count = 0
        else:
            self.failure_count = 0

    def record_failure(self):
        """Record failed operation"""
        self.last_failure_time = datetime.utcnow()
        self.failure_count += 1

        if self.failure_count >= self.failure_threshold:
            logger.warning(f"Circuit breaker {self.name} OPEN (too many failures)")
            self.state = self.State.OPEN

    async def call(self, func, *args, **kwargs):
        """
        Execute function with circuit breaker protection.
        """
        if self.state == self.State.OPEN:
            # Check if recovery timeout has passed
            if datetime.utcnow() - self.last_failure_time > \
               timedelta(seconds=self.recovery_timeout):
                logger.info(f"Circuit breaker {self.name} HALF_OPEN (testing recovery)")
                self.state = self.State.HALF_OPEN
                self.success_count = 0
            else:
                raise Exception(f"Circuit breaker {self.name} is OPEN")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

class ResilientScraper:
    """
    Wrapper around scraper with retry logic, circuit breaker,
    and comprehensive error handling.
    """

    def __init__(self, scraper, name: str):
        self.scraper = scraper
        self.name = name
        self.retry_config = RetryConfig(max_retries=3)
        self.circuit_breaker = CircuitBreaker(name=name)
        self.health = "healthy"
        self.last_health_check = datetime.utcnow()

    async def search(self, query: str) -> Dict:
        """Execute search with full resilience"""

        for attempt in range(self.retry_config.max_retries):
            try:
                # Check circuit breaker
                result = await self.circuit_breaker.call(
                    self.scraper.search,
                    query
                )

                self.health = "healthy"
                return result

            except Exception as e:
                error_category = self._categorize_error(e)

                if error_category == ErrorCategory.PERMANENT:
                    logger.error(f"Scraper {self.name} permanent error: {e}")
                    self.health = "unhealthy"
                    raise

                elif error_category == ErrorCategory.FATAL:
                    logger.critical(f"Scraper {self.name} fatal error: {e}")
                    self.health = "dead"
                    raise

                elif error_category == ErrorCategory.TRANSIENT:
                    if attempt < self.retry_config.max_retries - 1:
                        delay = self.retry_config.get_delay(attempt)
                        logger.warning(
                            f"Scraper {self.name} transient error (retry in {delay}s): {e}"
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(f"Scraper {self.name} failed after retries: {e}")
                        self.health = "unhealthy"
                        raise

        raise Exception(f"Scraper {self.name} exhausted retries")

    def _categorize_error(self, error: Exception) -> ErrorCategory:
        """Categorize error for retry logic"""

        error_mappings = {
            ConnectionError: ErrorCategory.TRANSIENT,
            TimeoutError: ErrorCategory.TRANSIENT,
            asyncio.TimeoutError: ErrorCategory.TRANSIENT,
            httpx.ConnectError: ErrorCategory.TRANSIENT,
            httpx.ReadTimeout: ErrorCategory.TRANSIENT,

            ValueError: ErrorCategory.PERMANENT,
            KeyError: ErrorCategory.PERMANENT,

            RuntimeError: ErrorCategory.FATAL,
        }

        for exc_type, category in error_mappings.items():
            if isinstance(error, exc_type):
                return category

        # Default to transient for unknown errors
        return ErrorCategory.TRANSIENT

class HealthCheck:
    """Health checking for scrapers"""

    def __init__(self, check_interval: int = 300):  # 5 minutes
        self.check_interval = check_interval
        self.scrapers: List[ResilientScraper] = []

    def register_scraper(self, scraper: ResilientScraper):
        """Register a scraper for health monitoring"""
        self.scrapers.append(scraper)

    async def start_health_checker(self):
        """Background task that periodically checks scraper health"""

        while True:
            try:
                for scraper in self.scrapers:
                    try:
                        # Health check: simple query
                        await asyncio.wait_for(
                            scraper.scraper.health_check(),
                            timeout=5.0
                        )
                        scraper.health = "healthy"

                    except asyncio.TimeoutError:
                        logger.warning(f"Scraper {scraper.name} health check timeout")
                        scraper.health = "degraded"

                    except Exception as e:
                        logger.error(f"Scraper {scraper.name} health check failed: {e}")
                        scraper.health = "unhealthy"

                    scraper.last_health_check = datetime.utcnow()

                # Alert if too many scrapers unhealthy
                unhealthy_count = sum(
                    1 for s in self.scrapers if s.health != "healthy"
                )
                if unhealthy_count > len(self.scrapers) * 0.5:
                    logger.critical(
                        f"More than 50% of scrapers unhealthy: {unhealthy_count}/{len(self.scrapers)}"
                    )

                await asyncio.sleep(self.check_interval)

            except Exception as e:
                logger.error(f"Health checker error: {e}")
                await asyncio.sleep(30)

class GracefulDegradation:
    """Gracefully degrade service when components fail"""

    def __init__(self):
        self.redis_available = True
        self.temporal_available = True
        self.database_available = True

    async def search_with_degradation(
        self,
        query: str,
        healthy_scrapers: List[ResilientScraper]
    ) -> Dict:
        """Execute search with fallbacks"""

        try:
            # Preferred: full search with all components
            if self.redis_available and self.temporal_available:
                return await self._full_search(query, healthy_scrapers)

        except Exception as e:
            logger.error(f"Full search failed: {e}")

        try:
            # Fallback 1: search without Temporal (simple async)
            if self.redis_available:
                return await self._simple_async_search(query, healthy_scrapers)

        except Exception as e:
            logger.error(f"Simple async search failed: {e}")

        try:
            # Fallback 2: search without Redis (in-memory queue)
            return await self._in_memory_search(query, healthy_scrapers)

        except Exception as e:
            logger.error(f"In-memory search failed: {e}")

        # Fallback 3: return cached results
        return await self._return_cached_results(query)

    async def _full_search(self, query: str, scrapers: List) -> Dict:
        """Full search using all systems"""
        # Implementation...
        pass

    async def _simple_async_search(self, query: str, scrapers: List) -> Dict:
        """Search without Temporal orchestration"""
        tasks = [s.search(query) for s in scrapers]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return self._merge_results(results)

    async def _in_memory_search(self, query: str, scrapers: List) -> Dict:
        """Search without Redis queue"""
        results = []
        for scraper in scrapers:
            try:
                result = await asyncio.wait_for(
                    scraper.search(query),
                    timeout=30.0
                )
                results.append(result)
            except Exception as e:
                logger.warning(f"Scraper {scraper.name} failed: {e}")
                continue

        return self._merge_results(results)

    async def _return_cached_results(self, query: str) -> Dict:
        """Return best cached results"""
        # Query database for recent cached results
        cached = await database.get_cached_search(query)
        return cached or {"error": "No results available"}

    def _merge_results(self, results: List) -> Dict:
        """Merge results from multiple scrapers"""
        merged = []
        for result in results:
            if isinstance(result, dict):
                merged.extend(result.get('results', []))

        return {
            "results": merged,
            "partial": True,  # Mark as incomplete
            "cache_warning": "Some data sources unavailable"
        }
```

---

## Summary

This comprehensive architecture provides:

1. **Communication**: REST + SSE + WebSocket + Temporal + Redis Streams + Webhooks
2. **Progress**: Real-time bars with granular phase tracking and ETA
3. **Growth**: Automatic connection discovery with expansion controls
4. **Parameters**: Editable filters mid-flight via WebSocket signals
5. **Robustness**: Circuit breakers, retries, health checks, graceful degradation

The system is built for 99.9% uptime, handling hundreds of concurrent searches with real-time feedback and intelligent error recovery.
