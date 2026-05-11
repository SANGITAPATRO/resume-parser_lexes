# =============================================================================
# constants.py
# All configuration constants for the resume parser.
# NO logic, NO imports of heavy libraries — pure data only.
# =============================================================================

from __future__ import annotations

import geonamescache

# ── Indian / US states set (used by location extractor & education parser) ────
_gc = geonamescache.GeonamesCache()

_STATES: set[str] = {
    s["name"] for s in _gc.get_us_states().values()
} | {
    # Indian States
    "Andhra Pradesh", "Arunachal Pradesh", "Assam", "Bihar",
    "Chhattisgarh", "Goa", "Gujarat", "Haryana", "Himachal Pradesh",
    "Jharkhand", "Karnataka", "Kerala", "Madhya Pradesh", "Maharashtra",
    "Manipur", "Meghalaya", "Mizoram", "Nagaland", "Odisha",
    "Punjab", "Rajasthan", "Sikkim", "Tamil Nadu", "Telangana",
    "Tripura", "Uttar Pradesh", "Uttarakhand", "West Bengal",
    # Union Territories
    "Andaman and Nicobar Islands", "Chandigarh",
    "Dadra and Nagar Haveli and Daman and Diu",
    "Delhi", "Jammu and Kashmir", "Ladakh",
    "Lakshadweep", "Puducherry", "Pondicherry",
    # Common abbreviations / alternate spellings
    "J&K", "AP", "UP", "MP", "TN", "WB",
    "Orissa",
}


# ── School-education levels that need special handling ────────────────────────
# Used in education parser to skip org-name assignment for school records.
_SCHOOL_LEVELS: set[str] = {"12th", "10th"}


# ── Synonyms for "still in this role" ────────────────────────────────────────
# Used in experience date parsing and total experience calculation.
_CURRENT_TERMS: frozenset[str] = frozenset({
    "present", "current", "currently", "ongoing",
    "till date", "till now", "now",
})


# ── Maps raw project key-value label → Project dataclass field name ───────────
_PROJECT_FIELD_MAP: dict[str, str] = {
    "client name":   "client",
    "client":        "client",
    "title":         "title",
    "role":          "role",
    "duration":      "duration",
    "technologies":  "technologies",
    "tech stack":    "technologies",
    "tools":         "technologies",
    "tech":          "technologies",
    "description":   "description",
}


# ── Maps proficiency keywords → standardised LinkedIn-style levels ─────────────
_PROFICIENCY_MAP: dict[str, str] = {
    "native":         "Native or bilingual proficiency",
    "bilingual":      "Native or bilingual proficiency",
    "fluent":         "Full professional proficiency",
    "professional":   "Professional working proficiency",
    "conversational": "Limited working proficiency",
    "basic":          "Elementary proficiency",
    "beginner":       "Elementary proficiency",
}


# ── Normalised degree labels: (pattern, display_label, education_level) ───────
_DEGREE_LABEL_MAP: list[tuple[str, str, str]] = [
    (r"\bPh\.?D\b|\bDoctorate\b|\bD\.Phil\b|\bpost.?doc\b",    "Ph.D",        "doctoral"),
    (r"\bM\.?Tech\b",                                            "M.Tech",      "master"),
    (r"\bM\.?E\b(?:\s*[-–(]|\s+in\b)",                          "M.E",         "master"),
    (r"\bMBA\b",                                                 "MBA",         "master"),
    (r"\bMCA\b|\bM\.?C\.?A\b",                                  "MCA",         "master"),
    (r"\bM\.?Sc\b",                                              "M.Sc",        "master"),
    (r"\bM\.?Com\b",                                             "M.Com",       "master"),
    (r"\bM\.?Phil\b",                                            "M.Phil",      "master"),
    (r"\bPGDM\b|\bPGD\b",                                       "PGDM",        "master"),
    (r"\bPGDIBO\b",                                              "PGDIBO",      "master"),
    (r"\bPost\s+Graduate\s+Diploma\b",                          "PG Diploma",  "master"),
    (r"\bMaster(?:s|\'s)?\s+(?:of|in)\b",                      "Master",      "master"),
    (r"\bB\.?Tech\b|\bBachelor\s+of\s+Technology\b",           "B.Tech",      "bachelor"),
    (r"\bB\.?E\b(?:\s*[-–(]|\s+in\b|\s+\()|"
     r"\bBachelor\s+of\s+Engineering\b",                        "B.E",         "bachelor"),
    (r"\bBCA\b",                                                "BCA",         "bachelor"),
    (r"\bBCS\b|\bBachelor\s+of\s+Computer\b",                  "BCS",         "bachelor"),
    (r"\bB\.?Sc\b|\bBSC\b",                                    "B.Sc",        "bachelor"),
    (r"\bB\.?Com\b|\bBCOM\b",                                  "B.Com",       "bachelor"),
    (r"\bBBA\b",                                                "BBA",         "bachelor"),
    (r"\bBMS\b",                                                "BMS",         "bachelor"),
    (r"\bMBBS\b",                                               "MBBS",        "bachelor"),
    (r"\bBachelor(?:s|\'s)?\s+(?:of|in)\b",                    "Bachelor",    "bachelor"),
    (r"\bB\s*E\s+Information\b",                                "B.E",         "bachelor"),
    (r"\bAdvanced\s+Diploma\b",                                 "Adv. Diploma","diploma"),
    (r"\bDiploma\b|\bPolytechnic\b|\bITI\b",                   "Diploma",     "diploma"),
    (r"\bHSC\b|\bClass\s*XII\b|\b12th\b|\bHigher\s+Secondary\b"
     r"|\bIntermediate\b|\bPUC\b|\bSenior\s+Secondary\b",      "HSC",         "12th"),
    (r"\bSSLC\b|\bS\.S\.C\b|\bSSC\b|\bClass\s*X\b|\b10th\b"
     r"|\bMatriculation\b|\bHigh\s+School\b|"
     r"\bSecondary\s+School\s+Leaving\b",                       "SSLC",        "10th"),
]


