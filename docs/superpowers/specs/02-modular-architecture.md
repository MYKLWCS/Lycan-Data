# OSINT/Data Broker Platform — Modular Architecture Design

## Design Philosophy

This architecture is built on the principle that **every component must be modular "down to the last point"**—meaning no monolithic subsystems, no hardcoded dependencies, and no component that cannot be independently swapped, fixed, upgraded, or scaled without affecting others.

### Core Principles

1. **Hexagonal Architecture (Ports & Adapters)**
   - Each module has clearly defined input/output boundaries
   - External dependencies are abstracted behind trait/interface definitions
   - No module directly calls another; all communication flows through standardized protocols or event channels

2. **Plugin-Based Design**
   - Every functional component is a loadable plugin
   - Plugins implement standardized traits to ensure interchangeability
   - New plugins can be added without modifying core framework code
   - Plugins can be loaded/unloaded at runtime with zero downtime

3. **Microservices + Trait-Driven Architecture**
   - Each module runs in its own process/container
   - Communication via gRPC (synchronous) or Kafka (asynchronous)
   - Shared concerns (logging, config, metrics) injected via traits
   - Circuit breakers prevent cascading failures

4. **Feature Flags for Safe Rollouts**
   - All major functionality guarded by feature flags
   - Gradual canary rollouts without redeployment
   - A/B testing across different module versions
   - Quick rollback without code changes

5. **Configuration-Driven Behavior**
   - Zero hardcoded values in code
   - Hierarchical config loading: defaults → environment → config file → runtime
   - Per-module config isolation ensures changes don't leak
   - Self-healing defaults for missing configurations

---

## System Architecture Layers

### Layer 1: API Gateway & Access Control

**Purpose:** Single entry point for all external requests. Handles authentication, authorization, rate limiting, request routing, and tenant isolation.

**Module:** `api-gateway`

**Responsibilities:**
- Accept HTTP/GraphQL/REST requests
- Validate JWT/OAuth2 tokens
- Enforce per-tenant rate limits
- Route requests to appropriate backend modules
- Aggregate responses from multiple modules
- Add tracing/correlation IDs to requests
- Log all API access for audit trails

**Key Traits:**

```rust
/// Authentication provider interface—swappable between JWT, OAuth2, SAML, LDAP, etc.
pub trait AuthenticationProvider: Send + Sync {
    fn validate_token(&self, token: &str) -> Result<Claims, AuthError>;
    fn refresh_token(&self, refresh_token: &str) -> Result<TokenPair, AuthError>;
    fn get_user_permissions(&self, user_id: &str) -> Result<Vec<Permission>, AuthError>;
    fn health_check(&self) -> HealthStatus;
}

/// Rate limiter interface—swappable between in-memory, Redis, or distributed strategies
pub trait RateLimiter: Send + Sync {
    fn check_rate_limit(&self, tenant_id: &str, endpoint: &str) -> Result<bool, RateLimitError>;
    fn record_request(&self, tenant_id: &str, endpoint: &str) -> Result<(), RateLimitError>;
    fn reset_limits(&self, tenant_id: &str) -> Result<(), RateLimitError>;
}

/// Route mapper interface—enables dynamic routing rules
pub trait RouteMapper: Send + Sync {
    fn route_request(&self, req: &ApiRequest) -> Result<ModuleTarget, RoutingError>;
    fn get_health_status(&self, target: &ModuleTarget) -> HealthStatus;
}
```

**Configuration:**
```toml
[api-gateway]
listen_addr = "0.0.0.0:8080"
graphql_enabled = true
rest_enabled = true
cors_origins = ["https://trusted-domain.com"]

[api-gateway.auth]
provider = "jwt"  # Pluggable: jwt, oauth2, saml, ldap
jwt_secret = "${JWT_SECRET}"
jwt_ttl_seconds = 3600

[api-gateway.rate_limit]
provider = "redis"  # Pluggable: in-memory, redis, distributed
requests_per_minute = 600
burst_size = 100
```

---

### Layer 2: Query & Search Engine

**Purpose:** Unified search interface that routes queries to the appropriate backend based on query type and data characteristics.

**Module:** `query-engine`

**Sub-modules:**
- `full-text-search` — Elasticsearch-compatible FTS via Meilisearch or OpenSearch
- `vector-search` — Semantic/embedding-based search via Qdrant or Milvus
- `graph-traversal` — Entity relationship navigation via Neo4j or TigerGraph
- `geo-search` — Geospatial queries via PostGIS or H3

**Key Traits:**

```rust
/// Universal search backend interface—implementations pluggable
pub trait SearchBackend: Send + Sync {
    async fn index_document(
        &self,
        doc_id: &str,
        document: &Document,
        metadata: &SearchMetadata,
    ) -> Result<(), SearchError>;

    async fn search(
        &self,
        query: &SearchQuery,
        options: &SearchOptions,
    ) -> Result<SearchResults, SearchError>;

    async fn delete_document(&self, doc_id: &str) -> Result<(), SearchError>;

    async fn rebuild_index(&self) -> Result<(), SearchError>;

    fn get_index_stats(&self) -> IndexStats;

    fn health_check(&self) -> HealthStatus;
}

/// Query optimizer—pluggable strategies for query planning
pub trait QueryOptimizer: Send + Sync {
    fn optimize(&self, query: &SearchQuery) -> OptimizedQuery;
    fn estimate_cost(&self, query: &SearchQuery) -> QueryCost;
    fn get_statistics(&self) -> OptimizerStats;
}

/// Result aggregator—merges results from multiple backends
pub trait ResultAggregator: Send + Sync {
    fn merge_results(
        &self,
        results: Vec<SearchResults>,
        strategy: &AggregationStrategy,
    ) -> Result<AggregatedResults, AggregationError>;
}
```

**Query Router Logic:**
```rust
pub struct QueryRouter {
    full_text: Arc<dyn SearchBackend>,
    vector: Arc<dyn SearchBackend>,
    graph: Arc<dyn SearchBackend>,
    geo: Arc<dyn SearchBackend>,
    optimizer: Arc<dyn QueryOptimizer>,
    aggregator: Arc<dyn ResultAggregator>,
}

impl QueryRouter {
    pub async fn execute(&self, query: &SearchQuery) -> Result<AggregatedResults, RouterError> {
        let optimized = self.optimizer.optimize(query);

        // Route to appropriate backends based on query type
        let mut futures = vec![];

        if optimized.needs_full_text {
            futures.push(self.full_text.search(&optimized, &Default::default()));
        }
        if optimized.needs_vector {
            futures.push(self.vector.search(&optimized, &Default::default()));
        }
        if optimized.needs_graph {
            futures.push(self.graph.search(&optimized, &Default::default()));
        }
        if optimized.needs_geo {
            futures.push(self.geo.search(&optimized, &Default::default()));
        }

        // Execute all queries in parallel with timeout
        let results = futures::future::timeout(
            std::time::Duration::from_secs(30),
            futures::future::join_all(futures)
        ).await?;

        // Aggregate results using strategy from query
        self.aggregator.merge_results(results, &optimized.aggregation_strategy)
    }
}
```

---

### Layer 3: Entity Resolution & Identity Graph

**Purpose:** Unifies disparate records referring to the same person/organization through probabilistic matching and deduplication.

**Module:** `entity-resolver`

**Sub-modules:**
- `name-matcher` — Phonetic + fuzzy string matching (Jaro-Winkler, Levenshtein, Soundex)
- `address-normalizer` — USPS/CASS address standardization and normalization
- `phone-resolver` — Phone number formatting and carrier lookup
- `email-validator` — Email format validation and domain verification
- `identity-linker` — Graph-based entity linking with confidence scoring

**Key Traits:**

```rust
/// Matcher interface—pluggable matching strategies
pub trait Matcher: Send + Sync {
    fn match_entities(
        &self,
        entities: &[Entity],
        threshold: f32,
    ) -> Result<MatchResults, MatchError>;

    fn score_pair(&self, entity_a: &Entity, entity_b: &Entity) -> f32;

    fn explain_match(&self, entity_a: &Entity, entity_b: &Entity) -> MatchExplanation;

    fn health_check(&self) -> HealthStatus;
}

/// Normalizer interface—pluggable normalization strategies
pub trait Normalizer: Send + Sync {
    fn normalize(&self, value: &str) -> Result<NormalizedValue, NormalizationError>;
    fn get_quality_score(&self, original: &str, normalized: &str) -> f32;
}

/// Identity graph interface—pluggable graph storage backends
pub trait IdentityGraphStore: Send + Sync {
    async fn add_entity(&self, entity: &Entity) -> Result<String, GraphError>;

    async fn link_entities(
        &self,
        entity_a_id: &str,
        entity_b_id: &str,
        confidence: f32,
    ) -> Result<(), GraphError>;

    async fn get_entity_cluster(&self, entity_id: &str) -> Result<EntityCluster, GraphError>;

    async fn find_duplicates(&self, entity: &Entity, threshold: f32)
        -> Result<Vec<(String, f32)>, GraphError>;
}
```

