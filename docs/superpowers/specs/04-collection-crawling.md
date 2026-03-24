# OSINT/Data Broker Platform — Collection & Crawling Infrastructure

## Collection Philosophy

The foundation of any effective OSINT/data broker platform rests on continuous, comprehensive data collection that operates at scale while respecting legal and technical boundaries. This document outlines a complete free/open-source infrastructure for collecting data from virtually every source available on the public internet, the deep web, and specialized databases.

### Core Principles

1. **Continuous Collection**: Data should be harvested perpetually from all identifiable sources with intelligent scheduling and prioritization
2. **Maximal Coverage**: Integrate every data source category — government records, social media, business registries, dark web monitoring, geospatial data, financial records, and specialized databases
3. **Anti-Detection**: Deploy sophisticated techniques to evade detection systems, rate limiting, and bot defenses while maintaining respect for infrastructure stability
4. **Distributed & Fault-Tolerant**: Build resilience through geographic distribution, redundancy, and self-healing mechanisms
5. **All Free/Open-Source**: Leverage no commercial crawling services, paid APIs beyond free tiers, or proprietary tools
6. **Adaptive Intelligence**: Implement change-detection, smart scheduling, and resource optimization based on data value and acquisition difficulty

---

## Crawl Architecture

### Distributed Crawler Design

The core of the collection infrastructure is a distributed, asynchronous web crawler designed for scale, reliability, and evasion.

#### High-Level Architecture

```
┌─────────────────────────────────────────────────────────┐
│         URL Frontier & Scheduler                         │
│  (Dragonfly Redis-Compatible + Priority Queue)          │
└────┬────────────────────────────────────────────────────┘
     │
     ├─────────────────────────────────────────────────────┐
     │                                                     │
┌────▼──────────────┐  ┌──────────────────┐  ┌───────────┴──┐
│ Crawler Pool      │  │ Crawler Pool      │  │ Crawler Pool │
│ (Instance 1)      │  │ (Instance 2)      │  │ (Instance N) │
│                   │  │                   │  │              │
│ ┌─────────────┐  │  │ ┌─────────────┐  │  │ ┌──────────┐ │
│ │reqwest      │  │  │ │reqwest      │  │  │ │reqwest   │ │
│ │+ tokio      │  │  │ │+ tokio      │  │  │ │+ tokio   │ │
│ │+ Playwright │  │  │ │+ Playwright │  │  │ │+ tor     │ │
│ │+ proxy mgr  │  │  │ │+ proxy mgr  │  │  │ │+ proxy   │ │
│ └─────────────┘  │  │ └─────────────┘  │  │ └──────────┘ │
└─────────────────┘  └──────────────────┘  └─────────────────┘
     │                   │                      │
     └───────────────────┼──────────────────────┘
                         │
         ┌───────────────▼────────────────┐
         │    Data Processing Pipeline    │
         │  (Parsing, NER, Extraction)    │
         └───────────────┬────────────────┘
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
┌───▼──────┐  ┌─────────▼─────┐  ┌───────────▼──┐
│  RDF      │  │  PostgreSQL   │  │  Elasticsearch│
│  Store    │  │  (Structured) │  │  (Full-Text) │
└──────────┘  └───────────────┘  └──────────────┘
```

#### Crawler Implementation (Rust + Tokio)

**Dependencies** (`Cargo.toml` excerpt):
```toml
[dependencies]
tokio = { version = "1.35", features = ["full"] }
reqwest = { version = "0.11", features = ["cookies", "gzip"] }
url = "2.5"
scraper = "0.18"
regex = "1.10"
serde = { version = "1.0", features = ["derive"] }
serde_json = "1.0"
redis = "0.24"
tokio-util = "0.7"
uuid = { version = "1.6", features = ["v4", "serde"] }
chrono = "0.4"
log = "0.4"
env_logger = "0.11"
anyhow = "1.0"
dashmap = "5.5"
bloom = "0.3"
governor = "0.10"
```

**Core Crawler Structure**:

