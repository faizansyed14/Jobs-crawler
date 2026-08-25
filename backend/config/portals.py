from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class IndustryDef:
    label: str
    cluster_ind: str  # portal-specific filter id (Naukrigulf ClusterInd / GulfTalent industry_id)


@dataclass(frozen=True)
class LocationDef:
    key: str
    label: str
    api_value: str
    country: str
    lat: float = 0.0
    lng: float = 0.0


def _normalize_location_key(raw: str) -> str:
    return raw.strip().lower().replace(" ", "-").replace("_", "-")


def _normalize_industry_key(raw: str) -> str:
    return raw.strip().lower().replace(" ", "_").replace("-", "_")


@dataclass
class _PortalMixin:
    name: str
    locations: dict[str, LocationDef]
    industries: dict[str, IndustryDef]
    industry_aliases: dict[str, str] = field(default_factory=dict)

    def resolve_locations(self, keys: list[str]) -> list[LocationDef]:
        out: list[LocationDef] = []
        for raw in keys:
            key = _normalize_location_key(raw)
            if key not in self.locations:
                known = ", ".join(sorted(self.locations))
                raise ValueError(f"Unknown location {raw!r}. Known: {known}")
            out.append(self.locations[key])
        return out

    def resolve_industry(self, key: str | None) -> IndustryDef | None:
        if not key:
            return None
        normalized = _normalize_industry_key(key)
        normalized = self.industry_aliases.get(normalized, normalized)
        if normalized not in self.industries:
            known = ", ".join(sorted(self.industries))
            raise ValueError(f"Unknown industry {key!r}. Known: {known}")
        return self.industries[normalized]

    def resolve_industry_keys(
        self,
        *,
        industry: str | None = None,
        industries: list[str] | None = None,
    ) -> list[str]:
        """Canonical industry keys from single or multi selection."""
        raw = list(industries or [])
        if not raw and industry:
            raw = [industry]
        if not raw:
            raise ValueError("Select at least one industry")
        out: list[str] = []
        seen: set[str] = set()
        for item in raw:
            normalized = _normalize_industry_key(item)
            normalized = self.industry_aliases.get(normalized, normalized)
            if normalized not in self.industries:
                known = ", ".join(sorted(self.industries))
                raise ValueError(f"Unknown industry {item!r}. Known: {known}")
            if normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
        return out


@dataclass
class NaukrigulfConfig(_PortalMixin):
    name: str = "naukrigulf"
    base_url: str = "https://www.naukrigulf.com"
    robots_url: str = "https://www.naukrigulf.com/robots.txt"
    search_path: str = "/spapi/jobapi/search"
    app_id: str = "205"
    system_id: str = "2323"
    default_limit: int = 30
    # None = no freshness restriction (all matching jobs, not just recent ones).
    default_freshness: int | None = None
    sort_preference_date: str = "1"
    industry_aliases: dict[str, str] = field(
        default_factory=lambda: {
            "information_technology": "it",
            "tech": "it",
            "banking_and_finance": "banking",
            "realestate": "real_estate",
        }
    )
    industries: dict[str, IndustryDef] = field(
        default_factory=lambda: {
            "it": IndustryDef(label="IT", cluster_ind="25"),
            "hospitality": IndustryDef(label="Hospitality", cluster_ind="20"),
            "construction": IndustryDef(label="Construction", cluster_ind="10"),
            "medical": IndustryDef(label="Medical", cluster_ind="30"),
            "recruitment": IndustryDef(label="Recruitment", cluster_ind="42"),
            "real_estate": IndustryDef(label="Real Estate", cluster_ind="41"),
            "banking": IndustryDef(label="Banking and Finance", cluster_ind="7"),
            "retail": IndustryDef(label="Retail", cluster_ind="43"),
        }
    )
    locations: dict[str, LocationDef] = field(
        default_factory=lambda: {
            "dubai": LocationDef("dubai", "Dubai", "dubai", "UAE", 25.2048, 55.2708),
            "abu-dhabi": LocationDef(
                "abu-dhabi", "Abu Dhabi", "abu-dhabi", "UAE", 24.4539, 54.3773
            ),
            "sharjah": LocationDef(
                "sharjah", "Sharjah", "sharjah", "UAE", 25.3463, 55.4209
            ),
            "riyadh": LocationDef(
                "riyadh", "Riyadh", "riyadh", "Saudi Arabia", 24.7136, 46.6753
            ),
            "jeddah": LocationDef(
                "jeddah", "Jeddah", "jeddah", "Saudi Arabia", 21.4858, 39.1925
            ),
            "dammam": LocationDef(
                "dammam", "Dammam", "dammam", "Saudi Arabia", 26.4207, 50.0888
            ),
            "qatar": LocationDef("qatar", "Qatar", "qatar", "Qatar", 25.2854, 51.5310),
            "doha": LocationDef("doha", "Doha", "doha", "Qatar", 25.2854, 51.5310),
            "kuwait": LocationDef(
                "kuwait", "Kuwait", "kuwait", "Kuwait", 29.3759, 47.9774
            ),
            "bahrain": LocationDef(
                "bahrain", "Bahrain", "bahrain", "Bahrain", 26.2285, 50.5860
            ),
            "oman": LocationDef("oman", "Oman", "oman", "Oman", 23.5859, 58.4059),
            "muscat": LocationDef(
                "muscat", "Muscat", "muscat", "Oman", 23.5859, 58.4059
            ),
        }
    )

    @property
    def search_url(self) -> str:
        return f"{self.base_url}{self.search_path}"


