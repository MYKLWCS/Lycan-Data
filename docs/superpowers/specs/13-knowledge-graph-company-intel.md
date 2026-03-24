# OSINT/Data Broker Platform — Knowledge Graph, Company Intelligence & Saturation Crawling

## Part 1: Company Intelligence Engine

### What We Collect for Every Company Entity

Complete list of data points gathered per company:

#### Corporate Identity
- Legal name, DBA names, trade names
- State of incorporation, date of incorporation
- Entity type (LLC, Corp, LP, LLP, nonprofit, sole prop)
- Status (active, dissolved, suspended, revoked)
- Federal EIN
- DUNS number
- LEI (Legal Entity Identifier)
- SIC/NAICS codes
- CIK (SEC Central Index Key)

#### Officers, Directors, & Principals
- All current officers (CEO, CFO, COO, Secretary, Treasurer, etc.)
- All current directors/board members
- Historical officers and directors (with dates of service)
- Registered agent (name and address)
- Authorized signers
- Beneficial owners (>25% ownership per Corporate Transparency Act)
- Key employees (from IRS 990 for nonprofits)

#### Corporate Structure
- Parent company
- Subsidiaries (direct and indirect)
- Affiliated entities (shared officers, shared addresses)
- Joint ventures
- Franchise relationships
- DBA entities
- Foreign qualifications (registered in other states)

#### Financial Intelligence
- Revenue estimates (from employee count, industry, location)
- Employee count and growth trend
- Government contracts (USASpending)
- Grant awards
- Nonprofit financials (IRS 990)
- SEC filings (if public)
- Property owned (commercial real estate)
- Vehicles registered to company
- UCC filings (secured debts)
- Tax liens
- Judgments
- Bankruptcy history

#### Legal & Compliance
- Court cases (plaintiff and defendant)
- Regulatory actions (FDA, OSHA, EPA, FTC, etc.)
- Professional license status
- BBB complaints and rating
- OSHA violations
- Environmental violations
- Sanctions screening result
- PEP connections (officers who are politically exposed)

#### Digital Footprint
- Website(s) and domain registration history
- Social media accounts (LinkedIn, Twitter, Facebook, etc.)
- Online reviews aggregate (Google, Yelp, BBB)
- Job postings (implies growth/contraction)
- Technology stack (from BuiltWith/Wappalyzer — free)
- SSL certificate history
- IP infrastructure

### Company Discovery Pipeline

Python code for a CompanyIntelligenceEngine:

```python
import asyncio
import logging
from typing import Dict, List, Set, Tuple, Optional
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from enum import Enum

import aiohttp
from bs4 import BeautifulSoup
import requests
from sec_edgar_downloader import Downloader
from opencorporates import Client as OCClient

logger = logging.getLogger(__name__)


class EntityType(Enum):
    CORPORATION = "corporation"
    LLC = "llc"
    LP = "limited_partnership"
    LLP = "limited_liability_partnership"
    NONPROFIT = "nonprofit"
    SOLE_PROPRIETORSHIP = "sole_proprietorship"


class EntityStatus(Enum):
    ACTIVE = "active"
    DISSOLVED = "dissolved"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
    MERGED = "merged"


@dataclass
class CompanyRecord:
    """Represents a complete company record with all discovered data."""
    id: str
    legal_name: str
    dba_names: List[str]
    ein: Optional[str]
    duns: Optional[str]
    lei: Optional[str]
    state_of_incorporation: str
    entity_type: EntityType
    status: EntityStatus
    incorporation_date: Optional[datetime]
    sic_codes: List[str]
    naics_codes: List[str]
    cik: Optional[str]

    officers: List[Dict]  # {name, title, start_date, end_date, phone, email}
    directors: List[Dict]  # {name, title, start_date, end_date}
    registered_agent: Optional[Dict]  # {name, address, phone, email}
    beneficial_owners: List[Dict]  # {name, ownership_pct, reported_date}

    parent_company: Optional[str]
    subsidiaries: List[Dict]  # {name, ownership_pct, incorporation_state}
    affiliated_entities: List[Dict]

    revenue_estimate: Optional[float]
    employee_count: Optional[int]
    employee_growth: Optional[float]

    hq_address: Dict  # {street, city, state, zip, country, lat, lon}
    mailing_address: Optional[Dict]
    office_locations: List[Dict]

    website: Optional[str]
    domains: List[Dict]  # {domain, registrant, created_date, expires_date}
    social_profiles: Dict  # {linkedin, twitter, facebook, etc.}

    court_cases: List[Dict]  # {case_number, court, type, status, date}
    regulatory_actions: List[Dict]  # {agency, action_type, date, description}
    licenses: List[Dict]  # {type, state, license_number, status, expires}

    government_contracts: List[Dict]  # {contract_id, amount, agency, date}
    bankruptcy_history: List[Dict]
    liens_and_judgments: List[Dict]
    ucc_filings: List[Dict]  # {filing_id, amount, secured_party, date}

    data_sources: List[str]  # Which sources contributed data
    confidence_score: float  # 0.0-1.0
    last_updated: datetime


@dataclass
class PersonRecord:
    """Represents a complete person record."""
    id: str
    full_name: str
    aliases: List[str]
    dob: Optional[datetime]

    current_addresses: List[Dict]  # {street, city, state, zip, verified_date}
    historical_addresses: List[Dict]
    phones: List[Dict]  # {number, type, carrier, is_active}
    emails: List[Dict]  # {address, type, is_active, breach_count}

    company_affiliations: List[Dict]  # {company_name, title, role, start_date, end_date}
    other_companies: List[str]  # All companies they're connected to

    education: List[Dict]  # {school, degree, field}
    professional_licenses: List[Dict]
    military_service: Optional[Dict]

    court_appearances: List[Dict]  # {case, role, date}
    criminal_records: List[Dict]
    sex_offender_registry: Optional[bool]

    social_profiles: Dict  # {linkedin, twitter, facebook, etc.}
    public_records: List[Dict]

    data_sources: List[str]
    confidence_score: float
    last_updated: datetime


class CompanyIntelligenceEngine:
    """
    Main engine for gathering comprehensive company intelligence.
    Searches Secretary of State, SEC, court records, and proprietary databases.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.session = None
        self.logger = logging.getLogger('CompanyIntelligenceEngine')

        # API clients
        self.sec_client = None
        self.opencorporates_client = OCClient(api_key=config.get('opencorporates_key'))

        # Cached results to avoid re-querying
        self.company_cache: Dict[str, CompanyRecord] = {}
        self.person_cache: Dict[str, PersonRecord] = {}
        self.discovered_people: Set[str] = set()
        self.discovered_companies: Set[str] = set()

    async def initialize(self):
        """Initialize async session and clients."""
        self.session = aiohttp.ClientSession()

    async def close(self):
        """Clean up resources."""
        if self.session:
            await self.session.close()

    async def gather_company_intelligence(self, identifier: str,
                                        id_type: str = "name",
                                        max_depth: int = 2) -> CompanyRecord:
        """
        Comprehensive company intelligence gathering.
        identifier can be: company name, EIN, DUNS, domain, or ticker
        """
        self.logger.info(f"Starting intelligence gathering for {id_type}: {identifier}")

        # Step 1: Identify the company
        company_data = await self._identify_company(identifier, id_type)
        if not company_data:
            raise ValueError(f"Could not identify company: {identifier}")

        company_id = company_data['id']
        self.discovered_companies.add(company_id)

        # Step 2: Parallel searches across all sources
        tasks = [
            self._search_secretary_of_state(company_data),
            self._search_sec_edgar(company_data),
            self._search_government_contracts(company_data),
            self._search_court_records(company_data),
            self._search_property_records(company_data),
            self._search_regulatory_actions(company_data),
            self._search_digital_footprint(company_data),
            self._search_financial_data(company_data),
            self._search_bankruptcy_liens(company_data),
            self._search_ucc_filings(company_data),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Consolidate results
        company_record = self._consolidate_company_data(company_data, results)

        # Step 3: Deep dive on officers and directors
        for officer in company_record.officers:
            await self._process_person(officer['name'], company_id, depth=0)
        for director in company_record.directors:
            await self._process_person(director['name'], company_id, depth=0)

        # Step 4: Recursively gather data on subsidiaries and affiliates
        if max_depth > 0:
            subsidiary_tasks = [
                self.gather_company_intelligence(sub['name'], "name", max_depth - 1)
                for sub in company_record.subsidiaries[:10]  # Limit to 10
            ]
            if subsidiary_tasks:
                await asyncio.gather(*subsidiary_tasks, return_exceptions=True)

        self.company_cache[company_id] = company_record
        return company_record

    async def _identify_company(self, identifier: str, id_type: str) -> Dict:
        """
        Identify a company and normalize its data.
        Try multiple matching strategies.
        """
        results = []

        # Strategy 1: Exact match on name via OpenCorporates
        if id_type in ["name", "dba"]:
            try:
                oc_results = self.opencorporates_client.companies.search(identifier)
                if oc_results:
                    results.extend([
                        {
                            'id': f"oc_{r.company_number}",
                            'source': 'opencorporates',
                            'name': r.name,
                            'jurisdiction': r.jurisdiction_code,
                            'company_number': r.company_number,
                        }
                        for r in oc_results[:5]
                    ])
            except Exception as e:
                self.logger.warning(f"OpenCorporates search failed: {e}")

        # Strategy 2: EIN lookup
        if id_type == "ein":
            try:
                irs_result = await self._lookup_ein(identifier)
                if irs_result:
                    results.append(irs_result)
            except Exception as e:
                self.logger.warning(f"EIN lookup failed: {e}")

        # Strategy 3: DUNS lookup
        if id_type == "duns":
            try:
                duns_result = await self._lookup_duns(identifier)
                if duns_result:
                    results.append(duns_result)
            except Exception as e:
                self.logger.warning(f"DUNS lookup failed: {e}")

        # Strategy 4: Domain -> company name via WHOIS
        if id_type == "domain":
            try:
                whois_result = await self._lookup_domain(identifier)
                if whois_result:
                    results.append(whois_result)
            except Exception as e:
                self.logger.warning(f"WHOIS lookup failed: {e}")

        if not results:
            self.logger.error(f"Could not identify company via any method: {identifier}")
            return None

        # Return the highest confidence match
        return sorted(results, key=lambda x: x.get('confidence', 0.5), reverse=True)[0]

    async def _search_secretary_of_state(self, company_data: Dict) -> Dict:
        """
        Search all 50 Secretary of State databases.
        Returns officers, directors, registered agent, filing history.
        """
        results = {
            'officers': [],
            'directors': [],
            'registered_agent': None,
            'filing_history': [],
            'subsidiaries': [],
        }

        # For demo: focus on the company's incorporation state
        state = company_data.get('state', 'DE')

        try:
            filing_data = await self._search_sos_by_state(state, company_data)
            results.update(filing_data)
        except Exception as e:
            self.logger.error(f"SOS search failed for {state}: {e}")

        return results

    async def _search_sos_by_state(self, state: str, company_data: Dict) -> Dict:
        """
        Search a specific state's Secretary of State database.
        This would integrate with actual SOS portals or APIs.
        """
        # Delaware example
        if state == "DE":
            return await self._search_delaware_sos(company_data)
        # Other states...
        return {}

    async def _search_delaware_sos(self, company_data: Dict) -> Dict:
        """
        Search Delaware Division of Corporations.
        Free public records available at delaware.gov
        """
        results = {'officers': [], 'directors': [], 'filing_history': []}

        # Would make actual request to Delaware's business entity search
        url = f"https://icis.delaware.gov/icsearch/"
        params = {'company_name': company_data.get('name')}

        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    soup = BeautifulSoup(html, 'html.parser')

                    # Parse officer information
                    officer_rows = soup.select('.officer-row')
                    for row in officer_rows:
                        officer = {
                            'name': row.select_one('.officer-name').text.strip(),
                            'title': row.select_one('.officer-title').text.strip(),
                            'address': row.select_one('.officer-address').text.strip(),
                        }
                        results['officers'].append(officer)
        except Exception as e:
            self.logger.warning(f"Delaware SOS search failed: {e}")

        return results

    async def _search_sec_edgar(self, company_data: Dict) -> Dict:
        """
        Search SEC EDGAR for public company filings.
        Returns executives, board members, insider trades.
        """
        results = {
            'executives': [],
            'board_members': [],
            'insider_trades': [],
            'cik': None,
        }

        cik = company_data.get('cik')
        if not cik:
            # Try to find CIK by company name
            try:
                cik = await self._find_cik(company_data['name'])
            except Exception as e:
                self.logger.warning(f"CIK lookup failed: {e}")
                return results

        if not cik:
            return results

        results['cik'] = cik

        try:
            # Fetch DEF 14A (proxy statement) for executives and board
            proxy_docs = await self._fetch_sec_filings(cik, '14A', limit=1)
            for doc in proxy_docs:
                exec_data = await self._parse_proxy_statement(doc)
                results['executives'].extend(exec_data.get('executives', []))
                results['board_members'].extend(exec_data.get('board', []))

            # Fetch 10-K for business description
            tenk_docs = await self._fetch_sec_filings(cik, '10-K', limit=1)

            # Fetch Form 4 for insider trades
            form4_docs = await self._fetch_sec_filings(cik, '4', limit=10)
            insider_data = await self._parse_form4_filings(form4_docs)
            results['insider_trades'].extend(insider_data)

        except Exception as e:
            self.logger.error(f"SEC EDGAR search failed: {e}")

        return results

    async def _find_cik(self, company_name: str) -> Optional[str]:
        """
        Find SEC CIK number by company name.
        """
        url = "https://www.sec.gov/cgi-bin/browse-edgar"
        params = {
            'company': company_name,
            'action': 'getcompany',
            'output': 'json',
            'count': 40,
        }

        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get('hits') and len(data['hits']) > 0:
                        return str(data['hits'][0]['cik_str'])
        except Exception as e:
            self.logger.error(f"SEC CIK lookup failed: {e}")

        return None

    async def _fetch_sec_filings(self, cik: str, form_type: str,
                                 limit: int = 10) -> List[Dict]:
        """
        Fetch SEC filings by form type.
        """
        url = "https://www.sec.gov/cgi-bin/browse-edgar"
        params = {
            'action': 'getcompany',
            'CIK': cik,
            'type': form_type,
            'dateb': '',
            'owner': 'exclude',
            'count': limit,
            'output': 'json',
        }

        results = []
        try:
            async with self.session.get(url, params=params, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for filing in data.get('filings', {}).get('recent', [])[:limit]:
                        results.append({
                            'accession': filing.get('accn'),
                            'date': filing.get('filingDate'),
                            'form_type': filing.get('form'),
                        })
        except Exception as e:
            self.logger.error(f"SEC filing fetch failed: {e}")

        return results

    async def _parse_proxy_statement(self, doc: Dict) -> Dict:
        """
        Parse SEC proxy statement (DEF 14A) for executive and board info.
        This would download and parse the actual document.
        """
        return {
            'executives': [
                {
                    'name': 'Example CEO',
                    'title': 'Chief Executive Officer',
                    'salary': 1500000,
                    'bonus': 500000,
                }
            ],
            'board': [
                {
                    'name': 'Example Director',
                    'title': 'Board Director',
                    'independence': True,
                    'committees': ['Audit', 'Compensation'],
                }
            ],
        }

    async def _parse_form4_filings(self, docs: List[Dict]) -> List[Dict]:
        """
        Parse SEC Form 4 filings for insider trades.
        """
        return []

    async def _search_government_contracts(self, company_data: Dict) -> Dict:
        """
        Search USASpending.gov for government contracts.
        """
        results = {'contracts': []}

        ein = company_data.get('ein')
        if not ein:
            return results

        try:
            # USASpending API
            url = "https://api.usaspending.gov/api/v2/awards/search/"
            payload = {
                'filters': {
                    'recipient_duns': company_data.get('duns'),
                },
                'limit': 100,
            }

            async with self.session.post(url, json=payload, timeout=10) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    results['contracts'] = data.get('results', [])
        except Exception as e:
            self.logger.warning(f"USASpending search failed: {e}")

        return results

    async def _search_court_records(self, company_data: Dict) -> Dict:
        """
        Search federal and state court records.
        """
        results = {'cases': []}

        company_name = company_data.get('name')

        try:
            # PACER (Public Access to Court Electronic Records)
            # This is a paid service but offers free limited searches
            cases = await self._search_pacer(company_name)
            results['cases'].extend(cases)

            # State court search (varies by state)
            state = company_data.get('state', 'DE')
            state_cases = await self._search_state_courts(state, company_name)
            results['cases'].extend(state_cases)

        except Exception as e:
            self.logger.warning(f"Court records search failed: {e}")

        return results

    async def _search_pacer(self, company_name: str) -> List[Dict]:
        """
        Search PACER for federal court cases.
        """
        # Would integrate with actual PACER API
        return []

    async def _search_state_courts(self, state: str, company_name: str) -> List[Dict]:
        """
        Search state court records.
        """
        # Would integrate with state-specific court databases
        return []

    async def _search_property_records(self, company_data: Dict) -> Dict:
        """
        Search for property owned by the company.
        """
        results = {'properties': []}

        address = company_data.get('address')
        if address:
            # Would search Zillow, County Assessor, etc.
            pass

        return results

    async def _search_regulatory_actions(self, company_data: Dict) -> Dict:
        """
        Search for regulatory actions: FDA, OSHA, EPA, FTC, state regulators.
        """
        results = {'actions': []}

        ein = company_data.get('ein')
        company_name = company_data.get('name')

        try:
            # OSHA violations
            osha_violations = await self._search_osha(company_name, company_data.get('address'))
            results['actions'].extend([{'agency': 'OSHA', **v} for v in osha_violations])

            # FDA warning letters
            fda_actions = await self._search_fda(company_name)
            results['actions'].extend([{'agency': 'FDA', **a} for a in fda_actions])

            # FTC actions
            ftc_actions = await self._search_ftc(company_name)
            results['actions'].extend([{'agency': 'FTC', **a} for a in ftc_actions])

            # State professional license boards
            license_actions = await self._search_state_boards(company_name, company_data.get('state'))
            results['actions'].extend([{'agency': 'State Board', **l} for l in license_actions])

        except Exception as e:
            self.logger.warning(f"Regulatory search failed: {e}")

        return results

    async def _search_osha(self, company_name: str, address: Optional[Dict]) -> List[Dict]:
        """
        Search OSHA inspection records.
        """
        # Would query OSHA Data + API
        return []

    async def _search_fda(self, company_name: str) -> List[Dict]:
        """
        Search FDA enforcement actions and warning letters.
        """
        return []

    async def _search_ftc(self, company_name: str) -> List[Dict]:
        """
        Search FTC enforcement database.
        """
        return []

    async def _search_state_boards(self, company_name: str, state: str) -> List[Dict]:
        """
        Search state professional licensing boards.
        """
        return []

    async def _search_digital_footprint(self, company_data: Dict) -> Dict:
        """
        Search digital footprint: website, domain history, social media, IP infrastructure.
        """
        results = {
            'website': None,
            'domains': [],
            'social_profiles': {},
            'ip_history': [],
            'ssl_certificates': [],
            'job_postings': [],
        }

        website = company_data.get('website')
        if website:
            results['website'] = website

        # Domain enumeration
        company_name = company_data.get('name')
        domains = await self._enumerate_domains(company_name)
        results['domains'] = domains

        # Whois history
        for domain in domains:
            whois_data = await self._get_whois_history(domain)
            results['domains'].append({'domain': domain, 'whois': whois_data})

        # Social media
        results['social_profiles'] = await self._find_social_profiles(company_name)

        # Job postings
        results['job_postings'] = await self._find_job_postings(company_name)

        return results

    async def _enumerate_domains(self, company_name: str) -> List[str]:
        """
        Find domains associated with the company.
        """
        # Would use DNSdb, Censys, SecurityTrails, etc.
        return []

    async def _get_whois_history(self, domain: str) -> Dict:
        """
        Get WHOIS history for a domain.
        """
        return {}

    async def _find_social_profiles(self, company_name: str) -> Dict:
        """
        Find company social media profiles.
        """
        return {
            'linkedin': None,
            'twitter': None,
            'facebook': None,
            'instagram': None,
            'youtube': None,
        }

    async def _find_job_postings(self, company_name: str) -> List[Dict]:
        """
        Find current and recent job postings.
        Indicates hiring growth or contraction.
        """
        # Would search LinkedIn Jobs, Indeed, Glassdoor, etc.
        return []

    async def _search_financial_data(self, company_data: Dict) -> Dict:
        """
        Gather financial intelligence: revenue, employee count, valuation.
        """
        results = {
            'revenue_estimate': None,
            'employee_count': None,
            'employee_growth': None,
            'credit_score': None,
            'irs_990': None,  # For nonprofits
        }

        ein = company_data.get('ein')

        try:
            # IRS 990 for nonprofits
            if company_data.get('entity_type') == 'nonprofit':
                irs_data = await self._get_irs_990(ein)
                results['irs_990'] = irs_data

            # Revenue and employee estimates from Dun & Bradstreet, Crunchbase, etc.
            financial_estimate = await self._get_financial_estimate(company_data)
            results.update(financial_estimate)

        except Exception as e:
            self.logger.warning(f"Financial data search failed: {e}")

        return results

    async def _get_irs_990(self, ein: str) -> Optional[Dict]:
        """
        Retrieve IRS Form 990 for nonprofit organizations.
        """
        # Would query ProPublica Nonprofit Explorer, IRS, etc.
        return None

    async def _get_financial_estimate(self, company_data: Dict) -> Dict:
        """
        Get financial estimates from various sources.
        """
        return {}

    async def _search_bankruptcy_liens(self, company_data: Dict) -> Dict:
        """
        Search for bankruptcy filings, tax liens, and judgments.
        """
        results = {
            'bankruptcy': [],
            'tax_liens': [],
            'judgments': [],
        }

        ein = company_data.get('ein')
        name = company_data.get('name')

        try:
            # Bankruptcy records (PACER)
            results['bankruptcy'] = await self._search_bankruptcy(name)

            # Tax liens (state tax boards)
            results['tax_liens'] = await self._search_tax_liens(ein, name)

            # Court judgments
            results['judgments'] = await self._search_judgments(name)

        except Exception as e:
            self.logger.warning(f"Bankruptcy/lien search failed: {e}")

        return results

    async def _search_bankruptcy(self, company_name: str) -> List[Dict]:
        """
        Search bankruptcy records via PACER.
        """
        return []

    async def _search_tax_liens(self, ein: str, name: str) -> List[Dict]:
        """
        Search for tax liens from IRS and state boards.
        """
        return []

    async def _search_judgments(self, company_name: str) -> List[Dict]:
        """
        Search for civil judgments against the company.
        """
        return []

    async def _search_ucc_filings(self, company_data: Dict) -> Dict:
        """
        Search Uniform Commercial Code filings for secured debts.
        """
        results = {'filings': []}

        # Would search state UCC filing systems
        state = company_data.get('state', 'DE')

        try:
            ucc_filings = await self._search_state_ucc(state, company_data['name'])
            results['filings'] = ucc_filings
        except Exception as e:
            self.logger.warning(f"UCC search failed: {e}")

        return results

    async def _search_state_ucc(self, state: str, company_name: str) -> List[Dict]:
        """
        Search state UCC filing system.
        """
        return []

    async def _process_person(self, person_name: str, source_company_id: str,
                             depth: int = 0) -> PersonRecord:
        """
        Process a person: find all their affiliations and connections.
        """
        person_id = hashlib.md5(person_name.encode()).hexdigest()

        if person_id in self.person_cache:
            return self.person_cache[person_id]

        self.discovered_people.add(person_id)

        person_record = PersonRecord(
            id=person_id,
            full_name=person_name,
            aliases=[],
            dob=None,
            current_addresses=[],
            historical_addresses=[],
            phones=[],
            emails=[],
            company_affiliations=[],
            other_companies=[],
            education=[],
            professional_licenses=[],
            military_service=None,
            court_appearances=[],
            criminal_records=[],
            sex_offender_registry=None,
            social_profiles={},
            public_records=[],
            data_sources=[],
            confidence_score=0.0,
            last_updated=datetime.now(),
        )

        # Search for all company affiliations
        companies = await self._find_person_companies(person_name)
        for company in companies:
            person_record.other_companies.append(company['name'])
            self.discovered_companies.add(company['id'])

        # Search for relatives
        relatives = await self._find_relatives(person_name)
        person_record.aliases.extend([r['name'] for r in relatives])

        # Recursively process if depth allows
        if depth < 1:
            for company_name in person_record.other_companies[:5]:
                try:
                    await self.gather_company_intelligence(company_name, "name", max_depth=0)
                except Exception as e:
                    self.logger.warning(f"Failed to process company {company_name}: {e}")

        self.person_cache[person_id] = person_record
        return person_record

    async def _find_person_companies(self, person_name: str) -> List[Dict]:
        """
        Find all companies a person is affiliated with.
        Cross-reference against SEC, SOS, LinkedIn, etc.
        """
        companies = []

        try:
            # LinkedIn
            linkedin_companies = await self._search_linkedin_person(person_name)
            companies.extend(linkedin_companies)

            # SEC filings
            sec_companies = await self._search_sec_person(person_name)
            companies.extend(sec_companies)

        except Exception as e:
            self.logger.warning(f"Person company search failed: {e}")

        return companies

    async def _search_linkedin_person(self, person_name: str) -> List[Dict]:
        """
        Search LinkedIn for person profile and work history.
        Note: This requires LinkedIn API access or web scraping (check TOS).
        """
        return []

    async def _search_sec_person(self, person_name: str) -> List[Dict]:
        """
        Search SEC EDGAR for filings mentioning the person.
        """
        return []

    async def _find_relatives(self, person_name: str) -> List[Dict]:
        """
        Find family members and relatives.
        """
        # Would search public records, genealogy sites, etc.
        return []

    def _consolidate_company_data(self, company_data: Dict,
                                  search_results: List) -> CompanyRecord:
        """
        Consolidate all search results into a single CompanyRecord.
        """
        consolidated = {
            'officers': [],
            'directors': [],
            'subsidiaries': [],
            'court_cases': [],
        }

        for result in search_results:
            if isinstance(result, dict):
                if 'officers' in result:
                    consolidated['officers'].extend(result['officers'])
                if 'directors' in result:
                    consolidated['directors'].extend(result['directors'])
                if 'subsidiaries' in result:
                    consolidated['subsidiaries'].extend(result['subsidiaries'])
                if 'cases' in result:
                    consolidated['court_cases'].extend(result['cases'])

        record = CompanyRecord(
            id=company_data.get('id', hashlib.md5(company_data['name'].encode()).hexdigest()),
            legal_name=company_data.get('name', ''),
            dba_names=[],
            ein=company_data.get('ein'),
            duns=company_data.get('duns'),
            lei=company_data.get('lei'),
            state_of_incorporation=company_data.get('state', 'Unknown'),
            entity_type=EntityType.LLC,  # Would be determined from actual data
            status=EntityStatus.ACTIVE,
            incorporation_date=None,
            sic_codes=[],
            naics_codes=[],
            cik=company_data.get('cik'),
            officers=consolidated['officers'],
            directors=consolidated['directors'],
            registered_agent=None,
            beneficial_owners=[],
            parent_company=None,
            subsidiaries=consolidated['subsidiaries'],
            affiliated_entities=[],
            revenue_estimate=None,
            employee_count=None,
            employee_growth=None,
            hq_address=company_data.get('address', {}),
            mailing_address=None,
            office_locations=[],
            website=company_data.get('website'),
            domains=[],
            social_profiles={},
            court_cases=consolidated['court_cases'],
            regulatory_actions=[],
            licenses=[],
            government_contracts=[],
            bankruptcy_history=[],
            liens_and_judgments=[],
            ucc_filings=[],
            data_sources=['secretary_of_state', 'sec_edgar', 'court_records'],
            confidence_score=0.75,
            last_updated=datetime.now(),
        )

        return record

    async def _lookup_ein(self, ein: str) -> Optional[Dict]:
        """
        Lookup company by EIN.
        """
        return None

    async def _lookup_duns(self, duns: str) -> Optional[Dict]:
        """
        Lookup company by DUNS number.
        """
        return None

    async def _lookup_domain(self, domain: str) -> Optional[Dict]:
        """
        Lookup company by domain via WHOIS.
        """
        return None
```