```rust
use std::collections::VecDeque;
use std::sync::Arc;
use dashmap::DashMap;
use governor::{Quota, RateLimiter};
use reqwest::Client;
use scraper::Html;
use tokio::sync::Semaphore;
use url::Url;
use uuid::Uuid;
use serde::{Serialize, Deserialize};
use chrono::{DateTime, Utc};

/// Represents a URL to be crawled with metadata
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct CrawlTask {
    pub url: String,
    pub depth: u32,
    pub priority: f64,
    pub task_id: String,
    pub source_category: String,
    pub discovered_at: DateTime<Utc>,
    pub retry_count: u32,
    pub browser_required: bool,
}

impl CrawlTask {
    pub fn new(url: String, depth: u32, source_category: String) -> Self {
        Self {
            url,
            depth,
            priority: 1.0,
            task_id: Uuid::new_v4().to_string(),
            source_category,
            discovered_at: Utc::now(),
            retry_count: 0,
            browser_required: false,
        }
    }
}

/// Crawl response with extracted content
#[derive(Debug, Serialize, Deserialize)]
pub struct CrawlResult {
    pub task_id: String,
    pub url: String,
    pub status_code: u16,
    pub html_content: String,
    pub links: Vec<String>,
    pub metadata: std::collections::HashMap<String, String>,
    pub crawled_at: DateTime<Utc>,
    pub processing_ms: u64,
}

/// URL Frontier with priority queue and deduplication
pub struct UrlFrontier {
    queue: Arc<DashMap<String, CrawlTask>>,
    seen_urls: Arc<bloom::BloomFilter>,
    max_frontier_size: usize,
}

impl UrlFrontier {
    pub fn new(max_size: usize, bloom_size: usize) -> Self {
        Self {
            queue: Arc::new(DashMap::new()),
            seen_urls: Arc::new(bloom::BloomFilter::new(bloom_size, 5)),
            max_frontier_size: max_size,
        }
    }

    pub fn add_url(&self, task: CrawlTask) -> Result<bool, String> {
        let url = task.url.clone();

        // Check bloom filter for deduplication
        if self.seen_urls.contains(&url.as_bytes()) {
            return Ok(false); // Already seen
        }

        // Add to bloom filter
        self.seen_urls.insert(url.as_bytes());

        // Check frontier size
        if self.queue.len() >= self.max_frontier_size {
            return Err("Frontier queue full".to_string());
        }

        self.queue.insert(url, task);
        Ok(true)
    }

    pub fn pop_highest_priority(&self) -> Option<CrawlTask> {
        if self.queue.is_empty() {
            return None;
        }

        // Find task with highest priority
        let highest = self.queue
            .iter()
            .max_by(|a, b| a.value().priority.partial_cmp(&b.value().priority).unwrap_or(std::cmp::Ordering::Equal))?;

        let (key, task) = highest.pair();
        let task = task.clone();
        drop(highest);
        self.queue.remove(key);

        Some(task)
    }

    pub fn size(&self) -> usize {
        self.queue.len()
    }
}

/// Per-domain rate limiter and politeness manager
pub struct PolitenessManager {
    limiters: Arc<DashMap<String, RateLimiter>>,
    default_rps: f64,
    respect_robots_txt: bool,
}

impl PolitenessManager {
    pub fn new(default_rps: f64, respect_robots_txt: bool) -> Self {
        Self {
            limiters: Arc::new(DashMap::new()),
            default_rps,
            respect_robots_txt,
        }
    }

    pub async fn wait_for_domain(&self, domain: &str) {
        let limiter = self.limiters
            .entry(domain.to_string())
            .or_insert_with(|| {
                let quota = Quota::per_second(
                    std::num::NonZeroU32::new(self.default_rps as u32).unwrap_or(
                        std::num::NonZeroU32::new(1).unwrap()
                    )
                );
                RateLimiter::direct(quota)
            });

        limiter.until_ready().await;
    }

    pub fn set_domain_rps(&self, domain: String, rps: f64) {
        let quota = Quota::per_second(
            std::num::NonZeroU32::new(rps as u32).unwrap_or(
                std::num::NonZeroU32::new(1).unwrap()
            )
        );
        self.limiters.insert(domain, RateLimiter::direct(quota));
    }
}

/// Main crawler worker
pub struct CrawlerWorker {
    id: String,
    client: Client,
    frontier: Arc<UrlFrontier>,
    politeness: Arc<PolitenessManager>,
    max_depth: u32,
    connection_timeout: u64,
}

impl CrawlerWorker {
    pub fn new(
        id: String,
        frontier: Arc<UrlFrontier>,
        politeness: Arc<PolitenessManager>,
        max_depth: u32,
    ) -> Self {
        let client = Client::builder()
            .timeout(std::time::Duration::from_secs(30))
            .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            .cookie_store(true)
            .gzip(true)
            .brotli(true)
            .build()
            .unwrap();

        Self {
            id,
            client,
            frontier,
            politeness,
            max_depth,
            connection_timeout: 30,
        }
    }

    pub async fn crawl_task(&self, task: CrawlTask) -> Result<CrawlResult, String> {
        let start = std::time::Instant::now();

        // Parse URL
        let url = Url::parse(&task.url)
            .map_err(|e| format!("Invalid URL: {}", e))?;

        let domain = url.domain().ok_or("No domain in URL")?;

        // Apply politeness
        self.politeness.wait_for_domain(domain).await;

        // Fetch content
        let response = self.client
            .get(task.url.clone())
            .send()
            .await
            .map_err(|e| format!("Request failed: {}", e))?;

        let status = response.status().as_u16();
        let content = response.text().await
            .map_err(|e| format!("Content read failed: {}", e))?;

        // Parse HTML
        let document = Html::parse_document(&content);

        // Extract links
        let mut links = Vec::new();
        if task.depth < self.max_depth {
            let selector = scraper::Selector::parse("a[href]")
                .map_err(|_| "Selector parse error")?;

            for element in document.select(&selector) {
                if let Some(href) = element.value().attr("href") {
                    // Resolve relative URLs
                    if let Ok(absolute_url) = url.join(href) {
                        if absolute_url.domain() == Some(domain) {
                            // Same-domain crawl
                            links.push(absolute_url.to_string());
                        }
                    }
                }
            }
        }

        // Extract basic metadata
        let mut metadata = std::collections::HashMap::new();

        if let Ok(title_selector) = scraper::Selector::parse("title") {
            if let Some(title_elem) = document.select(&title_selector).next() {
                metadata.insert("title".to_string(), title_elem.inner_html());
            }
        }

        if let Ok(desc_selector) = scraper::Selector::parse("meta[name='description']") {
            if let Some(desc_elem) = document.select(&desc_selector).next() {
                if let Some(content) = desc_elem.value().attr("content") {
                    metadata.insert("description".to_string(), content.to_string());
                }
            }
        }

        let processing_ms = start.elapsed().as_millis() as u64;

        Ok(CrawlResult {
            task_id: task.task_id,
            url: task.url,
            status_code: status,
            html_content: content,
            links,
            metadata,
            crawled_at: Utc::now(),
            processing_ms,
        })
    }

    pub async fn run(&self) {
        loop {
            // Pop next task from frontier
            if let Some(task) = self.frontier.pop_highest_priority() {
                match self.crawl_task(task.clone()).await {
                    Ok(result) => {
                        log::info!(
                            "Crawler {} crawled {} ({}ms)",
                            self.id,
                            result.url,
                            result.processing_ms
                        );

                        // Add discovered links back to frontier
                        for link in result.links {
                            let new_task = CrawlTask {
                                url: link,
                                depth: task.depth + 1,
                                source_category: task.source_category.clone(),
                                priority: 0.8,
                                ..CrawlTask::new(String::new(), 0, String::new())
                            };

                            if let Err(e) = self.frontier.add_url(new_task) {
                                log::debug!("Could not add URL to frontier: {}", e);
                            }
                        }
                    }
                    Err(e) => {
                        log::error!("Crawler {} error on {}: {}", self.id, task.url, e);
                    }
                }
            } else {
                // Frontier empty, wait briefly
                tokio::time::sleep(tokio::time::Duration::from_secs(5)).await;
            }
        }
    }
}

/// Distributed crawler coordinator
pub struct CrawlerPool {
    workers: Vec<tokio::task::JoinHandle<()>>,
    frontier: Arc<UrlFrontier>,
    politeness: Arc<PolitenessManager>,
}

impl CrawlerPool {
    pub fn new(num_workers: usize, frontier: Arc<UrlFrontier>, politeness: Arc<PolitenessManager>) -> Self {
        let mut workers = Vec::new();

        for i in 0..num_workers {
            let worker = CrawlerWorker::new(
                format!("worker-{}", i),
                frontier.clone(),
                politeness.clone(),
                10, // max depth
            );

            let handle = tokio::spawn(async move {
                worker.run().await;
            });

            workers.push(handle);
        }

        Self {
            workers,
            frontier,
            politeness,
        }
    }

    pub fn add_seed_url(&self, url: String, category: String) -> Result<(), String> {
        let task = CrawlTask::new(url, 0, category);
        self.frontier.add_url(task)
    }

    pub fn frontier_size(&self) -> usize {
        self.frontier.size()
    }
}
```

