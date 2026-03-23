from enum import Enum


class SeedType(str, Enum):
    PHONE = "phone"
    EMAIL = "email"
    USERNAME = "username"
    FULL_NAME = "full_name"
    IP_ADDRESS = "ip_address"
    CRYPTO_WALLET = "crypto_wallet"
    DOMAIN = "domain"
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    COMPANY_REG = "company_reg"


class IdentifierType(str, Enum):
    PHONE = "phone"
    EMAIL = "email"
    USERNAME = "username"
    FULL_NAME = "full_name"
    ALIAS = "alias"
    IP_ADDRESS = "ip_address"
    CRYPTO_WALLET = "crypto_wallet"
    DOMAIN = "domain"
    NATIONAL_ID = "national_id"
    PASSPORT = "passport"
    COMPANY_REG = "company_reg"
    VEHICLE_REG = "vehicle_reg"
    IMEI = "imei"


class RelType(str, Enum):
    ASSOCIATE = "associate"
    FAMILY = "family"
    EMPLOYER = "employer"
    EMPLOYEE = "employee"
    COHABITANT = "cohabitant"
    BUSINESS_PARTNER = "business_partner"
    CO_SIGNATORY = "co_signatory"
    SHARED_DEVICE = "shared_device"
    SHARED_NETWORK = "shared_network"
    SOCIAL_FOLLOW = "social_follow"
    SOCIAL_INTERACT = "social_interact"
    ALIAS_OF = "alias_of"


class Platform(str, Enum):
    INSTAGRAM = "instagram"
    TWITTER = "twitter"
    FACEBOOK = "facebook"
    LINKEDIN = "linkedin"
    TIKTOK = "tiktok"
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    SNAPCHAT = "snapchat"
    REDDIT = "reddit"
    GITHUB = "github"
    YOUTUBE = "youtube"
    PINTEREST = "pinterest"
    DISCORD = "discord"
    ONLYFANS = "onlyfans"
    TRUECALLER = "truecaller"
    DARK_FORUM = "dark_forum"
    DARK_PASTE = "dark_paste"
    DARK_MARKET = "dark_market"
    IRC = "irc"
    UNKNOWN = "unknown"


class AlertSeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertType(str, Enum):
    NEW_IDENTIFIER = "new_identifier"
    NEW_ASSOCIATION = "new_association"
    DARKWEB_MENTION = "darkweb_mention"
    SANCTIONS_HIT = "sanctions_hit"
    BREACH_FOUND = "breach_found"
    BURNER_DETECTED = "burner_detected"
    CRIMINAL_SIGNAL = "criminal_signal"
    RISK_SCORE_CHANGE = "risk_score_change"
    WEALTH_CHANGE = "wealth_change"


class CrawlStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    RATE_LIMITED = "rate_limited"
    BLOCKED = "blocked"


class WealthBand(str, Enum):
    ULTRA_HNW = "ultra_hnw"       # > $10M
    HIGH_HNW = "high_hnw"         # $1M - $10M
    AFFLUENT = "affluent"          # $250K - $1M
    MIDDLE = "middle"              # $50K - $250K
    LOWER = "lower"                # $15K - $50K
    STRESSED = "stressed"          # < $15K or distress signals
    UNKNOWN = "unknown"


class LineType(str, Enum):
    MOBILE = "mobile"
    LANDLINE = "landline"
    VOIP = "voip"
    PREPAID = "prepaid"
    TOLL_FREE = "toll_free"
    UNKNOWN = "unknown"


class BurnerConfidence(str, Enum):
    CONFIRMED = "confirmed"       # >= 0.70
    LIKELY = "likely"             # 0.40 - 0.69
    POSSIBLE = "possible"         # 0.20 - 0.39
    CLEAN = "clean"               # < 0.20


class DefaultRiskTier(str, Enum):
    DO_NOT_LEND = "do_not_lend"   # 0.80 - 1.00
    HIGH_RISK = "high_risk"       # 0.60 - 0.79
    MEDIUM_RISK = "medium_risk"   # 0.40 - 0.59
    LOW_RISK = "low_risk"         # 0.20 - 0.39
    PREFERRED = "preferred"       # 0.00 - 0.19


class CriminalSignalType(str, Enum):
    DRUG_DEALING = "drug_dealing"
    FRAUD = "fraud"
    MONEY_LAUNDERING = "money_laundering"
    WEAPONS = "weapons"
    STOLEN_GOODS = "stolen_goods"
    HUMAN_TRAFFICKING = "human_trafficking"
    DOCUMENT_FRAUD = "document_fraud"
    FINANCIAL_CRIME = "financial_crime"
    SANCTIONS_EVASION = "sanctions_evasion"


class Chain(str, Enum):
    BTC = "btc"
    ETH = "eth"
    USDT_TRC20 = "usdt_trc20"
    USDT_ERC20 = "usdt_erc20"
    BNB = "bnb"
    SOL = "sol"
    XMR = "xmr"
    LTC = "ltc"
    MATIC = "matic"
    UNKNOWN = "unknown"


class VerificationStatus(str, Enum):
    UNVERIFIED = "unverified"
    CORROBORATED = "corroborated"  # same fact in 2+ sources
    VERIFIED = "verified"          # active probe confirmed


# Source reliability scores (0.0 - 1.0)
SOURCE_RELIABILITY: dict[str, float] = {
    "government_registry": 0.95,
    "court_record": 0.92,
    "financial_record": 0.88,
    "company_registry": 0.85,
    "property_registry": 0.85,
    "linkedin": 0.75,
    "truecaller": 0.70,
    "whitepages": 0.65,
    "facebook": 0.60,
    "instagram": 0.55,
    "twitter": 0.55,
    "tiktok": 0.50,
    "telegram": 0.50,
    "paste_site": 0.35,
    "dark_forum": 0.30,
    "dark_paste": 0.25,
    "unknown": 0.20,
}

# Freshness half-lives in hours
FRESHNESS_HALF_LIFE: dict[str, float] = {
    "sanctions": 6.0,
    "watchlist": 6.0,
    "breach_database": 24.0,
    "social_media_post": 72.0,       # 3 days
    "social_media_profile": 168.0,   # 7 days
    "phone_registration": 336.0,     # 14 days
    "court_record": 720.0,           # 30 days
    "employment": 1440.0,            # 60 days
    "property": 2160.0,              # 90 days
    "education": 8760.0,             # 365 days
    "default": 168.0,                # 7 days
}

# Known burner/VoIP carrier substrings (lowercase match)
BURNER_CARRIERS = frozenset([
    "textnow", "google voice", "hushed", "burner", "mysudo", "sideline",
    "2ndline", "iplum", "talkatone", "bandwidth", "twilio", "vonage",
    "telnyx", "flowroute", "magicjack", "ooma", "grasshopper", "openphone",
    "dialpad", "ringcentral", "nextiva", "8x8", "textfree", "pinger",
    "fongo", "textplus", "numberbarn", "skype", "viber", "line",
    "textme", "choicetelecom", "tracfone", "safelink", "net10",
    "boost mobile virtual", "cricket virtual", "metro virtual",
    "visible wireless", "ultra mobile", "mint mobile virtual",
])