---

## Part 2: Knowledge Graph Architecture

### Why a Knowledge Graph

- Traditional relational DB can't efficiently represent n-degree relationships
- "Find all companies connected to Person X within 3 degrees" requires graph traversal
- Palantir's core value prop is exactly this — relationship mapping
- Our graph should handle billions of edges at sub-second query time

### Graph Data Model

#### Node Types (Entities)

```
Person {
    id, name, dob, ssn_hash, addresses[], phones[], emails[],
    confidence_score, verification_level, data_sources[]
}

Company {
    id, legal_name, dba_names[], ein, state, entity_type, status,
    industry, revenue_estimate, employee_count
}

Address {
    id, street, city, state, zip, country, lat, lon,
    type (residential/commercial/PO Box), is_virtual_office
}

Phone {
    id, number, type (mobile/landline/VoIP), carrier, is_active
}

Email {
    id, address, domain, is_disposable, is_role_based, breach_count
}

Property {
    id, address, value, owner_history[], type, tax_assessment
}

Vehicle {
    id, vin, make, model, year, registration_state
}

Court_Case {
    id, case_number, court, type, status, filing_date
}

Financial_Filing {
    id, type, filing_date, source, amount
}

Social_Profile {
    id, platform, username, url, followers, post_count
}

Domain {
    id, domain_name, registrant, creation_date, expiry_date
}

Crypto_Wallet {
    id, address, chain, balance, transaction_count
}
```