---

## Anti-Detection & Bypass Techniques

### Browser Fingerprint Rotation

Modern websites employ sophisticated fingerprinting to detect crawlers. This requires constant rotation of identifying characteristics.

#### User-Agent Rotation Strategy

```rust
use std::sync::Arc;
use parking_lot::RwLock;
use rand::Rng;

pub struct UserAgentRotator {
    user_agents: Vec<String>,
    current_index: Arc<RwLock<usize>>,
}

impl UserAgentRotator {
    pub fn new() -> Self {
        let user_agents = vec![
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36".to_string(),
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36".to_string(),
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36".to_string(),
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0".to_string(),
            "Mozilla/5.0 (X11; Linux x86_64; rv:121.0) Gecko/20100101 Firefox/121.0".to_string(),
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15".to_string(),
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edge/120.0.0.0".to_string(),
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1".to_string(),
            "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36".to_string(),
        ];

        Self {
            user_agents,
            current_index: Arc::new(RwLock::new(0)),
        }
    }

    pub fn get_random(&self) -> String {
        let mut rng = rand::thread_rng();
        let idx = rng.gen_range(0..self.user_agents.len());
        self.user_agents[idx].clone()
    }

    pub fn get_next(&self) -> String {
        let mut index = self.current_index.write();
        let ua = self.user_agents[*index].clone();
        *index = (*index + 1) % self.user_agents.len();
        ua
    }
}
```

#### TLS Fingerprint Randomization

```python
# Using utls-python bindings for TLS fingerprint rotation
from utls import ClientHello, TLS_CHROME_120, TLS_FIREFOX_121, TLS_SAFARI_17

class TLSFingerprintRotator:
    def __init__(self):
        self.profiles = [
            TLS_CHROME_120,
            TLS_FIREFOX_121,
            TLS_SAFARI_17,
        ]
        self.current_idx = 0

    def get_next_profile(self):
        """Return next TLS profile for fingerprint rotation"""
        profile = self.profiles[self.current_idx]
        self.current_idx = (self.current_idx + 1) % len(self.profiles)
        return profile

    def create_client_hello(self):
        """Build randomized ClientHello with selected profile"""
        profile = self.get_next_profile()

        # Add entropy
        ch = ClientHello(
            cipher_suites=self._randomize_ciphers(profile.ciphers),
            extensions=self._randomize_extensions(profile.extensions),
            supported_groups=self._randomize_groups(profile.groups),
            supported_signatures=self._randomize_signatures(profile.sigs),
        )
        return ch

    def _randomize_ciphers(self, ciphers):
        """Randomize order while keeping weak ciphers for authenticity"""
        import random
        ciphers = list(ciphers)
        random.shuffle(ciphers)
        return ciphers

    def _randomize_extensions(self, extensions):
        """Randomize extension order and parameters"""
        import random
        exts = list(extensions)
        random.shuffle(exts)

        # Add minor variations (supported_versions, key_share, etc)
        return exts

    def _randomize_groups(self, groups):
        import random
        g = list(groups)
        random.shuffle(g)
        return g

    def _randomize_signatures(self, sigs):
        import random
        s = list(sigs)
        random.shuffle(s)
        return s
```

#### Canvas Fingerprint Spoofing

```python
# Playwright-based canvas fingerprint randomization
from playwright.async_api import async_playwright
import asyncio

class CanvasFingerprintSpoofer:
    """Inject JavaScript to randomize canvas fingerprint"""

    SPOOF_SCRIPT = """
    (() => {
        const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
        const originalToBlob = HTMLCanvasElement.prototype.toBlob;
        const originalGetContext = HTMLCanvasElement.prototype.getContext;

        const noise = Math.random() * 0.01; // 1% noise

        HTMLCanvasElement.prototype.getContext = function(type, ...args) {
            const context = originalGetContext.apply(this, [type, ...args]);

            if (type === '2d') {
                const originalFillRect = context.fillRect;
                context.fillRect = function(...args) {
                    // Add imperceptible noise
                    const rand = (Math.random() - 0.5) * noise;
                    args[0] += rand;
                    return originalFillRect.apply(this, args);
                };
            }

            return context;
        };

        HTMLCanvasElement.prototype.toDataURL = function(type, ...args) {
            const data = originalToDataURL.apply(this, [type, ...args]);
            // Imperceptibly modify pixel data
            return data.replace(/([0-9a-f]{2})/gi, (match) => {
                const val = parseInt(match, 16);
                const modified = Math.max(0, Math.min(255, val + Math.floor((Math.random() - 0.5) * 2)));
                return modified.toString(16).padStart(2, '0');
            });
        };

        HTMLCanvasElement.prototype.toBlob = function(callback, type, ...args) {
            originalToDataURL.call(this, type, ...args);
            return originalToBlob.apply(this, [callback, type, ...args]);
        };
    })();
    """

    async def create_spoofed_browser(self):
        """Create browser context with spoofing enabled"""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context()

            # Inject spoof script before any page loads
            await context.add_init_script(self.SPOOF_SCRIPT)

            return browser, context

    async def fetch_with_spoofing(self, url):
        """Fetch URL with canvas spoofing active"""
        browser, context = await self.create_spoofed_browser()
        page = await context.new_page()

        await page.goto(url)
        content = await page.content()

        await page.close()
        await context.close()
        await browser.close()

        return content
```

### Proxy Infrastructure (Free/Self-Hosted)

#### Tor Integration with Circuit Rotation