# ── Field-of-study mapping: canonical name → list of match patterns ───────────
_FIELD_MAP: dict[str, list[str]] = {
    "Computer Science and Engineering":  ["computer science and engineering", r"\bcse\b"],
    "Computer Science":                  ["computer science"],
    "Information Technology":            ["information technology"],
    "Electronics and Communication":     ["electronics and communication", r"\bece\b", r"e\s*&\s*c"],
    "Electrical and Electronics":        [r"electrical.*electronics", r"\beee\b"],
    "Electrical Engineering":            [r"\belectrical engineering\b"],
    "Mechanical Engineering":            [r"\bmechanical engineering\b"],
    "Computer Applications":             ["computer applications"],
    "Mathematics":                       [r"\bmathematics\b"],
    "Physics":                           [r"\bphysics\b"],
    "IT & Management":                   [r"it\s*&\s*m"],
    "Commerce":                          [r"\bcommerce\b"],
    "Business Administration":           ["business administration"],
    "Project Management":                ["project management"],
    "Civil Engineering":                 [r"\bcivil engineering\b"],
    "Biotechnology":                     [r"\bbiotechnology\b"],
    "Artificial Intelligence and ML":    ["artificial intelligence", "machine learning",
                                          r"\baiml\b", r"\bai\b", r"\bml\b"],
    "Data Science":                      ["data science", r"\bds\b", "data analytics", "big data"],
    "Chemical Engineering":              ["chemical engineering", r"\bch\b", r"\bchem\b"],
    "Aerospace Engineering":             ["aerospace engineering", r"\baero\b"],
    "Electronics Engineering":           ["electronics engineering", r"\belectronics\b", r"\beie\b"],
    "Software Engineering":              ["software engineering", r"\bse\b"],
    "Economics":                         ["economics"],
    "English Literature":                ["english literature", "english"],
    "Medicine":                          ["mbbs", "medicine", "medical"],
    "Pharmacy":                          ["pharmacy", r"\bbpharm\b", r"\bdpharm\b"],
    "Nursing":                           ["nursing", r"\bbsc nursing\b"],
}