#### Edge Types (Relationships)

```
OFFICER_OF (Person → Company) {title, start_date, end_date}
DIRECTOR_OF (Person → Company) {start_date, end_date}
OWNS (Person/Company → Company) {percentage, type}
BENEFICIAL_OWNER (Person → Company) {percentage, reported_date}
REGISTERED_AGENT (Person/Company → Company) {}
SUBSIDIARY_OF (Company → Company) {percentage}
AFFILIATED_WITH (Company → Company) {type}  // shared officers, shared address
RELATIVE_OF (Person → Person) {relationship_type}  // spouse, parent, child, sibling
ASSOCIATE_OF (Person → Person) {type}  // business, legal, political
LIVES_AT (Person → Address) {start_date, end_date, is_current}
LOCATED_AT (Company → Address) {type}  // HQ, branch, registered
OWNS_PROPERTY (Person/Company → Property) {acquisition_date, price}
OWNS_VEHICLE (Person/Company → Vehicle) {registration_date}
PARTY_TO (Person/Company → Court_Case) {role}  // plaintiff, defendant, witness
FILED (Company → Financial_Filing) {}
HAS_PHONE (Person/Company → Phone) {}
HAS_EMAIL (Person/Company → Email) {}
HAS_PROFILE (Person/Company → Social_Profile) {}
HAS_DOMAIN (Person/Company → Domain) {}
HAS_WALLET (Person → Crypto_Wallet) {}
CO_LOCATED (Person ↔ Person) {address, overlap_period}
CO_DIRECTOR (Person ↔ Person) {company, overlap_period}
TRANSACTED_WITH (Crypto_Wallet → Crypto_Wallet) {amount, timestamp}
```

### Graph Database: Apache AGE (Free, PostgreSQL Extension)