```python
import asyncio
from stem import Signal
from stem.control import EventType, Controller
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time

class TorProxyRotator:
    """Manage Tor circuits and rotate identity on demand"""

    def __init__(self, control_port=9051, socks_port=9050, password=None):
        self.control_port = control_port
        self.socks_port = socks_port
        self.password = password
        self.circuit_count = 0
        self._session = self._create_session()

    def _create_session(self):
        """Create requests session with Tor SOCKS proxy"""
        session = requests.Session()

        # Configure SOCKS proxy
        proxies = {
            'http': f'socks5://127.0.0.1:{self.socks_port}',
            'https': f'socks5://127.0.0.1:{self.socks_port}',
        }
        session.proxies.update(proxies)

        # Add retries
        retry_strategy = Retry(
            total=3,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=1
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount('http://', adapter)
        session.mount('https://', adapter)

        return session

    def get_current_ip(self):
        """Verify current exit node IP"""
        try:
            response = self._session.get(
                'https://api.ipify.org?format=json',
                timeout=10
            )
            return response.json()['ip']
        except Exception as e:
            print(f"Error getting IP: {e}")
            return None

    def rotate_circuit(self):
        """Request new Tor circuit (new identity)"""
        try:
            with Controller.from_port(port=self.control_port) as controller:
                if self.password:
                    controller.authenticate(password=self.password)

                # Signal NEWNYM to get new circuit
                controller.signal(Signal.NEWNYM)

                # Wait for circuit to establish
                time.sleep(5)

                self.circuit_count += 1
                new_ip = self.get_current_ip()
                print(f"[Circuit #{self.circuit_count}] New Tor identity: {new_ip}")

                return new_ip
        except Exception as e:
            print(f"Error rotating circuit: {e}")
            return None

    async def fetch_with_rotation(self, url, rotate_every_n=5):
        """Fetch URL, rotating circuits periodically"""
        for attempt in range(1, rotate_every_n + 1):
            try:
                if attempt > 1 and attempt % rotate_every_n == 0:
                    print(f"Rotating circuit before request {attempt}...")
                    self.rotate_circuit()

                response = self._session.get(url, timeout=15)
                response.raise_for_status()

                print(f"Successfully fetched {url} via {self.get_current_ip()}")
                return response.text

            except Exception as e:
                print(f"Attempt {attempt} failed: {e}")
                if attempt < rotate_every_n:
                    await asyncio.sleep(2)
                else:
                    raise
```

#### Free Proxy Scraping & Validation

```python
import asyncio
import aiohttp
from bs4 import BeautifulSoup
from typing import List, Dict
import time

class FreeProxyScraper:
    """Scrape and validate free proxies from public sources"""

    PROXY_SOURCES = [
        'https://www.proxy-list.download/api/v1/get?type=http',
        'https://www.proxy-list.download/api/v1/get?type=socks4',
        'https://www.proxy-list.download/api/v1/get?type=socks5',
        'https://raw.githubusercontent.com/clarketm/proxy-list/master/proxy-list-raw.txt',
        'https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt',
    ]

    def __init__(self, timeout=5, max_workers=20):
        self.timeout = timeout
        self.max_workers = max_workers
        self.validated_proxies = []

    async def scrape_proxies(self) -> List[str]:
        """Scrape proxies from multiple sources"""
        all_proxies = set()

        async with aiohttp.ClientSession() as session:
            tasks = [
                self._scrape_source(session, source)
                for source in self.PROXY_SOURCES
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for result in results:
            if isinstance(result, list):
                all_proxies.update(result)

        return list(all_proxies)

    async def _scrape_source(self, session, source_url) -> List[str]:
        """Scrape single proxy source"""
        try:
            async with session.get(source_url, timeout=10) as resp:
                text = await resp.text()

                # Try to parse JSON first
                try:
                    import json
                    data = json.loads(text)
                    if isinstance(data, dict) and 'listProxy' in data:
                        proxies = [p.strip() for p in data['listProxy'].split('\r\n') if p.strip()]
                        return proxies
                except:
                    pass

                # Parse as plain text
                proxies = [
                    line.strip()
                    for line in text.split('\n')
                    if line.strip() and ':' in line
                ]
                return proxies
        except Exception as e:
            print(f"Error scraping {source_url}: {e}")
            return []

    async def validate_proxy(self, proxy: str, test_url='http://httpbin.org/ip') -> bool:
        """Test if proxy is working"""
        proxy_url = f'http://{proxy}'

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    test_url,
                    proxy=proxy_url,
                    timeout=aiohttp.ClientTimeout(total=self.timeout),
                    ssl=False
                ) as resp:
                    return resp.status == 200
        except:
            return False

    async def validate_all(self, proxies: List[str]) -> List[str]:
        """Validate proxies in parallel"""
        semaphore = asyncio.Semaphore(self.max_workers)

        async def bounded_validate(proxy):
            async with semaphore:
                return proxy, await self.validate_proxy(proxy)

        tasks = [bounded_validate(p) for p in proxies]
        results = await asyncio.gather(*tasks)

        validated = [p for p, is_valid in results if is_valid]
        print(f"Validated {len(validated)}/{len(proxies)} proxies")

        return validated

    async def run_full_cycle(self) -> List[str]:
        """Complete scrape and validation cycle"""
        print("Scraping proxies...")
        proxies = await self.scrape_proxies()
        print(f"Found {len(proxies)} proxies")

        print("Validating proxies...")
        validated = await self.validate_all(proxies[:100])  # Test first 100

        self.validated_proxies = validated
        return validated
```

### CAPTCHA Handling

#### Image-Based CAPTCHA Solving