# ── Skill categories ──────────────────────────────────────────────────────────
SKILL_CATEGORIES: dict[str, list[str]] = {

    # ── Languages (spoken/written) ────────────────────────────────────────────
    "Languages (Spoken)": [
        "english", "tamil", "hindi", "kannada", "telugu", "malayalam",
        "marathi", "gujarati", "bengali", "punjabi", "odia", "assamese",
        "urdu", "sanskrit", "french", "german", "spanish", "japanese",
        "chinese", "mandarin", "arabic", "korean", "portuguese",
        "italian", "russian",
    ],

    # ── Programming languages ─────────────────────────────────────────────────
    "Programming Languages": [
        "python", "java", "c#", "c++", "c ", "c language",
        "javascript", "typescript", "go", "golang", "rust", "swift",
        "kotlin", "scala", "ruby", "perl", "r language", "matlab",
        "vba", "cobol", "fortran", "assembly", "bash", "shell",
        "powershell", "groovy", "dart", "elixir", "haskell", "lua",
        "php", "vb.net", "visual basic",
    ],

    # ── Web / frontend ────────────────────────────────────────────────────────
    "Web / Frontend": [
        "html", "html5", "css", "css3", "tailwindcss", "bootstrap",
        "sass", "less", "jquery", "ajax", "reactjs", "react",
        "next.js", "angular", "angularjs", "vue", "vue.js",
        "svelte", "nuxt", "gatsby", "webpack", "vite", "babel",
        "redux", "mobx", "graphql", "rest api", "restful",
        "asp.net", "asp.net mvc", "asp.net core", "mvc", "razor",
        "blazor",
    ],

    # ── Backend / server ──────────────────────────────────────────────────────
    "Backend / Server": [
        "node.js", "nodejs", "express", "express.js", "sequelize",
        "django", "flask", "fastapi", "spring", "spring boot",
        "laravel", "symfony", "rails", "ruby on rails",
        "dotnet", ".net", ".net core", ".net framework",
        "hibernate", "jpa", "servlet",
    ],

    # ── Databases ─────────────────────────────────────────────────────────────
    "Databases": [
        "sql", "mysql", "postgresql", "postgres", "oracle",
        "sql server", "mssql", "sqlite", "mariadb",
        "mongodb", "cassandra", "redis", "dynamodb",
        "elasticsearch", "neo4j", "hbase", "couchdb",
        "stored procedure", "stored procedures",
        "pl/sql", "t-sql", "nosql",
    ],

    # ── Cloud / DevOps ────────────────────────────────────────────────────────
    "Cloud / DevOps": [
        "aws", "azure", "gcp", "google cloud",
        "docker", "kubernetes", "k8s", "helm",
        "jenkins", "gitlab ci", "github actions", "circleci",
        "terraform", "ansible", "puppet", "chef",
        "devops", "ci/cd", "continuous integration",
        "azure devops", "azure pipelines",
    ],

    # ── Version control / collaboration ───────────────────────────────────────
    "Version Control / Collaboration": [
        "git", "github", "gitlab", "bitbucket", "svn",
        "mercurial", "jira", "confluence", "trello",
        "asana", "slack", "microsoft teams",
    ],

    # ── Testing / QA ──────────────────────────────────────────────────────────
    "Testing / QA": [
        "junit", "pytest", "selenium", "playwright",
        "cypress", "jest", "mocha", "chai",
        "postman", "soapui", "jmeter",
        "testng", "nunit", "xunit",
        "unit testing", "integration testing",
        "performance testing", "load testing",
        "manual testing", "automation testing",
        "veracode", "cwe",
    ],

    # ── Data Science / ML / AI ────────────────────────────────────────────────
    "Data Science / ML / AI": [
        "machine learning", "deep learning", "neural network",
        "tensorflow", "keras", "pytorch", "scikit-learn",
        "pandas", "numpy", "scipy", "matplotlib", "seaborn",
        "tableau", "power bi", "qlik",
        "nlp", "natural language processing",
        "computer vision", "opencv",
        "data analysis", "data analytics",
        "data science", "big data",
        "hadoop", "spark", "kafka", "airflow",
        "statistics", "statistical analysis",
    ],

    # ── Reporting / BI tools ──────────────────────────────────────────────────
    "Reporting / BI Tools": [
        "crystal reports", "crystal report",
        "ssrs", "ssis", "ssas",
        "cognos", "microstrategy", "looker",
        "devexpress", "telerik", "rdlc",
        "excel", "advanced excel", "pivot table",
    ],

    # ── ERP / CRM / Enterprise ────────────────────────────────────────────────
    "ERP / CRM / Enterprise": [
        "sap", "oracle erp", "dynamics", "ms dynamics",
        "salesforce", "crm", "siebel",
        "sharepoint", "ms sharepoint", "sharegate",
        "servicenow", "workday",
        "erp", "enterprise resource planning",
    ],

    # ── Development tools / IDEs ──────────────────────────────────────────────
    "Development Tools / IDEs": [
        "visual studio", "vs code", "vscode",
        "eclipse", "intellij", "pycharm",
        "netbeans", "android studio", "xcode",
        "putty", "justdecompile",
        "iis", "apache", "nginx", "tomcat",
    ],

    # ── OS / Infrastructure ───────────────────────────────────────────────────
    "OS / Infrastructure": [
        "linux", "ubuntu", "centos", "rhel", "debian",
        "windows", "windows server", "unix",
        "macos", "ios", "android",
        "networking", "tcp/ip", "dns", "dhcp",
        "firewall", "vpn", "active directory",
    ],

    # ── Office / productivity ─────────────────────────────────────────────────
    "Office / Productivity": [
        "ms office", "microsoft office",
        "ms word", "ms excel", "ms powerpoint",
        "ms access", "ms outlook",
        "google workspace", "google docs", "google sheets",
        "libreoffice",
    ],

    # ── Finance / accounting ──────────────────────────────────────────────────
    "Finance / Accounting": [
        "tally", "quickbooks", "zoho books",
        "accounts", "accounting", "bookkeeping",
        "taxation", "gst", "tds",
        "financial analysis", "financial reporting",
        "budgeting", "forecasting", "auditing",
        "cost accounting", "management accounting",
    ],

    # ── Marketing / digital ───────────────────────────────────────────────────
    "Marketing / Digital": [
        "seo", "sem", "google ads", "facebook ads",
        "content marketing", "email marketing",
        "social media", "social media marketing",
        "google analytics", "digital marketing",
        "affiliate marketing", "ppc",
        "brand management", "market research",
    ],

    # ── Project / process management ──────────────────────────────────────────
    "Project / Process Management": [
        "project management", "agile", "scrum",
        "kanban", "waterfall", "prince2", "pmp",
        "sdlc", "software development life cycle",
        "six sigma", "lean", "iso",
        "itil", "change management",
        "risk management", "stakeholder management",
    ],

    # ── Soft skills ───────────────────────────────────────────────────────────
    "Soft Skills": [
        "communication", "leadership", "teamwork",
        "team player", "problem solving", "critical thinking",
        "time management", "multitasking",
        "adaptability", "flexibility",
        "creativity", "innovation",
        "presentation", "negotiation",
        "client management", "customer service",
        "relationship management",
        "analytical thinking",
        "decision making",
        "attention to detail",
        "result oriented", "target driven",
    ],

    # ── Healthcare / clinical ─────────────────────────────────────────────────
    "Healthcare / Clinical": [
        "patient care", "clinical", "diagnosis",
        "pharmacology", "nursing", "ehr", "emr",
        "icd", "cpt coding", "medical billing",
    ],

    # ── Legal ─────────────────────────────────────────────────────────────────
    "Legal": [
        "contract management", "legal research",
        "litigation", "compliance", "regulatory",
        "intellectual property", "ip law",
    ],

    # ── Design / creative ─────────────────────────────────────────────────────
    "Design / Creative": [
        "photoshop", "illustrator", "indesign",
        "figma", "sketch", "adobe xd",
        "ui design", "ux design", "ui/ux",
        "wireframing", "prototyping",
        "canva", "coreldraw",
        "video editing", "premiere pro", "after effects",
    ],

    # ── Miscellaneous (fallback) ───────────────────────────────────────────────
    "Miscellaneous": [],
}