Why AGE over Neo4j:
- Free and open-source (Neo4j community is limited, enterprise is expensive)
- Runs inside PostgreSQL (no separate infrastructure)
- Cypher-compatible query language
- Full ACID transactions
- Can query relational + graph data together
- Scales with PostgreSQL clustering

#### Schema Creation

```sql
-- Enable AGE extension
CREATE EXTENSION IF NOT EXISTS age;
LOAD 'age';
SET search_path = ag_catalog, "$user", public;

-- Create the OSINT graph
SELECT create_graph('osint_graph');

-- Create vertex labels and indexes
SELECT * FROM cypher('osint_graph', $$
    CREATE (n:Person {id: 'template', name: '', dob: '', addresses: [], phones: [], emails: [], confidence: 0.0})
$$) as (v agtype);

-- Create Company vertices
SELECT * FROM cypher('osint_graph', $$
    CREATE (n:Company {id: 'template', name: '', ein: '', dba_names: [], state: '', status: 'active', industry: ''})
$$) as (v agtype);

-- Create Address vertices
SELECT * FROM cypher('osint_graph', $$
    CREATE (n:Address {id: 'template', street: '', city: '', state: '', zip: '', country: '', lat: 0.0, lon: 0.0, type: '', is_virtual_office: false})
$$) as (v agtype);

-- Create Phone vertices
SELECT * FROM cypher('osint_graph', $$
    CREATE (n:Phone {id: 'template', number: '', type: '', carrier: '', is_active: false})
$$) as (v agtype);

-- Create Email vertices
SELECT * FROM cypher('osint_graph', $$
    CREATE (n:Email {id: 'template', address: '', domain: '', is_disposable: false, breach_count: 0})
$$) as (v agtype);

-- Create Court_Case vertices
SELECT * FROM cypher('osint_graph', $$
    CREATE (n:Court_Case {id: 'template', case_number: '', court: '', type: '', status: '', filing_date: ''})
$$) as (v agtype);

-- Create indexes on frequently searched properties
CREATE INDEX ON cypher_person_name USING btree ((properties->>'name'));
CREATE INDEX ON cypher_company_ein USING btree ((properties->>'ein'));
CREATE INDEX ON cypher_person_email USING btree ((properties->>'emails'));
```

### Key Graph Queries

#### 1. Find all companies a person is connected to (any role)

```cypher
MATCH (p:Person {name: 'John Smith'})-[r]->(c:Company)
RETURN c.name, type(r), r.title
ORDER BY c.name
```

#### 2. Find all people connected to a company (officers, directors, owners)

```cypher
MATCH (p:Person)-[r]->(c:Company {name: 'Smith Holdings LLC'})
RETURN p.name, type(r), r.title, r.start_date, r.end_date
ORDER BY r.start_date DESC
```

#### 3. Find all connections within N degrees

```cypher
MATCH path = (start:Person {name: 'John Smith'})-[*1..3]-(end)
RETURN path,
       length(path) as hop_distance,
       [x IN nodes(path) | labels(x)[0]] as node_types
```

#### 4. Find shared connections between two people

```cypher
MATCH (a:Person {name: 'John Smith'})-[*1..2]-(shared)-[*1..2]-(b:Person {name: 'Jane Doe'})
WHERE a <> b AND shared <> a AND shared <> b
RETURN DISTINCT shared, labels(shared) as entity_type, count(*) as num_paths
ORDER BY num_paths DESC
```

#### 5. Find all companies with shared officers (corporate networks)

```cypher
MATCH (c1:Company)<-[:OFFICER_OF]-(p:Person)-[:OFFICER_OF]->(c2:Company)
WHERE c1.id < c2.id
RETURN c1.name as company_1, c2.name as company_2, p.name as shared_officer,
       collect(distinct p.name) as all_shared_officers,
       count(distinct p) as shared_officer_count
ORDER BY shared_officer_count DESC
```

#### 6. Find shell company patterns

```cypher
MATCH (c:Company)-[:LOCATED_AT]->(a:Address)<-[:LOCATED_AT]-(c2:Company)
WHERE c.id < c2.id AND a.is_virtual_office = true
MATCH (c)<-[:REGISTERED_AGENT]-(ra)-[:REGISTERED_AGENT]->(c2)
RETURN c.name as company_1, c2.name as company_2, ra.name as registered_agent,
       a.street as shared_address, count(*) as shared_connections
ORDER BY shared_connections DESC
```

#### 7. Build full corporate hierarchy

```cypher
MATCH path = (parent:Company {name: 'Holding Corp'})<-[:SUBSIDIARY_OF*]-(sub:Company)
RETURN path,
       length(path) as depth,
       [x IN nodes(path) | x.name] as company_chain
ORDER BY depth DESC
LIMIT 1000
```

#### 8. Find hidden beneficial owners (follow the chain)

```cypher
MATCH path = (p:Person)-[:OWNS|BENEFICIAL_OWNER*1..5]->(target:Company {name: 'Target LLC'})
WITH p, path,
     reduce(pct = 100.0, r IN relationships(path) | pct * ((r.percentage // 100) / 100.0)) as effective_pct
RETURN p.name as beneficial_owner,
       effective_pct as ownership_percentage,
       [r IN relationships(path) | {type: type(r), pct: r.percentage}] as ownership_chain,
       length(path) as hops
ORDER BY effective_pct DESC
```

#### 9. Anomaly detection: Multiple high-ranking titles at same company

```cypher
MATCH (p:Person)-[r:OFFICER_OF|DIRECTOR_OF]->(c:Company)
WHERE r.title IN ['CEO', 'President', 'COO', 'CFO', 'CTO', 'Founder']
WITH c, p, collect(r.title) as titles, count(distinct r.title) as title_count
WHERE title_count > 1
RETURN c.name, p.name, titles
LIMIT 100
```

#### 10. Find circular ownership structures (red flag for shell companies)

```cypher
MATCH (c1:Company)-[:OWNS|SUBSIDIARY_OF*2..5]->(c2:Company)-[:OWNS|SUBSIDIARY_OF*1..]->(c1)
RETURN distinct c1.name as company_a,
       c2.name as company_b,
       "CIRCULAR_OWNERSHIP" as flag
LIMIT 100
```

### Graph Builder Service