```python
import cv2
import numpy as np
from PIL import Image
import pytesseract
from io import BytesIO
import aiohttp

class ImageCAPTCHASolver:
    """Solve image-based CAPTCHAs using OCR and ML"""

    def __init__(self):
        # Simple CNN model for digit recognition
        self.model = self._load_simple_model()

    def _load_simple_model(self):
        """Load or train simple CNN for character recognition"""
        try:
            import tensorflow as tf
            # In production, load pre-trained model
            # model = tf.keras.models.load_model('captcha_model.h5')
            # For now, use Tesseract
            return None
        except:
            return None

    async def solve_from_url(self, image_url: str) -> str:
        """Download and solve CAPTCHA from URL"""
        async with aiohttp.ClientSession() as session:
            async with session.get(image_url) as resp:
                image_bytes = await resp.read()

        return self.solve_from_bytes(image_bytes)

    def solve_from_bytes(self, image_bytes: bytes) -> str:
        """Solve CAPTCHA from byte data"""
        image = Image.open(BytesIO(image_bytes))
        return self.solve_image(image)

    def solve_image(self, image: Image.Image) -> str:
        """Solve CAPTCHA image"""
        # Preprocessing
        img_array = np.array(image)

        # Convert to grayscale
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # Threshold
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)

        # Denoise
        denoised = cv2.medianBlur(binary, 5)

        # Deskew (optional)
        # denoised = self._deskew(denoised)

        # OCR with Tesseract
        text = pytesseract.image_to_string(denoised, config='--psm 8')

        # Clean result
        text = ''.join(c for c in text if c.isalnum())

        return text

    def _deskew(self, image):
        """Deskew image for better OCR"""
        coords = np.column_stack(np.where(image > 0))
        angle = cv2.minAreaRect(coords)[2]

        if angle < -45:
            angle = -(90 + angle)
        else:
            angle = -angle

        h, w = image.shape
        center = (w // 2, h // 2)
        matrix = cv2.getRotationMatrix2D(center, angle, 1.0)

        return cv2.warpAffine(image, matrix, (w, h), cval=255)


class hCaptchaTokenHarvester:
    """Harvest hCaptcha/reCAPTCHA tokens via browser automation"""

    def __init__(self, site_key: str, page_url: str):
        self.site_key = site_key
        self.page_url = page_url

    async def get_token_via_browser(self) -> str:
        """Use Playwright to solve CAPTCHA and get token"""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            context = await browser.new_context()
            page = await context.new_page()

            # Inject token harvester script
            harvest_script = f"""
            window.captchaTokens = [];

            // Hook form submission
            document.addEventListener('submit', (e) => {{
                const token = document.querySelector('input[name="g-recaptcha-response"]')?.value ||
                              document.querySelector('input[name="h-captcha-response"]')?.value;
                if (token) {{
                    window.captchaTokens.push(token);
                    console.log('Token harvested:', token);
                }}
            }}, true);
            """

            await page.add_init_script(harvest_script)
            await page.goto(self.page_url)

            # Wait for CAPTCHA solving (manual or automatic)
            try:
                # Wait for token to appear
                await page.wait_for_selector(
                    'input[name="g-recaptcha-response"], input[name="h-captcha-response"]',
                    timeout=60000
                )

                # Give time for any value
                await page.wait_for_timeout(2000)

                # Extract token
                token = await page.evaluate('() => window.captchaTokens[0] || ""')

            finally:
                await context.close()
                await browser.close()

            return token
```

---

## Data Sources — Comprehensive List

### Public Records & Government (Free)

**Court Records:**
- PACER (Federal): Free opinions at pacer.uscourts.gov, opinions.uscourts.gov
- CourtListener: Free API for court documents
- State court websites (many offer public access)

**Property Records:**
- County assessor websites (GIS systems)
- Zillow API (limited free tier)
- Google Maps/Google Earth (satellite data)

**Business Registrations:**
- Secretary of State corporate filings (all 50 states + D.C.)
- State business database APIs (many free)
- OpenCorporates API (free tier)

**Government Financial Data:**
- SEC EDGAR API (free, unlimited)
- FEC.gov campaign finance API
- USASpending.gov API (federal contracting)
- Grants.gov (federal grants database)

**Regulatory & Enforcement:**
- EPA violations database
- OSHA violations (OSHA data + IMIS)
- FAA pilot/aircraft registrations
- FCC license database
- DEA registered handlers (CSOS)

**Sanctions & Compliance:**
- OFAC SDN List (free download)
- BIS Denied Persons List
- Commerce Department restricted parties
- State department terrorist designations

**Identity Records:**
- Social Security Death Index (SSDI) — via various free sources
- State vital records (limited public access)
- Inmate locator systems (state DOC)

### Social Media & Online Presence (Free)

**Mainstream Platforms:**
- Twitter/X: Free API tier (v2), search archives, scraping tools
- Facebook: Public profile scraping (ToS dependent)
- Instagram: Public profile data (no API, scraping with care)
- LinkedIn: Public profiles (ToS violation risk)
- TikTok: Public video/profile scraping
- Reddit: Pushshift archives, official API, public data dumps

**Developer Platforms:**
- GitHub: Public profiles, repositories, commits (API free)
- GitLab: Public instances
- Stack Overflow: Public data dumps, API

**Archival & Historical:**
- Internet Archive Wayback Machine (API free)
- Pushshift Reddit/social data archives
- Archive.today (snapshot service)

### Business & Corporate Data (Free)

**Company Information:**
- OpenCorporates API (free tier, millions of companies)
- Crunchbase (limited free)
- Google Maps Business API (limited free)
- Yelp public listings (scraping)

**Financial Data:**
- SEC EDGAR (10-K, 10-Q, 8-K, S-1, etc.)
- Federal Reserve Economic Data (FRED) API
- FDIC bank data
- Nonprofit 990s (ProPublica, GuideStar archives)

**Professional Data:**
- State professional license databases
- Bar association registries
- Medical board registries
- Real estate agent licenses

### Domain & Internet Intelligence (Free)

**DNS & Infrastructure:**
- WHOIS servers (free whois lookups)
- Passive DNS (Rapid7 Sonar, Team Cymru)
- Certificate Transparency logs (crt.sh)
- DNS enumeration tools (fierce, sublist3r)

**IP Intelligence:**
- MaxMind GeoLite2 (free geolocation database)
- Shodan (limited free searches, but self-host via nmap/masscan)
- ASN lookup (BGP data)
- Abuse.net reputation data

**Web Technology:**
- Wappalyzer (open source)
- BuiltWith (limited free)
- TLS certificate analysis

### Dark Web & Deep Web (Free)

**Tor Directory:**
- OnionScan (scanning .onion sites)
- Ahmia.fi (Tor search engine)
- DarkWeb Link scraping

**Alternative Networks:**
- I2P eepsite crawling
- Freenet (decentralized network)

**Paste Sites & Data:**
- Pastebin (public scraping)
- Ghostbin
- Leak databases (various public archives)

**Blockchain & Cryptocurrency:**
- Bitcoin blockchain (public ledger)
- Ethereum blockchain + contracts
- Chain.com, Blockchair APIs (limited free)