# ── Education levels keyword mapping ─────────────────────────────────────────
EDUCATION_LEVELS: dict[str, list[str]] = {

    "doctoral": [
        "phd", "ph.d", "ph.d.", "p.h.d", "doctor of philosophy",
        "doctorate", "doctoral degree", "doctoral program",
        "d.phil", "dphil",
        "post doctoral", "post-doctoral", "post doc", "post-doc",
        "postdoctoral", "postdoc", "postdoctoral research",
        "edd", "ed.d", "doctor of education",
        "dba", "d.b.a", "doctor of business administration",
        "dsc", "d.sc", "doctor of science",
        "jd", "j.d", "juris doctor", "doctor of law",
        "md", "m.d", "doctor of medicine",
        "dds", "doctor of dental surgery",
        "pharmd", "pharm.d", "doctor of pharmacy",
        "psyd", "psy.d", "doctor of psychology",
        "dnp", "doctor of nursing practice",
        "dpt", "doctor of physical therapy",
        "drph", "doctor of public health",
        "lld", "ll.d", "doctor of laws",
        "dlit", "d.lit", "doctor of literature",
        "dmus", "doctor of music",
        "deng", "doctor of engineering",
        "dtech", "doctor of technology",
        "phd (tech)", "ph.d (engineering)",
    ],

    "master": [
        "master", "masters", "master's", "master's degree",
        "master degree", "graduate degree", "postgraduate",
        "post graduate", "postgraduate degree", "pg",
        "post graduation",
        "msc", "m.sc", "m.sc.", "ms", "m.s", "m.s.",
        "master of science", "master of applied science", "mas",
        "mres", "master of research",
        "ma", "m.a", "m.a.", "master of arts",
        "mcom", "m.com", "m.comm", "master of commerce",
        "mtech", "m.tech", "m.tech.", "master of technology",
        "me", "m.e", "m.e.", "master of engineering",
        "meng", "m.eng", "master of engineering",
        "mse", "m.s.e", "master of science in engineering",
        "mba", "m.b.a", "m.b.a.", "master of business administration",
        "pgdm", "post graduate diploma in management",
        "pgpm", "post graduate program in management",
        "emba", "executive mba", "executive master",
        "mib", "master of international business",
        "mfin", "master of finance", "msf", "master of science in finance",
        "mms", "master of management studies",
        "mim", "master of international management",
        "mca", "m.c.a", "master of computer applications",
        "mcs", "m.c.s", "master of computer science",
        "mis", "master of information systems",
        "mist", "master of information science and technology",
        "msit", "master of science in information technology",
        "mscs", "master of science in computer science",
        "msc it", "msc cs", "msc data science", "msc ai",
        "med", "m.ed", "master of education",
        "mphil", "m.phil", "m.phil.", "master of philosophy",
        "m.arch", "march", "master of architecture",
        "mdes", "m.des", "master of design",
        "mfa", "m.f.a", "master of fine arts",
        "llm", "ll.m", "master of laws",
        "mpa", "master of public administration",
        "mpp", "master of public policy",
        "mph", "master of public health",
        "mha", "master of health administration",
        "msw", "master of social work",
        "mpharm", "m.pharm", "master of pharmacy",
        "mpt", "master of physiotherapy",
        "mns", "master of nursing science",
        "mbiotech", "master of biotechnology",
        "pgd", "pg diploma", "post graduate diploma",
        "pgdba", "pgdm", "pgdca", "pgdcs", "pgdit",
        "master of", "masters in", "m. tech", "m .tech",
    ],

    "bachelor": [
        "bachelor", "bachelors", "bachelor's", "bachelor's degree",
        "bachelor degree",
        "graduation", "graduated", "graduate",
        "undergraduate", "under graduate", "ug",
        "undergraduate degree", "under graduation",
        "bsc", "b.sc", "b.sc.", "bs", "b.s", "b.s.",
        "bachelor of science", "b.sc hons", "bsc hons",
        "ba", "b.a", "b.a.", "bachelor of arts",
        "bfa", "b.f.a", "bachelor of fine arts",
        "bcom", "b.com", "b.comm", "bachelor of commerce",
        "bba", "b.b.a", "bachelor of business administration",
        "bms", "bachelor of management studies",
        "bbm", "bachelor of business management",
        "bbs", "bachelor of business studies",
        "btech", "b.tech", "b.tech.", "bachelor of technology",
        "be", "b.e", "b.e.", "bachelor of engineering",
        "beng", "b.eng", "bachelor of engineering",
        "b engineering", "bachelor of engineering",
        "b e information technology", "b.e. it", "b.tech cse",
        "b.tech ece", "b.tech eee", "b.tech mechanical",
        "b.tech civil", "b.tech chemical",
        "bca", "b.c.a", "bachelor of computer applications",
        "bcs", "b.c.s", "bachelor of computer science",
        "bit", "b.i.t", "bachelor of information technology",
        "bscit", "b.sc it", "bsc cs", "bsc computer science",
        "b.arch", "barch", "bachelor of architecture",
        "bdes", "b.des", "bachelor of design",
        "llb", "ll.b", "bachelor of laws",
        "bbl", "bachelor of business law",
        "mbbs", "m.b.b.s", "bachelor of medicine and surgery",
        "bds", "b.d.s", "bachelor of dental surgery",
        "bpharm", "b.pharm", "b pharm", "bachelor of pharmacy",
        "bpt", "b.p.t", "bachelor of physiotherapy",
        "bnys", "bachelor of naturopathy",
        "bams", "bachelor of ayurvedic medicine",
        "bhms", "bachelor of homeopathic medicine",
        "bvsc", "bachelor of veterinary science",
        "bsc nursing", "b.sc nursing", "bachelor of nursing",
        "bed", "b.ed", "bachelor of education",
        "bsw", "b.s.w", "bachelor of social work",
        "bsc agriculture", "bsc ag", "b.sc agriculture",
        "bvsc & ah",
        "bhmct", "bsc hotel management", "bht",
        "bachelor of hotel management",
        "bachelor of", "bachelors in", "b. tech", "b .tech",
        "b e", "b tech",
    ],

    "associate": [
        "associate", "associate's", "associate degree",
        "associate of arts", "aa", "a.a",
        "associate of science", "as", "a.s",
        "associate of applied science", "aas",
        "associate of business", "ab",
        "associate of engineering", "ae",
    ],

    "diploma": [
        "diploma", "diploma course",
        "polytechnic", "poly", "iti", "i.t.i",
        "industrial training", "industrial training institute",
        "d pharm", "d.pharm", "diploma in pharmacy",
        "gnm", "g.n.m", "general nursing and midwifery",
        "anm", "a.n.m", "auxiliary nurse midwife",
        "dmlt", "diploma in medical lab technology",
        "dml", "diploma in medical laboratory",
        "advanced diploma", "higher diploma",
        "pg diploma", "post graduate diploma", "pgd",
        "professional diploma",
        "dca", "d.c.a", "diploma in computer applications",
        "dcse", "diploma in computer science",
        "dit", "diploma in information technology",
        "doeacc", "nielit diploma",
        "dba diploma", "diploma in business administration",
        "dbm", "diploma in business management",
        "d.ed", "ded", "diploma in education",
        "d.el.ed", "deled", "diploma in elementary education",
        "b.ed diploma",
        "diploma in engineering", "dme", "dee", "dce", "dte",
        "diploma in mechanical", "diploma in electrical",
        "diploma in civil", "diploma in computer engineering",
        "hotel management diploma", "fashion design diploma",
        "interior design diploma", "graphic design diploma",
        "journalism diploma",
    ],

    "12th": [
        "12th", "12", "class 12", "class xii", "std 12", "std xii",
        "grade 12", "xii", "xii std", "xii grade",
        "+2", "plus two", "plus 2", "10+2",
        "intermediate", "intermediate education",
        "hsc", "h.s.c", "higher secondary certificate",
        "higher secondary", "higher secondary school certificate",
        "hssc", "higher secondary school",
        "senior secondary", "senior secondary certificate",
        "all india senior school certificate",
        "cbse 12", "icse 12", "isc",
        "puc", "p.u.c", "pre university course",
        "pre university", "puc 2", "2nd puc", "ii puc",
        "hpuc", "dpuc",
        "hs", "h.s", "higher school",
        "a levels", "a-levels", "a level", "advanced level",
        "as levels", "as-levels",
        "ib diploma", "international baccalaureate",
        "aice", "igcse advanced",
        "junior college", "jc",
    ],

    "10th": [
        "10th", "10", "class 10", "class x", "std 10", "std x",
        "grade 10", "x", "x std", "x grade",
        "ssc", "s.s.c", "secondary school certificate",
        "sslc", "s.s.l.c", "secondary school leaving certificate",
        "matric", "matriculation", "matriculate",
        "matriculation certificate",
        "high school", "high school diploma", "high school certificate",
        "secondary school", "secondary education", "secondary",
        "secondary school certificate",
        "middle school",
        "cbse 10", "icse 10", "cbse", "icse",
        "all india secondary school examination",
        "gcse", "gce o level", "o levels", "o level",
        "igcse", "cambridge igcse",
        "nhd", "national high school diploma",
        "ged", "general educational development",
    ],

    "foundation": [
        "foundation", "foundation course", "foundation year",
        "foundation degree",
        "pre degree", "pre-degree",
        "bridging course", "access course",
        "preparatory course",
        "1st puc", "i puc", "1st year pre university",
        "11th", "class 11", "class xi", "xi",
    ],

    "professional_certification": [
        "pmp", "prince2", "capm",
        "aws certified", "azure certified", "gcp certified",
        "google cloud certified", "aws solutions architect",
        "aws developer", "aws sysops", "azure administrator",
        "azure developer", "azure architect",
        "cissp", "ceh", "comptia security+", "cism", "cisa",
        "oscp", "security+",
        "ccna", "ccnp", "ccie", "network+",
        "tensorflow developer", "google data analytics",
        "ibm data science", "microsoft ai",
        "databricks certified",
        "ca", "cpa", "cfa", "acca", "cma", "frm",
        "chartered accountant", "certified public accountant",
        "shrm", "phr", "sphr",
        "google analytics", "hubspot certified", "facebook blueprint",
        "csm", "psd", "safe", "scrum master",
        "certified scrum master", "agile certified",
        "oracle certified", "sap certified",
        "cisco certified",
        "mcsa", "mcse", "mcts", "mcp",
        "itil", "itil v3", "itil 4",
    ],
}