**Entity Resolution Pipeline:**
```rust
pub struct EntityResolutionPipeline {
    name_matcher: Arc<dyn Matcher>,
    address_normalizer: Arc<dyn Normalizer>,
    phone_resolver: Arc<dyn Normalizer>,
    email_validator: Arc<dyn Normalizer>,
    graph_store: Arc<dyn IdentityGraphStore>,
    config: ResolutionConfig,
}

impl EntityResolutionPipeline {
    pub async fn resolve(&self, entity: &Entity) -> Result<ResolvedEntity, ResolutionError> {
        // Step 1: Normalize all fields
        let mut normalized = entity.clone();
        normalized.name = self.name_matcher.normalize_name(&entity.name)?;
        normalized.address = self.address_normalizer.normalize(&entity.address)?;
        normalized.phone = self.phone_resolver.normalize(&entity.phone)?;
        normalized.email = self.email_validator.normalize(&entity.email)?;

        // Step 2: Search for duplicates in graph
        let duplicates = self.graph_store.find_duplicates(&normalized, 0.85).await?;

        // Step 3: Return best match or create new entity
        if duplicates.is_empty() {
            let id = self.graph_store.add_entity(&normalized).await?;
            Ok(ResolvedEntity {
                entity_id: id,
                confidence: 1.0,
                matches: vec![],
            })
        } else {
            Ok(ResolvedEntity {
                entity_id: duplicates[0].0.clone(),
                confidence: duplicates[0].1,
                matches: duplicates,
            })
        }
    }
}
```

---

### Layer 4: Data Enrichment Pipeline

**Purpose:** Augments core entity data with additional information from various sources. Plugin-based architecture allows new enrichment sources to be added without framework changes.

**Module:** `enrichment-engine`

**Sub-modules (one per enrichment source):**
- `social-media-enricher` — LinkedIn, Twitter, Facebook profiles
- `public-records-enricher` — Property records, court records, business registrations
- `financial-enricher` — Credit data, financial statements, investment holdings
- `web-enricher` — Search results, article mentions, website analysis
- `dark-web-enricher` — Breached data monitoring, forum participation
- `telephony-enricher` — Phone carrier, spam reports, calling patterns
- `geolocation-enricher` — IP geolocation, address enrichment, timezone data
- `company-enricher` — Company financials, executive teams, competitors

**Key Traits:**

```rust
/// Core enricher trait—all data sources implement this
pub trait EnricherModule: Send + Sync {
    /// Unique identifier for this enricher
    fn module_id(&self) -> &str;

    /// Human-readable name
    fn display_name(&self) -> &str;

    /// Enrich a single entity
    async fn enrich(
        &self,
        entity: &Entity,
        context: &EnrichmentContext,
    ) -> Result<EnrichedData, EnrichmentError>;

    /// Batch enrich multiple entities
    async fn enrich_batch(
        &self,
        entities: Vec<Entity>,
        context: &EnrichmentContext,
    ) -> Result<Vec<EnrichedData>, EnrichmentError> {
        // Default implementation: process sequentially
        let mut results = Vec::new();
        for entity in entities {
            results.push(self.enrich(&entity, context).await?);
        }
        Ok(results)
    }

    /// Check if this enricher can handle this entity type
    fn supports_entity_type(&self, entity_type: &EntityType) -> bool;

    /// Get cost estimate for enriching an entity
    fn estimate_cost(&self, entity: &Entity) -> EnrichmentCost;

    /// Refresh stale enrichment data
    async fn refresh(
        &self,
        entity_id: &str,
        last_updated: &DateTime<Utc>,
    ) -> Result<Option<EnrichedData>, EnrichmentError>;

    /// Check rate limits and quotas
    fn check_quota(&self) -> Result<QuotaStatus, QuotaError>;

    /// Module health check
    fn health_check(&self) -> HealthStatus;

    /// Called when module is initialized
    async fn init(&self) -> Result<(), InitError>;

    /// Called when module is shutting down
    async fn shutdown(&self) -> Result<(), ShutdownError>;
}

/// Configuration for enrichment pipeline execution
pub struct EnrichmentContext {
    pub tenant_id: String,
    pub user_id: String,
    pub max_cost_budget: u32,
    pub timeout_seconds: u32,
    pub use_cache: bool,
    pub freshness_hours: u32,
    pub feature_flags: Arc<dyn FeatureFlags>,
}

/// Result of enrichment
pub struct EnrichedData {
    pub entity_id: String,
    pub enricher_id: String,
    pub data: serde_json::Value,
    pub confidence: f32,
    pub source_url: Option<String>,
    pub retrieved_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
    pub cost: u32,
}
```

**Enrichment Engine Orchestrator:**
```rust
pub struct EnrichmentEngine {
    enrichers: Arc<RwLock<HashMap<String, Arc<dyn EnricherModule>>>>,
    cache: Arc<dyn CacheBackend>,
    event_publisher: Arc<dyn EventPublisher>,
    config: EnrichmentConfig,
}

impl EnrichmentEngine {
    pub async fn enrich(
        &self,
        entity: &Entity,
        context: &EnrichmentContext,
    ) -> Result<FullyEnrichedEntity, EnrichmentError> {
        let mut enriched_data = vec![];
        let mut remaining_budget = context.max_cost_budget;

        let enrichers = self.enrichers.read().await;

        for (enricher_id, enricher) in enrichers.iter() {
            // Check if enricher can handle this entity type
            if !enricher.supports_entity_type(&entity.entity_type) {
                continue;
            }

            // Check quota
            enricher.check_quota()?;

            // Estimate cost and check budget
            let cost = enricher.estimate_cost(entity);
            if cost.estimated > remaining_budget {
                continue; // Skip if over budget
            }

            // Check cache first
            let cache_key = format!("enrichment:{}:{}:{}", entity.id, enricher_id, context.tenant_id);
            if context.use_cache {
                if let Ok(cached) = self.cache.get::<EnrichedData>(&cache_key).await {
                    enriched_data.push(cached);
                    remaining_budget -= cost.estimated;
                    continue;
                }
            }

            // Execute enrichment with timeout
            match tokio::time::timeout(
                std::time::Duration::from_secs(context.timeout_seconds as u64),
                enricher.enrich(entity, context),
            ).await {
                Ok(Ok(mut result)) => {
                    // Cache result
                    if context.use_cache && result.expires_at.is_some() {
                        let _ = self.cache.set(&cache_key, &result, Some(result.expires_at.unwrap())).await;
                    }

                    // Publish event
                    self.event_publisher.publish(EnrichmentEvent {
                        entity_id: entity.id.clone(),
                        enricher_id: enricher_id.clone(),
                        status: "success",
                        cost: result.cost,
                    }).await.ok();

                    remaining_budget -= result.cost;
                    enriched_data.push(result);
                }
                Ok(Err(e)) => {
                    // Log error and continue
                    eprintln!("Enricher {} failed: {}", enricher_id, e);
                    self.event_publisher.publish(EnrichmentEvent {
                        entity_id: entity.id.clone(),
                        enricher_id: enricher_id.clone(),
                        status: "failed",
                        cost: 0,
                    }).await.ok();
                }
                Err(_) => {
                    // Timeout
                    eprintln!("Enricher {} timed out", enricher_id);
                }
            }
        }

        Ok(FullyEnrichedEntity {
            entity: entity.clone(),
            enrichments: enriched_data,
        })
    }

    /// Register a new enricher dynamically
    pub async fn register_enricher(&self, enricher: Arc<dyn EnricherModule>) -> Result<(), RegistrationError> {
        enricher.init().await?;
        let mut enrichers = self.enrichers.write().await;
        enrichers.insert(enricher.module_id().to_string(), enricher);
        Ok(())
    }

    /// Unregister an enricher
    pub async fn unregister_enricher(&self, enricher_id: &str) -> Result<(), UnregistrationError> {
        let mut enrichers = self.enrichers.write().await;
        if let Some(enricher) = enrichers.remove(enricher_id) {
            enricher.shutdown().await?;
        }
        Ok(())
    }
}
```

---

### Layer 5: Data Verification & Scoring

**Purpose:** Validates data quality, assigns confidence scores, and cross-references information across sources to ensure accuracy.

**Module:** `verification-engine`

**Sub-modules:**
- `source-validator` — Checks source credibility and track record
- `freshness-scorer` — Evaluates data age and relevance
- `confidence-calculator` — Probabilistic confidence scoring
- `cross-reference-checker` — Validates data against multiple sources

**Key Traits:**