### Financial Data (Free)

**SEC Filings:**
- EDGAR database (all public company filings)
- Quarterly & annual reports
- Insider trading disclosures (Form 4)
- Executive compensation (DEF 14A)

**Banking & Financial:**
- FDIC data
- Federal Reserve H.8 data
- OCC enforcement actions
- Credit Union data (NCUA)

**Tax & Audit:**
- IRS 990 nonprofit data (ProPublica, GuideStar)
- Congressional stock trades (House Clerk, Senate)

### Geospatial Data (Free)

**Maps & Imagery:**
- OpenStreetMap (complete free map data)
- Mapillary (street-level imagery)
- Google Street View (API limited free, scraping possible)
- USGS imagery (Landsat, DEM)

**Mapping Layers:**
- Census TIGER/Line files
- County property boundaries (GIS)
- FEMA floodplain data
- Historical maps (various archives)

---

## JavaScript Rendering Pipeline

Many modern sites require JavaScript execution to reveal content. The architecture supports both headless browser rendering and lightweight JS execution.

```python
from playwright.async_api import async_playwright, Browser, Page
from typing import Optional, Dict, List
import asyncio
from datetime import datetime
import json

class JavaScriptRenderingPool:
    """Manage pool of headless browsers for JS rendering"""

    def __init__(self, pool_size: int = 5, headless: bool = True):
        self.pool_size = pool_size
        self.headless = headless
        self.browsers: List[Browser] = []
        self.available_pages: asyncio.Queue = asyncio.Queue(maxsize=pool_size)

    async def initialize(self):
        """Start browser pool"""
        async with async_playwright() as playwright:
            for i in range(self.pool_size):
                browser = await playwright.chromium.launch(
                    headless=self.headless,
                    args=[
                        '--disable-blink-features=AutomationControlled',
                        '--disable-dev-shm-usage',
                        '--no-first-run',
                        '--no-default-browser-check',
                    ]
                )
                self.browsers.append(browser)

    async def render_page(
        self,
        url: str,
        wait_time_ms: int = 3000,
        wait_selector: Optional[str] = None,
        extract_js: Optional[str] = None,
    ) -> Dict:
        """
        Render page with JavaScript execution

        Args:
            url: Page URL
            wait_time_ms: Time to wait for page load
            wait_selector: CSS selector to wait for
            extract_js: JavaScript to execute for data extraction

        Returns:
            Dict with page content and extracted data
        """
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=self.headless)
            page = await browser.new_page(
                # Spoof browser properties
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                viewport={"width": 1920, "height": 1080},
                device_scale_factor=1,
                locale="en-US",
                timezone_id="America/New_York",
            )

            try:
                # Navigate
                await page.goto(url, wait_until='networkidle', timeout=30000)

                # Wait for selector if provided
                if wait_selector:
                    try:
                        await page.wait_for_selector(wait_selector, timeout=10000)
                    except:
                        pass

                # Wait for dynamic content
                await page.wait_for_timeout(wait_time_ms)

                # Get rendered HTML
                content = await page.content()

                # Extract data if script provided
                extracted_data = None
                if extract_js:
                    try:
                        extracted_data = await page.evaluate(extract_js)
                    except Exception as e:
                        print(f"JS extraction error: {e}")

                return {
                    'url': url,
                    'html': content,
                    'extracted': extracted_data,
                    'rendered_at': datetime.utcnow().isoformat(),
                }

            finally:
                await page.close()
                await browser.close()

    async def render_multiple(
        self,
        urls: List[str],
        wait_time_ms: int = 3000,
    ) -> List[Dict]:
        """Render multiple pages in parallel"""
        tasks = [
            self.render_page(url, wait_time_ms)
            for url in urls
        ]
        return await asyncio.gather(*tasks)


class ClientSideDataExtraction:
    """Extract data from client-rendered content"""

    @staticmethod
    def get_json_from_script_tags() -> str:
        """Extract JSON from script tags in page"""
        return """
        const scripts = Array.from(document.querySelectorAll('script'));
        const jsonData = {};

        scripts.forEach((script, idx) => {
            if (script.type === 'application/ld+json') {
                try {
                    jsonData[`structured_data_${idx}`] = JSON.parse(script.textContent);
                } catch (e) {}
            }

            if (script.textContent.includes('__INITIAL_STATE__')) {
                const match = script.textContent.match(/__INITIAL_STATE__ = ({.*?});/);
                if (match) {
                    try {
                        jsonData['initial_state'] = JSON.parse(match[1]);
                    } catch (e) {}
                }
            }
        });

        return jsonData;
        """

    @staticmethod
    def get_dynamic_table_data() -> str:
        """Extract data from dynamically rendered tables"""
        return """
        const tables = [];
        document.querySelectorAll('table').forEach((table, idx) => {
            const rows = [];
            table.querySelectorAll('tr').forEach(tr => {
                const cells = [];
                tr.querySelectorAll('td, th').forEach(td => {
                    cells.push(td.textContent.trim());
                });
                if (cells.length > 0) rows.push(cells);
            });
            if (rows.length > 0) tables.push(rows);
        });
        return tables;
        """

    @staticmethod
    def get_spa_content() -> str:
        """Extract all rendered content from SPA (Single Page App)"""
        return """
        return {
            html: document.documentElement.outerHTML,
            title: document.title,
            url: window.location.href,
            allText: document.body.innerText,
        };
        """
```

---

## Crawl Scheduling & Optimization