@dataclass
class GulfTalentConfig(_PortalMixin):
    """GulfTalent — HTML listing pages (category/industry) with table + JSON-LD.

    Live check: `/api/jobs/search` ignores category/industry/location query params.
    Filtered results come from SSR pages, e.g.:
      /jobs/category/software[/N]
      /uae/jobs/category/software[/N]
      /jobs/industry/it[/N]
      /dubai/jobs[/N]
    """

    name: str = "gulftalent"
    base_url: str = "https://www.gulftalent.com"
    robots_url: str = "https://www.gulftalent.com/robots.txt"
    search_path: str = "/api/jobs/search"  # unfiltered feed only; not used for crawl
    default_limit: int = 25
    # country display name -> URL path segment
    country_slugs: dict[str, str] = field(
        default_factory=lambda: {
            "UAE": "uae",
            "Saudi Arabia": "saudi-arabia",
            "Qatar": "qatar",
            "Kuwait": "kuwait",
            "Bahrain": "bahrain",
            "Oman": "oman",
            "Egypt": "egypt",
            "Jordan": "jordan",
        }
    )
    # industry key -> (listing_kind, listing_slug) for HTML paths
    # Source of truth: https://www.gulftalent.com/jobs/industry (live Aug 2026)
    industry_paths: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {
            # IT roles: Software category is the densest tech listing; industry/it
            # also exists but overlaps — keep category/software for the "it" key.
            "it": ("category", "software"),
            "accountancy": ("industry", "accountancy"),
            "automotive": ("industry", "automotive"),
            "aviation": ("industry", "aviation"),
            "banking": ("industry", "banking"),
            "construction": ("industry", "construction"),
            "consulting": ("industry", "consulting"),
            "cosmetics": ("industry", "cosmetics"),
            "cyber_network_security": ("industry", "cyber-network-security"),
            "education": ("industry", "education"),
            "engineering": ("industry", "engineering"),
            "facilities_management": ("industry", "facilities-management"),
            "textiles_apparel_fashion": ("industry", "textiles-apparel-fashion"),
            "finance": ("industry", "finance"),
            "fmcg": ("industry", "fmcg"),
            "general_trading": ("industry", "general-trading"),
            "government": ("industry", "government"),
            "healthcare": ("industry", "healthcare"),
            "hospitality": ("industry", "hospitality"),
            "hr": ("industry", "hr"),
            "insurance": ("industry", "insurance"),
            "it_hardware_networking": ("industry", "it-hardware-networking"),
            "law": ("industry", "law"),
            "logistics": ("industry", "logistics"),
            "manufacturing": ("industry", "manufacturing"),
            "marketing": ("industry", "marketing"),
            "media": ("industry", "media"),
            "mining_quarrying": ("industry", "mining-quarrying"),
            "non_profit": ("industry", "non-profit"),
            "oil_gas": ("industry", "oil-gas"),
            "professional_services": ("industry", "professional-services"),
            "publishing": ("industry", "publishing"),
            "real_estate": ("industry", "real-estate"),
            "restaurants_catering": ("industry", "restaurants-catering-food-services"),
            "retail": ("industry", "retail"),
            "security": ("industry", "security"),
            "shipping": ("industry", "shipping"),
            "telecom": ("industry", "telecom"),
            "utilities": ("industry", "utilities"),
        }
    )
    industry_aliases: dict[str, str] = field(
        default_factory=lambda: {
            "information_technology": "it",
            "tech": "it",
            "software": "it",
            "oil_and_gas": "oil_gas",
            "realestate": "real_estate",
            "property": "real_estate",
            "cyber_security": "cyber_network_security",
            "fashion": "textiles_apparel_fashion",
            "legal": "law",
            "ngo": "non_profit",
            "catering": "restaurants_catering",
            "telecommunications": "telecom",
        }
    )
    industries: dict[str, IndustryDef] = field(
        default_factory=lambda: {
            "it": IndustryDef(label="IT / Software", cluster_ind="software"),
            "accountancy": IndustryDef(label="Accountancy", cluster_ind="accountancy"),
            "automotive": IndustryDef(label="Automotive", cluster_ind="automotive"),
            "aviation": IndustryDef(label="Aviation", cluster_ind="aviation"),
            "banking": IndustryDef(label="Banking", cluster_ind="banking"),
            "construction": IndustryDef(label="Construction", cluster_ind="construction"),
            "consulting": IndustryDef(label="Consulting", cluster_ind="consulting"),
            "cosmetics": IndustryDef(label="Cosmetics", cluster_ind="cosmetics"),
            "cyber_network_security": IndustryDef(
                label="Cyber / Network Security", cluster_ind="cyber-network-security"
            ),
            "education": IndustryDef(label="Education", cluster_ind="education"),
            "engineering": IndustryDef(label="Engineering", cluster_ind="engineering"),
            "facilities_management": IndustryDef(
                label="Facilities Management", cluster_ind="facilities-management"
            ),
            "textiles_apparel_fashion": IndustryDef(
                label="Textiles / Apparel / Fashion",
                cluster_ind="textiles-apparel-fashion",
            ),
            "finance": IndustryDef(label="Finance", cluster_ind="finance"),
            "fmcg": IndustryDef(label="FMCG", cluster_ind="fmcg"),
            "general_trading": IndustryDef(
                label="General Trading", cluster_ind="general-trading"
            ),
            "government": IndustryDef(label="Government", cluster_ind="government"),
            "healthcare": IndustryDef(label="Healthcare", cluster_ind="healthcare"),
            "hospitality": IndustryDef(label="Hospitality", cluster_ind="hospitality"),
            "hr": IndustryDef(label="HR", cluster_ind="hr"),
            "insurance": IndustryDef(label="Insurance", cluster_ind="insurance"),
            "it_hardware_networking": IndustryDef(
                label="IT Hardware / Networking",
                cluster_ind="it-hardware-networking",
            ),
            "law": IndustryDef(label="Law", cluster_ind="law"),
            "logistics": IndustryDef(label="Logistics", cluster_ind="logistics"),
            "manufacturing": IndustryDef(
                label="Manufacturing", cluster_ind="manufacturing"
            ),
            "marketing": IndustryDef(label="Marketing", cluster_ind="marketing"),
            "media": IndustryDef(label="Media", cluster_ind="media"),
            "mining_quarrying": IndustryDef(
                label="Mining / Quarrying", cluster_ind="mining-quarrying"
            ),
            "non_profit": IndustryDef(label="Non-Profit", cluster_ind="non-profit"),
            "oil_gas": IndustryDef(label="Oil & Gas", cluster_ind="oil-gas"),
            "professional_services": IndustryDef(
                label="Professional Services", cluster_ind="professional-services"
            ),
            "publishing": IndustryDef(label="Publishing", cluster_ind="publishing"),
            "real_estate": IndustryDef(label="Real Estate", cluster_ind="real-estate"),
            "restaurants_catering": IndustryDef(
                label="Restaurants / Catering",
                cluster_ind="restaurants-catering-food-services",
            ),
            "retail": IndustryDef(label="Retail", cluster_ind="retail"),
            "security": IndustryDef(label="Security", cluster_ind="security"),
            "shipping": IndustryDef(label="Shipping", cluster_ind="shipping"),
            "telecom": IndustryDef(label="Telecom", cluster_ind="telecom"),
            "utilities": IndustryDef(label="Utilities", cluster_ind="utilities"),
        }
    )
    locations: dict[str, LocationDef] = field(
        default_factory=lambda: {
            "dubai": LocationDef("dubai", "Dubai", "dubai", "UAE", 25.2048, 55.2708),
            "abu-dhabi": LocationDef(
                "abu-dhabi", "Abu Dhabi", "abu-dhabi", "UAE", 24.4539, 54.3773
            ),
            "sharjah": LocationDef(
                "sharjah", "Sharjah", "sharjah", "UAE", 25.3463, 55.4209
            ),
            "ras-al-khaimah": LocationDef(
                "ras-al-khaimah",
                "Ras Al Khaimah",
                "ras-al-khaimah",
                "UAE",
                25.7895,
                55.9432,
            ),
            "riyadh": LocationDef(
                "riyadh", "Riyadh", "riyadh", "Saudi Arabia", 24.7136, 46.6753
            ),
            "jeddah": LocationDef(
                "jeddah", "Jeddah", "jeddah", "Saudi Arabia", 21.4858, 39.1925
            ),
            "doha": LocationDef("doha", "Doha", "doha", "Qatar", 25.2854, 51.5310),
            "kuwait": LocationDef(
                "kuwait", "Kuwait", "kuwait", "Kuwait", 29.3759, 47.9774
            ),
            "manama": LocationDef(
                "manama", "Manama", "manama", "Bahrain", 26.2285, 50.5860
            ),
            "muscat": LocationDef(
                "muscat", "Muscat", "muscat", "Oman", 23.5859, 58.4059
            ),
            "cairo": LocationDef("cairo", "Cairo", "cairo", "Egypt", 30.0444, 31.2357),
            "amman": LocationDef(
                "amman", "Amman", "amman", "Jordan", 31.9454, 35.9284
            ),
        }
    )

    @property
    def search_url(self) -> str:
        return f"{self.base_url}{self.search_path}"

    def country_slug(self, location: LocationDef) -> str:
        slug = self.country_slugs.get(location.country)
        if not slug:
            raise ValueError(f"No GulfTalent country slug for {location.country!r}")
        return slug

    def listing_path(
        self,
        *,
        location: LocationDef,
        industry_key: str | None,
        page: int = 1,
    ) -> str:
        """Build listing path. Page 1 has no trailing /N; page>=2 uses /N."""
        if industry_key:
            kind_slug = self.industry_paths.get(industry_key)
            if not kind_slug:
                raise ValueError(f"No GulfTalent listing path for industry {industry_key!r}")
            kind, slug = kind_slug
            country = self.country_slug(location)
            base = f"/{country}/jobs/{kind}/{slug}"
        else:
            base = f"/{location.api_value}/jobs"
        if page <= 1:
            return base
        return f"{base}/{page}"

    def listing_url(
        self,
        *,
        location: LocationDef,
        industry_key: str | None,
        page: int = 1,
    ) -> str:
        return f"{self.base_url}{self.listing_path(location=location, industry_key=industry_key, page=page)}"