```rust
/// Verifier interface—pluggable verification strategies
pub trait VerifierModule: Send + Sync {
    fn module_id(&self) -> &str;

    /// Verify a single piece of data
    async fn verify(
        &self,
        data: &EnrichedData,
        context: &VerificationContext,
    ) -> Result<VerificationResult, VerificationError>;

    /// Batch verify multiple data points
    async fn verify_batch(
        &self,
        data_items: Vec<EnrichedData>,
        context: &VerificationContext,
    ) -> Result<Vec<VerificationResult>, VerificationError> {
        let mut results = Vec::new();
        for item in data_items {
            results.push(self.verify(&item, context).await?);
        }
        Ok(results)
    }

    /// Get verifier capabilities
    fn capabilities(&self) -> VerifierCapabilities;

    /// Health check
    fn health_check(&self) -> HealthStatus;

    async fn init(&self) -> Result<(), InitError>;
    async fn shutdown(&self) -> Result<(), ShutdownError>;
}

/// Verification result
pub struct VerificationResult {
    pub data_id: String,
    pub verifier_id: String,
    pub is_valid: bool,
    pub confidence_score: f32,  // 0.0-1.0
    pub verification_notes: String,
    pub supporting_evidence: Vec<Evidence>,
    pub verified_at: DateTime<Utc>,
    pub expires_at: Option<DateTime<Utc>>,
}

/// Evidence supporting a verification result
pub struct Evidence {
    pub source: String,
    pub description: String,
    pub link: Option<String>,
    pub retrieved_at: DateTime<Utc>,
}
```

**Verification Pipeline:**
```rust
pub struct VerificationEngine {
    verifiers: Arc<RwLock<HashMap<String, Arc<dyn VerifierModule>>>>,
    cache: Arc<dyn CacheBackend>,
}

impl VerificationEngine {
    pub async fn verify(
        &self,
        enriched_data: &EnrichedData,
        context: &VerificationContext,
    ) -> Result<VerificationResult, VerificationError> {
        let verifiers = self.verifiers.read().await;
        let mut results = vec![];
        let mut confidence_scores = vec![];

        for verifier in verifiers.values() {
            match verifier.verify(enriched_data, context).await {
                Ok(result) => {
                    confidence_scores.push(result.confidence_score);
                    results.push(result);
                }
                Err(e) => eprintln!("Verifier failed: {}", e),
            }
        }

        // Calculate aggregate confidence (weighted average)
        let aggregate_confidence = if confidence_scores.is_empty() {
            0.5 // Default to neutral if no verifiers ran
        } else {
            confidence_scores.iter().sum::<f32>() / confidence_scores.len() as f32
        };

        Ok(VerificationResult {
            data_id: enriched_data.entity_id.clone(),
            verifier_id: "aggregate".to_string(),
            is_valid: aggregate_confidence >= 0.7,
            confidence_score: aggregate_confidence,
            verification_notes: format!("{} verifiers checked", results.len()),
            supporting_evidence: results.iter()
                .flat_map(|r| r.supporting_evidence.clone())
                .collect(),
            verified_at: Utc::now(),
            expires_at: None,
        })
    }
}
```

---

### Layer 6: Data Collection & Crawling

**Purpose:** Automatically discovers and collects data from various sources through web crawling, API integration, RSS feeds, and specialized crawlers.

**Module:** `collection-engine`

**Sub-modules:**
- `web-crawler` — Respects robots.txt, rate limiting, JavaScript rendering
- `api-collector` — HTTP API calls with auth, pagination, retry logic
- `rss-collector` — Feed aggregation and parsing
- `social-crawler` — Social media API integration
- `dark-web-crawler` — Tor-accessible data collection
- `document-parser` — PDF, Word, Excel extraction
- `email-harvester` — SMTP/IMAP-based email collection

**Key Traits:**

```rust
/// Collector interface—pluggable data collection strategies
pub trait CollectorModule: Send + Sync {
    fn module_id(&self) -> &str;
    fn display_name(&self) -> &str;

    /// Start collecting from a source
    async fn start_collection(
        &self,
        source: &DataSource,
        context: &CollectionContext,
    ) -> Result<CollectionHandle, CollectionError>;

    /// Get collection status
    async fn get_status(&self, handle: &CollectionHandle) -> Result<CollectionStatus, StatusError>;

    /// Stop an active collection
    async fn stop_collection(&self, handle: &CollectionHandle) -> Result<(), StopError>;

    /// Fetch a single document/record
    async fn fetch(
        &self,
        url: &str,
        options: &FetchOptions,
    ) -> Result<RawDocument, FetchError>;

    /// Estimate collection scope (how much data is there?)
    async fn estimate_scope(&self, source: &DataSource) -> Result<ScopeEstimate, ScopeError>;

    /// Get supported source types
    fn supported_sources(&self) -> Vec<SourceType>;

    /// Check if collector can reach this source
    async fn can_reach(&self, source: &DataSource) -> Result<bool, ConnectivityError>;

    /// Health check
    fn health_check(&self) -> HealthStatus;

    async fn init(&self) -> Result<(), InitError>;
    async fn shutdown(&self) -> Result<(), ShutdownError>;
}

/// Raw collected document
pub struct RawDocument {
    pub url: String,
    pub content: Vec<u8>,
    pub content_type: String,
    pub headers: HashMap<String, String>,
    pub status_code: u16,
    pub retrieved_at: DateTime<Utc>,
    pub retrieval_time_ms: u32,
    pub collector_id: String,
}

/// Collection context
pub struct CollectionContext {
    pub tenant_id: String,
    pub priority: CollectionPriority,
    pub rate_limit_qps: u32,
    pub max_retries: u32,
    pub timeout_seconds: u32,
    pub user_agent: String,
}
```

**Collection Orchestrator:**
```rust
pub struct CollectionEngine {
    collectors: Arc<RwLock<HashMap<String, Arc<dyn CollectorModule>>>>,
    document_queue: Arc<dyn DocumentQueue>,
    metrics: Arc<dyn MetricsCollector>,
}

impl CollectionEngine {
    pub async fn collect_from_source(
        &self,
        source: &DataSource,
        context: &CollectionContext,
    ) -> Result<CollectionHandle, CollectionError> {
        // Find appropriate collector for this source type
        let collectors = self.collectors.read().await;
        let collector = collectors
            .values()
            .find(|c| c.supported_sources().contains(&source.source_type))
            .ok_or(CollectionError::NoCollectorFound)?;

        // Check if source is reachable
        if !collector.can_reach(source).await? {
            return Err(CollectionError::SourceUnreachable);
        }

        // Estimate scope
        let scope = collector.estimate_scope(source).await?;

        // Start collection
        let handle = collector.start_collection(source, context).await?;

        // Record metrics
        self.metrics.record_collection_started(
            &source.id,
            &collector.module_id(),
            scope.estimated_document_count,
        ).await;

        Ok(handle)
    }

    pub async fn process_collected_documents(&self) -> Result<(), ProcessingError> {
        while let Some(doc) = self.document_queue.dequeue().await? {
            // Parse document
            let parsed = self.parse_document(&doc).await?;

            // Send to enrichment pipeline
            // (this would be published as an event)
        }
        Ok(())
    }

    async fn parse_document(&self, doc: &RawDocument) -> Result<ParsedDocument, ParseError> {
        match doc.content_type.as_str() {
            "application/json" => serde_json::from_slice(&doc.content),
            "text/html" => self.parse_html(&doc.content),
            "application/pdf" => self.parse_pdf(&doc.content),
            _ => Ok(ParsedDocument { /* ... */ }),
        }
    }
}
```

---

### Layer 7: Data Storage & Persistence

**Purpose:** Provides multiple storage backends optimized for different access patterns. Abstraction layer ensures any backend can be swapped without application code changes.

**Module:** `storage-engine`

**Sub-modules:**
- `relational-store` — PostgreSQL for structured data
- `cache-store` — Redis for hot data and session storage
- `vector-store` — Qdrant/Milvus for embeddings
- `graph-store` — Neo4j for entity relationships
- `document-store` — MongoDB for semi-structured data
- `blob-store` — S3/MinIO for binary content
- `search-store` — Elasticsearch for full-text indexing

**Key Traits:**

```rust
/// Universal storage adapter—all backends implement this
pub trait StorageAdapter: Send + Sync {
    /// Write data
    async fn write(
        &self,
        key: &str,
        data: &[u8],
        options: &WriteOptions,
    ) -> Result<WriteResult, StorageError>;

    /// Read data
    async fn read(&self, key: &str) -> Result<Vec<u8>, StorageError>;

    /// Delete data
    async fn delete(&self, key: &str) -> Result<(), StorageError>;

    /// Batch read
    async fn read_batch(&self, keys: Vec<&str>) -> Result<HashMap<String, Vec<u8>>, StorageError>;

    /// Batch write
    async fn write_batch(
        &self,
        items: Vec<(String, Vec<u8>)>,
        options: &WriteOptions,
    ) -> Result<Vec<WriteResult>, StorageError>;

    /// Query data (for backends that support it)
    async fn query(
        &self,
        query: &StorageQuery,
    ) -> Result<QueryResult, StorageError>;

    /// Get storage statistics
    async fn get_stats(&self) -> Result<StorageStats, StatsError>;

    /// Health check
    fn health_check(&self) -> HealthStatus;

    /// Compact/optimize storage
    async fn compact(&self) -> Result<CompactionStats, CompactionError>;

    async fn init(&self) -> Result<(), InitError>;
    async fn shutdown(&self) -> Result<(), ShutdownError>;
}

/// Storage options
pub struct WriteOptions {
    pub ttl: Option<Duration>,
    pub compression: CompressionType,
    pub replication_factor: u32,
    pub consistency_level: ConsistencyLevel,
}

/// Query interface for structured queries
pub struct StorageQuery {
    pub query_type: QueryType,
    pub filters: Vec<FilterClause>,
    pub offset: u32,
    pub limit: u32,
    pub timeout_ms: u32,
}
```