# ── Section keywords ──────────────────────────────────────────────────────────
SECTION_KEYWORDS: dict[str, list[str]] = {

    "about": [
        "about", "about me", "about us",
        "summary", "profile summary", "professional summary", "career summary",
        "executive summary", "brief summary", "summary of qualifications",
        "summary of experience", "summary of skills", "summary statement",
        "profile", "professional profile", "personal profile", "candidate profile",
        "career profile", "job profile",
        "objective", "career objective", "professional objective", "job objective",
        "employment objective", "position objective",
        "personal statement", "professional statement", "mission statement",
        "value proposition",
        "overview", "professional overview", "career overview",
        "introduction", "professional introduction",
        "bio", "biography", "short bio", "professional bio",
        "highlights", "career highlights", "key highlights",
        "snapshot", "professional snapshot",
        "at a glance", "in brief",
        "sumary", "summery", "proffessional summary", "profesional summary",
    ],

    "experience": [
        "experience", "experiences",
        "work experience", "work experiences", "work history",
        "work summary", "work profile",
        "professional experience", "professional history",
        "professional background", "professional work experience",
        "employment", "employment history", "employment record",
        "employment background", "employment details",
        "career history", "career experience", "career background",
        "career summary", "career progression",
        "job history", "job experience", "job profile",
        "industry experience", "relevant experience", "related experience",
        "core experience", "key experience",
        "positions held", "positions of responsibility", "roles",
        "roles and responsibilities", "previous roles", "past roles",
        "consulting experience", "contract experience", "freelance experience",
        "project experience",
        "track record", "service history", "appointment history",
    ],

    "skills": [
        "skills", "skill", "skill set", "skillset",
        "technical skills", "technical skill", "technical skills & tools",
        "technical expertise", "technical knowledge", "technical proficiency",
        "technical abilities",
        "professional skills", "core skills", "key skills",
        "primary skills", "main skills", "relevant skills",
        "competencies", "core competencies", "key competencies",
        "competency profile", "areas of competence",
        "expertise", "areas of expertise", "domain expertise",
        "functional expertise", "subject matter expertise",
        "strengths", "key strengths", "core strengths", "professional strengths",
        "capabilities", "core capabilities", "key capabilities",
        "soft skills", "interpersonal skills", "people skills",
        "communication skills", "leadership skills", "management skills",
        "skills & expertise", "skills & abilities", "skills & competencies",
        "skills summary", "skill summary", "skills overview",
        "abilities", "proficiencies", "aptitudes",
        "skils", "skiils",
        
    ],
    "tools_breadth":["tools", "technical tools", "dev tools", "developer tools",
        "tools used", "tools & technologies", "tools and technologies",
        "tools & platforms", "tools & library", "tools & frameworks",
        "tools & software",
        "technologies", "technology stack", "tech stack", "tech skills",
        "frameworks", "frameworks & libraries", "libraries",
        "frameworks and libraries",
        "platforms", "cloud platforms", "cloud technologies", "cloud services",
        "cloud & devops",
        "programming languages", "coding languages", "scripting languages",
        "markup languages",
        "databases", "database skills", "data stores",
        "software", "software skills", "software tools",
        "applications", "enterprise applications",
        "apis", "integrations", "environments", "operating systems",
        "devops tools", "ci/cd tools", "infrastructure tools",
        "monitoring tools", "testing tools",
        "methodologies", "development methodologies", "agile tools",
        "version control"],

    "education": [
        "education", "educational background", "educational details",
        "educational history", "educational information",
        "academic background", "academic details", "academic history",
        "academic information", "academic profile", "academics",
        "academic credentials", "academic qualifications",
        "academic qualification",
        "qualifications", "qualification", "educational qualifications",
        "educational qualification", "education qualifications",
        "education qualification", "academic qualifications",
        "academic qualification", "professional qualifications",
        "degrees", "degree", "degrees obtained", "formal education",
        "tertiary education", "higher education", "post-secondary education",
        "schooling", "school education", "university", "college",
        "college education",
        "courses", "course", "education & training", "training & education",
        "formal training",
        "certification & education", "education & certifications",
        "credentials", "educational credentials",
        "graduation", "graduation details",
    ],

    "projects": [
        "projects", "project", "projects handled", "projects undertaken",
        "projects completed",
        "personal projects", "academic projects", "university projects",
        "college projects", "student projects", "capstone projects",
        "final year projects", "major projects", "minor projects",
        "key projects", "notable projects", "significant projects",
        "featured projects", "highlighted projects", "selected projects",
        "independent projects", "side projects", "open source projects",
        "professional projects", "industry projects", "client projects",
        "research projects", "data science projects",
        "portfolio", "portfolio projects", "works", "work samples",
        "case studies", "case study",
        "applications developed", "products built", "products developed",
        "products & api development",
        "assignments", "project assignments",
    ],

    "certifications": [
        "certifications", "certification", "certificates", "certificate",
        "professional certifications", "professional certificates",
        "industry certifications",
        "licenses", "license", "licenses & certifications",
        "certifications & licenses", "professional licenses",
        "training", "trainings", "professional training",
        "technical training", "training & development",
        "courses", "online courses", "coursework", "relevant coursework",
        "continuing education", "professional development",
        "e-learning",
        "workshops", "seminars", "webinars",
        "achievements & certifications", "certifications & achievements",
        "education & certifications", "certification & education",
        "courses & certifications",
        "badges", "accreditations", "accreditation",
        "credentials",
    ],

    "achievements": [
        "achievements", "achievement",
        "awards", "award", "awards & honors", "awards and honors",
        "honors", "honours", "honors & awards",
        "accomplishments", "accomplishment",
        "key accomplishments", "notable accomplishments",
        "recognitions", "recognition", "professional recognitions",
        "merits", "merit", "distinctions", "distinction",
        "key achievements", "career achievements", "notable achievements",
        "major achievements", "highlights & achievements",
        "scholarships", "scholarship", "fellowships", "fellowship",
        "grants", "grant",
        "rankings", "leaderboard positions", "competitive achievements",
        "milestones", "career milestones", "notable contributions",
    ],

    "personal_details": [
        "contact", "contact information", "contact details", "contact info",
        "contacts", "get in touch",
        "personal details", "personal information", "personal info",
        "personal data", "personal profile",
        "details",
        "address", "phone", "mobile", "email", "telephone",
        "date of birth", "dob", "nationality", "gender",
        "marital status", "place of birth",
        "basic information", "basic details",
        "demographic details", "candidate information",
    ],

    "profiles": [
        "linkedin", "github", "gitlab", "bitbucket", "stackoverflow",
        "stack overflow", "hackerrank", "leetcode", "codechef",
        "codeforces", "topcoder", "kaggle", "behance", "dribbble",
        "portfolio", "personal website", "website", "personal blog",
        "blog", "portfolio website",
        "online profiles", "online presence", "social profiles",
        "social media", "web profiles", "digital profiles",
        "professional profiles", "professional links",
        "links", "urls", "web links", "online links",
        "publications & links", "profiles & links",
        "github & open source",
    ],

    "internships": [
        "internship", "internships",
        "industrial training", "industrial internship",
        "summer internship", "winter internship",
        "graduate internship", "undergraduate internship",
        "co-op", "co-op experience", "cooperative education",
        "work placement", "placement", "placement training",
        "student internship",
        "apprenticeship", "apprentice",
        "trainee", "trainee experience", "traineeship",
        "practical training", "on the job training", "ojt",
        "in-plant training", "in plant training",
        "industry exposure",
    ],

    "publications": [
        "publications", "publication",
        "research", "research experience", "research work",
        "research & publications", "publications & research",
        "papers", "research papers", "white papers", "working papers",
        "journals", "journal articles", "journal papers",
        "conferences", "conference papers", "conference proceedings",
        "presentations", "posters", "poster presentations",
        "patents", "patent", "intellectual property",
        "preprints", "arxiv", "theses", "thesis", "dissertations",
        "books", "book chapters", "authored works",
        "cited works", "bibliography",
    ],

    "interests": [
        "interests", "interest",
        "hobbies", "hobby",
        "hobbies & interests", "interests & hobbies",
        "activities", "personal activities",
        "extracurricular", "extracurricular activities",
        "co-curricular", "co-curricular activities",
        "personal interests", "professional interests",
        "passions", "pastimes",
        "sports & activities", "leisure activities",
    ],

    "languages_spoken": [
        "languages", "language",
        "language proficiency", "language skills",
        "languages known", "languages spoken",
        "spoken languages", "written languages",
        "linguistic skills", "linguistic abilities",
        "foreign languages", "foreign language skills",
        "language fluency",
        "multilingual skills",
    ],

    "references": [
        "references", "reference",
        "referees", "referee",
        "professional references",
        "character references",
        "references available upon request",
        "references on request",
        "recommendations",
    ],

    "volunteer": [
        "volunteer", "volunteering", "volunteer experience",
        "volunteer work", "volunteering experience",
        "community service", "community involvement",
        "community engagement", "civic engagement",
        "social work", "social service",
        "ngo", "non-profit", "nonprofit",
        "charity work", "philanthropic work",
        "pro bono", "pro bono work",
        "outreach", "outreach activities",
    ],

    "leadership": [
        "leadership", "leadership experience", "leadership roles",
        "positions of responsibility", "responsibilities held",
        "student leadership",
        "management experience", "team leadership",
        "committee roles", "board positions",
        "executive positions", "club roles",
        "co-curricular roles", "extracurricular leadership",
        "organizational roles",
    ],

    "declaration": [
        "declaration", "i hereby declare",
        "i declare", "self-declaration",
        "declaration of authenticity",
        "undertaking",
    ],

    "training": [
        "training", "training & development", "development",
        "professional development", "learning & development",
        "l&d", "upskilling", "reskilling",
        "corporate training", "technical training programs",
        "on-the-job training",
    ],

    "military": [
        "military service", "military experience",
        "military history", "armed forces",
        "defence service", "defense service",
        "service record", "military training",
        "national service", "military background",
    ],

    "speaking": [
        "speaking", "speaking engagements", "talks",
        "guest lectures", "guest speaking",
        "conference presentations", "keynotes",
        "panel discussions", "workshops conducted",
        "webinars hosted",
    ],

    "open_source": [
        "open source", "open source contributions",
        "open source projects", "oss contributions",
        "contributions", "github contributions",
        "community contributions",
    ],

    "affiliations": [
        "affiliations", "affiliation",
        "memberships", "membership",
        "professional affiliations", "professional memberships",
        "associations", "association",
        "organizational memberships",
        "society memberships", "technical societies",
        "industry associations",
        "clubs", "club memberships",
    ],

    "portfolio": [
        "portfolio", "work samples", "work portfolio",
        "design portfolio", "creative portfolio",
        "sample work", "showcases",
        "demo projects", "live projects", "deployed projects",
    ],

    "patents": [
        "patents", "patent", "filed patents",
        "intellectual property", "ip", "inventions",
        "utility models",
    ],

    "coursework": [
        "coursework", "relevant coursework",
        "key coursework", "notable coursework",
        "graduate coursework", "undergraduate coursework",
        "related coursework", "core courses",
        "electives", "modules", "relevant modules",
    ],

    "extracurricular": [
        "extracurricular", "extracurricular activities",
        "extra curricular", "extra-curricular",
        "co-curricular activities",
        "student activities",
        "campus activities", "campus involvement",
        "club activities",
    ],

    "research_experience": [
        "research experience", "research background",
        "research interests", "research focus",
        "research areas", "research work",
        "academic research", "lab experience",
        "laboratory experience", "thesis work",
    ],

    "others": [],
}