```python
import heapq
from typing import Dict, List, Tuple
from datetime import datetime, timedelta
import math

class AdaptiveCrawlScheduler:
    """
    Intelligently schedule crawls based on:
    - Content change frequency
    - Data value/priority
    - Resource availability
    - Time zone patterns
    """

    def __init__(self):
        self.change_history: Dict[str, List[bool]] = {}  # Track if content changed
        self.priority_queue = []
        self.last_crawl: Dict[str, datetime] = {}

    def estimate_change_frequency(self, url: str, history_size: int = 10) -> float:
        """
        Estimate how often content at URL changes
        Returns: estimated days between changes
        """
        if url not in self.change_history:
            return 1.0  # Default: daily

        changes = self.change_history[url][-history_size:]
        change_rate = sum(changes) / len(changes) if changes else 0.5

        # Convert change frequency to days between crawls
        if change_rate > 0.8:
            return 0.25  # High change: every 6 hours
        elif change_rate > 0.5:
            return 1.0   # Medium: daily
        elif change_rate > 0.2:
            return 3.0   # Low: every 3 days
        else:
            return 7.0   # Very low: weekly

    def calculate_priority(self, url: str, category: str) -> float:
        """
        Calculate priority score (0-100)
        Higher = crawl sooner
        """
        category_weights = {
            'court_records': 95,
            'sec_filings': 90,
            'government': 85,
            'news': 75,
            'social_media': 60,
            'web_generic': 30,
        }

        base_priority = category_weights.get(category, 50)

        # Adjust by change frequency
        change_freq = self.estimate_change_frequency(url)
        frequency_bonus = (1.0 / change_freq) * 20  # More frequent = higher priority

        # Adjust by time since last crawl
        if url not in self.last_crawl:
            recency_penalty = 0
        else:
            days_since = (datetime.utcnow() - self.last_crawl[url]).days
            expected_days = self.estimate_change_frequency(url)
            recency_penalty = min(30, (days_since / expected_days) * 50)

        return min(100, base_priority + frequency_bonus + recency_penalty)

    def schedule_crawl(self, urls: Dict[str, str]) -> List[Tuple[str, str]]:
        """
        Schedule crawls in priority order
        Returns: [(url, category), ...]
        """
        self.priority_queue = []

        for url, category in urls.items():
            priority = self.calculate_priority(url, category)
            # Python heapq is min-heap, so negate for max-heap
            heapq.heappush(self.priority_queue, (-priority, url, category))

        scheduled = []
        while self.priority_queue:
            neg_priority, url, category = heapq.heappop(self.priority_queue)
            scheduled.append((url, category))

        return scheduled

    def record_crawl_result(self, url: str, content_changed: bool):
        """Record if content changed during crawl"""
        if url not in self.change_history:
            self.change_history[url] = []

        self.change_history[url].append(content_changed)
        self.last_crawl[url] = datetime.utcnow()

        # Keep only last 50 crawls
        if len(self.change_history[url]) > 50:
            self.change_history[url] = self.change_history[url][-50:]


class TimeZoneAwareCrawler:
    """Coordinate crawls across time zones for better data freshness"""

    OPTIMAL_CRAWL_TIMES = {
        'business_records': (9, 17),      # Business hours (9 AM - 5 PM)
        'court_records': (9, 16),          # Before court closes
        'government': (9, 17),             # Business hours
        'news': (0, 24),                   # 24/7, prefer early morning
        'social_media': (8, 23),           # Avoid midnight
    }

    def is_optimal_crawl_time(self, source_timezone: str, category: str) -> bool:
        """Check if current time is optimal for crawling this source"""
        from datetime import datetime
        import pytz

        tz = pytz.timezone(source_timezone)
        current_hour = datetime.now(tz).hour

        start, end = self.OPTIMAL_CRAWL_TIMES.get(category, (0, 24))
        return start <= current_hour < end
```

---

## Data Extraction & Transformation Pipeline

```python
from typing import Dict, List, Any, Optional
import json
import re
from datetime import datetime
from dataclasses import dataclass, asdict

@dataclass
class ExtractedRecord:
    """Unified extracted data record"""
    source_url: str
    source_category: str
    primary_name: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    address: Optional[str]
    organization: Optional[str]
    extracted_at: datetime
    raw_data: Dict[str, Any]
    confidence: float  # 0-1 confidence score

class DataExtractionPipeline:
    """
    Multi-stage pipeline:
    1. HTML → Structured data
    2. Named Entity Recognition (NER)
    3. Table extraction
    4. Data deduplication & linking
    5. Confidence scoring
    """

    def __init__(self):
        self.name_regex = re.compile(r'^[A-Z][a-z]+ [A-Z][a-z]+', re.MULTILINE)
        self.email_regex = re.compile(r'[\w\.-]+@[\w\.-]+\.\w+')
        self.phone_regex = re.compile(r'\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
        self.address_regex = re.compile(r'\d+\s+[A-Z].*?(?:St|Ave|Blvd|Rd|Dr|Ln)\.?')

    async def process_crawl_result(
        self,
        url: str,
        html_content: str,
        category: str,
    ) -> List[ExtractedRecord]:
        """
        Process raw crawl result into structured records
        """
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'html.parser')
        records = []

        # Extract text
        text = soup.get_text(separator=' ', strip=True)

        # Named Entity Recognition
        ner_results = await self._run_ner(text)

        # Table extraction
        tables = self._extract_tables(soup)

        # Process NER results
        for entity in ner_results:
            record = ExtractedRecord(
                source_url=url,
                source_category=category,
                primary_name=entity.get('name'),
                phone=entity.get('phone'),
                email=entity.get('email'),
                address=entity.get('address'),
                organization=entity.get('org'),
                extracted_at=datetime.utcnow(),
                raw_data=entity,
                confidence=entity.get('confidence', 0.5),
            )
            records.append(record)

        # Process tables
        for table_data in tables:
            for row in table_data:
                record = self._extract_record_from_row(row, url, category)
                if record:
                    records.append(record)

        return records

    async def _run_ner(self, text: str) -> List[Dict]:
        """Run Named Entity Recognition"""
        try:
            import spacy
            nlp = spacy.load('en_core_web_sm')
            doc = nlp(text[:5000])  # Limit to 5000 chars

            entities = []
            for ent in doc.ents:
                if ent.label_ in ['PERSON', 'ORG', 'GPE']:
                    entities.append({
                        'text': ent.text,
                        'label': ent.label_,
                        'confidence': 0.85,
                    })

            return entities
        except Exception as e:
            print(f"NER error: {e}")
            return []

    def _extract_tables(self, soup) -> List[List[Dict]]:
        """Extract data from HTML tables"""
        tables = []

        for table in soup.find_all('table'):
            rows = []
            headers = []

            # Get headers
            for th in table.find_all('th'):
                headers.append(th.get_text(strip=True))

            # Get rows
            for tr in table.find_all('tr')[1:]:  # Skip header row
                cells = [td.get_text(strip=True) for td in tr.find_all('td')]
                if cells:
                    row_dict = dict(zip(headers, cells)) if headers else {'raw': cells}
                    rows.append(row_dict)

            if rows:
                tables.append(rows)

        return tables

    def _extract_record_from_row(
        self,
        row: Dict,
        url: str,
        category: str,
    ) -> Optional[ExtractedRecord]:
        """Extract record from table row"""

        # Try to identify key fields
        row_text = ' '.join(str(v) for v in row.values())

        name = None
        for match in self.name_regex.finditer(row_text):
            name = match.group()
            break

        emails = self.email_regex.findall(row_text)
        phones = self.phone_regex.findall(row_text)
        addresses = self.address_regex.findall(row_text)

        if name or emails or phones:
            return ExtractedRecord(
                source_url=url,
                source_category=category,
                primary_name=name,
                phone=phones[0] if phones else None,
                email=emails[0] if emails else None,
                address=addresses[0] if addresses else None,
                organization=row.get('organization') or row.get('company'),
                extracted_at=datetime.utcnow(),
                raw_data=row,
                confidence=0.7 if name else 0.5,
            )

        return None
```