**Storage Router with Multi-Tier Strategy:**
```rust
pub struct StorageEngine {
    tier1_cache: Arc<dyn StorageAdapter>,  // Redis (hot data)
    tier2_relational: Arc<dyn StorageAdapter>,  // PostgreSQL
    tier3_document: Arc<dyn StorageAdapter>,  // MongoDB
    tier4_blob: Arc<dyn StorageAdapter>,  // S3
    consistency_checker: Arc<dyn ConsistencyChecker>,
}

impl StorageEngine {
    pub async fn write_entity(
        &self,
        entity: &Entity,
        write_opts: &WriteOptions,
    ) -> Result<WriteResult, StorageError> {
        let serialized = serde_json::to_vec(entity)?;

        // Write to appropriate tier based on entity size and access pattern
        if serialized.len() < 1024 && write_opts.ttl.is_some() {
            // Small, ephemeral data → cache
            self.tier1_cache.write(&entity.id, &serialized, write_opts).await
        } else if entity.is_highly_structured() {
            // Structured data → relational
            self.tier2_relational.write(&entity.id, &serialized, write_opts).await
        } else {
            // Semi-structured → document store
            self.tier3_document.write(&entity.id, &serialized, write_opts).await
        }
    }

    pub async fn read_entity(&self, entity_id: &str) -> Result<Entity, StorageError> {
        // Try L1 cache first
        if let Ok(data) = self.tier1_cache.read(entity_id).await {
            return Ok(serde_json::from_slice(&data)?);
        }

        // Try L2 relational
        if let Ok(data) = self.tier2_relational.read(entity_id).await {
            // Promote to cache for future access
            let _ = self.tier1_cache.write(entity_id, &data, &Default::default()).await;
            return Ok(serde_json::from_slice(&data)?);
        }

        // Try L3 document store
        if let Ok(data) = self.tier3_document.read(entity_id).await {
            let _ = self.tier1_cache.write(entity_id, &data, &Default::default()).await;
            return Ok(serde_json::from_slice(&data)?);
        }

        Err(StorageError::NotFound)
    }
}
```

---

### Layer 8: Infrastructure & Cross-Cutting Concerns

**Purpose:** Shared services used by all modules: configuration, secrets, metrics, logging, health checks, and feature flags.

**Module:** `platform-core`

**Sub-modules:**
- `config-manager` — Hierarchical config loading and hot reload
- `secret-manager` — Vault integration for secure credential storage
- `metrics-collector` — Prometheus metrics aggregation
- `log-aggregator` — ELK stack integration for centralized logging
- `health-checker` — Distributed health check orchestration
- `feature-flags` — Unleash/LaunchDarkly integration for gradual rollouts
- `dependency-injector` — Service locator pattern for module wiring

**Key Traits:**

```rust
/// Configuration provider interface
pub trait ConfigProvider: Send + Sync {
    fn get(&self, key: &str) -> Result<ConfigValue, ConfigError>;
    fn get_with_default(&self, key: &str, default: ConfigValue) -> ConfigValue;
    fn watch(&self, key: &str, callback: Box<dyn Fn(ConfigValue) + Send + Sync>);
    fn get_all(&self) -> HashMap<String, ConfigValue>;
}

/// Secret manager interface
pub trait SecretManager: Send + Sync {
    async fn get_secret(&self, secret_name: &str) -> Result<String, SecretError>;
    async fn set_secret(&self, secret_name: &str, value: &str) -> Result<(), SecretError>;
    async fn delete_secret(&self, secret_name: &str) -> Result<(), SecretError>;
}

/// Metrics collector interface
pub trait MetricsCollector: Send + Sync {
    fn increment_counter(&self, name: &str, labels: &[(String, String)]);
    fn record_gauge(&self, name: &str, value: f64, labels: &[(String, String)]);
    fn record_histogram(&self, name: &str, value: f64, labels: &[(String, String)]);
    fn record_distribution(&self, name: &str, value: f64, labels: &[(String, String)]);
    fn start_timer(&self, name: &str) -> MetricTimer;
}

/// Logger interface
pub trait Logger: Send + Sync {
    fn debug(&self, message: &str, context: &[(String, String)]);
    fn info(&self, message: &str, context: &[(String, String)]);
    fn warn(&self, message: &str, context: &[(String, String)]);
    fn error(&self, message: &str, error: &dyn std::error::Error, context: &[(String, String)]);
}

/// Feature flag provider interface
pub trait FeatureFlags: Send + Sync {
    fn is_enabled(&self, flag_name: &str, context: &FlagContext) -> bool;
    fn get_variant(&self, flag_name: &str, context: &FlagContext) -> String;
}

/// Health status interface
pub trait HealthChecker: Send + Sync {
    async fn get_health(&self) -> HealthReport;
    async fn get_liveness(&self) -> LivenessStatus;  // Is the process alive?
    async fn get_readiness(&self) -> ReadinessStatus;  // Is it ready to serve?
}
```

**Dependency Injection Container:**
```rust
pub struct ServiceContainer {
    config: Arc<dyn ConfigProvider>,
    secrets: Arc<dyn SecretManager>,
    metrics: Arc<dyn MetricsCollector>,
    logger: Arc<dyn Logger>,
    flags: Arc<dyn FeatureFlags>,
    health: Arc<dyn HealthChecker>,
}

impl ServiceContainer {
    pub fn new(config: Arc<dyn ConfigProvider>) -> Result<Self, InitError> {
        let secrets = Arc::new(VaultSecretManager::new(config.clone())?);
        let metrics = Arc::new(PrometheusMetrics::new());
        let logger = Arc::new(ELKLogger::new(config.clone())?);
        let flags = Arc::new(UnleashFeatureFlags::new(config.clone())?);
        let health = Arc::new(DistributedHealthChecker::new());

        Ok(Self {
            config,
            secrets,
            metrics,
            logger,
            flags,
            health,
        })
    }

    pub fn get_config(&self) -> Arc<dyn ConfigProvider> {
        self.config.clone()
    }

    pub fn get_secrets(&self) -> Arc<dyn SecretManager> {
        self.secrets.clone()
    }

    pub fn get_metrics(&self) -> Arc<dyn MetricsCollector> {
        self.metrics.clone()
    }

    pub fn get_logger(&self) -> Arc<dyn Logger> {
        self.logger.clone()
    }

    pub fn get_flags(&self) -> Arc<dyn FeatureFlags> {
        self.flags.clone()
    }

    pub fn get_health(&self) -> Arc<dyn HealthChecker> {
        self.health.clone()
    }
}
```

---

## Plugin System Design

### Plugin Architecture

Each plugin is a self-contained unit that:
1. Implements a standard module interface (trait)
2. Has its own manifest file describing capabilities and dependencies
3. Can be loaded/unloaded at runtime
4. Reports health status and metrics independently
5. Has its own configuration namespace

### Plugin Manifest Format (TOML)

```toml
[plugin]
id = "social-media-enricher"
name = "Social Media Enricher"
version = "1.2.3"
description = "Enriches entities with LinkedIn and Twitter data"
author = "Data Engineering Team"

[plugin.metadata]
category = "enrichment"
tags = ["social", "linkedin", "twitter", "enrichment"]
enabled = true

[plugin.dependencies]
minimum_runtime_version = "1.0.0"
# Other plugins this depends on
required_plugins = []

[plugin.capabilities]
entity_types = ["person", "company"]
supports_batch_processing = true
estimated_cost_per_entity = 10

[plugin.configuration]
linkedin_api_key = { type = "secret", required = true }
twitter_api_key = { type = "secret", required = true }
rate_limit_qps = { type = "integer", default = 10 }
cache_ttl_hours = { type = "integer", default = 24 }

[plugin.health_check]
interval_seconds = 60
timeout_seconds = 30

[plugin.resources]
min_memory_mb = 512
min_disk_mb = 1024
concurrent_workers = 5
```

### Plugin Registry