@dataclass
class BaytConfig(_PortalMixin):
    """Bayt.com — Cloudflare-protected SSR listing pages.

    curl_cffi alone gets CF 403. Transport: try curl, then headed Chrome (nodriver).

    Robots-safe SEO URLs only (no /en/jobs/?, no filters[, no options[):
      /en/{country}/jobs/jobs-in-{city}/?page=N
      /en/{country}/jobs/{industry}-jobs-in-{city}/?page=N
    """

    name: str = "bayt"
    base_url: str = "https://www.bayt.com"
    robots_url: str = "https://www.bayt.com/robots.txt"
    locale: str = "en"
    default_limit: int = 20
    country_slugs: dict[str, str] = field(
        default_factory=lambda: {
            "UAE": "uae",
            "Saudi Arabia": "saudi-arabia",
            "Qatar": "qatar",
            "Kuwait": "kuwait",
            "Bahrain": "bahrain",
            "Oman": "oman",
            "Egypt": "egypt",
            "Jordan": "jordan",
        }
    )
    # industry key -> SEO slug segment before "-jobs-in-{city}"
    # Validated live against Dubai listings (Aug 2026).
    industry_slugs: dict[str, str] = field(
        default_factory=lambda: {
            "it": "information-technology",
            "software": "software",
            "cyber_security": "cyber-security",
            "devops": "devops",
            "cloud_computing": "cloud-computing",
            "data_science": "data-science",
            "artificial_intelligence": "artificial-intelligence",
            "network_engineering": "network-engineering",
            "telecommunications": "telecommunications",
            "it_support": "it-support",
            "hospitality": "hospitality",
            "construction": "construction",
            "healthcare": "healthcare",
            "education": "education",
            "retail": "retail",
            "banking": "banking",
            "finance": "finance",
            "engineering": "engineering",
            "oil_gas": "oil-and-gas",
            "real_estate": "real-estate",
            "hr": "human-resources",
            "marketing": "marketing",
            "sales": "sales",
            "accounting": "accounting",
            "customer_service": "customer-service",
            "administration": "administration",
            "legal": "legal",
            "media": "media",
            "insurance": "insurance",
            "manufacturing": "manufacturing",
            "logistics": "logistics",
            "aviation": "aviation",
            "automotive": "automotive",
            "government": "government",
            "security": "security",
            "tourism": "tourism",
            "travel": "travel",
            "fmcg": "fmcg",
            "pharmaceutical": "pharmaceutical",
            "architecture": "architecture",
            "design": "design",
            "qa_qc": "quality-control-qa-and-qc",
            "procurement": "procurement",
            "supply_chain": "supply-chain",
            "secretarial": "secretarial",
            "training": "training",
            "sports": "sports",
            "beauty": "beauty",
            "fashion": "fashion",
            "entertainment": "entertainment",
            "publishing": "publishing",
            "ngo": "ngo",
            "non_profit": "non-profit",
            "facilities_management": "facilities-management",
            "maintenance": "maintenance",
            "mechanical_engineering": "mechanical-engineering",
            "civil_engineering": "civil-engineering",
            "electrical_engineering": "electrical-engineering",
        }
    )
    industry_aliases: dict[str, str] = field(
        default_factory=lambda: {
            "information_technology": "it",
            "tech": "it",
            "oil_and_gas": "oil_gas",
            "realestate": "real_estate",
            "human_resources": "hr",
            "quality_control": "qa_qc",
            "qa": "qa_qc",
            "customer_service": "customer_service",
            "admin": "administration",
        }
    )
    industries: dict[str, IndustryDef] = field(
        default_factory=lambda: {
            "it": IndustryDef(label="IT", cluster_ind="information-technology"),
            "software": IndustryDef(label="Software", cluster_ind="software"),
            "cyber_security": IndustryDef(
                label="Cyber Security", cluster_ind="cyber-security"
            ),
            "devops": IndustryDef(label="DevOps", cluster_ind="devops"),
            "cloud_computing": IndustryDef(
                label="Cloud Computing", cluster_ind="cloud-computing"
            ),
            "data_science": IndustryDef(
                label="Data Science", cluster_ind="data-science"
            ),
            "artificial_intelligence": IndustryDef(
                label="AI", cluster_ind="artificial-intelligence"
            ),
            "network_engineering": IndustryDef(
                label="Network Engineering", cluster_ind="network-engineering"
            ),
            "telecommunications": IndustryDef(
                label="Telecom", cluster_ind="telecommunications"
            ),
            "it_support": IndustryDef(label="IT Support", cluster_ind="it-support"),
            "hospitality": IndustryDef(label="Hospitality", cluster_ind="hospitality"),
            "construction": IndustryDef(label="Construction", cluster_ind="construction"),
            "healthcare": IndustryDef(label="Healthcare", cluster_ind="healthcare"),
            "education": IndustryDef(label="Education", cluster_ind="education"),
            "retail": IndustryDef(label="Retail", cluster_ind="retail"),
            "banking": IndustryDef(label="Banking", cluster_ind="banking"),
            "finance": IndustryDef(label="Finance", cluster_ind="finance"),
            "engineering": IndustryDef(label="Engineering", cluster_ind="engineering"),
            "oil_gas": IndustryDef(label="Oil & Gas", cluster_ind="oil-and-gas"),
            "real_estate": IndustryDef(label="Real Estate", cluster_ind="real-estate"),
            "hr": IndustryDef(label="HR", cluster_ind="human-resources"),
            "marketing": IndustryDef(label="Marketing", cluster_ind="marketing"),
            "sales": IndustryDef(label="Sales", cluster_ind="sales"),
            "accounting": IndustryDef(label="Accounting", cluster_ind="accounting"),
            "customer_service": IndustryDef(
                label="Customer Service", cluster_ind="customer-service"
            ),
            "administration": IndustryDef(
                label="Administration", cluster_ind="administration"
            ),
            "legal": IndustryDef(label="Legal", cluster_ind="legal"),
            "media": IndustryDef(label="Media", cluster_ind="media"),
            "insurance": IndustryDef(label="Insurance", cluster_ind="insurance"),
            "manufacturing": IndustryDef(
                label="Manufacturing", cluster_ind="manufacturing"
            ),
            "logistics": IndustryDef(label="Logistics", cluster_ind="logistics"),
            "aviation": IndustryDef(label="Aviation", cluster_ind="aviation"),
            "automotive": IndustryDef(label="Automotive", cluster_ind="automotive"),
            "government": IndustryDef(label="Government", cluster_ind="government"),
            "security": IndustryDef(label="Security", cluster_ind="security"),
            "tourism": IndustryDef(label="Tourism", cluster_ind="tourism"),
            "travel": IndustryDef(label="Travel", cluster_ind="travel"),
            "fmcg": IndustryDef(label="FMCG", cluster_ind="fmcg"),
            "pharmaceutical": IndustryDef(
                label="Pharmaceutical", cluster_ind="pharmaceutical"
            ),
            "architecture": IndustryDef(
                label="Architecture", cluster_ind="architecture"
            ),
            "design": IndustryDef(label="Design", cluster_ind="design"),
            "qa_qc": IndustryDef(
                label="QA / QC", cluster_ind="quality-control-qa-and-qc"
            ),
            "procurement": IndustryDef(label="Procurement", cluster_ind="procurement"),
            "supply_chain": IndustryDef(
                label="Supply Chain", cluster_ind="supply-chain"
            ),
            "secretarial": IndustryDef(label="Secretarial", cluster_ind="secretarial"),
            "training": IndustryDef(label="Training", cluster_ind="training"),
            "sports": IndustryDef(label="Sports", cluster_ind="sports"),
            "beauty": IndustryDef(label="Beauty", cluster_ind="beauty"),
            "fashion": IndustryDef(label="Fashion", cluster_ind="fashion"),
            "entertainment": IndustryDef(
                label="Entertainment", cluster_ind="entertainment"
            ),
            "publishing": IndustryDef(label="Publishing", cluster_ind="publishing"),
            "ngo": IndustryDef(label="NGO", cluster_ind="ngo"),
            "non_profit": IndustryDef(label="Non-Profit", cluster_ind="non-profit"),
            "facilities_management": IndustryDef(
                label="Facilities Management", cluster_ind="facilities-management"
            ),
            "maintenance": IndustryDef(label="Maintenance", cluster_ind="maintenance"),
            "mechanical_engineering": IndustryDef(
                label="Mechanical Engineering", cluster_ind="mechanical-engineering"
            ),
            "civil_engineering": IndustryDef(
                label="Civil Engineering", cluster_ind="civil-engineering"
            ),
            "electrical_engineering": IndustryDef(
                label="Electrical Engineering", cluster_ind="electrical-engineering"
            ),
        }
    )
    locations: dict[str, LocationDef] = field(
        default_factory=lambda: {
            "dubai": LocationDef("dubai", "Dubai", "dubai", "UAE", 25.2048, 55.2708),
            "abu-dhabi": LocationDef(
                "abu-dhabi", "Abu Dhabi", "abu-dhabi", "UAE", 24.4539, 54.3773
            ),
            "sharjah": LocationDef(
                "sharjah", "Sharjah", "sharjah", "UAE", 25.3463, 55.4209
            ),
            "riyadh": LocationDef(
                "riyadh", "Riyadh", "riyadh", "Saudi Arabia", 24.7136, 46.6753
            ),
            "jeddah": LocationDef(
                "jeddah", "Jeddah", "jeddah", "Saudi Arabia", 21.4858, 39.1925
            ),
            "dammam": LocationDef(
                "dammam", "Dammam", "dammam", "Saudi Arabia", 26.4207, 50.0888
            ),
            "doha": LocationDef("doha", "Doha", "doha", "Qatar", 25.2854, 51.5310),
            "kuwait": LocationDef(
                "kuwait", "Kuwait", "kuwait", "Kuwait", 29.3759, 47.9774
            ),
            "manama": LocationDef(
                "manama", "Manama", "manama", "Bahrain", 26.2285, 50.5860
            ),
            "muscat": LocationDef(
                "muscat", "Muscat", "muscat", "Oman", 23.5859, 58.4059
            ),
            "cairo": LocationDef("cairo", "Cairo", "cairo", "Egypt", 30.0444, 31.2357),
            "amman": LocationDef(
                "amman", "Amman", "amman", "Jordan", 31.9454, 35.9284
            ),
        }
    )

    def country_slug(self, location: LocationDef) -> str:
        slug = self.country_slugs.get(location.country)
        if not slug:
            raise ValueError(f"No Bayt country slug for {location.country!r}")
        return slug

    def listing_path(
        self,
        *,
        location: LocationDef,
        industry_key: str | None,
        page: int = 1,
    ) -> str:
        country = self.country_slug(location)
        city = location.api_value
        if industry_key:
            ind = self.industry_slugs.get(industry_key) or (
                self.industries[industry_key].cluster_ind
                if industry_key in self.industries
                else None
            )
            if not ind:
                raise ValueError(f"No Bayt industry slug for {industry_key!r}")
            path = f"/{self.locale}/{country}/jobs/{ind}-jobs-in-{city}/"
        else:
            path = f"/{self.locale}/{country}/jobs/jobs-in-{city}/"
        if page > 1:
            return f"{path}?page={page}"
        return path

    def listing_url(
        self,
        *,
        location: LocationDef,
        industry_key: str | None,
        page: int = 1,
    ) -> str:
        return f"{self.base_url}{self.listing_path(location=location, industry_key=industry_key, page=page)}"


