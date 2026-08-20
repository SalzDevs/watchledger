"""Target references for the POC.

A target is (brand, reference) as written on the watch. Resolution to MEW
slugs happens at fetch time via the /api/references/resolve endpoint; any
target that cannot be resolved is skipped and reported in fetch output.
"""

TARGETS = [
    ("Rolex", "126610LN"),
    ("Rolex", "124060"),
    ("Rolex", "116500LN"),
    ("Rolex", "126710BLRO"),
    ("Rolex", "124270"),
    ("Rolex", "226570"),
    ("Omega", "310.30.42.50.01.001"),
    ("Omega", "311.30.42.30.01.005"),
    ("Patek Philippe", "5711/1A"),
    ("Patek Philippe", "5712/1A"),
    ("Audemars Piguet", "15500ST.OO.1220ST.01"),
    ("Audemars Piguet", "15202ST.OO.1240ST.01"),
    ("Cartier", "WSSA0039"),
    ("Cartier", "WSSA0013"),
    ("Tudor", "M79230N-0009"),
    ("Tudor", "M79030N-0001"),
    ("IWC", "IW371605"),
    ("Jaeger-LeCoultre", "Q4108420"),
    ("Vacheron Constantin", "4500V/110A-B128"),
    ("Grand Seiko", "SBGA413"),
]

MEW_BASE = "https://mostexpensivewatches.net"

RAW_DIR = "data/raw"
DB_PATH = "data/ledger.sqlite"
REPORTS_DIR = "reports"
STATIC_DIR = "static"