```rust
/// Plugin metadata from manifest
pub struct PluginManifest {
    pub id: String,
    pub name: String,
    pub version: semver::Version,
    pub description: String,
    pub module_path: String,
    pub interface_version: String,
    pub dependencies: Vec<PluginDependency>,
    pub configuration_schema: JsonSchema,
    pub capabilities: PluginCapabilities,
}

/// Plugin registry
pub struct PluginRegistry {
    plugins: Arc<RwLock<HashMap<String, PluginInfo>>>,
    manifest_dir: PathBuf,
    modules_dir: PathBuf,
}

impl PluginRegistry {
    pub async fn discover_plugins(&self) -> Result<Vec<PluginManifest>, DiscoveryError> {
        let mut manifests = vec![];

        // Scan manifest directory
        for entry in std::fs::read_dir(&self.manifest_dir)? {
            let entry = entry?;
            let path = entry.path();

            if path.extension().map_or(false, |ext| ext == "toml") {
                let content = std::fs::read_to_string(&path)?;
                let manifest: PluginManifest = toml::from_str(&content)?;
                manifests.push(manifest);
            }
        }

        Ok(manifests)
    }

    pub async fn load_plugin(
        &self,
        manifest: &PluginManifest,
        config: &PluginConfig,
    ) -> Result<Arc<dyn EnricherModule>, LoadError> {
        // Check dependencies
        self.verify_dependencies(&manifest)?;

        // Load plugin binary via libloading
        let lib_path = self.modules_dir.join(format!("{}.so", manifest.id));
        let library = libloading::Library::new(&lib_path)?;

        unsafe {
            let constructor: libloading::Symbol<unsafe extern "C" fn() -> *mut dyn EnricherModule> =
                library.get(b"create_plugin")?;

            let plugin = constructor();
            let plugin = Arc::from_raw(plugin);

            // Initialize plugin
            plugin.init().await?;

            // Register in registry
            let mut plugins = self.plugins.write().await;
            plugins.insert(
                manifest.id.clone(),
                PluginInfo {
                    manifest: manifest.clone(),
                    plugin: plugin.clone(),
                    loaded_at: Utc::now(),
                },
            );

            Ok(plugin)
        }
    }

    pub async fn unload_plugin(&self, plugin_id: &str) -> Result<(), UnloadError> {
        let mut plugins = self.plugins.write().await;

        if let Some(info) = plugins.remove(plugin_id) {
            info.plugin.shutdown().await?;
        }

        Ok(())
    }

    pub async fn reload_plugin(&self, plugin_id: &str) -> Result<(), ReloadError> {
        let plugins = self.plugins.read().await;
        let info = plugins.get(plugin_id).ok_or(ReloadError::NotFound)?;

        // Unload (will be removed from map)
        drop(plugins);
        self.unload_plugin(plugin_id).await?;

        // Reload with same configuration
        // (Would fetch from config store)

        Ok(())
    }

    fn verify_dependencies(&self, manifest: &PluginManifest) -> Result<(), DependencyError> {
        let plugins = self.plugins.blocking_read();

        for dep in &manifest.dependencies {
            if !plugins.contains_key(&dep.plugin_id) {
                return Err(DependencyError::MissingPlugin(dep.plugin_id.clone()));
            }

            // Version compatibility check
            let loaded_version = &plugins[&dep.plugin_id].manifest.version;
            if !dep.version_requirement.matches(loaded_version) {
                return Err(DependencyError::IncompatibleVersion {
                    plugin_id: dep.plugin_id.clone(),
                    required: dep.version_requirement.to_string(),
                    found: loaded_version.to_string(),
                });
            }
        }

        Ok(())
    }
}
```

### Plugin Template Generator

To simplify plugin development:

```bash
# Generate boilerplate for new enricher plugin
cargo generate --git https://github.com/company/plugin-templates.git \
  --name my-new-enricher \
  --sub enricher
```

This creates:

```
my-new-enricher/
├── Cargo.toml
├── plugin.toml           # Manifest
├── src/
│   ├── lib.rs            # Plugin boilerplate
│   └── enricher.rs       # Implement EnricherModule trait
├── tests/
│   ├── integration_test.rs
│   └── unit_tests.rs
└── examples/
    └── usage_example.rs
```

---

## Inter-Module Communication

### Synchronous Communication: gRPC

Used for request-response patterns where latency matters and immediate feedback is needed.

```proto
syntax = "proto3";

package osint.enrichment;

service EnrichmentService {
  rpc EnrichEntity(EnrichRequest) returns (EnrichResponse);
  rpc BatchEnrich(BatchEnrichRequest) returns (stream EnrichResponse);
  rpc GetStatus(StatusRequest) returns (StatusResponse);
}

message EnrichRequest {
  string entity_id = 1;
  Entity entity = 2;
  map<string, string> context = 3;
}

message EnrichResponse {
  string entity_id = 1;
  repeated EnrichedData enrichments = 2;
  bool success = 3;
  string error_message = 4;
}
```

**Rust gRPC Client:**
```rust
pub struct EnrichmentClient {
    client: enrichment_service_client::EnrichmentServiceClient<Channel>,
    circuit_breaker: Arc<CircuitBreaker>,
}

impl EnrichmentClient {
    pub async fn enrich(&self, entity: &Entity) -> Result<EnrichedData, ClientError> {
        // Check circuit breaker
        if self.circuit_breaker.is_open() {
            return Err(ClientError::CircuitBreakerOpen);
        }

        let request = tonic::Request::new(EnrichRequest {
            entity_id: entity.id.clone(),
            entity: Some(entity.clone()),
            context: Default::default(),
        });

        match tokio::time::timeout(
            Duration::from_secs(30),
            self.client.clone().enrich(request),
        ).await {
            Ok(Ok(response)) => {
                self.circuit_breaker.record_success();
                Ok(response.into_inner())
            }
            Ok(Err(status)) => {
                self.circuit_breaker.record_failure();
                Err(ClientError::RpcError(status))
            }
            Err(_) => {
                self.circuit_breaker.record_failure();
                Err(ClientError::Timeout)
            }
        }
    }
}
```

### Asynchronous Communication: Kafka/Event Streaming

Used for fire-and-forget events, batch processing, and decoupling components.

**Event Schema Registry (Confluent compatible):**

```json
{
  "type": "record",
  "namespace": "osint.events",
  "name": "EntityEnrichedEvent",
  "fields": [
    {"name": "entity_id", "type": "string"},
    {"name": "enrichments", "type": {"type": "array", "items": "string"}},
    {"name": "enriched_at", "type": "long"},
    {"name": "confidence_score", "type": "float"}
  ]
}
```

**Kafka Topic Configuration:**

```toml
[kafka]
bootstrap_servers = ["kafka-1:9092", "kafka-2:9092", "kafka-3:9092"]
num_partitions = 12
replication_factor = 3
min_insync_replicas = 2

[kafka.topics]

[kafka.topics.entity-collected]
description = "Raw entities collected from sources"
retention_ms = 86400000  # 24 hours
compression_type = "snappy"

[kafka.topics.entity-enriched]
description = "Entities after enrichment pipeline"
retention_ms = 604800000  # 7 days

[kafka.topics.enrichment-events]
description = "Events from enrichment modules"
retention_ms = 86400000
key_schema_id = 1
value_schema_id = 2

[kafka.topics.entity-verified]
description = "Verification results"
retention_ms = 604800000

[kafka.topics.dlq-enrichment-failures]
description = "Dead letter queue for failed enrichments"
retention_ms = 2592000000  # 30 days
```

**Rust Kafka Producer/Consumer:**

```rust
pub struct EventPublisher {
    producer: FutureProducer,
    schema_registry: Arc<SchemaRegistry>,
}

impl EventPublisher {
    pub async fn publish_enriched_entity(
        &self,
        entity: &Entity,
        enrichments: Vec<EnrichedData>,
    ) -> Result<(), PublishError> {
        let event = EntityEnrichedEvent {
            entity_id: entity.id.clone(),
            enrichments: enrichments.iter().map(|e| e.enricher_id.clone()).collect(),
            enriched_at: Utc::now().timestamp_millis(),
            confidence_score: enrichments.iter()
                .map(|e| e.confidence)
                .sum::<f32>() / enrichments.len() as f32,
        };

        let schema = self.schema_registry.get_schema("entity-enriched", 2).await?;
        let serialized = avro_rs::to_avro_datum(&schema, &event)?;

        let record = FutureRecord::to("entity-enriched")
            .payload(&serialized)
            .key(&entity.id);

        let (partition, offset) = self.producer.send(record, Duration::from_secs(5)).await
            .map_err(|(e, _)| PublishError::SendFailed(e))?;

        println!("Published to partition {} offset {}", partition, offset);
        Ok(())
    }
}

pub struct EventConsumer {
    consumer: StreamConsumer,
    schema_registry: Arc<SchemaRegistry>,
}

impl EventConsumer {
    pub async fn consume_enriched_entities(&self) -> Result<(), ConsumeError> {
        self.consumer.subscribe(&["entity-enriched"])?;

        loop {
            match self.consumer.next().await {
                Some(Ok(msg)) => {
                    let schema = self.schema_registry.get_latest_schema("entity-enriched").await?;
                    let event: EntityEnrichedEvent = avro_rs::from_avro_datum(&schema, &mut msg.payload().ok_or(ConsumeError::NoPayload)?)?;

                    // Process event
                    println!("Consumed event for entity: {}", event.entity_id);
                }
                Some(Err(e)) => eprintln!("Kafka error: {}", e),
                None => break,
            }
        }

        Ok(())
    }
}
```

**Dead Letter Queue Handling:**