class PortalConfig(Protocol):
    name: str
    locations: dict[str, LocationDef]
    industries: dict[str, IndustryDef]

    def resolve_locations(self, keys: list[str]) -> list[LocationDef]: ...

    def resolve_industry(self, key: str | None) -> IndustryDef | None: ...


PORTALS: dict[str, Any] = {
    "naukrigulf": NaukrigulfConfig(),
    "gulftalent": GulfTalentConfig(),
    "bayt": BaytConfig(),
}

PORTAL_LABELS: dict[str, str] = {
    "naukrigulf": "Naukrigulf",
    "gulftalent": "GulfTalent",
    "bayt": "Bayt",
}


def list_portals() -> list[dict[str, str]]:
    return [
        {"key": key, "label": PORTAL_LABELS.get(key, key)}
        for key in sorted(PORTALS)
    ]


def get_portal_config(name: str) -> Any:
    key = name.strip().lower().replace(" ", "").replace("_", "")
    aliases = {
        "gulf-talent": "gulftalent",
        "gulftalentcom": "gulftalent",
        "naukri": "naukrigulf",
        "naukrigulfcom": "naukrigulf",
        "baytcom": "bayt",
    }
    key = aliases.get(key, key)
    if key not in PORTALS:
        raise ValueError(f"Unknown portal {name!r}. Known: {', '.join(sorted(PORTALS))}")
    return PORTALS[key]