# ── Summary sentence-splitter: protected tokens ───────────────────────────────
_SUMMARY_PROTECT: list[tuple[str, str]] = [
    ("__ASPNETCORE__",   "ASP.NET Core"),
    ("__ASPNET__",       "ASP.NET"),
    ("__ADONET__",       "ADO.NET"),
    ("__NETCORE__",      ".NET Core"),
    ("__NETFRAMEWORK__", ".NET Framework"),
    ("__NETSTANDARD__",  ".NET Standard"),
    ("__DOTNET__",       ".NET"),
    ("__NEXTJS__",       "Next.js"),
    ("__NUXTJS__",       "Nuxt.js"),
    ("__REACTJS__",      "React.js"),
    ("__VUEJS__",        "Vue.js"),
    ("__ANGULARJS__",    "AngularJS"),
    ("__EXPRESSJS__",    "Express.js"),
    ("__NESTJS__",       "Nest.js"),
    ("__REMIXJS__",      "Remix.js"),
    ("__THREEJS__",      "Three.js"),
    ("__NODEJS__",       "Node.js"),
    ("__JQUERY__",       "jQuery"),
    ("__SCIKIT__",       "scikit-learn"),
    ("__SKLEARN__",      "sklearn"),
    ("__PROF__",         "Prof."),
    ("__DR__",           "Dr."),
    ("__MRS__",          "Mrs."),
    ("__MR__",           "Mr."),
    ("__MS__",           "Ms."),
    ("__SR__",           "Sr."),
    ("__JR__",           "Jr."),
    ("__EG__",           "e.g."),
    ("__IE__",           "i.e."),
    ("__ETC__",          "etc."),
    ("__VS__",           "vs."),
    ("__NO__",           "No."),
    ("__FIG__",          "Fig."),
    ("__PP__",           "pp."),
]


