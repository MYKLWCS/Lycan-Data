"""Generate __init__.py for each category directory."""
import os

BASE = "/home/wolf/Lycan-Data/modules/crawlers"

CATEGORY_CRAWLERS = {
    "people": [
        ("people_thatsthem", "PeopleThatSThemCrawler"),
        ("people_intelx", "PeopleIntelxCrawler"),
        ("people_familysearch", "PeopleFamilySearchCrawler"),
        ("people_fbi_wanted", "PeopleFbiWantedCrawler"),
        ("people_findagrave", "PeopleFindAGraveCrawler"),
        ("people_immigration", "PeopleImmigrationCrawler"),
        ("people_interpol", "PeopleInterpolCrawler"),
        ("people_namus", "PeopleNamusCrawler"),
        ("people_phonebook", "PeoplePhonebookCrawler"),
        ("people_usmarshals", "PeopleUsMarshals"),
        ("people_zabasearch", "PeopleZabaSearchCrawler"),
        ("fastpeoplesearch", "FastPeopleSearchCrawler"),
        ("truepeoplesearch", "TruePeopleSearchCrawler"),
        ("whitepages", "WhitepagesCrawler"),
        ("spokeo", "SpokeoCrawler"),
        ("radaris", "RadarisCrawler"),
        ("familytreenow", "FamilyTreeNowCrawler"),
        ("obituary_search", "ObituarySearchCrawler"),
        ("interests_extractor", "InterestsExtractorCrawler"),
        ("username_maigret", "UsernameMaigretCrawler"),
        ("username_sherlock", "UsernameSherlockCrawler"),
        ("clustrmaps", "ClustrMapsCrawler"),
    ],
    "social_media": [
        ("twitter", "TwitterCrawler"),
        ("facebook", "FacebookCrawler"),
        ("instagram", "InstagramCrawler"),
        ("linkedin", "LinkedInCrawler"),
        ("reddit", "RedditCrawler"),
        ("youtube", "YoutubeCrawler"),
        ("tiktok", "TikTokCrawler"),
        ("snapchat", "SnapchatCrawler"),
        ("pinterest", "PinterestCrawler"),
        ("discord", "DiscordCrawler"),
        ("whatsapp", "WhatsAppCrawler"),
        ("telegram", "TelegramCrawler"),
        ("bluesky_profile", "BlueskyProfileCrawler"),
        ("threads_profile", "ThreadsProfileCrawler"),
        ("social_mastodon", "SocialMastodonCrawler"),
        ("social_spotify", "SocialSpotifyCrawler"),
        ("social_steam", "SocialSteamCrawler"),
        ("social_twitch", "SocialTwitchCrawler"),
        ("social_graph", "SocialGraphCrawler"),
        ("social_posts_analyzer", "SocialPostsAnalyzerCrawler"),
        ("github", "GitHubCrawler"),
        ("github_profile", "GitHubProfileCrawler"),
        ("spotify_public", "SpotifyPublicCrawler"),
        ("stackoverflow_profile", "StackOverflowProfileCrawler"),
    ],
    "public_records": [
        ("txcourts", "TxCourtsCrawler"),
        ("fl_courts", "FlCourtsCrawler"),
        ("ca_courts", "CaCourtsCrawler"),
        ("court_courtlistener", "CourtListenerCrawler"),
        ("court_state", "CourtStateCrawler"),
        ("bankruptcy_pacer", "BankruptcyPacerCrawler"),
        ("public_faa", "PublicFaaCrawler"),
        ("public_npi", "PublicNpiCrawler"),
        ("public_nsopw", "PublicNsopwCrawler"),
        ("public_voter", "PublicVoterCrawler"),
    ],
    "financial": [
        ("financial_crunchbase", "FinancialCrunchbaseCrawler"),
        ("financial_finra", "FinancialFinraCrawler"),
        ("financial_worldbank", "FinancialWorldBankCrawler"),
        ("sec_insider", "SecInsiderCrawler"),
        ("crypto_bitcoin", "CryptoBitcoinCrawler"),
        ("crypto_blockchair", "CryptoBlockchairCrawler"),
        ("crypto_bscscan", "CryptoBscscanCrawler"),
        ("crypto_ethereum", "CryptoEthereumCrawler"),
        ("crypto_polygonscan", "CryptoPolygonscanCrawler"),
        ("mortgage_deed", "MortgageDeedCrawler"),
        ("mortgage_hmda", "MortgageHmdaCrawler"),
    ],
    "business": [
        ("company_companies_house", "CompanyCompaniesHouseCrawler"),
        ("company_opencorporates", "CompanyOpenCorporatesCrawler"),
        ("company_sec", "CompanySecCrawler"),
        ("google_maps", "GoogleMapsCrawler"),
    ],
    "dark_web": [
        ("darkweb_ahmia", "DarkwebAhmiaCrawler"),
        ("darkweb_torch", "DarkwebTorchCrawler"),
        ("telegram_dark", "TelegramDarkCrawler"),
        ("paste_ghostbin", "PasteGhostbinCrawler"),
        ("paste_pastebin", "PastePastebinCrawler"),
        ("paste_psbdmp", "PastePsbdmpCrawler"),
    ],
    "phone_email": [
        ("phone_carrier", "PhoneCarrierCrawler"),
        ("phone_fonefinder", "PhoneFoneFinderCrawler"),
        ("phone_numlookup", "PhoneNumLookupCrawler"),
        ("phone_phoneinfoga", "PhonePhoneInfogaCrawler"),
        ("phone_truecaller", "PhoneTruecallerCrawler"),
        ("email_breach", "EmailBreachCrawler"),
        ("email_dehashed", "EmailDehashedCrawler"),
        ("email_emailrep", "EmailEmailRepCrawler"),
        ("email_hibp", "EmailHibpCrawler"),
        ("email_holehe", "EmailHoleheCrawler"),
        ("email_mx_validator", "EmailMxValidatorCrawler"),
        ("email_socialscan", "EmailSocialScanCrawler"),
        ("domain_theharvester", "DomainTheHarvesterCrawler"),
        ("domain_whois", "DomainWhoisCrawler"),
    ],
    "sanctions_aml": [
        ("sanctions_australia", "SanctionsAustraliaCrawler"),
        ("sanctions_canada", "SanctionsCanadaCrawler"),
        ("sanctions_eu", "SanctionsEuCrawler"),
        ("sanctions_fatf", "SanctionsFatfCrawler"),
        ("sanctions_fbi", "SanctionsFbiCrawler"),
        ("sanctions_ofac", "SanctionsOfacCrawler"),
        ("sanctions_opensanctions", "SanctionsOpenSanctionsCrawler"),
        ("sanctions_uk", "SanctionsUkCrawler"),
        ("sanctions_un", "SanctionsUnCrawler"),
        ("sanctions_worldbank_debarment", "SanctionsWorldBankDebarmentCrawler"),
    ],
    "news_media": [
        ("news_search", "NewsSearchCrawler"),
        ("news_archive", "NewsArchiveCrawler"),
        ("news_wikipedia", "NewsWikipediaCrawler"),
        ("google_news_rss", "GoogleNewsRssCrawler"),
        ("bing_news", "BingNewsCrawler"),
        ("gdelt_mentions", "GdeltMentionsCrawler"),
        ("adverse_media_search", "AdverseMediaSearchCrawler"),
    ],
    "cyber": [
        ("cyber_abuseipdb", "CyberAbuseIpdbCrawler"),
        ("cyber_alienvault", "CyberAlienVaultCrawler"),
        ("cyber_crt", "CyberCrtCrawler"),
        ("cyber_dns", "CyberDnsCrawler"),
        ("cyber_greynoise", "CyberGreyNoiseCrawler"),
        ("cyber_shodan", "CyberShodanCrawler"),
        ("cyber_urlscan", "CyberUrlScanCrawler"),
        ("cyber_virustotal", "CyberVirusTotalCrawler"),
        ("cyber_wayback", "CyberWaybackCrawler"),
    ],
    "monitoring": [],
}

for cat, crawlers in CATEGORY_CRAWLERS.items():
    dirpath = os.path.join(BASE, cat)
    init_path = os.path.join(dirpath, "__init__.py")
    
    # Skip if __init__.py already has real content (property/, gov/, etc.)
    if os.path.exists(init_path):
        with open(init_path) as f:
            existing = f.read().strip()
        if existing and len(existing) > 10:
            print(f"SKIP (has content): {cat}/__init__.py")
            continue
    
    lines = [f'"""Crawlers in the {cat} category."""\n']
    
    if not crawlers:
        lines.append("# No crawlers yet — add new scrapers here.\n")
    
    with open(init_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    
    print(f"OK: {cat}/__init__.py ({len(crawlers)} crawlers)")