---

## Legal & Ethical Considerations

### Compliance Framework

The platform must balance maximal data acquisition with legal obligations:

1. **CFRA (California Financial Privacy Act)**
   - Obtained under FCRA Section 603(p) consumer report definition
   - Requires legitimate purpose (background check, etc.)
   - Consumer notification requirements

2. **FCRA (Fair Credit Reporting Act)**
   - Applies if data used in credit decisions
   - Must have consumer consent where applicable
   - Accuracy and dispute resolution requirements

3. **GDPR (EU General Data Protection Regulation)**
   - Applies to EU data subjects
   - Legal basis requirements (contract, consent, legitimate interest)
   - Right to access, erasure, portability
   - Data Processing Agreements (DPAs) with processors

4. **CCPA (California Consumer Privacy Act)**
   - Opt-out rights for CA residents
   - Business Purpose Limitation Clause (BPLC)
   - Disclosure requirements
   - "Do Not Sell My Personal Information" mechanism

5. **State Privacy Laws**
   - Virginia CDPA
   - Colorado CPA
   - Connecticut CTDPA
   - Utah Consumer Privacy Act
   - Similar state laws emerging

### Implementation Approach

```python
class ComplianceManager:
    """Manage compliance across jurisdictions"""

    def __init__(self):
        self.opted_out_emails = set()  # CCPA opt-outs
        self.gdpr_erasure_requests = set()  # Right to be forgotten
        self.do_not_call = set()  # DNC registry

    def load_do_not_call_registry(self):
        """Load FTC Do Not Call registry"""
        # In production: sync with FTC registry periodically
        # For now: placeholder
        return self.do_not_call

    def load_gdpr_erasure_requests(self):
        """Load GDPR right to erasure requests"""
        # Sync with privacy request database
        return self.gdpr_erasure_requests

    def load_ccpa_opt_outs(self):
        """Load CCPA opt-out requests"""
        return self.opted_out_emails

    def is_allowed_to_contact(self, email: str, phone: str, jurisdiction: str) -> bool:
        """Check if contact is allowed under applicable law"""

        # Check DNC registry
        if phone and phone in self.do_not_call:
            return False

        # Check GDPR erasure
        if email in self.gdpr_erasure_requests:
            return False

        # Check CCPA opt-out
        if jurisdiction == 'CA' and email in self.opted_out_emails:
            return False

        return True

    def get_privacy_policy_notice(self, jurisdiction: str) -> str:
        """
        Return jurisdiction-appropriate privacy notice
        """
        notices = {
            'CA': """
                California Residents: You have the right to know what personal
                information is collected and to delete information about you.
                You also have the right to opt out of the sale of personal
                information.
            """,
            'EU': """
                GDPR Notice: We process personal data under the basis of
                legitimate interest. You have the right to access, rectify,
                or erase your data. Contact our DPO for requests.
            """,
            'default': """
                Privacy Notice: We collect and maintain data for business purposes.
                For questions, contact our privacy team.
            """
        }

        return notices.get(jurisdiction, notices['default'])
```

### robots.txt & Rate Limiting

```python
import urllib.robotparser
from urllib.parse import urljoin

class RobotsTextCompliance:
    """Manage robots.txt compliance (configurable)"""

    def __init__(self, respect_robots_txt: bool = True):
        self.respect = respect_robots_txt
        self.parsers = {}  # Cache per domain

    def can_fetch(self, url: str, user_agent: str = 'DataBot/1.0') -> bool:
        """Check if URL can be fetched according to robots.txt"""

        if not self.respect:
            return True  # Ignore robots.txt

        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = f"{parsed.scheme}://{parsed.netloc}"

        # Get or create parser for domain
        if domain not in self.parsers:
            parser = urllib.robotparser.RobotFileParser()
            parser.set_url(urljoin(domain, '/robots.txt'))
            try:
                parser.read()
            except:
                # If robots.txt fails to load, assume allowed
                return True
            self.parsers[domain] = parser

        parser = self.parsers[domain]
        return parser.can_fetch(user_agent, url)

    def get_crawl_delay(self, domain: str, user_agent: str = 'DataBot/1.0') -> float:
        """Get crawl delay from robots.txt (seconds)"""

        if domain not in self.parsers:
            return 1.0  # Default 1 second

        parser = self.parsers[domain]

        # Check for crawl-delay directive
        delay = parser.crawl_delay(user_agent)
        if delay:
            return delay

        # Fall back to request-rate
        request_rate = parser.request_rate(user_agent)
        if request_rate:
            return request_rate.requests / request_rate.seconds

        return 1.0  # Default
```

---

## Summary: Complete Crawl Lifecycle

1. **Frontier Population**: Seed URLs and continuous discovery
2. **Scheduling**: Adaptive prioritization and timing
3. **Anti-Detection**: Rotate fingerprints, proxies, headers
4. **Fetching**: Async crawler with politeness limits
5. **Rendering**: JS execution where needed (Playwright)
6. **Extraction**: HTML parsing, NER, table extraction
7. **Deduplication**: Bloom filters, content hashing
8. **Storage**: PostgreSQL (structured), RDF (linked), Elasticsearch (full-text)
9. **Compliance**: Opt-outs, GDPR erasures, DNC list checks

This architecture enables continuous, comprehensive data collection at scale while maintaining technical sophistication in evasion and operational resilience.