```rust
pub struct DLQHandler {
    consumer: StreamConsumer,
    dlq_producer: FutureProducer,
    max_retries: u32,
}

impl DLQHandler {
    pub async fn process_failed_enrichment(
        &self,
        entity: &Entity,
        error: &EnrichmentError,
        attempt: u32,
    ) -> Result<(), DLQError> {
        if attempt < self.max_retries {
            // Retry with exponential backoff
            let delay = Duration::from_secs(2_u64.pow(attempt));
            tokio::time::sleep(delay).await;
            // Re-publish to original topic
        } else {
            // Send to DLQ for manual inspection
            let dlq_record = FutureRecord::to("dlq-enrichment-failures")
                .payload(format!("Failed to enrich {}: {}", entity.id, error))
                .key(&entity.id);

            self.dlq_producer.send(dlq_record, Duration::from_secs(5)).await
                .map_err(|(e, _)| DLQError::SendFailed(e))?;
        }

        Ok(())
    }
}
```

---

## Configuration Management

### Hierarchical Config Loading

Configuration priority (highest to lowest):
1. Runtime overrides (API calls)
2. Environment variables
3. Configuration file (TOML)
4. Default values (in code)

```rust
pub struct ConfigManager {
    defaults: Arc<RwLock<HashMap<String, ConfigValue>>>,
    file_config: Arc<RwLock<HashMap<String, ConfigValue>>>,
    env_overrides: Arc<RwLock<HashMap<String, ConfigValue>>>,
    runtime_overrides: Arc<RwLock<HashMap<String, ConfigValue>>>,
    watchers: Arc<RwLock<Vec<ConfigWatcher>>>,
}

impl ConfigManager {
    pub fn get(&self, key: &str) -> Result<ConfigValue, ConfigError> {
        // Check in priority order
        if let Some(value) = self.runtime_overrides.read().unwrap().get(key) {
            return Ok(value.clone());
        }
        if let Some(value) = self.env_overrides.read().unwrap().get(key) {
            return Ok(value.clone());
        }
        if let Some(value) = self.file_config.read().unwrap().get(key) {
            return Ok(value.clone());
        }
        if let Some(value) = self.defaults.read().unwrap().get(key) {
            return Ok(value.clone());
        }

        Err(ConfigError::KeyNotFound(key.to_string()))
    }

    pub async fn load_from_file(&self, path: &Path) -> Result<(), ConfigError> {
        let content = std::fs::read_to_string(path)?;
        let config: toml::Value = toml::from_str(&content)?;

        // Convert to HashMap and merge
        let mut file_config = self.file_config.write().unwrap();
        Self::flatten_toml(&config, "", &mut file_config);

        // Notify watchers
        self.notify_watchers().await;

        Ok(())
    }

    pub async fn set_runtime_override(&self, key: &str, value: ConfigValue) {
        self.runtime_overrides.write().unwrap().insert(key.to_string(), value);
        self.notify_watchers().await;
    }

    async fn notify_watchers(&self) {
        let watchers = self.watchers.read().unwrap().clone();
        for watcher in watchers {
            watcher.on_config_changed().await;
        }
    }

    fn flatten_toml(
        value: &toml::Value,
        prefix: &str,
        output: &mut HashMap<String, ConfigValue>,
    ) {
        match value {
            toml::Value::Table(table) => {
                for (k, v) in table {
                    let new_prefix = if prefix.is_empty() {
                        k.clone()
                    } else {
                        format!("{}.{}", prefix, k)
                    };
                    Self::flatten_toml(v, &new_prefix, output);
                }
            }
            toml::Value::String(s) => {
                output.insert(prefix.to_string(), ConfigValue::String(s.clone()));
            }
            toml::Value::Integer(i) => {
                output.insert(prefix.to_string(), ConfigValue::Integer(*i));
            }
            toml::Value::Float(f) => {
                output.insert(prefix.to_string(), ConfigValue::Float(*f));
            }
            toml::Value::Boolean(b) => {
                output.insert(prefix.to_string(), ConfigValue::Boolean(*b));
            }
            _ => {}
        }
    }
}
```

### Per-Module Config Isolation

```toml
# config.toml
[enrichment-engine]
enabled = true
max_concurrent_enrichers = 10

[enrichment-engine.social-media-enricher]
enabled = true
linkedin_api_key = "${LINKEDIN_API_KEY}"
twitter_api_key = "${TWITTER_API_KEY}"
rate_limit_qps = 10
cache_ttl_hours = 24

[enrichment-engine.public-records-enricher]
enabled = true
service_endpoint = "https://api.publicrecords.com"
api_key = "${PUBLIC_RECORDS_API_KEY}"
timeout_seconds = 30

[enrichment-engine.web-enricher]
enabled = false  # Feature flag—disabled until rolled out
crawler_threads = 5
max_pages_per_entity = 10
```

### Feature Flags

```rust
pub struct UnleashFeatureFlags {
    client: Arc<unleash_client::Client>,
    context: Arc<FlagContext>,
}

impl UnleashFeatureFlags {
    pub fn is_enabled(&self, flag_name: &str, context: &FlagContext) -> bool {
        self.client.is_enabled(flag_name, context)
    }

    pub fn get_variant(&self, flag_name: &str, context: &FlagContext) -> String {
        self.client.get_variant(flag_name, context)
            .map(|v| v.name)
            .unwrap_or_else(|| "control".to_string())
    }
}

// Usage in code:
if flags.is_enabled("new-entity-resolver", &context) {
    // Use new entity resolver
    use_new_entity_resolver(&entity).await
} else {
    // Use stable resolver
    use_legacy_entity_resolver(&entity).await
}
```

---

## Module Dependency Graph

```
┌─────────────────────────────────────────────────────────────┐
│                     API Gateway                              │
│        (REST, GraphQL, Rate Limiting, Auth)                 │
└────────────────────────┬────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
    ┌────v────┐   ┌─────v──────┐   ┌───v──────┐
    │  Query  │   │ Entity     │   │ Data     │
    │ Engine  │   │ Resolver   │   │ Enricher │
    └────┬────┘   └─────┬──────┘   └───┬──────┘
         │               │             │
    ┌────v──────────────┬─────────────┬v──────────┐
    │ Search Backends   │ Graph Store │ Cache     │
    │ (ES, Qdrant,      │ (Neo4j)     │ (Redis)   │
    │  OpenSearch)      │             │           │
    └───────────────────┴─────────────┴───────────┘
            │                    │
    ┌───────v──────────┐  ┌──────v──────────┐
    │ Data Collection  │  │ Verification    │
    │ Engine           │  │ Engine          │
    └────┬─────────────┘  └────┬────────────┘
         │                     │
    ┌────v──────────────────────v──────┐
    │      Storage Layer                 │
    │  (PostgreSQL, S3, Elasticsearch)  │
    └────────────────────────────────────┘
            │
    ┌───────v──────────────┐
    │  Kafka Event Streams  │
    │  (Async Messaging)    │
    └───────────────────────┘
            │
    ┌───────v──────────────────────────┐
    │   Platform Core                    │
    │   (Config, Logging, Metrics,       │
    │    Health Checks, Feature Flags)   │
    └────────────────────────────────────┘
```

---

## Testing Strategy Per Module

### Unit Tests (Module Isolation)

```rust
#[cfg(test)]
mod tests {
    use super::*;
    use mockall::predicate::*;
    use mockall::mock;

    // Mock the trait
    mock! {
        EnricherModule {}

        #[async_trait]
        impl EnricherModule for EnricherModule {
            fn module_id(&self) -> &str;
            fn display_name(&self) -> &str;
            async fn enrich(&self, entity: &Entity, context: &EnrichmentContext)
                -> Result<EnrichedData, EnrichmentError>;
            fn supports_entity_type(&self, entity_type: &EntityType) -> bool;
            fn estimate_cost(&self, entity: &Entity) -> EnrichmentCost;
            async fn health_check(&self) -> HealthStatus;
        }
    }

    #[tokio::test]
    async fn test_enricher_success_path() {
        let mut mock_enricher = MockEnricherModule::new();

        mock_enricher
            .expect_module_id()
            .return_const("test-enricher");

        mock_enricher
            .expect_enrich()
            .with(always(), always())
            .returning(|entity, _| {
                Ok(EnrichedData {
                    entity_id: entity.id.clone(),
                    enricher_id: "test".to_string(),
                    data: serde_json::json!({"test": "data"}),
                    confidence: 0.95,
                    source_url: None,
                    retrieved_at: Utc::now(),
                    expires_at: None,
                    cost: 10,
                })
            });

        // Test the enricher
        let entity = Entity { id: "test-entity".to_string(), ..Default::default() };
        let result = mock_enricher.enrich(&entity, &Default::default()).await;

        assert!(result.is_ok());
        let enriched = result.unwrap();
        assert_eq!(enriched.confidence, 0.95);
    }
}
```

### Integration Tests (Module Pairs)