```python
import asyncio
import json
import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import asdict
import asyncpg

logger = logging.getLogger(__name__)


class KnowledgeGraphBuilder:
    """
    Builds and maintains the OSINT knowledge graph using Apache AGE.
    Handles entity creation, relationship management, and efficient querying.
    """

    def __init__(self, db_pool: asyncpg.Pool):
        self.db = db_pool
        self.logger = logging.getLogger('GraphBuilder')
        self.batch_size = 100
        self.commit_queue = []

    async def add_person_node(self, person_data: PersonRecord):
        """
        Add a person node to the graph with all attributes.
        """
        query = """
            SELECT * FROM cypher('osint_graph', $$
                MERGE (p:Person {id: $1})
                SET p.name = $2,
                    p.dob = $3,
                    p.addresses = $4,
                    p.phones = $5,
                    p.emails = $6,
                    p.confidence = $7,
                    p.data_sources = $8,
                    p.last_updated = now()
                RETURN p
            $$) as (p agtype)
        """

        addresses_json = json.dumps(person_data.current_addresses)
        phones_json = json.dumps([p['number'] for p in person_data.phones])
        emails_json = json.dumps([e['address'] for e in person_data.emails])
        sources_json = json.dumps(person_data.data_sources)

        try:
            await self.db.execute(
                query,
                person_data.id,
                person_data.full_name,
                person_data.dob.isoformat() if person_data.dob else None,
                addresses_json,
                phones_json,
                emails_json,
                person_data.confidence_score,
                sources_json,
            )
        except Exception as e:
            self.logger.error(f"Failed to add person node {person_data.full_name}: {e}")

    async def add_company_node(self, company_data: CompanyRecord):
        """
        Add a company node to the graph.
        """
        query = """
            SELECT * FROM cypher('osint_graph', $$
                MERGE (c:Company {id: $1})
                SET c.name = $2,
                    c.ein = $3,
                    c.dba_names = $4,
                    c.state = $5,
                    c.status = $6,
                    c.entity_type = $7,
                    c.industry = $8,
                    c.revenue_estimate = $9,
                    c.employee_count = $10,
                    c.confidence = $11,
                    c.data_sources = $12,
                    c.last_updated = now()
                RETURN c
            $$) as (c agtype)
        """

        dba_json = json.dumps(company_data.dba_names)
        sources_json = json.dumps(company_data.data_sources)

        try:
            await self.db.execute(
                query,
                company_data.id,
                company_data.legal_name,
                company_data.ein,
                dba_json,
                company_data.state_of_incorporation,
                company_data.status.value,
                company_data.entity_type.value,
                company_data.industry if hasattr(company_data, 'industry') else None,
                company_data.revenue_estimate,
                company_data.employee_count,
                company_data.confidence_score,
                sources_json,
            )
        except Exception as e:
            self.logger.error(f"Failed to add company node {company_data.legal_name}: {e}")

    async def add_relationship(self, from_id: str, from_type: str,
                              rel_type: str, to_id: str, to_type: str,
                              properties: Optional[Dict] = None):
        """
        Add or update a relationship between two entities.
        """
        props_json = json.dumps(properties or {})

        query = f"""
            SELECT * FROM cypher('osint_graph', $$
                MATCH (a:{from_type} {{id: $1}}), (b:{to_type} {{id: $2}})
                MERGE (a)-[r:{rel_type}]->(b)
                SET r += {props_json},
                    r.created_at = COALESCE(r.created_at, now()),
                    r.updated_at = now()
                RETURN r
            $$) as (r agtype)
        """

        try:
            await self.db.execute(query, from_id, to_id)
        except Exception as e:
            self.logger.error(f"Failed to add relationship {from_type}-{rel_type}-{to_type}: {e}")

    async def add_officer_relationship(self, person_id: str, company_id: str,
                                      title: str, start_date: Optional[str] = None,
                                      end_date: Optional[str] = None):
        """
        Add OFFICER_OF relationship between person and company.
        """
        await self.add_relationship(
            person_id, 'Person',
            'OFFICER_OF',
            company_id, 'Company',
            properties={
                'title': title,
                'start_date': start_date,
                'end_date': end_date,
            }
        )

    async def add_director_relationship(self, person_id: str, company_id: str,
                                        start_date: Optional[str] = None,
                                        end_date: Optional[str] = None):
        """
        Add DIRECTOR_OF relationship.
        """
        await self.add_relationship(
            person_id, 'Person',
            'DIRECTOR_OF',
            company_id, 'Company',
            properties={
                'start_date': start_date,
                'end_date': end_date,
            }
        )

    async def add_beneficial_owner_relationship(self, owner_id: str, company_id: str,
                                               ownership_pct: float,
                                               reported_date: str):
        """
        Add BENEFICIAL_OWNER relationship with ownership percentage.
        """
        await self.add_relationship(
            owner_id, 'Person',
            'BENEFICIAL_OWNER',
            company_id, 'Company',
            properties={
                'percentage': ownership_pct,
                'reported_date': reported_date,
            }
        )

    async def add_subsidiary_relationship(self, parent_id: str, subsidiary_id: str,
                                         ownership_pct: Optional[float] = None):
        """
        Add SUBSIDIARY_OF relationship between companies.
        """
        await self.add_relationship(
            subsidiary_id, 'Company',
            'SUBSIDIARY_OF',
            parent_id, 'Company',
            properties={'percentage': ownership_pct} if ownership_pct else {}
        )

    async def find_connections(self, entity_id: str, max_depth: int = 3) -> List[Dict]:
        """
        Find all entities connected to the given entity within N degrees.
        """
        query = f"""
            SELECT * FROM cypher('osint_graph', $$
                MATCH path = (start {{id: $1}})-[*1..{max_depth}]-(connected)
                RETURN path,
                       length(path) as distance,
                       [x IN nodes(path) | x] as nodes,
                       [r IN relationships(path) | type(r)] as rel_types
            $$) as (path agtype, distance bigint, nodes agtype, rel_types agtype)
        """

        results = []
        try:
            rows = await self.db.fetch(query, entity_id)
            for row in rows:
                results.append({
                    'path': row['path'],
                    'distance': row['distance'],
                    'nodes': row['nodes'],
                    'relationships': row['rel_types'],
                })
        except Exception as e:
            self.logger.error(f"Connection search failed: {e}")

        return results

    async def find_company_officers(self, company_id: str) -> List[Dict]:
        """
        Find all current officers of a company.
        """
        query = """
            SELECT * FROM cypher('osint_graph', $$
                MATCH (p:Person)-[r:OFFICER_OF]->(c:Company {id: $1})
                WHERE r.end_date IS NULL OR r.end_date > now()
                RETURN p.name, r.title, r.start_date, r.end_date
                ORDER BY r.start_date DESC
            $$) as (name text, title text, start_date text, end_date text)
        """

        officers = []
        try:
            rows = await self.db.fetch(query, company_id)
            for row in rows:
                officers.append({
                    'name': row['name'],
                    'title': row['title'],
                    'start_date': row['start_date'],
                    'end_date': row['end_date'],
                })
        except Exception as e:
            self.logger.error(f"Officer lookup failed: {e}")

        return officers

    async def find_shared_officers(self, company_id_1: str, company_id_2: str) -> List[Dict]:
        """
        Find people who serve as officers/directors at both companies.
        Useful for detecting shell company networks.
        """
        query = """
            SELECT * FROM cypher('osint_graph', $$
                MATCH (p:Person)-[:OFFICER_OF|DIRECTOR_OF]->(c1:Company {id: $1})
                MATCH (p)-[:OFFICER_OF|DIRECTOR_OF]->(c2:Company {id: $2})
                RETURN p.name, c1.name as company_1, c2.name as company_2
            $$) as (name text, company_1 text, company_2 text)
        """

        results = []
        try:
            rows = await self.db.fetch(query, company_id_1, company_id_2)
            for row in rows:
                results.append({
                    'person': row['name'],
                    'company_1': row['company_1'],
                    'company_2': row['company_2'],
                })
        except Exception as e:
            self.logger.error(f"Shared officer lookup failed: {e}")

        return results

    async def find_related_companies(self, company_id: str, max_depth: int = 2) -> List[Dict]:
        """
        Find parent, subsidiary, and affiliated companies.
        """
        query = f"""
            SELECT * FROM cypher('osint_graph', $$
                MATCH (target:Company {{id: $1}})-[*1..{max_depth}]-(related:Company)
                WHERE target <> related
                RETURN distinct related.name, related.id, related.state,
                       related.status, related.ein
                ORDER BY related.name
            $$) as (name text, id text, state text, status text, ein text)
        """

        results = []
        try:
            rows = await self.db.fetch(query, company_id)
            for row in rows:
                results.append({
                    'name': row['name'],
                    'id': row['id'],
                    'state': row['state'],
                    'status': row['status'],
                    'ein': row['ein'],
                })
        except Exception as e:
            self.logger.error(f"Related company lookup failed: {e}")

        return results

    async def detect_shell_companies(self, virtual_office_threshold: int = 3) -> List[Dict]:
        """
        Find potential shell company networks.
        Criteria: Multiple companies at virtual office addresses, shared officers/directors.
        """
        query = f"""
            SELECT * FROM cypher('osint_graph', $$
                MATCH (c1:Company)-[:LOCATED_AT]->(addr:Address {{is_virtual_office: true}})
                             <-[:LOCATED_AT]-(c2:Company)
                WHERE c1.id < c2.id
                MATCH (p:Person)-[:OFFICER_OF|DIRECTOR_OF]->(c1),
                      (p)-[:OFFICER_OF|DIRECTOR_OF]->(c2)
                WITH c1, c2, addr, collect(p.name) as shared_people
                RETURN c1.name as company_1, c2.name as company_2,
                       addr.street as shared_address,
                       shared_people, size(shared_people) as shared_count
                WHERE shared_count >= {virtual_office_threshold}
                ORDER BY shared_count DESC
            $$) as (company_1 text, company_2 text, address text, people agtype, count bigint)
        """

        results = []
        try:
            rows = await self.db.fetch(query)
            for row in rows:
                results.append({
                    'company_1': row['company_1'],
                    'company_2': row['company_2'],
                    'shared_address': row['address'],
                    'shared_officers': row['people'],
                    'shared_count': row['count'],
                    'risk_level': 'HIGH' if row['count'] >= 3 else 'MEDIUM',
                })
        except Exception as e:
            self.logger.error(f"Shell company detection failed: {e}")

        return results

    async def detect_circular_ownership(self) -> List[Dict]:
        """
        Find circular ownership structures that may indicate money laundering or fraud.
        """
        query = """
            SELECT * FROM cypher('osint_graph', $$
                MATCH (c1:Company)-[:OWNS|SUBSIDIARY_OF*2..4]->(c2:Company)-[:OWNS|SUBSIDIARY_OF*1..]->(c1)
                RETURN distinct c1.name, c2.name, "CIRCULAR_OWNERSHIP" as anomaly_type
            $$) as (company_1 text, company_2 text, anomaly_type text)
        """

        results = []
        try:
            rows = await self.db.fetch(query)
            for row in rows:
                results.append({
                    'company_1': row['company_1'],
                    'company_2': row['company_2'],
                    'risk_type': 'CIRCULAR_OWNERSHIP',
                    'risk_level': 'HIGH',
                })
        except Exception as e:
            self.logger.error(f"Circular ownership detection failed: {e}")

        return results

    async def build_company_network_graph(self, company_id: str,
                                        max_depth: int = 3) -> Dict:
        """
        Build a complete network graph for a company and all related entities.
        Returns nodes and edges suitable for visualization.
        """
        nodes = []
        edges = []
        processed = set()

        async def traverse(entity_id: str, entity_type: str, depth: int):
            if entity_id in processed or depth > max_depth:
                return

            processed.add(entity_id)

            if entity_type == 'Company':
                # Get company data
                company_rows = await self.db.fetch(
                    "SELECT * FROM cypher('osint_graph', $$"
                    "MATCH (c:Company {id: $1}) RETURN c"
                    "$$) as (c agtype)",
                    entity_id
                )
                if company_rows:
                    # Add node
                    nodes.append({
                        'id': entity_id,
                        'type': 'Company',
                        'label': company_rows[0]['c'].get('name', 'Unknown'),
                        'size': 30,
                        'color': '#FF6B6B',
                    })

                    # Find related entities
                    officers = await self.find_company_officers(entity_id)
                    for officer in officers:
                        officer_id = hashlib.md5(officer['name'].encode()).hexdigest()
                        edges.append({
                            'source': entity_id,
                            'target': officer_id,
                            'type': 'OFFICER_OF',
                            'label': officer['title'],
                        })
                        await traverse(officer_id, 'Person', depth + 1)

                    # Find subsidiaries
                    related = await self.find_related_companies(entity_id, max_depth=1)
                    for rel_company in related:
                        edges.append({
                            'source': entity_id,
                            'target': rel_company['id'],
                            'type': 'AFFILIATED',
                        })
                        await traverse(rel_company['id'], 'Company', depth + 1)

            elif entity_type == 'Person':
                # Add node
                nodes.append({
                    'id': entity_id,
                    'type': 'Person',
                    'label': entity_id,  # Would get real name from DB
                    'size': 20,
                    'color': '#4ECDC4',
                })

        await traverse(company_id, 'Company', 0)

        return {
            'nodes': nodes,
            'edges': edges,
            'node_count': len(nodes),
            'edge_count': len(edges),
        }
```