# ── Real words ending with connective fragments (sentence-split guard) ────────
_REAL_WORDS_ENDING_WITH_CONNECTIVE: frozenset[str] = frozenset([
    "software", "healthcare", "hardware", "firmware", "wetware",
    "beware", "aware", "declare", "compare", "prepare", "welfare",
    "warfare", "fanfare", "daycare", "shareware", "freeware",
    "middleware", "groupware",
    "contain", "maintain", "obtain", "attain", "certain", "captain",
    "mountain", "fountain", "bargain", "terrain", "foreign", "remain",
    "explain", "sustain", "entertain", "origin", "margin",
    "begin", "basin", "cabin", "domain", "chain", "brain", "train",
    "retain", "refrain", "restrain", "constrain", "strain", "plain",
    "within",
    "information", "education", "solution", "production", "section",
    "function", "action", "question", "mention", "attention", "intention",
    "organization", "foundation", "innovation", "motivation", "direction",
    "condition", "position", "decision", "operation", "communication",
    "transformation", "optimization", "automation", "integration",
    "application", "implementation", "evaluation", "validation",
    "generation", "migration", "configuration", "demonstration",
    "python", "button", "cotton", "lesson", "reason", "season", "person",
    "icon", "silicon", "ribbon", "common", "salon",
    "analysis", "basis", "crisis", "thesis", "emphasis", "diagnosis",
    "synthesis", "hypothesis", "parenthesis",
    "combat", "format", "habitat", "acrobat",
    "understand", "demand", "expand", "command", "island",
    "highland", "lowland", "mainland", "overland", "upland",
    "therefore",
    "auto", "photo", "proto",
    "hereby", "whereby", "nearby", "standby", "lullaby",
    "perhaps",
    "systems", "platforms", "protocols", "environments", "algorithms",
    "frameworks", "databases", "containers", "microservices",
    "DevOps", "GitHub", "GitLab", "SharePoint", "WordPress",
])


_NAME_BLACKLIST = frozenset({
    # Section headings that a naive parser would grab instead of the name
    "professional", "summary", "objective", "profile", "overview",
    "experience", "education", "skills", "about", "contact", "details",
    "information", "background", "career", "personal", "resume", "cv",
    "curriculum", "vitae", "declaration", "references", "achievements",
    "certifications", "internship", "projects", "publications",
    # Titles / honorifics that appear alone on a line
    "mr", "mrs", "ms", "dr", "prof", "sir",
    # Common boilerplate
    "name", "full", "first", "last", "middle",
    "key", "core", "technical", "domain",
})