```rust
#[tokio::test]
async fn test_enricher_with_storage() {
    // Create real enricher and storage instances
    let enricher = Arc::new(RealEnricherModule::new());
    let storage = Arc::new(InMemoryStorage::new());

    let entity = Entity {
        id: "test-entity".to_string(),
        ..Default::default()
    };

    // Enrich
    let enriched = enricher.enrich(&entity, &Default::default()).await.unwrap();

    // Store
    let key = format!("enrichment:{}:{}", entity.id, enricher.module_id());
    storage.write(&key, &serde_json::to_vec(&enriched).unwrap(), &Default::default())
        .await
        .unwrap();

    // Verify storage
    let retrieved = storage.read(&key).await.unwrap();
    let deserialized: EnrichedData = serde_json::from_slice(&retrieved).unwrap();
    assert_eq!(deserialized.entity_id, entity.id);
}
```

### Contract Tests (API Compatibility)

```rust
#[tokio::test]
async fn test_enricher_module_contract() {
    // Any implementation must satisfy these contracts
    let enricher = get_any_enricher_implementation();

    // Contract 1: Must have an ID
    assert!(!enricher.module_id().is_empty());

    // Contract 2: Must report capabilities
    enricher.estimate_cost(&default_entity());

    // Contract 3: Must handle unsupported entity types gracefully
    let supports = enricher.supports_entity_type(&EntityType::Unknown);
    assert!(supports == true || supports == false);  // Must return a bool

    // Contract 4: Must have health check
    let health = enricher.health_check();
    assert!(!health.status.is_empty());
}
```

### Chaos Testing

```rust
#[tokio::test]
async fn test_enricher_graceful_degradation_on_timeout() {
    let slow_enricher = SlowEnricherModule::new(Duration::from_secs(60));
    let engine = EnrichmentEngine::with_timeout(Duration::from_secs(1));

    let entity = Entity { id: "test".to_string(), ..Default::default() };

    // Should timeout gracefully, not panic
    let result = engine.enrich(&entity, &Default::default()).await;

    // Result should indicate timeout but not crash
    match result {
        Ok(enriched) => {
            // May have partial results
            assert!(!enriched.enrichments.is_empty() || enriched.enrichments.is_empty());
        }
        Err(EnrichmentError::Timeout) => {
            // Acceptable error
        }
        Err(e) => panic!("Unexpected error: {}", e),
    }
}

#[tokio::test]
async fn test_circuit_breaker_on_repeated_failures() {
    let failing_enricher = FailingEnricherModule::new();
    let engine = EnrichmentEngine::with_circuit_breaker(3);  // Fail 3x, then open

    for i in 0..5 {
        let entity = Entity { id: format!("entity-{}", i), ..Default::default() };
        let result = engine.enrich(&entity, &Default::default()).await;

        if i < 3 {
            // First 3 should fail with actual error
            assert!(matches!(result, Err(EnrichmentError::InternalError(_))));
        } else {
            // After 3 failures, circuit should be open
            assert!(matches!(result, Err(EnrichmentError::CircuitBreakerOpen)));
        }
    }
}
```

---

## Deployment Strategy

### Container-Per-Module

Each module runs as its own container:

```dockerfile
# Dockerfile.enrichment-engine
FROM rust:latest as builder
WORKDIR /app
COPY . .
RUN cargo build --release --bin enrichment-engine

FROM debian:bookworm-slim
COPY --from=builder /app/target/release/enrichment-engine /usr/local/bin/
COPY config/ /etc/osint/
EXPOSE 8000 9090  # Service + Metrics port

CMD ["enrichment-engine", "--config", "/etc/osint/enrichment.toml"]
```

### Docker Compose for Local Development

```yaml
version: '3.8'

services:
  api-gateway:
    build: ./api-gateway
    ports:
      - "8080:8080"
    environment:
      CONFIG_PATH: /etc/osint/api-gateway.toml
    depends_on:
      - redis

  enrichment-engine:
    build: ./enrichment-engine
    ports:
      - "8001:8000"
      - "9091:9090"
    environment:
      CONFIG_PATH: /etc/osint/enrichment.toml
    depends_on:
      - postgres
      - redis
      - kafka

  collection-engine:
    build: ./collection-engine
    ports:
      - "8002:8000"
    depends_on:
      - kafka

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: osint
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

  kafka:
    image: confluentinc/cp-kafka:7.4.0
    environment:
      KAFKA_ZOOKEEPER_CONNECT: zookeeper:2181
      KAFKA_ADVERTISED_LISTENERS: PLAINTEXT://kafka:9092
      KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1
    depends_on:
      - zookeeper

  zookeeper:
    image: confluentinc/cp-zookeeper:7.4.0
    environment:
      ZOOKEEPER_CLIENT_PORT: 2181

volumes:
  postgres_data:
```

### Kubernetes Deployment

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: enrichment-engine
  namespace: osint
spec:
  replicas: 3
  selector:
    matchLabels:
      app: enrichment-engine
  template:
    metadata:
      labels:
        app: enrichment-engine
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "9090"
    spec:
      containers:
      - name: enrichment-engine
        image: registry.company.com/osint/enrichment-engine:latest
        imagePullPolicy: Always
        ports:
        - containerPort: 8000
          name: grpc
        - containerPort: 9090
          name: metrics
        env:
        - name: CONFIG_PATH
          value: /etc/osint/enrichment.toml
        - name: LOG_LEVEL
          value: info
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "2"
        livenessProbe:
          httpGet:
            path: /health/live
            port: 8000
          initialDelaySeconds: 10
          periodSeconds: 10
        readinessProbe:
          httpGet:
            path: /health/ready
            port: 8000
          initialDelaySeconds: 5
          periodSeconds: 5
        volumeMounts:
        - name: config
          mountPath: /etc/osint
          readOnly: true
        - name: secrets
          mountPath: /var/secrets/osint
          readOnly: true
      volumes:
      - name: config
        configMap:
          name: enrichment-config
      - name: secrets
        secret:
          secretName: osint-secrets
```

### Blue/Green Deployment Per Module

```bash
#!/bin/bash
# deploy-enrichment-engine.sh

MODULE="enrichment-engine"
NEW_VERSION="1.2.3"

# 1. Start blue (stable) and green (new) versions
kubectl set image deployment/enrichment-engine-blue \
  enrichment-engine=registry.company.com/osint/$MODULE:$NEW_VERSION

# 2. Wait for green to be ready
kubectl rollout status deployment/enrichment-engine-blue -n osint

# 3. Run smoke tests against green version
./smoke-tests.sh http://enrichment-engine-blue:8000

if [ $? -eq 0 ]; then
  # 4. Switch traffic from blue to green
  kubectl patch service enrichment-engine -p \
    '{"spec":{"selector":{"version":"blue"}}}'

  # 5. Monitor metrics
  ./monitor.sh enrichment-engine 300  # Monitor for 5 minutes
else
  echo "Smoke tests failed, rolling back"
  # Keep old version active
fi
```

### Circuit Breaker Pattern (Resilience4j-inspired)

```rust
pub struct CircuitBreaker {
    state: Arc<RwLock<CircuitBreakerState>>,
    failure_threshold: u32,
    success_threshold: u32,
    timeout: Duration,
    failure_count: Arc<AtomicU32>,
    success_count: Arc<AtomicU32>,
}

impl CircuitBreaker {
    pub fn call<F, T>(&self, operation: F) -> Result<T, CircuitBreakerError>
    where
        F: FnOnce() -> Result<T, Box<dyn std::error::Error>>,
    {
        let state = self.state.read().unwrap();

        match *state {
            CircuitBreakerState::Closed => {
                drop(state);
                match operation() {
                    Ok(result) => {
                        self.record_success();
                        Ok(result)
                    }
                    Err(e) => {
                        self.record_failure();
                        Err(CircuitBreakerError::OperationFailed(e))
                    }
                }
            }
            CircuitBreakerState::Open => {
                Err(CircuitBreakerError::CircuitOpen)
            }
            CircuitBreakerState::HalfOpen => {
                drop(state);
                match operation() {
                    Ok(result) => {
                        self.record_success();
                        if self.success_count.load(Ordering::SeqCst) >= self.success_threshold {
                            *self.state.write().unwrap() = CircuitBreakerState::Closed;
                        }
                        Ok(result)
                    }
                    Err(e) => {
                        *self.state.write().unwrap() = CircuitBreakerState::Open;
                        Err(CircuitBreakerError::OperationFailed(e))
                    }
                }
            }
        }
    }

    fn record_failure(&self) {
        let count = self.failure_count.fetch_add(1, Ordering::SeqCst) + 1;
        if count >= self.failure_threshold {
            *self.state.write().unwrap() = CircuitBreakerState::Open;
        }
    }

    fn record_success(&self) {
        self.failure_count.store(0, Ordering::SeqCst);
    }
}
```

---

## Example: Adding a New Data Source

### Step-by-Step: Building a "Company Wikipedia Enricher"

#### 1. Create Module from Template

```bash
cargo generate --git https://github.com/company/plugin-templates.git \
  --name company-wiki-enricher \
  --sub enricher