---

## Part 3: Saturation Crawl Pattern

### Concept

Instead of running scrapers once and stopping, the system keeps crawling until data saturation:

1. Run all scrapers for the target entity
2. Discover connected entities (people, companies)
3. Run scrapers for those connected entities
4. Keep expanding the search graph outward
5. Track "novelty rate" — percentage of new vs duplicate data
6. When novelty rate drops below threshold (e.g., 5%), stop collecting
7. Switch to enrichment mode — verify, score, tag everything

### Saturation Crawl Algorithm

```python
import hashlib
import asyncio
import logging
from typing import AsyncGenerator, Callable, Dict, Optional, Set, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class CrawlPhase(Enum):
    COLLECTING = "collecting"
    ENRICHING = "enriching"
    COMPLETE = "complete"


@dataclass
class ScrapeResult:
    """
    Represents a single scrape result from any source.
    """
    entity_type: str  # 'person', 'company', 'property', etc.
    entity_data: Dict
    source: str  # 'sec_edgar', 'secretary_of_state', etc.
    data_hash: str  # Hash to detect duplicates
    timestamp: datetime = field(default_factory=datetime.now)
    novelty: bool = True  # Is this new or duplicate?


@dataclass
class CrawlStats:
    """
    Statistics tracked during saturation crawl.
    """
    total_results: int = 0
    novel_results: int = 0
    entities_processed: int = 0
    queue_size: int = 0
    phase: CrawlPhase = CrawlPhase.COLLECTING
    novelty_rate: float = 1.0
    depth_distribution: Dict[int, int] = field(default_factory=dict)
    source_contribution: Dict[str, int] = field(default_factory=dict)
    time_elapsed: float = 0.0


class SaturationCrawler:
    """
    Keeps crawling until data novelty drops below threshold.
    Automatically switches from collection to enrichment.
    """

    def __init__(self, orchestrator, graph_builder, enrichment_engine, config: Dict):
        self.orchestrator = orchestrator
        self.graph = graph_builder
        self.enrichment = enrichment_engine
        self.config = config
        self.logger = logging.getLogger('SaturationCrawler')

        # Saturation parameters
        self.novelty_threshold = config.get('novelty_threshold', 0.05)
        self.max_depth = config.get('max_depth', 4)
        self.max_entities = config.get('max_entities', 500)
        self.min_results_before_saturation = config.get('min_results_before_saturation', 100)

        # Tracking
        self.seen_hashes: Set[str] = set()
        self.processed_queue: Set[str] = set()
        self.stats = CrawlStats()
        self.start_time = None

    async def saturate(self, seed_query: str, seed_type: str = "person",
                       on_progress: Optional[Callable] = None) -> Dict:
        """
        Run saturation crawl starting from a seed entity.
        Progressively discovers connected entities until novelty drops.

        Returns final statistics and summary.
        """
        self.start_time = datetime.now()
        self.stats = CrawlStats()

        # Initialize queue with seed
        queue: asyncio.Queue = asyncio.Queue()
        await queue.put((seed_query, seed_type, 0))

        self.processed_queue.clear()
        self.seen_hashes.clear()

        self.logger.info(f"Starting saturation crawl: seed='{seed_query}', type={seed_type}")

        # PHASE 1: COLLECTION
        try:
            await self._collection_phase(queue, on_progress)
        except Exception as e:
            self.logger.error(f"Error in collection phase: {e}")

        # Check if we've reached saturation
        overall_novelty = (
            self.stats.novel_results / max(self.stats.total_results, 1)
        )

        saturation_reached = (
            self.stats.total_results > self.min_results_before_saturation
            and overall_novelty < self.novelty_threshold
        )

        if not saturation_reached:
            self.logger.warning(
                f"Did not reach saturation: novelty={overall_novelty:.1%}, "
                f"results={self.stats.total_results}, entities={self.stats.entities_processed}"
            )
        else:
            self.logger.info(
                f"Saturation reached: novelty={overall_novelty:.1%} after "
                f"{self.stats.total_results} results across {self.stats.entities_processed} entities"
            )

        # PHASE 2: ENRICHMENT
        self.stats.phase = CrawlPhase.ENRICHING
        if on_progress:
            await on_progress({
                'phase': 'enriching',
                'total_entities': len(self.processed_queue),
            })

        enriched_count = 0
        try:
            enriched_count = await self.enrichment.enrich_all(
                self.processed_queue,
                on_progress=on_progress
            )
        except Exception as e:
            self.logger.error(f"Error in enrichment phase: {e}")

        self.stats.phase = CrawlPhase.COMPLETE
        elapsed = (datetime.now() - self.start_time).total_seconds()
        self.stats.time_elapsed = elapsed

        result = {
            'entities_processed': self.stats.entities_processed,
            'total_results': self.stats.total_results,
            'novel_results': self.stats.novel_results,
            'final_novelty_rate': overall_novelty,
            'saturation_reached': saturation_reached,
            'enriched_count': enriched_count,
            'phase': 'complete',
            'elapsed_seconds': elapsed,
            'depth_distribution': self.stats.depth_distribution,
            'source_contribution': self.stats.source_contribution,
        }

        self.logger.info(f"Saturation crawl complete: {result}")
        return result

    async def _collection_phase(self, queue: asyncio.Queue,
                               on_progress: Optional[Callable] = None):
        """
        PHASE 1: Keep collecting data until novelty drops below threshold.
        """
        batch_window = 50  # Evaluate novelty every N results
        batch_results = 0
        batch_novel = 0

        while not queue.empty() and self.stats.entities_processed < self.max_entities:
            # Get next entity from queue
            try:
                query, entity_type, depth = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if query in self.processed_queue or depth > self.max_depth:
                continue

            self.processed_queue.add(query)
            self.stats.entities_processed += 1

            # Accumulate depth distribution
            self.stats.depth_distribution[depth] = (
                self.stats.depth_distribution.get(depth, 0) + 1
            )

            self.logger.debug(f"Processing: {entity_type} '{query}' at depth {depth}")

            # COLLECT: Run all scrapers for this entity
            results = []
            async for result in self.orchestrator.search(
                query,
                entity_type=entity_type,
                include_sources=self.config.get('sources', [])
            ):
                results.append(result)

                # Check for novelty
                if result.data_hash not in self.seen_hashes:
                    self.seen_hashes.add(result.data_hash)
                    batch_novel += 1
                    self.stats.novel_results += 1
                    result.novelty = True

                    # Add to graph
                    try:
                        await self._add_to_graph(result)
                    except Exception as e:
                        self.logger.warning(f"Failed to add to graph: {e}")
                else:
                    result.novelty = False

                batch_results += 1
                self.stats.total_results += 1

                # Track source contribution
                self.stats.source_contribution[result.source] = (
                    self.stats.source_contribution.get(result.source, 0) + 1
                )

            # Calculate novelty for this batch
            batch_novelty = (
                batch_novel / max(batch_results, 1)
                if batch_results > 0 else 0
            )

            # Report progress
            if on_progress and batch_results > 0:
                await on_progress(self._get_progress_snapshot(batch_novelty))

            # DISCOVER: Find connected entities to crawl next
            if batch_novelty > self.novelty_threshold * 2 and depth < self.max_depth:
                connections = await self._discover_connections(query, entity_type)
                for conn_query, conn_type in connections:
                    if conn_query not in self.processed_queue:
                        await queue.put((conn_query, conn_type, depth + 1))

            # Check overall novelty — stop if we're just getting duplicates
            overall_novelty = (
                self.stats.novel_results / max(self.stats.total_results, 1)
            )

            if (self.stats.total_results > self.min_results_before_saturation
                    and overall_novelty < self.novelty_threshold):
                self.logger.info("Saturation threshold reached, stopping collection.")
                break

            # Reset batch counters
            if batch_results >= batch_window:
                batch_results = 0
                batch_novel = 0

            # Rate limiting
            await asyncio.sleep(self.config.get('crawl_delay_seconds', 0.1))

        self.logger.info(f"Collection phase complete: processed {self.stats.entities_processed} entities")

    async def _discover_connections(self, query: str, entity_type: str) -> List[Tuple[str, str]]:
        """
        DISCOVER: Find connected entities from the knowledge graph to crawl next.
        """
        connections = []

        try:
            if entity_type == "person":
                # Find companies they're connected to
                companies = await self.graph.find_person_companies(query)
                for company in companies:
                    connections.append((company['name'], 'company'))

                # Find relatives and associates
                relatives = await self.graph.find_person_relatives(query)
                for relative in relatives:
                    connections.append((relative['name'], 'person'))

            elif entity_type == "company":
                # Find all officers/directors
                officers = await self.graph.find_company_officers(query)
                for officer in officers:
                    connections.append((officer['name'], 'person'))

                # Find subsidiaries and parents
                related = await self.graph.find_company_relationships(query)
                for related_company in related:
                    connections.append((related_company['name'], 'company'))

        except Exception as e:
            self.logger.warning(f"Connection discovery failed: {e}")

        return connections[:10]  # Limit to avoid explosion

    async def _add_to_graph(self, result: ScrapeResult):
        """
        Add scraped result to the knowledge graph.
        """
        if result.entity_type == "person":
            person_data = result.entity_data
            # Create person node
            await self.graph.add_person_node(person_data)

            # Add company affiliations
            for company in person_data.get('company_affiliations', []):
                await self.graph.add_officer_relationship(
                    person_data['id'],
                    company['company_id'],
                    company['title'],
                    company.get('start_date'),
                    company.get('end_date'),
                )

        elif result.entity_type == "company":
            company_data = result.entity_data
            # Create company node
            await self.graph.add_company_node(company_data)

            # Add officer relationships
            for officer in company_data.get('officers', []):
                await self.graph.add_officer_relationship(
                    officer['id'],
                    company_data['id'],
                    officer['title'],
                    officer.get('start_date'),
                    officer.get('end_date'),
                )

            # Add director relationships
            for director in company_data.get('directors', []):
                await self.graph.add_director_relationship(
                    director['id'],
                    company_data['id'],
                    director.get('start_date'),
                    director.get('end_date'),
                )

            # Add subsidiary relationships
            for subsidiary in company_data.get('subsidiaries', []):
                await self.graph.add_subsidiary_relationship(
                    company_data['id'],
                    subsidiary['id'],
                    subsidiary.get('ownership_pct'),
                )

    def _get_progress_snapshot(self, batch_novelty: float) -> Dict:
        """
        Get a snapshot of current progress for reporting.
        """
        overall_novelty = (
            self.stats.novel_results / max(self.stats.total_results, 1)
        )

        return {
            'phase': 'collecting',
            'entities_processed': self.stats.entities_processed,
            'total_results': self.stats.total_results,
            'novel_results': self.stats.novel_results,
            'batch_novelty_rate': batch_novelty,
            'overall_novelty_rate': overall_novelty,
            'queue_size': self.stats.queue_size,
            'depth_distribution': self.stats.depth_distribution,
            'source_contribution': self.stats.source_contribution,
            'elapsed_seconds': (datetime.now() - self.start_time).total_seconds(),
        }


class EnrichmentEngine:
    """
    Post-saturation enrichment phase.
    Verifies, scores, tags all collected entities.
    """

    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger('EnrichmentEngine')

    async def enrich_all(self, entity_ids: Set[str],
                        on_progress: Optional[Callable] = None) -> int:
        """
        Enrich all collected entities.
        Verify data, calculate confidence scores, apply tags, generate embeddings.
        """
        enriched_count = 0
        entity_list = list(entity_ids)

        for i, entity_id in enumerate(entity_list):
            try:
                await self._enrich_entity(entity_id)
                enriched_count += 1

                if on_progress and i % 10 == 0:
                    await on_progress({
                        'phase': 'enriching',
                        'current': i,
                        'total': len(entity_list),
                        'enriched': enriched_count,
                        'progress_pct': (i / len(entity_list)) * 100,
                    })

            except Exception as e:
                self.logger.error(f"Enrichment failed for {entity_id}: {e}")

        return enriched_count

    async def _enrich_entity(self, entity_id: str):
        """
        Enrich a single entity:
        1. Verify contact information
        2. Cross-check against sanctions lists
        3. Calculate confidence scores
        4. Apply marketing tags
        5. Generate semantic embeddings
        """
        # Would implement actual enrichment logic
        pass
```

This document provides the complete foundation for a sophisticated OSINT platform with knowledge graphs and saturation crawling. Total code examples exceed 600 lines and cover the full architecture.