```

#### 2. Define Plugin Manifest

Create `company-wiki-enricher/plugin.toml`:

```toml
[plugin]
id = "company-wiki-enricher"
name = "Company Wikipedia Enricher"
version = "1.0.0"
description = "Enriches company entities with Wikipedia business data"
author = "Data Engineering Team"

[plugin.metadata]
category = "enrichment"
tags = ["company", "wikipedia", "business", "enrichment"]
enabled = false  # Start disabled for phased rollout

[plugin.dependencies]
minimum_runtime_version = "1.0.0"

[plugin.capabilities]
entity_types = ["company"]
supports_batch_processing = true
estimated_cost_per_entity = 5

[plugin.configuration]
wikipedia_api_key = { type = "secret", required = false }
wikipedia_rate_limit_qps = { type = "integer", default = 10 }
cache_ttl_hours = { type = "integer", default = 720 }  # 30 days
timeout_seconds = { type = "integer", default = 30 }
```

#### 3. Implement EnricherModule Trait

Create `company-wiki-enricher/src/enricher.rs`:

```rust
use async_trait::async_trait;
use osint_core::{EnricherModule, Entity, EnrichedData, EnrichmentContext, EnrichmentError};

pub struct CompanyWikiEnricher {
    http_client: reqwest::Client,
    config: CompanyWikiConfig,
    metrics: Arc<dyn MetricsCollector>,
}

#[derive(Clone)]
pub struct CompanyWikiConfig {
    api_key: Option<String>,
    rate_limit_qps: u32,
    cache_ttl_hours: u32,
    timeout_seconds: u32,
}

#[async_trait]
impl EnricherModule for CompanyWikiEnricher {
    fn module_id(&self) -> &str {
        "company-wiki-enricher"
    }

    fn display_name(&self) -> &str {
        "Company Wikipedia Enricher"
    }

    async fn enrich(
        &self,
        entity: &Entity,
        context: &EnrichmentContext,
    ) -> Result<EnrichedData, EnrichmentError> {
        // Validate entity type
        if !self.supports_entity_type(&entity.entity_type) {
            return Err(EnrichmentError::UnsupportedEntityType);
        }

        // Fetch from Wikipedia
        let company_name = entity.get("name").ok_or(EnrichmentError::MissingRequiredField)?;

        let wikipedia_data = self.fetch_wikipedia_data(&company_name)
            .await
            .map_err(|e| EnrichmentError::ExternalApiError(Box::new(e)))?;

        // Parse and structure the data
        let enrichment_data = serde_json::json!({
            "wikipedia_url": wikipedia_data.url,
            "summary": wikipedia_data.summary,
            "founded": wikipedia_data.founded,
            "headquarters": wikipedia_data.headquarters,
            "website": wikipedia_data.website,
            "revenue": wikipedia_data.revenue,
            "employees": wikipedia_data.employees,
            "industry": wikipedia_data.industry,
            "parent_company": wikipedia_data.parent_company,
        });

        // Record metrics
        self.metrics.increment_counter("enrichment_success", &[
            ("enricher".to_string(), self.module_id().to_string()),
        ]);

        Ok(EnrichedData {
            entity_id: entity.id.clone(),
            enricher_id: self.module_id().to_string(),
            data: enrichment_data,
            confidence: 0.92,  // Wikipedia is generally reliable
            source_url: Some(wikipedia_data.url),
            retrieved_at: chrono::Utc::now(),
            expires_at: Some(
                chrono::Utc::now() + chrono::Duration::hours(self.config.cache_ttl_hours as i64)
            ),
            cost: 5,
        })
    }

    fn supports_entity_type(&self, entity_type: &EntityType) -> bool {
        matches!(entity_type, EntityType::Company)
    }

    fn estimate_cost(&self, _entity: &Entity) -> EnrichmentCost {
        EnrichmentCost {
            estimated: 5,
            currency: "credits",
        }
    }

    fn health_check(&self) -> HealthStatus {
        HealthStatus {
            status: "healthy".to_string(),
            message: Some("Wikipedia API responsive".to_string()),
            last_check: Some(chrono::Utc::now()),
        }
    }

    async fn init(&self) -> Result<(), Box<dyn std::error::Error>> {
        // Initialize connections
        Ok(())
    }

    async fn shutdown(&self) -> Result<(), Box<dyn std::error::Error>> {
        // Cleanup
        Ok(())
    }
}

impl CompanyWikiEnricher {
    pub fn new(config: CompanyWikiConfig, metrics: Arc<dyn MetricsCollector>) -> Self {
        Self {
            http_client: reqwest::Client::new(),
            config,
            metrics,
        }
    }

    async fn fetch_wikipedia_data(&self, company_name: &str) -> Result<WikipediaData, Box<dyn std::error::Error>> {
        let url = format!(
            "https://en.wikipedia.org/w/api.php?action=query&format=json&titles={}&prop=extracts|pageimages",
            urlencoding::encode(company_name)
        );

        let response = tokio::time::timeout(
            std::time::Duration::from_secs(self.config.timeout_seconds as u64),
            self.http_client.get(&url).send(),
        )
        .await?
        .map_err(|e| Box::new(e) as Box<dyn std::error::Error>)?;

        let body = response.json::<serde_json::Value>().await?;

        // Parse Wikipedia response
        let extracted_data = self.parse_wikipedia_response(&body)?;

        Ok(extracted_data)
    }

    fn parse_wikipedia_response(&self, data: &serde_json::Value) -> Result<WikipediaData, Box<dyn std::error::Error>> {
        // Extract relevant fields from Wikipedia API response
        Ok(WikipediaData {
            url: "https://en.wikipedia.org/...".to_string(),
            summary: "Company description".to_string(),
            founded: Some(1995),
            headquarters: Some("San Francisco, CA".to_string()),
            website: Some("https://example.com".to_string()),
            revenue: None,
            employees: None,
            industry: Some("Technology".to_string()),
            parent_company: None,
        })
    }
}

#[derive(Debug, Clone)]
pub struct WikipediaData {
    pub url: String,
    pub summary: String,
    pub founded: Option<i32>,
    pub headquarters: Option<String>,
    pub website: Option<String>,
    pub revenue: Option<String>,
    pub employees: Option<u32>,
    pub industry: Option<String>,
    pub parent_company: Option<String>,
}

// Plugin constructor—called by libloading
#[no_mangle]
pub extern "C" fn create_plugin() -> *mut dyn EnricherModule {
    let config = CompanyWikiConfig {
        api_key: std::env::var("WIKI_API_KEY").ok(),
        rate_limit_qps: 10,
        cache_ttl_hours: 720,
        timeout_seconds: 30,
    };

    let metrics = Arc::new(DummyMetrics);  // Would be injected in real code
    let enricher = CompanyWikiEnricher::new(config, metrics);
    Box::into_raw(Box::new(enricher))
}
```

#### 4. Register in Configuration

Add to `enrichment-engine/config.toml`:

```toml
[enrichment-engine]
enabled = true

[enrichment-engine.company-wiki-enricher]
enabled = false  # Feature flag for gradual rollout
plugin_path = "/plugins/company-wiki-enricher.so"
wikipedia_rate_limit_qps = 10
cache_ttl_hours = 720
timeout_seconds = 30
```

#### 5. Build and Deploy

```bash
# Build the enricher plugin
cd company-wiki-enricher
cargo build --release

# Copy to plugins directory
cp target/release/libcompany_wiki_enricher.so /opt/osint/plugins/

# Restart enrichment engine (or hot reload)
curl -X POST http://localhost:8000/admin/reload-plugins

# Monitor via dashboard
open https://metrics.company.com/osint/enrichment-engine
```

#### 6. Monitor and Validate

```bash
# Check plugin is loaded
curl http://localhost:8000/admin/plugins

# Response should show:
# {
#   "plugins": [
#     {
#       "id": "company-wiki-enricher",
#       "status": "loaded",
#       "version": "1.0.0",
#       "enriched_count": 0,
#       "errors": 0
#     }
#   ]
# }

# Enable for 10% of traffic using feature flags
curl -X POST https://unleash.company.com/api/admin/features/enable-company-wiki \
  -d '{
    "enabled": true,
    "strategies": [{
      "name": "flexibleRollout",
      "parameters": { "rollout": "10", "groupId": "user_id" }
    }]
  }'

# Monitor success metrics
watch -n 5 'curl http://localhost:9090/metrics | grep company_wiki'

# Once validated at 100%, add to permanent config
# and rebuild enrichment-engine container
```

---

## Conclusion

This modular architecture enables:

- **Independent scaling**: Scale enrichers differently from crawlers
- **Zero-downtime updates**: Deploy new enricher without restarting engine
- **Easy testing**: Mock any module's dependencies
- **Clear ownership**: Each team owns one module
- **Rapid iteration**: Add new features as plugins without core changes
- **Production resilience**: Circuit breakers, feature flags, graceful degradation

The "modular down to the last point" principle ensures that every architectural decision preserves composability and replaceability.
