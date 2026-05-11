from __future__ import annotations

import concurrent.futures
import hashlib
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unicodedata
import warnings
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv
import numpy as np
import pdfplumber
load_dotenv()
logger = logging.getLogger(__name__)

_MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024   # 50 MB

try:
    from cachetools import LRUCache
    _EXTRACTION_CACHE: "LRUCache[str, str] | dict[str, str]" = LRUCache(maxsize=256)
except ImportError:
    warnings.warn(
        "cachetools not installed — extraction cache is unbounded. "
        "Run: pip install cachetools",
        RuntimeWarning,
        stacklevel=1,
    )
    _EXTRACTION_CACHE = {}

_CACHE_LOCK = threading.Lock()

_IS_WINDOWS = sys.platform.startswith("win")


def _find_libreoffice_windows() -> str:
    env = os.environ.get("LIBREOFFICE_PATH", "")
    if env and Path(env).exists():
        return env
    return os.getenv('LIBREOFFICE_PATH')


if _IS_WINDOWS:
    _LIBREOFFICE_EXE = _find_libreoffice_windows()
    _TESSERACT_EXE   = os.environ.get(
        "TESSERACT_PATH",
        os.getenv('TESSERACT_PATH')
    )
else:
    _LIBREOFFICE_EXE = os.environ.get("LIBREOFFICE_PATH", "libreoffice")
    _TESSERACT_EXE   = os.environ.get("TESSERACT_PATH",   "tesseract")

# ─────────────────────────────────────────────────────────────────────────────
# Optional-dependency guards
# ─────────────────────────────────────────────────────────────────────────────

try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

try:
    from PIL import Image, ImageEnhance, ImageFilter
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

try:
    import pypdfium2 as pdfium
    PDFIUM_AVAILABLE = True
except ImportError:
    PDFIUM_AVAILABLE = False

try:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = _TESSERACT_EXE
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

_HEADING_MARKER     = "§HEADER§"
_PAGE_MARKER_RE     = re.compile(r"\[\[P:(\d+)\]\]")
Y_TOLERANCE         = 3
_MIN_CHARS_PER_PAGE = 800
_MIN_CHAR_OBJECTS   = 200
_TABLE_START        = "TABLE_START"
_TABLE_END          = "TABLE_END"

# ─────────────────────────────────────────────────────────────────────────────
# Cache helpers
# ─────────────────────────────────────────────────────────────────────────────

def _file_hash(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _cache_get(path: Path) -> Optional[str]:
    key = _file_hash(path)
    with _CACHE_LOCK:
        return _EXTRACTION_CACHE.get(key)


def _cache_set(path: Path, text: str) -> None:
    key = _file_hash(path)
    with _CACHE_LOCK:
        _EXTRACTION_CACHE[key] = text


# ─────────────────────────────────────────────────────────────────────────────
# Input validation
# ─────────────────────────────────────────────────────────────────────────────

def _validate_input_path(file_path: Path) -> None:
    if not file_path.exists():
        raise FileNotFoundError(f"Resume file not found: '{file_path}'")
    if not file_path.is_file():
        raise ValueError(f"Path is not a regular file: '{file_path}'")
    if not os.access(file_path, os.R_OK):
        raise PermissionError(f"No read permission for file: '{file_path}'")
    size = file_path.stat().st_size
    if size == 0:
        raise ValueError(f"File is empty (0 bytes): '{file_path}'")
    if size > _MAX_FILE_SIZE_BYTES:
        mb = size / (1024 * 1024)
        raise ValueError(
            f"File too large ({mb:.1f} MB); limit is "
            f"{_MAX_FILE_SIZE_BYTES // (1024*1024)} MB: '{file_path}'"
        )
    ext = file_path.suffix.lower()
    if ext not in (".pdf", ".docx", ".doc"):
        raise ValueError(f"Unsupported file type '{ext}': '{file_path}'")


# ─────────────────────────────────────────────────────────────────────────────
# Language / script detection
# ─────────────────────────────────────────────────────────────────────────────

def detect_script(text: str) -> str:
    dev = sum(1 for ch in text if "\u0900" <= ch <= "\u097F")
    tam = sum(1 for ch in text if "\u0B80" <= ch <= "\u0BFF")
    if dev > 50:
        return "devanagari"
    if tam > 50:
        return "tamil"
    return "latin"


def _ocr_lang_string(script: str) -> str:
    return {"devanagari": "eng+hin", "tamil": "eng+tam"}.get(script, "eng")


# ─────────────────────────────────────────────────────────────────────────────
# Unicode / text-cleaning
# ─────────────────────────────────────────────────────────────────────────────

_ZERO_WIDTH = {
    0x200B, 0x200C, 0x200D, 0x200E, 0x200F,
    0xFEFF, 0x00AD, 0x2028, 0x2029,
}

_BULLET_CHARS = {
    "●", "■", "▪", "▫", "►", "▸", "▶", "◆", "◇", "◉", "○", "•",
    "–", "—", "✓", "✔", "✗", "✘", "★", "☆", "→", "➤", "➢", "➣",
    "🔹", "🔸", "🔷", "🔶",
    "\u00a2", "\u00ab", "\u00ae", "\u00b7",
    "\u22c4", "\u2b25", "\u25c6",
    ">", "@", "e", "\uf0b7", "#",
}

_QUOTE_MAP = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201A": "'", "\u201B": "'",
    "\u201C": '"', "\u201D": '"', "\u201E": '"', "\u201F": '"',
    "\u2010": "-", "\u2011": "-", "\u2012": "-",
    "\u2013": "-", "\u2014": "-", "\u2015": "-",
    "\u00A0": " ",
    "\u2002": " ", "\u2003": " ", "\u2004": " ", "\u2005": " ",
    "\uFB00": "ff", "\uFB01": "fi", "\uFB02": "fl",
    "\uFB03": "ffi", "\uFB04": "ffl",
    "\u00B7": ".",
    "\u00a2": "", "\u00ab": "", "\u00ae": "",
})

_DROP_CATEGORIES = frozenset({"Cc", "Cs", "Co"})


def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    return (
        0x1F300 <= cp <= 0x1FAFF
        or 0x2600 <= cp <= 0x27BF
        or 0xFE00 <= cp <= 0xFE0F
    )


def clean_unicode(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    lines_pre = text.split("\n")
    lines_cleaned = []
    for line in lines_pre:
        stripped = line.lstrip()
        m = re.match(r"^([\u00a2\u00ab\u00ae@>#][\u00a2\u00ab\u00ae@>#\s]*)", stripped)
        if m and len(stripped) > len(m.group(0)):
            indent = line[: len(line) - len(stripped)]
            rest   = stripped[len(m.group(0)):].lstrip()
            lines_cleaned.append(indent + "- " + rest)
        else:
            lines_cleaned.append(line)
    text = "\n".join(lines_cleaned)
    out = []
    for ch in text:
        cp = ord(ch)
        if cp in _ZERO_WIDTH:
            continue
        cat = unicodedata.category(ch)
        if cat in _DROP_CATEGORIES and ch not in ("\n", "\r", "\t"):
            continue
        if _is_emoji(ch):
            continue
        out.append(ch)
    text = "".join(out).translate(_QUOTE_MAP)
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.lstrip()
        if stripped and stripped[0] in _BULLET_CHARS:
            indent = line[: len(line) - len(stripped)]
            cleaned.append(indent + "- " + stripped[1:].lstrip())
        else:
            cleaned.append(line)
    return "\n".join(cleaned)


_CID_RE    = re.compile(r"\(cid:\d+\)")
_MAILTO_RE = re.compile(r"\s*\[mailto:[^\]]*\]", re.IGNORECASE)
_HASH_RE   = re.compile(r"^#\s+")

_GARBAGED_ID_RE = re.compile(
    r"((?:SAP\s+ID|EMP(?:LOYEE)?\s*(?:ID|NO|CODE)|ID\s*[:\-])[\s:]*\d+)[^a-zA-Z0-9\s\-]*",
    re.IGNORECASE,
)

_NAME_GARBAGE_RE = re.compile(
    r"^([A-Z][A-Z\s\.']{2,60}?)\s*[.\-–|/\\]+\s*\S+.*$"
)

_EQUALS_PREFIX_RE = re.compile(r"^=(\+?\d)", re.MULTILINE)


def clean_pdf_artifacts(text: str) -> str:
    text = _CID_RE.sub(" ", text)
    text = _MAILTO_RE.sub("", text)
    text = _GARBAGED_ID_RE.sub(r"\1", text)
    text = _EQUALS_PREFIX_RE.sub(r"\1", text)
    return "\n".join(_HASH_RE.sub("", l) for l in text.split("\n"))


def _clean_name_line(text: str) -> str:
    lines = text.split("\n")
    for i, line in enumerate(lines[:5]):
        stripped = line.strip()
        if not stripped:
            continue
        m = _NAME_GARBAGE_RE.match(stripped)
        if m:
            candidate = m.group(1).strip()
            words = candidate.split()
            if len(words) >= 1 and all(w[0].isupper() or w.isupper() for w in words):
                lines[i] = line[: line.index(stripped)] + candidate
        break
    return "\n".join(lines)


_TECH_SPLIT_RE = re.compile(
    r"(?<=[a-z])(?=[A-Z][a-z])|"
    r"(?<=[a-z]{3})(?=\d{4}\b)|"
    r"(?<=\d)(?=[A-Z][a-z])",
)


def repair_compact_text(text: str) -> str:
    lines = text.split("\n")
    out = []
    for line in lines:
        stripped = line.strip()
        if (
            len(stripped) > 40
            and " " not in stripped
            and not stripped.isupper()
            and any(c.islower() for c in stripped)
            and any(c.isupper() for c in stripped)
        ):
            fixed = _TECH_SPLIT_RE.sub(" ", stripped)
            out.append(line[: len(line) - len(stripped)] + fixed)
        else:
            out.append(line)
    return "\n".join(out)


def fix_intraword_spaces(text: str, x_tol_was_high: bool = False) -> str:
    if not x_tol_was_high:
        return text

    def _fix_line(line: str) -> str:
        parts = line.split(" ")
        if len(parts) < 3:
            return line
        merged = []
        i = 0
        while i < len(parts):
            part = parts[i]
            if (
                1 <= len(part) <= 2
                and part.islower()
                and i > 0
                and i < len(parts) - 1
                and merged
                and merged[-1]
                and merged[-1][-1].islower()
                and parts[i + 1]
                and parts[i + 1][0].islower()
            ):
                merged[-1] = merged[-1] + part
            elif (
                1 <= len(part) <= 3
                and part.islower()
                and i > 0
                and merged
                and merged[-1]
                and merged[-1][-1].islower()
                and not merged[-1].endswith((".", ",", ":", ";"))
            ):
                merged[-1] = merged[-1] + part
            else:
                merged.append(part)
            i += 1
        return " ".join(merged)

    lines = text.split("\n")
    return "\n".join(_fix_line(l) for l in lines)


def detect_encoding(raw: bytes) -> str:
    if raw[:3] == b"\xef\xbb\xbf":
        return "utf-8-sig"
    if raw[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return "utf-16"
    try:
        raw.decode("utf-8")
        return "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        raw.decode("windows-1252")
        return "windows-1252"
    except UnicodeDecodeError:
        pass
    return "latin-1"


def read_text_file(path: Path) -> str:
    raw = path.read_bytes()
    return raw.decode(detect_encoding(raw), errors="replace")


# ─────────────────────────────────────────────────────────────────────────────
# Hyperlink extraction
# ─────────────────────────────────────────────────────────────────────────────

_URL_RE = re.compile(
    r"https?://[^\s\)\]\>\"\']+|"
    r"(?:www\.|linkedin\.com|github\.com|behance\.net|dribbble\.com)"
    r"[^\s\)\]\>\"\']*",
    re.IGNORECASE,
)


def extract_pdf_hyperlinks(path: Path) -> list[dict]:
    results = []
    try:
        with pdfplumber.open(path) as pdf:
            for pnum, page in enumerate(pdf.pages):
                page_width = page.width
                for link in (page.hyperlinks or []):
                    uri = link.get("uri", "") or ""
                    if not uri:
                        continue
                    lx0, ly0 = link["x0"], link["top"]
                    lx1, ly1 = link["x1"], link["bottom"]
                    link_mid_x   = (lx0 + lx1) / 2
                    page_mid     = page_width / 2
                    col_x0_bound = 0        if link_mid_x < page_mid else page_mid
                    col_x1_bound = page_mid if link_mid_x < page_mid else page_width
                    chars = [
                        c for c in page.chars
                        if lx0 - 2 <= c["x1"]
                        and c["x0"] <= lx1 + 2
                        and ly0 - 2 <= c["bottom"]
                        and c["top"] <= ly1 + 2
                        and col_x0_bound <= c["x0"] < col_x1_bound
                    ]
                    display = "".join(
                        c["text"] for c in sorted(chars, key=lambda c: c["x0"])
                    ).strip()
                    results.append({
                        "uri": uri,
                        "display_text": display or uri,
                        "page": pnum + 1,
                        "x0": lx0, "y0": ly0, "x1": lx1, "y1": ly1,
                    })
    except Exception as e:
        logger.debug("extract_pdf_hyperlinks failed for '%s': %s", path, e)
    return results


def extract_docx_hyperlinks(file_path: Path) -> list[dict]:
    results = []
    if not DOCX_AVAILABLE:
        return results
    rid_to_url: dict[str, str] = {}
    try:
        with zipfile.ZipFile(file_path) as z:
            for name in z.namelist():
                if re.match(r"word/_rels/document\.xml\.rels", name):
                    rels_xml = z.read(name).decode("utf-8", errors="replace")
                    for rid, url in re.findall(
                        r'Id="(rId\d+)"[^>]+Target="(https?://[^"]+)"', rels_xml
                    ):
                        rid_to_url[rid] = url
    except Exception as e:
        logger.debug("extract_docx_hyperlinks (rels) failed for '%s': %s", file_path, e)
    if not rid_to_url:
        return results
    try:
        with zipfile.ZipFile(file_path) as z:
            doc_xml = z.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as e:
        logger.debug("extract_docx_hyperlinks (doc_xml) failed for '%s': %s", file_path, e)
        return results
    for m in re.finditer(
        r'<w:hyperlink\b[^>]*?r:id="(rId\d+)"[^>]*?>(.*?)</w:hyperlink>',
        doc_xml,
        re.DOTALL,
    ):
        rid, inner = m.group(1), m.group(2)
        url = rid_to_url.get(rid, "")
        if not url:
            continue
        texts = re.findall(r"<w:t[^>]*>([^<]+)</w:t>", inner)
        display = "".join(texts).strip()
        results.append({"uri": url, "display_text": display or url})
    return results


def _format_links_block(links: list[dict]) -> str:
    if not links:
        return ""
    lines = ["LINKS / URLS DETECTED"]
    seen: set[str] = set()
    for lk in links:
        uri = lk["uri"]
        if uri in seen:
            continue
        seen.add(uri)
        display = lk.get("display_text", "") or ""
        if display and display.lower() != uri.lower():
            looks_garbled = (
                len(display) > 30
                and " " not in display
                and not re.match(r"^[\w\.\-@/:#]+$", display)
            )
            if not looks_garbled:
                lines.append(f"  {display}: {uri}")
            else:
                lines.append(f"  {uri}")
        else:
            lines.append(f"  {uri}")
    return "\n".join(lines)


def _inject_links_into_text(raw_text: str, links: list[dict]) -> str:
    if not links:
        return raw_text
    for lk in links:
        display = lk.get("display_text", "").strip()
        uri = lk.get("uri", "").strip()
        if not display or not uri:
            continue
        if len(display) > 30 and " " not in display and not re.match(r"^[\w\.\-@/:#]+$", display):
            continue
        pattern = re.compile(
            re.escape(display) + r"(?!\s*[\[\(]?https?://)", re.IGNORECASE
        )
        raw_text = pattern.sub(f"{display} [{uri}]", raw_text, count=1)
    return raw_text


# ─────────────────────────────────────────────────────────────────────────────
# Contact metadata extraction
# ─────────────────────────────────────────────────────────────────────────────

_EMAIL_RE     = re.compile(r"[a-zA-Z0-9_.+\-]+@[a-zA-Z0-9\-]+\.[a-zA-Z]{2,}", re.IGNORECASE)
_PHONE_RE     = re.compile(r"(?:\+?91[\s\-]?)?(?:\(?\d{3,5}\)?[\s\-]?)?\d{3,5}[\s\-]?\d{4,5}")
_LINKEDIN_RE  = re.compile(r"(?:linkedin\.com/in/|linkedin\.com/pub/)([^\s/\]\)\"\']+)", re.IGNORECASE)
_GITHUB_RE    = re.compile(r"github\.com/([^\s/\]\)\"\']+)", re.IGNORECASE)
_TWITTER_RE   = re.compile(r"(?:twitter\.com|x\.com)/([^\s/\]\)\"\']+)", re.IGNORECASE)
_NOTICE_RE    = re.compile(r"(?:notice\s+period|serving\s+notice|available\s+in|joining\s+time)[^\n]{0,80}", re.IGNORECASE)
_CTC_RE       = re.compile(r"(?:ctc|current\s+ctc|expected\s+ctc|salary|package|lpa|per\s+annum)[^\n]{0,80}", re.IGNORECASE)
_PASSPORT_RE  = re.compile(r"(?:passport\s*(?:no|number|num)?\.?\s*[:\-]\s*[A-Z]\d{7}|passport\s+available|passport\s+valid(?:ity)?[^\n]{0,60})", re.IGNORECASE)


def extract_contact_metadata(text: str) -> dict:
    emails  = list(dict.fromkeys(_EMAIL_RE.findall(text)))
    phones  = list(dict.fromkeys(
        p.strip() for p in _PHONE_RE.findall(text)
        if len(re.sub(r"\D", "", p)) >= 10
    ))
    return {
        "emails":        emails,
        "phones":        phones,
        "linkedin":      list(dict.fromkeys(_LINKEDIN_RE.findall(text))),
        "github":        list(dict.fromkeys(_GITHUB_RE.findall(text))),
        "twitter":       list(dict.fromkeys(_TWITTER_RE.findall(text))),
        "ctc_hints":     [l.strip() for l in _CTC_RE.findall(text)[:3]],
        "notice_period": [l.strip() for l in _NOTICE_RE.findall(text)[:2]],
        "passport":      [l.strip() for l in _PASSPORT_RE.findall(text)[:2]],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Section regex
# ─────────────────────────────────────────────────────────────────────────────

_SECTION_RE = re.compile(
    r"^[\s\*\-•]*("
    r"(career|professional)?\s*objective|"
    r"(professional\s+)?summ?ary|"
    r"(career|experience|profile)\s+summ?ary|"
    r"summ?ary\s+of\s+(experience|qualifications?)|"
    r"profile(\s+(summary|synopsis))?|"
    r"(professional|technical|career|usp)\s+profile|"
    r"professional\s*/\s*usp\s+summ?ary|"
    r"about\s*me|"
    r"(work|professional|working|previous|career)?\s*experience|"
    r"employment(\s+history)?|work\s+history|organization\s+details?|"
    r"(technical|technology|professional|core|soft|key|language)?\s*skills?"
    r"(\s*(and\s+strengths?|\([^)]*\)))?|"
    r"technical\s+(expertise|proficiency)|core\s+(competenc(y|ies)|skills?)|"
    r"tools?(\s+used)?|"
    r"education(\s+(qualification[s]?|details?|profile))?|"
    r"educational(\s+qualification[s]?)?|"
    r"academic(\s+(profile|credentials?|qualification[s]?))?|"
    r"academic\s+qualification[s]?|"
    r"(professional|educational|academic)\s+qualification[s]?|qualification[s]?|"
    r"certifications?(\s+(courses?|[&and]+\s+trainings?))?|training[s]?(\s+attended)?|"
    r"(key|professional)?\s*achievements?(\s+at\s+\w+)?(\s+[&and]+\s+(awards?|certificates?))?|"
    r"awards?(\s+(and\s+)?(certificates?|achievements?))?|recognitions?|strengths?|"
    r"(key|independent|major|significant)?\s*projects?(\s+(handled|highlights?|lists?|details?))?|"
    r"project\s+(highlights?|lists?|details?)|significant\s+project\s+(experience|details?|lists?)|"
    r"(key\s+)?responsibilities|roles?\s*(and|[&])\s*responsibilities|"
    r"personal(\s+(information|details?|profile|data))?|"
    r"contact(\s+(me|details?|information|profile))?|"
    r"(work\s+)?activities|internship[s']?|languages?(\s+skills?)?|"
    r"hobbies?(\s+and\s+interests?)?|area[s]?\s+of\s+interest[s]?|interests?|"
    r"declaration|references?|white\s+papers?\s*(published|authored)?|passport|"
    r"(professional\s+)?publications?|volunteering|(professional\s+)?memberships?|"
    r"salary\s+(details?|expectations?)|notice\s+period|"
    r"date\s+of\s+birth|d\.o\.b\.?|gender|nationality|marital\s+status|"
    r"current\s+location|preferred\s+location|"
    r"total\s+(experience|exp\.?)|relevant\s+(experience|exp\.?)|"
    r"domain\s+(skills?|expertise)|it\s+skills?|"
    r"extra.curricular(\s+activities)?|co.curricular(\s+activities)?"
    r")[\s:\-–]*$",
    re.IGNORECASE,
)

_DISQUALIFYING_PREFIX_RE = re.compile(
    r"^(other|my|our|your|their|main|additional|more|extra|"
    r"further|related|various|special|general|basic|advanced)\s+",
    re.IGNORECASE,
)

_SECTION_SPLIT_RE = re.compile(
    r"(?<=[a-z0-9,\)\.])"
    r"(Professional\s+(Summary|Experience)|Technical\s+Skills?|"
    r"Work\s+Experience|Key\s+Projects?|Personal\s+(Information|Details?)|"
    r"Education(\s+Details?)?|Certifications?|Skills?(\s*\([^)]*\))?|"
    r"Contact(\s+Details?)?|Declaration|Awards?(\s+and\s+Certificates?)?|"
    r"Projects?(\s+Handled)?|Internships?|Activities|Languages?)",
    re.IGNORECASE,
)

_INLINE_SECTION_RE = re.compile(
    r"(?<!\w)("
    r"Professional\s*/?\s*USP\s+Summ?ary|"
    r"Professional\s+Summ?ary|"
    r"Technical\s+Skills?|"
    r"Work\s+Experience|"
    r"Professional\s+Experience|"
    r"Key\s+Projects?|"
    r"Education(?:\s+Details?)?|"
    r"Certifications?|"
    r"Contact(?:\s+Details?)?|"
    r"Languages?(?:\s+Known)?|"
    r"Personal(?:\s+(?:Information|Details?))?|"
    r"Hobbies?\s+and\s+Interests?|"
    r"Academic\s+Profile|"
    r"Summary"
    r")(?!\w)",
    re.IGNORECASE,
)

_KNOWN_SECTIONS_MERGED = [
    "SUMMARY", "SUMARY", "OBJECTIVE", "PROFILE", "ABOUTME", "EXPERIENCE",
    "WORKEXPERIENCE", "WORKHISTORY", "EMPLOYMENT", "EDUCATION", "SKILLS",
    "TECHNICALSKILLS", "TECHNICALEXPERTISE", "CONTACT", "CONTACTPROFILE",
    "CONTACTDETAILS", "CERTIFICATIONS", "CERTIFICATION", "ACHIEVEMENTS",
    "KEYACHIEVEMENTS", "AWARDS", "RECOGNITIONS", "PROJECTS", "PROJECTSHANDLED",
    "PROJECTHIGHLIGHTS", "LANGUAGES", "DECLARATION", "ACTIVITIES", "INTERNSHIPS",
    "PERSONALDETAILS", "PERSONALINFORMATION", "PERSONALPROFILE",
    "PROFESSIONALPROFILE", "PROFILESUMMARY", "CAREEROBJECTIVE", "ACADEMICPROFILE",
    "PREVIOUSEXPERIENCE", "CORECOMPETENCIES", "STRENGTHS", "RESPONSIBILITIES",
    "ACADEMICQUALIFICATION", "ACADEMICQUALIFICATIONS",
    "WORK EXPERIENCE", "TECHNICAL SKILLS", "KEY PROJECTS",
    "PERSONAL DETAILS", "CONTACT DETAILS", "CAREER OBJECTIVE",
    "PROFESSIONAL SUMMARY", "ACADEMIC PROFILE",
]

_MERGED_HEADERS = [
    (r"\bTECHNICALSKILLS\b",         "TECHNICAL SKILLS"),
    (r"\bTECHNOLOGYSKILLS\b",        "TECHNOLOGY SKILLS"),
    (r"\bTECHNICALEXPERTISE\b",      "TECHNICAL EXPERTISE"),
    (r"\bPROJECTSHANDLED\b",         "PROJECTS HANDLED"),
    (r"\bPROJECTHIGHLIGHTS\b",       "PROJECT HIGHLIGHTS"),
    (r"\bWORKEXPERIENCE\b",          "WORK EXPERIENCE"),
    (r"\bWORKHISTORY\b",             "WORK HISTORY"),
    (r"\bPROFESSIONALEXPERIENCE\b",  "PROFESSIONAL EXPERIENCE"),
    (r"\bTECHNICALLEAD\b",           "TECHNICAL LEAD"),
    (r"\bSOFTWAREENGINEER\b",        "SOFTWARE ENGINEER"),
    (r"\bDATAANALYST\b",             "DATA ANALYST"),
    (r"\bCAREEROBJECTIVE\b",         "CAREER OBJECTIVE"),
    (r"\bPROFESSIONALSUMMARY\b",     "PROFESSIONAL SUMMARY"),
    (r"\bPROFILESUMMARY\b",          "PROFILE SUMMARY"),
    (r"\bEXPERIENCESUMMARY\b",       "EXPERIENCE SUMMARY"),
    (r"\bCONTACTPROFILE\b",          "CONTACT PROFILE"),
    (r"\bCONTACTDETAILS\b",          "CONTACT DETAILS"),
    (r"\bPERSONALDETAILS\b",         "PERSONAL DETAILS"),
    (r"\bPERSONALINFORMATION\b",     "PERSONAL INFORMATION"),
    (r"\bPERSONALPROFILE\b",         "PERSONAL PROFILE"),
    (r"\bPROFESSIONALPROFILE\b",     "PROFESSIONAL PROFILE"),
    (r"\bACADEMICPROFILE\b",         "ACADEMIC PROFILE"),
    (r"\bACADEMICQUALIFICATIONS?\b", "EDUCATION"),
    (r"\bPREVIOUSEXPERIENCE\b",      "PREVIOUS EXPERIENCE"),
    (r"\bCORECOMPETENCIES\b",        "CORE COMPETENCIES"),
    (r"\bKEYACHIEVEMENTS\b",         "KEY ACHIEVEMENTS"),
    (r"\bKEYRESPONSIBILITIES\b",     "KEY RESPONSIBILITIES"),
]

_CONTENT_DISQUALIFIER_RE = re.compile(
    r"[|@]|^\#|\b\d{4}\s*[-–]\s*(till|present|\d{4})"
    r"|(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\b.{1,25}\d{4}",
    re.IGNORECASE,
)

_TYPO_HEADERS = [
    (r"\bSUMARY\b",    "SUMMARY"),
    (r"\bSUMMARY\b",   "SUMMARY"),
    (r"\bEXPERIANCE\b","EXPERIENCE"),
    (r"\bEDUCATION QUALIFICATIONS\b", "EDUCATIONAL QUALIFICATIONS"),
    (r"\bCERTIFICATION\b", "CERTIFICATIONS"),
    (r"\bACADEMIC QUALIFICATIONS?\b", "EDUCATION"),
]


# ─────────────────────────────────────────────────────────────────────────────
# Strong-heading detector
# ─────────────────────────────────────────────────────────────────────────────

def is_strong_heading(
    line: str,
    font_size: Optional[float] = None,
    is_bold: bool = False,
    x_pos: Optional[float] = None,
    page_width: Optional[float] = None,
) -> bool:
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if font_size is not None:
        threshold = 36 if font_size > 100 else 14
        if font_size >= threshold and len(re.sub(r"[\s:\-–]+$", "", s)) <= 65:
            return True
    if is_bold:
        s_clean = re.sub(r"[\s:\-–]+$", "", s)
        if s_clean == s_clean.upper() and any(c.isalpha() for c in s_clean) and len(s_clean) <= 65:
            return True
    if is_bold and x_pos is not None and page_width is not None:
        if x_pos / page_width < 0.15 and bool(_SECTION_RE.match(s)):
            return True
    return bool(_SECTION_RE.match(s))


def _block_confidence(
    text: str,
    font_size: Optional[float] = None,
    is_bold: bool = False,
    is_heading: bool = False,
    source: str = "native",
) -> float:
    score = 0.5
    if source == "native":  score += 0.2
    elif source == "table": score += 0.1
    if is_bold:             score += 0.1
    if font_size and font_size >= 36: score += 0.05
    if is_heading:          score += 0.05
    if len(text.strip()) < 10: score -= 0.2
    return round(min(max(score, 0.0), 1.0), 2)


# ─────────────────────────────────────────────────────────────────────────────
# PDF Table extraction
# ─────────────────────────────────────────────────────────────────────────────

def _is_layout_artifact_table(table: list) -> bool:
    if not table:
        return True
    all_cells = [str(c).strip() for row in table for c in (row or []) if c]
    if not all_cells:
        return True
    if any(len(c) > 300 for c in all_cells):
        return True
    max_cols = max(len(row) for row in table if row)
    if max_cols <= 1 and len(table) <= 3:
        return True
    if max_cols <= 1 and all(len(c) <= 80 for c in all_cells):
        return True
    return False


def _extract_page_tables(page, is_two_column: bool = False) -> str:
    if is_two_column:
        return ""
    try:
        tables = page.extract_tables()
    except Exception as e:
        logger.debug("_extract_page_tables failed: %s", e)
        return ""
    if not tables:
        return ""
    parts = []
    for table in tables:
        if not table or _is_layout_artifact_table(table):
            continue
        rows = []
        for row in table:
            if row is None:
                continue
            cells = [str(c).strip() if c is not None else "" for c in row]
            if any(cells):
                rows.append(" | ".join(cells))
        if rows:
            parts.append(_TABLE_START + "\n" + "\n".join(rows) + "\n" + _TABLE_END)
    return "\n".join(parts)


_TABLE_BLOCK_RE = re.compile(r"TABLE_START\n(.*?)\nTABLE_END", re.DOTALL)


def _guess_table_type(rows: list[list[str]]) -> str:
    flat = " ".join(c.lower() for row in rows for c in row)
    if any(k in flat for k in (
        "java", "python", "sql", "html", "css", "javascript", "excel",
        "tools", "proficiency", "rating", "skill", "programming",
        "framework", "web technolog", "database", "vb.net", "asp.net",
        "react", "angular", "backend", "frontend", "cloud", "devops",
        "server", "language",
    )):
        return "skills"
    if any(k in flat for k in (
        "b.tech", "b.e.", "mba", "degree", "university", "college",
        "cgpa", "percentage", "graduation", "school", "board",
    )):
        return "education"
    if any(k in flat for k in (
        "company", "employer", "designation", "from", "to",
        "duration", "worked", "period", "responsibilities",
    )):
        return "experience"
    return "generic"


def tables_to_structured(text: str) -> tuple[str, list[dict]]:
    structured: list[dict] = []

    def _replace(m: re.Match) -> str:
        raw_rows = m.group(1).strip().split("\n")
        parsed   = [r.split(" | ") for r in raw_rows]
        ttype    = _guess_table_type(parsed)
        if len(parsed) >= 2:
            headers = [h.strip() for h in parsed[0]]
            data = [
                {headers[i]: row[i].strip() if i < len(row) else "" for i in range(len(headers))}
                for row in parsed[1:]
            ]
            structured.append({"type": ttype, "headers": headers, "data": data})
        else:
            structured.append({"type": ttype, "raw": parsed})
        lines_out = []
        for row in parsed:
            cells = [c.strip() for c in row if c.strip()]
            if cells:
                lines_out.append("  " + "  |  ".join(cells))
        return "\n".join(lines_out)

    converted = _TABLE_BLOCK_RE.sub(_replace, text)
    return converted, structured


# ─────────────────────────────────────────────────────────────────────────────
# OCR pipeline
# ─────────────────────────────────────────────────────────────────────────────

def _preprocess_for_ocr(img: "Image.Image") -> "Image.Image":
    if not PIL_AVAILABLE:
        return img
    img = img.convert("L")
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = img.filter(ImageFilter.SHARPEN)
    return img


def _ocr_image(img: "Image.Image", lang: str = "eng") -> str:
    if not TESSERACT_AVAILABLE:
        raise RuntimeError("Install pytesseract + Tesseract binary.")
    img_proc = _preprocess_for_ocr(img) if PIL_AVAILABLE else img
    text = pytesseract.image_to_string(img_proc, config=f"--oem 3 --psm 3 -l {lang}")
    if len(text.strip()) < 50:
        text = pytesseract.image_to_string(img_proc, config=f"--oem 3 --psm 6 -l {lang}")
    return text


def _render_pdf_pages(path: Path, dpi: int = 300) -> list:
    if not PDFIUM_AVAILABLE:
        raise RuntimeError("Install pypdfium2")
    if not PIL_AVAILABLE:
        raise RuntimeError("Install Pillow")
    scale = dpi / 72
    pdf = pdfium.PdfDocument(str(path))
    pages = []
    for i in range(len(pdf)):
        bitmap = pdf[i].render(scale=scale)
        pages.append(bitmap.to_pil())
    pdf.close()
    return pages


def detect_sidebar_from_rects(path: Path) -> Optional[float]:
    try:
        with pdfplumber.open(path) as pdf:
            page = pdf.pages[0]
            W, H = page.width, page.height
            sidebar_rects = [
                r for r in page.rects
                if r.get("height", 0) > H * 0.5
                and 0 < r.get("width", 0) < W * 0.5
            ]
            if sidebar_rects:
                best = max(sidebar_rects, key=lambda r: r["height"])
                return best["x1"] / W
    except Exception as e:
        logger.debug("detect_sidebar_from_rects failed for '%s': %s", path, e)
    return None


def ocr_image_based_pdf(
    path: Path,
    sidebar_frac: Optional[float] = None,
    lang: str = "eng",
) -> str:
    pages = _render_pdf_pages(path, dpi=300)
    all_text = []
    for img in pages:
        IW, IH = img.size
        if sidebar_frac:
            sp = int(IW * sidebar_frac)
            header_t = _ocr_image(img.crop((sp, 0, IW, int(IH * 0.22))), lang=lang)
            left_t   = _ocr_image(img.crop((0, int(IH * 0.26), sp, IH)), lang=lang)
            right_t  = _ocr_image(img.crop((sp, int(IH * 0.22), IW, IH)), lang=lang)
            page_t   = "\n\n".join(filter(None, [header_t.strip(), right_t.strip(), left_t.strip()]))
        else:
            page_t = _ocr_image(img, lang=lang)
        all_text.append(page_t.strip())
    return "\n\n".join(all_text)


def is_image_based_pdf(path: Path) -> bool:
    try:
        with pdfplumber.open(path) as pdf:
            total_chars  = sum(len(p.chars)  for p in pdf.pages)
            total_images = sum(len(p.images) for p in pdf.pages)
        return total_chars < 200 and (total_images > 0)
    except Exception as e:
        logger.warning("is_image_based_pdf check failed for '%s': %s", path, e)
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Hybrid native+OCR per-page extraction  (single-column path)
# ─────────────────────────────────────────────────────────────────────────────

def _extract_page_native(page, x_tol: int, is_two_column: bool = False) -> str:
    native = page.extract_text(x_tolerance=x_tol, y_tolerance=Y_TOLERANCE) or ""
    tables = _extract_page_tables(page, is_two_column=is_two_column)
    if tables:
        native = native + "\n" + tables
    return native


def _extract_single_page_with_timeout(
    path: Path,
    page_index: int,
    x_tol: int,
    is_two_column: bool = False,
    timeout: int = 30,
) -> tuple[str, int]:
    def _worker() -> str:
        with pdfplumber.open(path) as pdf:
            if page_index >= len(pdf.pages):
                return ""
            return _extract_page_native(pdf.pages[page_index], x_tol, is_two_column)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        fut = ex.submit(_worker)
        try:
            return fut.result(timeout=timeout), page_index
        except concurrent.futures.TimeoutError:
            logger.warning("Page %d timed out in '%s'", page_index + 1, path)
            return f"[PAGE {page_index + 1}: TIMEOUT]", page_index
        except Exception as e:
            logger.debug("Page %d extraction error in '%s': %s", page_index + 1, path, e)
            return f"[PAGE {page_index + 1}: ERROR {e}]", page_index


def extract_hybrid_pdf(
    path: Path,
    x_tol: int,
    lang: str = "eng",
    verbose: bool = False,
    is_two_column: bool = False,
) -> str:
    num_pages = 0
    page_char_counts: list[int] = []
    try:
        with pdfplumber.open(path) as pdf:
            num_pages = len(pdf.pages)
            page_char_counts = [len(pg.chars) for pg in pdf.pages]
    except Exception as e:
        raise RuntimeError(f"pdfplumber cannot open '{path.name}': {e}") from e

    results: list[Optional[str]] = [None] * num_pages
    max_workers = min(num_pages, max(4, os.cpu_count() or 4))

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {
            ex.submit(
                _extract_single_page_with_timeout,
                path, i, x_tol, is_two_column, 30
            ): i
            for i in range(num_pages)
        }
        for fut in concurrent.futures.as_completed(futs):
            text, idx = fut.result()
            results[idx] = text

    needs_ocr = [
        i for i, char_count in enumerate(page_char_counts)
        if char_count < _MIN_CHAR_OBJECTS
    ]

    if needs_ocr:
        if verbose:
            print(f"       hybrid OCR on {len(needs_ocr)} sparse page(s): {[i+1 for i in needs_ocr]}")
        try:
            pil_pages = _render_pdf_pages(path, dpi=300)
            for i in needs_ocr:
                if i < len(pil_pages):
                    ocr_text = _ocr_image(pil_pages[i], lang=lang)
                    if len(ocr_text.strip()) > len((results[i] or "").strip()):
                        results[i] = ocr_text
        except RuntimeError as e:
            logger.debug("OCR skipped for '%s': %s", path, e)

    page_texts = []
    for i in range(num_pages):
        page_text = results[i] or ""
        page_texts.append(f"\n{page_text}")
    return "\n".join(page_texts)


# ─────────────────────────────────────────────────────────────────────────────
# NEW v5: Row-aware two-column extractor
# Replaces the old crop-based extract_two_column() for PDFs where the left
# column contains date labels and the right column contains all content.
# Works correctly for resumes like Anuj Kumar's format where:
#   - pdfplumber's extract_text() mixes left/right columns
#   - "Responsibilities:" was getting promoted to a top-level section header
#   - Date ranges were split across two rows ("March 2022 -" / "Present")
# ─────────────────────────────────────────────────────────────────────────────

# Regex helpers for date stitching
_DATE_MONTH_RE = r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
_DATE_END_RE   = re.compile(
    rf"^(?:\d{{4}}|Present|Current|Till\s*Date|{_DATE_MONTH_RE}\w*\s+\d{{4}})$",
    re.IGNORECASE,
)
_DATE_PARTIAL_RE = re.compile(
    rf"^{_DATE_MONTH_RE}\w*\s+\d{{4}}\s*[-–]\s*$",
    re.IGNORECASE,
)
_DATE_COMPACT_RE = re.compile(
    rf"^{_DATE_MONTH_RE}\w*\s+\d{{4}}\s*[-–]{_DATE_MONTH_RE}\w*$",
    re.IGNORECASE,
)


def _auto_detect_col_boundary(path: Path, default: int = 140) -> int:
    """
    Auto-detect the x-boundary between the date column (left) and the
    content column (right).

    Strategy: scan all pages for rows where a date/year token appears at
    a small x0 and a keyword (Employer/Role/Description) appears at a
    larger x0 on the same row. The boundary is just below the maximum
    x1 of the date tokens.
    """
    _date_tok = re.compile(
        r"^(?:\d{4}|Present|Current|"
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
        r"|[-–])$",
        re.IGNORECASE,
    )
    _content_tok = re.compile(
        r"Employer|Designation|Description|Role|Responsibilities",
        re.IGNORECASE,
    )
    date_x1_vals: list[float] = []
    try:
        with pdfplumber.open(path) as pdf:
            W = pdf.pages[0].width if pdf.pages else 595.0
            for page in pdf.pages:
                words = page.extract_words(x_tolerance=3, y_tolerance=3)
                # Group by row
                rows: dict = defaultdict(list)
                for w in words:
                    rows[round(w["top"] / 3) * 3].append(w)
                for row_words in rows.values():
                    if len(row_words) < 2:
                        continue
                    sorted_words = sorted(row_words, key=lambda w: w["x0"])
                    # Left-most word(s) look like date tokens
                    left_part  = sorted_words[:3]
                    right_part = sorted_words[3:]
                    left_text  = " ".join(w["text"] for w in left_part)
                    right_text = " ".join(w["text"] for w in right_part)
                    left_toks  = left_text.split()
                    if (
                        left_toks
                        and all(_date_tok.match(t) for t in left_toks)
                        and _content_tok.search(right_text)
                    ):
                        # Boundary = max x1 of date tokens + small margin
                        boundary = max(w["x1"] for w in left_part) + 5
                        if boundary < W * 0.40:   # sanity: must be in left 40%
                            date_x1_vals.append(boundary)
    except Exception as e:
        logger.debug("_auto_detect_col_boundary failed: %s", e)
        return default

    if not date_x1_vals:
        return default
    # Use the median to be robust against outliers
    date_x1_vals.sort()
    return int(date_x1_vals[len(date_x1_vals) // 2])


def extract_row_aware_two_column(path: Path, col_boundary: Optional[int] = None) -> str:
    """
    Row-aware two-column PDF extractor.

    Algorithm:
      1. Extract all words from every page with x_tolerance=5 (merges
         close glyphs, eliminates bullet-gap double-spaces).
      2. Split words per row (round top to nearest 3px bucket).
      3. Left bucket  (x0 < col_boundary): date/year labels.
         Right bucket (x0 >= col_boundary): all content.
      4. Pass 1 — stitch split date rows:
           "March 2022 -"  + next-row-left "Present"
           "July 2019 -March" + next-row-left "2022"
      5. Pass 2 — format into clean indented text, detecting ALL-CAPS
         section headers on right-only rows.
      6. Final cleanup: collapse multi-spaces, limit blank lines,
         remove orphan blank lines inside bullet blocks.

    This fixes three issues with the old crop-based extractor:
      - "Responsibilities:" being promoted to a standalone section header
      - Date ranges split across two rows
      - Double-spaces from PDF bullet glyph gaps
    """
    if col_boundary is None:
        col_boundary = _auto_detect_col_boundary(path)

    all_rows: list[tuple[str, str]] = []

    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            # x_tolerance=5 merges closely-spaced glyphs (e.g. bullet item gaps)
            words = page.extract_words(x_tolerance=5, y_tolerance=3)
            if not words:
                continue
            rows: dict = defaultdict(lambda: {"left": [], "right": []})
            for w in words:
                key    = round(w["top"] / 3) * 3
                bucket = "left" if w["x0"] < col_boundary else "right"
                rows[key][bucket].append(w)

            for top in sorted(rows.keys()):
                r     = rows[top]
                left  = " ".join(w["text"] for w in sorted(r["left"],  key=lambda w: w["x0"])).strip()
                right = " ".join(w["text"] for w in sorted(r["right"], key=lambda w: w["x0"])).strip()
                all_rows.append((left, right))

    # ── Pass 1: stitch split date rows ───────────────────────────────────────
    stitched: list[tuple[str, str]] = []
    i = 0
    while i < len(all_rows):
        left, right = all_rows[i]

        is_partial = bool(_DATE_PARTIAL_RE.match(left))   # "March 2022 -"
        is_compact = bool(_DATE_COMPACT_RE.match(left))   # "July 2019 -March"

        if (is_partial or is_compact) and i + 1 < len(all_rows):
            nxt_left, nxt_right = all_rows[i + 1]
            if _DATE_END_RE.match(nxt_left):
                # Join date parts; ensure space after dash (e.g. "-March" → "- March")
                raw_date = left.rstrip() + " " + nxt_left
                date_str = re.sub(r"([-–])([A-Za-z])", r"\1 \2", raw_date).strip()
                # Preserve right content from current row — may already contain
                # employer text when date+employer land on the same PDF row
                # e.g. ("March 2022 -", "Current Employer: Absolutdata...") + ("Present","")
                combined_right = right or nxt_right
                stitched.append((date_str, combined_right))
                # If next row also had distinct right content, emit it separately
                if nxt_right and nxt_right != combined_right:
                    stitched.append(("", nxt_right))
                i += 2
                continue

        stitched.append((left, right))
        i += 1

    # ── Pass 2: format rows into clean text ──────────────────────────────────
    out: list[str] = []
    for left, right in stitched:
        left  = left.strip()
        right = right.strip()
        if not left and not right:
            continue

        # Collapse any residual multi-spaces (PDF glyph-gap artifact)
        left  = re.sub(r" {2,}", " ", left)
        right = re.sub(r" {2,}", " ", right)

        # Section header: right-only, ALL CAPS, <= 60 chars, no special chars/digits
        if (not left
                and right
                and right == right.upper()
                and len(right) <= 60
                and not re.search(r"[@:/\d]", right)):
            out.append("")
            out.append(right)
            continue

        if not left:
            out.append("  " + right)
        elif not right:
            out.append("  " + left)
        else:
            # Date label + content on the same row
            out.append(f"  {left}  {right}")

    # ── Pass 3: whitespace cleanup ────────────────────────────────────────────
    text = "\n".join(out)
    # Remove lines that are ONLY a bullet character (orphaned PDF bullet glyphs)
    text = re.sub(r"(?m)^[ \t]*[\uf0b7\uf0a7\u2022\u25cf\u25aa\u25ba][ \t]*$", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)              # max 1 blank line
    text = re.sub(r"\n\n(  [^A-Z\n])", r"\n\1", text)   # remove orphan blanks inside bullet blocks
    text = re.sub(r" {2,}", " ", text)                   # final multi-space collapse
    # Strip leading bullet glyph from content lines
    text = re.sub(r"(?m)^([ \t]*)([\uf0b7\uf0a7\u2022\u25cf] )", r"\1", text)
    return text.strip()


# ─────────────────────────────────────────────────────────────────────────────
# Layout detection helpers (kept for single-column path and detect_layout())
# ─────────────────────────────────────────────────────────────────────────────

def _is_word_gap_real_two_column(words: list, col_x: float) -> bool:
    rows: dict = defaultdict(lambda: {"left": [], "right": []})
    for w in words:
        row_y = round(w["top"] / 5) * 5
        if w["x0"] < col_x:
            rows[row_y]["left"].append(w)
        else:
            rows[row_y]["right"].append(w)

    both_count = continuation_count = 0
    for r in rows.values():
        if not (r["left"] and r["right"]):
            continue
        left_sorted  = sorted(r["left"],  key=lambda w: w["x0"])
        right_sorted = sorted(r["right"], key=lambda w: w["x0"])
        left_text    = " ".join(w["text"] for w in left_sorted)
        right_text   = " ".join(w["text"] for w in right_sorted)
        last_left    = left_sorted[-1]["text"]
        first_right  = right_sorted[0]["text"]
        left_is_header = (
            left_text.strip() == left_text.strip().upper()
            and len(left_text.strip()) <= 30
            and any(c.isalpha() for c in left_text)
        )
        right_is_header = (
            right_text.strip() == right_text.strip().upper()
            and len(right_text.strip()) <= 30
            and any(c.isalpha() for c in right_text)
        )
        if left_is_header and right_is_header:
            continue
        both_count += 1
        starts_lower   = bool(first_right) and first_right[0].islower()
        left_no_punct  = bool(last_left)   and last_left[-1] not in ".,:;|–—()"
        right_is_alpha = bool(first_right) and first_right[0].isalpha()
        if starts_lower or (left_no_punct and right_is_alpha):
            continuation_count += 1

    if both_count == 0:
        return True
    return (continuation_count / both_count) <= 0.35


def _detect_column_by_desert(words: list, page_width: float) -> tuple[Optional[float], int]:
    if not words:
        return None, 0
    bucket_size = 5
    n_buckets   = int(page_width / bucket_size) + 1
    buckets     = [0] * n_buckets
    for w in words:
        b = int(w["x0"] / bucket_size)
        if 0 <= b < n_buckets:
            buckets[b] += 1
    lo_limit = int(page_width * 0.20 / bucket_size)
    hi_limit = int(page_width * 0.80 / bucket_size)
    best_mid:   Optional[float] = None
    best_width: int             = 0
    start: Optional[int]        = None
    for i in range(lo_limit, hi_limit + 1):
        if buckets[i] == 0:
            if start is None:
                start = i
        else:
            if start is not None:
                width = i - start
                if width > best_width:
                    best_width = width
                    best_mid   = (start + i) / 2 * bucket_size
            start = None
    if start is not None:
        width = hi_limit - start
        if width > best_width:
            best_width = width
            best_mid   = (start + hi_limit) / 2 * bucket_size
    actual_width = best_width * bucket_size
    if actual_width >= 30 and best_mid is not None:
        return best_mid, actual_width
    return None, 0


def detect_layout(path: Path) -> tuple:
    with pdfplumber.open(path) as pdf:
        page  = pdf.pages[0]
        lines = page.lines
        rects = page.rects
        words = page.extract_words(x_tolerance=1, y_tolerance=3)
        W, H  = page.width, page.height

        horiz    = [(l["x0"], l["x1"], l["top"]) for l in lines
                    if abs(l.get("top", 0) - l.get("bottom", 0)) < 3
                    and l.get("width", 0) > 50]
        y_groups: dict = defaultdict(list)
        for x0, x1, y in horiz:
            y_groups[round(y / 5) * 5].append((x0, x1))

        for y, segs in sorted(y_groups.items()):
            if len(segs) >= 2:
                left_s  = [s for s in segs if s[0] < W / 2]
                right_s = [s for s in segs if s[1] > W / 2]
                if left_s and right_s:
                    left_end    = max(s[1] for s in left_s)
                    right_start = min(s[0] for s in right_s)
                    if right_start > left_end + 10:
                        gf = (right_start - left_end) / W
                        ll = max(s[1] - s[0] for s in left_s)
                        rl = max(s[1] - s[0] for s in right_s)
                        if gf > 0.10 or ll / (W / 2) < 0.5 or rl / (W / 2) < 0.5:
                            continue
                        col_x = (left_end + right_start) / 2
                        return col_x, float(y), "paired_hlines"

        vert    = [(l["x0"], l["top"]) for l in lines
                   if abs(l.get("x0", 0) - l.get("x1", 0)) < 2
                   and l.get("height", 0) > H * 0.50]
        sidebar = [r for r in rects
                   if r.get("height", 0) > H * 0.35
                   and 0 < r.get("width", 0) < W * 0.45]

        if vert or sidebar:
            col_x = hend = None
            if sidebar:
                best  = max(sidebar, key=lambda r: r["height"])
                col_x = best["x1"] + 5
                hend  = best["top"]
            if vert:
                vx = float(np.median([x for x, _ in vert]))
                vy = min(y for _, y in vert)
                if col_x is None or vx < col_x:
                    col_x, hend = vx, vy
            return col_x, float(hend or 0), "sidebar"

        if len(words) > 20:
            desert_mid, desert_width = _detect_column_by_desert(words, W)
            if desert_mid is not None:
                if desert_width >= 40:
                    return desert_mid, 0.0, "word_gap"
                if _is_word_gap_real_two_column(words, desert_mid):
                    return desert_mid, 0.0, "word_gap"

        if len(words) > 20:
            x0s   = np.sort(np.array([w["x0"] for w in words]))
            diffs = np.diff(x0s)
            for idx in np.argsort(diffs)[::-1][:3]:
                gap = diffs[idx]
                gm  = x0s[idx] + gap / 2
                if gap > 30 and W * 0.2 < gm < W * 0.8:
                    if _is_word_gap_real_two_column(words, gm):
                        return gm, 0.0, "word_gap"

        return None, None, "single"


def _safe_crop(page, x0, top, x1, bottom, x_tol: int = 3) -> str:
    try:
        return (
            page.crop((x0, top, x1, bottom), relative=True)
            .extract_text(x_tolerance=x_tol, y_tolerance=Y_TOLERANCE)
            or ""
        )
    except Exception as e:
        logger.debug("_safe_crop failed: %s", e)
        return ""


def _redetect_col_x(words: list, page_width: float, fallback: float) -> float:
    if len(words) < 10:
        return fallback
    x0s   = np.sort(np.array([w["x0"] for w in words]))
    diffs = np.diff(x0s)
    for idx in np.argsort(diffs)[::-1][:5]:
        gap = diffs[idx]
        gm  = x0s[idx] + gap / 2
        if gap > 25 and page_width * 0.15 < gm < page_width * 0.85:
            return gm
    return fallback


def extract_two_column(
    path: Path, col_x: float, header_end_y: float, lang: str = "eng"
) -> str:
    """
    Legacy crop-based two-column extractor.
    Used for sidebar layouts where left column is a styled sidebar panel,
    not a narrow date-label column.
    For date-label layouts (word_gap / paired_hlines where col_x < 200),
    parse_resume() calls extract_row_aware_two_column() instead.
    """
    header_parts, page1_left, page1_right = [], [], []
    subsequent_parts: list[str] = []
    x_tol = auto_x_tolerance(path)

    with pdfplumber.open(path) as pdf:
        current_col_x = col_x
        for page_num, page in enumerate(pdf.pages):
            W, H = page.width, page.height
            if page_num == 0 and header_end_y and header_end_y > 5:
                hdr_raw   = _safe_crop(page, 0, 0, W, header_end_y, x_tol)
                hdr_lines = [l for l in hdr_raw.splitlines() if not is_dual_section_artifact(l)]
                hdr_clean = "\n".join(hdr_lines).strip()
                if hdr_clean:
                    header_parts.append(f"\n{hdr_clean}")
                left  = _safe_crop(page, 0,             header_end_y, current_col_x, H, x_tol)
                right = _safe_crop(page, current_col_x, header_end_y, W,             H, x_tol)
                tbls  = _extract_page_tables(page, is_two_column=True)
                if left.strip():  page1_left.append(left.strip())
                if right.strip(): page1_right.append(right.strip())
                if tbls:          page1_right.append(tbls)
            else:
                words         = page.extract_words()
                current_col_x = _redetect_col_x(words, W, current_col_x)
                left  = _safe_crop(page, 0,             0, current_col_x, H, x_tol)
                right = _safe_crop(page, current_col_x, 0, W,             H, x_tol)
                if page_num == 0:
                    tbls = _extract_page_tables(page, is_two_column=True)
                    if left.strip():  page1_left.append(left.strip())
                    if right.strip(): page1_right.append(right.strip())
                    if tbls:          page1_right.append(tbls)
                else:
                    if len(right.strip()) < len(left.strip()) * 0.10:
                        full = _safe_crop(page, 0, 0, W, H, x_tol)
                        if full.strip():
                            subsequent_parts.append(full.strip())
                    else:
                        tbls = _extract_page_tables(page, is_two_column=True)
                        if left.strip():  subsequent_parts.append(left.strip())
                        if right.strip(): subsequent_parts.append(right.strip())
                        if tbls:          subsequent_parts.append(tbls)

    all_parts = header_parts + page1_left + page1_right + subsequent_parts
    return "\n\n".join(p for p in all_parts if p)


# ─────────────────────────────────────────────────────────────────────────────
# auto_x_tolerance (cache keyed on content hash)
# ─────────────────────────────────────────────────────────────────────────────

def _has_spaced_letter_lines(path: Path, page_num: int = 0) -> bool:
    try:
        with pdfplumber.open(path) as pdf:
            if page_num >= len(pdf.pages):
                return False
            text = pdf.pages[page_num].extract_text(x_tolerance=1, y_tolerance=3) or ""
        for line in text.split("\n")[:15]:
            if re.match(r"^[A-Za-z](\s[A-Za-z]){4,}$", line.strip()):
                return True
            if re.match(r"^([A-Z]\s){2,}[A-Z](\s{2,}([A-Z]\s)*[A-Z])?$", line.strip()):
                return True
    except Exception as e:
        logger.debug("_has_spaced_letter_lines failed for '%s': %s", path, e)
    return False


_AUTO_TOL_CACHE: dict[tuple, int] = {}


def auto_x_tolerance(path: Path, page_num: int = 0, default: int = 3) -> int:
    if _has_spaced_letter_lines(path, page_num):
        return 5

    file_hash = _file_hash(path)
    cache_key = (file_hash, page_num, default)

    cached = _AUTO_TOL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    try:
        with pdfplumber.open(path) as pdf:
            if page_num >= len(pdf.pages):
                _AUTO_TOL_CACHE[cache_key] = default
                return default
            chars = pdf.pages[page_num].chars
    except Exception as e:
        logger.debug("auto_x_tolerance failed for '%s': %s", path, e)
        _AUTO_TOL_CACHE[cache_key] = default
        return default

    if len(chars) < 50:
        _AUTO_TOL_CACHE[cache_key] = default
        return default

    chars_sorted = sorted(chars, key=lambda c: (round(c["top"] / 5) * 5, c["x0"]))
    gaps = []
    for i in range(1, len(chars_sorted)):
        c1, c2 = chars_sorted[i - 1], chars_sorted[i]
        if abs(c1["top"] - c2["top"]) < 3:
            gap = c2["x0"] - c1["x1"]
            if -2 < gap < 30:
                gaps.append(gap)
    if not gaps:
        _AUTO_TOL_CACHE[cache_key] = default
        return default

    gaps_arr = np.array(gaps)
    hist, edges = np.histogram(gaps_arr[gaps_arr < 20], bins=80)
    centers = (edges[:-1] + edges[1:]) / 2
    first_peak_idx   = int(np.argmax(hist[:40]))
    first_peak_count = hist[first_peak_idx]
    for i in range(first_peak_idx + 1, min(len(hist) - 1, 55)):
        if hist[i] <= hist[i - 1] and hist[i] <= hist[i + 1]:
            if hist[i] < first_peak_count * 0.15:
                result = int(np.clip(int(np.ceil(centers[i])), 1, 7))
                _AUTO_TOL_CACHE[cache_key] = result
                return result

    _AUTO_TOL_CACHE[cache_key] = default
    return default


# ─────────────────────────────────────────────────────────────────────────────
# Text helpers
# ─────────────────────────────────────────────────────────────────────────────

def fix_ocr_spacing(text: str) -> str:
    def _collapse(s: str) -> str:
        return re.sub(r"\b(?:[A-Z] ){2,}[A-Z]\b", lambda m: m.group(0).replace(" ", ""), s)
    return " ".join(_collapse(p) for p in re.split(r"  +", text))


def fix_merged_headers(text: str) -> str:
    for pattern, replacement in _MERGED_HEADERS:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    for pattern, replacement in _TYPO_HEADERS:
        text = re.sub(pattern, replacement, text)
    return text


def normalize(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "").replace("\t", " ")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def clean_line(line: str) -> str:
    return re.sub(r" {2,}", " ", line).strip()


def is_section_header(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 65:
        return False
    if _DISQUALIFYING_PREFIX_RE.match(s):
        return False
    if _SECTION_RE.match(s):
        return True
    if re.match(r"^([A-Z]\s){3,}[A-Z]$", s):
        return True
    return False


def is_dual_section_artifact(line: str) -> bool:
    s = line.strip()
    if re.match(r"^[A-Z](\s[A-Z])+$", s):
        merged = s.replace(" ", "")
        found = i = 0
        while i < len(merged):
            matched = False
            for sec in sorted(_KNOWN_SECTIONS_MERGED, key=len, reverse=True):
                sec_key = sec.replace(" ", "")
                if merged[i:].upper().startswith(sec_key):
                    found += 1
                    i += len(sec_key)
                    matched = True
                    break
            if not matched:
                i += 1
        return found >= 2

    words = s.upper().split()
    if 2 <= len(words) <= 4:
        known_upper = {k.upper().replace(" ", "") for k in _KNOWN_SECTIONS_MERGED}
        for split_i in range(1, len(words)):
            left_merged  = "".join(words[:split_i])
            right_merged = "".join(words[split_i:])
            if left_merged in known_upper and right_merged in known_upper:
                return True
    return False


def collapse_spaced_letters(text: str) -> str:
    def _collapse_line(line: str) -> str:
        stripped = line.strip()
        if re.match(r"^[A-Za-z](\s[A-Za-z])+$", stripped):
            word_groups = re.split(r"\s{2,}", stripped)
            collapsed = []
            for group in word_groups:
                letters = group.split()
                collapsed.append(
                    "".join(letters).upper() if all(len(l) == 1 for l in letters) else group
                )
            return " ".join(collapsed)
        if re.match(r"^([A-Z]\s)+[A-Z](\s{2,}([A-Z]\s)*[A-Z])?$", stripped):
            word_groups = re.split(r"\s{2,}", stripped)
            collapsed = []
            for group in word_groups:
                letters = group.strip().split()
                if all(len(l) == 1 for l in letters):
                    collapsed.append("".join(letters))
                else:
                    collapsed.append(group)
            return " ".join(collapsed)
        return line

    return "\n".join(_collapse_line(l) for l in text.split("\n"))


# ─────────────────────────────────────────────────────────────────────────────
# Section re-ordering
# ─────────────────────────────────────────────────────────────────────────────

_TERMINAL_SECTIONS = frozenset({
    "ACHIEVEMENTS", "KEY ACHIEVEMENTS", "AWARDS", "CERTIFICATIONS",
    "CERTIFICATION", "LANGUAGES", "HOBBIES", "DECLARATION", "REFERENCES",
    "PERSONAL DETAILS", "PERSONAL INFORMATION", "PERSONAL PROFILE",
    "ACTIVITIES", "EXTRA-CURRICULAR ACTIVITIES",
})

_EXPERIENCE_SECTIONS = frozenset({
    "EXPERIENCE", "WORK EXPERIENCE", "PROFESSIONAL EXPERIENCE",
    "EMPLOYMENT", "WORK HISTORY", "CAREER SUMMARY", "PREVIOUS EXPERIENCE",
    "PROJECTS", "KEY PROJECTS", "PROJECTS HANDLED",
})

_WH_DATE_RE = re.compile(
    r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)"
    r"[\s\.\,]+\d{4}|"
    r"\b(19|20)\d{2}\s*[-–]\s*(19|20)\d{2}\b|"
    r"\b(19|20)\d{2}\s*[-–]\s*(present|till|current)\b",
    re.IGNORECASE,
)
_WH_COMPANY_RE = re.compile(
    r"\b(pvt\.?\s*ltd\.?|limited|llc|inc\.?|corp\.?|solutions|technologies|"
    r"systems|services|consulting|group|associates|private|infotech|software|"
    r"tata|accenture|infosys|wipro|cognizant|hcl|capgemini|ibm|deloitte)\b",
    re.IGNORECASE,
)


def _looks_like_work_history(body_lines: list[str]) -> bool:
    text = " ".join(body_lines)
    return bool(_WH_DATE_RE.search(text)) and bool(_WH_COMPANY_RE.search(text))


def _split_body_at_work_history(body_lines: list[str]) -> tuple[list[str], list[str]]:
    n = len(body_lines)
    if n < 3:
        return body_lines, []
    for i in range(n):
        window = " ".join(body_lines[i:min(i + 6, n)])
        if _WH_DATE_RE.search(window) and _WH_COMPANY_RE.search(window):
            if i == 0:
                return [], body_lines
            return body_lines[:i], body_lines[i:]
    return body_lines, []


def _reorder_sections(lines: list[str]) -> list[str]:
    if not lines:
        return lines
    sections: list[dict] = []
    current_header: Optional[str] = None
    current_body:   list[str]     = []

    def _flush():
        sections.append({"header": current_header, "body": list(current_body)})

    for line in lines:
        if line and not line.startswith(" ") and is_section_header(line.strip()):
            _flush()
            current_header = line
            current_body   = []
        else:
            current_body.append(line)
    _flush()

    def _is_terminal(sec: dict) -> bool:
        h = (sec["header"] or "").strip().upper()
        return h in _TERMINAL_SECTIONS

    def _is_experience(sec: dict) -> bool:
        h = (sec["header"] or "").strip().upper()
        return h in _EXPERIENCE_SECTIONS

    first_terminal_idx = next(
        (i for i, s in enumerate(sections) if _is_terminal(s)), None
    )
    if first_terminal_idx is None:
        return lines

    misplaced_indices = [
        i for i in range(first_terminal_idx + 1, len(sections))
        if _is_experience(sections[i])
    ]
    orphaned_lines: list[str] = []
    for i in range(first_terminal_idx, len(sections)):
        sec = sections[i]
        if not _is_terminal(sec):
            continue
        body = sec["body"]
        if not _looks_like_work_history(body):
            continue
        keep, orphan = _split_body_at_work_history(body)
        if orphan:
            while orphan and orphan[0].strip() == "":
                orphan.pop(0)
            orphaned_lines.extend(orphan)
            sec["body"] = keep

    has_changes = bool(misplaced_indices) or bool(orphaned_lines)
    if not has_changes:
        return lines

    misplaced_set = set(misplaced_indices)
    last_exp_before_terminal = next(
        (i for i in range(first_terminal_idx - 1, -1, -1) if _is_experience(sections[i])),
        None,
    )
    if orphaned_lines and last_exp_before_terminal is not None:
        exp_body = sections[last_exp_before_terminal]["body"]
        while exp_body and exp_body[-1].strip() == "":
            exp_body.pop()
        exp_body.append("")
        exp_body.extend(orphaned_lines)
    elif orphaned_lines:
        sections.insert(first_terminal_idx, {
            "header": "EXPERIENCE",
            "body": orphaned_lines,
        })
        first_terminal_idx += 1
        misplaced_indices = [i + 1 for i in misplaced_indices]
        misplaced_set = set(misplaced_indices)

    before_terminal    = [s for i, s in enumerate(sections) if i < first_terminal_idx]
    terminal_and_after = [s for i, s in enumerate(sections)
                          if i >= first_terminal_idx and i not in misplaced_set]
    moved              = [sections[i] for i in misplaced_indices]
    reordered = before_terminal + moved + terminal_and_after

    out: list[str] = []
    for sec in reordered:
        if sec["header"] is not None:
            while out and out[-1] == "":
                out.pop()
            out.append("")
            out.append(sec["header"])
        for bl in sec["body"]:
            out.append(bl)

    while out and out[0] == "":
        out.pop(0)
    return out


def _fix_truncated_sublabels(lines: list[str]) -> list[str]:
    _DANGLING_AND_RE = re.compile(r"^\s*&\s+\S.*$")
    result = []
    for line in lines:
        stripped = line.strip()
        if _DANGLING_AND_RE.match(stripped) and result:
            for i in range(len(result) - 1, -1, -1):
                if result[i].strip():
                    result[i] = result[i].rstrip() + " " + stripped
                    break
            else:
                result.append(line)
        else:
            result.append(line)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# DOCX helpers
# ─────────────────────────────────────────────────────────────────────────────

def _is_heading_style(style_id: str) -> bool:
    return bool(re.match(r"Heading\d+", style_id, re.IGNORECASE))


def _get_para_style_id(child, _qn) -> str:
    ppr = child.find(_qn("w:pPr"))
    if ppr is not None:
        ps = ppr.find(_qn("w:pStyle"))
        if ps is not None:
            return ps.get(_qn("w:val"), "Normal")
    return "Normal"


def _get_para_font_size(child, _qn) -> Optional[int]:
    for run in child.iter(_qn("w:r")):
        rpr = run.find(_qn("w:rPr"))
        if rpr is not None:
            sz = rpr.find(_qn("w:sz"))
            if sz is not None:
                try:
                    return int(sz.get(_qn("w:val"), 0))
                except ValueError:
                    pass
    return None


def _is_bold_para(child, _qn) -> bool:
    for run in child.iter(_qn("w:r")):
        rpr = run.find(_qn("w:rPr"))
        if rpr is not None and rpr.find(_qn("w:b")) is not None:
            return True
    return False


def _para_char_count(child, _qn) -> int:
    return sum(len(t.text or "") for t in child.iter(_qn("w:t")))


def _has_mixed_boldness(child, _qn) -> bool:
    bold_seen = nonbold_seen = False
    for run in child.iter(_qn("w:r")):
        text = "".join(t.text or "" for t in run.iter(_qn("w:t")))
        if not text.strip():
            continue
        rpr = run.find(_qn("w:rPr"))
        is_bold = rpr is not None and rpr.find(_qn("w:b")) is not None
        if is_bold:
            bold_seen = True
        else:
            nonbold_seen = True
    return bold_seen and nonbold_seen


def _split_by_inline_sections(text: str) -> list:
    results = []
    pos = 0
    for m in _INLINE_SECTION_RE.finditer(text):
        before = text[pos:m.start()].strip()
        if before:
            results.append((before, False))
        results.append((m.group(0).strip(), True))
        pos = m.end()
    tail = text[pos:].strip()
    if tail:
        results.append((tail, False))
    return results if results else [(text.strip(), False)]


def split_blob_paragraph(child, _qn) -> list:
    runs = []
    for run in child.iter(_qn("w:r")):
        text = "".join(t.text or "" for t in run.iter(_qn("w:t")))
        if not text:
            continue
        rpr = run.find(_qn("w:rPr"))
        is_bold = rpr is not None and rpr.find(_qn("w:b")) is not None
        runs.append((text, is_bold))
    if not runs:
        return []
    merged = []
    cur_text, cur_bold = runs[0]
    for text, bold in runs[1:]:
        if bold == cur_bold:
            cur_text += text
        else:
            merged.append((cur_text, cur_bold))
            cur_text, cur_bold = text, bold
    merged.append((cur_text, cur_bold))
    fragments = []
    for chunk_text, is_bold in merged:
        for frag_text, frag_is_inline_header in _split_by_inline_sections(chunk_text):
            frag_text = frag_text.strip()
            if not frag_text:
                continue
            is_header = frag_is_inline_header or (
                is_bold
                and len(frag_text) <= 65
                and not _DISQUALIFYING_PREFIX_RE.match(frag_text)
                and bool(_SECTION_RE.match(frag_text))
                and not bool(_CONTENT_DISQUALIFIER_RE.search(frag_text))
            )
            fragments.append((frag_text, is_header))
    return fragments if fragments else [("".join(t for t, _ in merged), False)]


def extract_docx_header_text(file_path: Path) -> str:
    if not DOCX_AVAILABLE:
        return ""
    lines = []
    try:
        doc = Document(file_path)
        for section in doc.sections:
            header = section.header
            if header is None:
                continue
            for para in header.paragraphs:
                t = para.text.strip()
                if t:
                    lines.append(t)
            for table in header.tables:
                for row in table.rows:
                    for cell in row.cells:
                        t = cell.text.strip()
                        if t and t not in lines:
                            lines.append(t)
    except Exception as e:
        logger.debug("extract_docx_header_text (docx) failed for '%s': %s", file_path, e)
    if not lines:
        try:
            with zipfile.ZipFile(file_path) as z:
                for name in z.namelist():
                    if re.match(r"word/header\d+\.xml", name):
                        content = z.read(name).decode("utf-8", errors="replace")
                        for t in re.findall(r"<w:t[^>]*>([^<]+)</w:t>", content):
                            t = t.strip()
                            if t:
                                lines.append(t)
        except Exception as e:
            logger.debug("extract_docx_header_text (xml) failed for '%s': %s", file_path, e)
    return "\n".join(lines)


def _docx_table_has_borders(tbl_elem, _qn) -> bool:
    tbl_pr = tbl_elem.find(_qn("w:tblPr"))
    if tbl_pr is None:
        return False
    borders = tbl_pr.find(_qn("w:tblBorders"))
    if borders is None:
        return False
    for border in borders:
        val = border.get(_qn("w:val"), "none")
        if val.lower() not in ("none", "nil", ""):
            return True
    return False


def _docx_table_to_text(tbl_elem, _qn, has_borders: bool) -> str:
    rows_out = []
    for row in tbl_elem.findall(".//" + _qn("w:tr")):
        cell_texts = []
        seen: set[str] = set()
        for cell in row.findall(_qn("w:tc")):
            cell_content = "\n".join(
                "".join(run.text for run in para.iter(_qn("w:t")))
                for para in cell.findall(".//" + _qn("w:p"))
            ).strip()
            if cell_content and cell_content not in seen:
                cell_texts.append(cell_content)
                seen.add(cell_content)
        if cell_texts:
            rows_out.append(" | ".join(cell_texts))
    if not rows_out:
        return ""
    if has_borders:
        return _TABLE_START + "\n" + "\n".join(rows_out) + "\n" + _TABLE_END
    return "\n".join("  ".join(r.split(" | ")) for r in rows_out)


def extract_docx_text(file_path: Path) -> str:
    from docx.oxml.ns import qn as _qn

    doc  = Document(file_path)
    body = doc.element.body
    blocks: list[str] = []

    header_text = extract_docx_header_text(file_path)
    if header_text.strip():
        for line in header_text.strip().splitlines():
            line = line.strip()
            if line:
                blocks.append(line)
        blocks.append("")

    def _split_embedded_headers(text: str) -> list[str]:
        parts, last = [], 0
        for m in _SECTION_SPLIT_RE.finditer(text):
            before = text[last:m.start()].strip()
            if before:
                parts.append(before)
            last = m.start()
        parts.append(text[last:].strip())
        return [p for p in parts if p]

    for child in body:
        tag = child.tag.split("}")[-1] if "}" in child.tag else child.tag

        if tag == "p":
            text = "".join(run.text for run in child.iter(_qn("w:t")))
            if not text.strip():
                continue

            style_id   = _get_para_style_id(child, _qn)
            font_size  = _get_para_font_size(child, _qn)
            is_bold    = _is_bold_para(child, _qn)
            char_count = _para_char_count(child, _qn)

            is_blob = (
                char_count > 200
                and _has_mixed_boldness(child, _qn)
                and bool(_INLINE_SECTION_RE.search(text))
            )
            if is_blob:
                for frag_text, frag_is_header in split_blob_paragraph(child, _qn):
                    frag_text = frag_text.strip()
                    if not frag_text:
                        continue
                    prefix = _HEADING_MARKER if frag_is_header else ""
                    blocks.append(f"{prefix}{frag_text}")
                continue

            forced = _is_heading_style(style_id)

            if not forced and font_size is not None:
                t       = text.strip()
                t_clean = re.sub(r"[\s:\-–]+$", "", t)
                is_allcaps   = t_clean == t_clean.upper() and any(c.isalpha() for c in t_clean)
                large_font   = font_size >= 36
                short_enough = len(t) <= 65
                label_ending = t.endswith(":") or t.endswith(": -") or is_allcaps
                if short_enough and label_ending and (is_allcaps or large_font):
                    forced = True

            if not forced:
                forced = is_strong_heading(text, font_size=font_size, is_bold=is_bold)

            if not forced and is_bold:
                t = text.strip()
                if (
                    len(t) <= 65
                    and not bool(_CONTENT_DISQUALIFIER_RE.search(t))
                    and not bool(_DISQUALIFYING_PREFIX_RE.match(t))
                    and bool(_SECTION_RE.match(t))
                ):
                    forced = True

            for part in _split_embedded_headers(text.strip()):
                prefix = _HEADING_MARKER if forced else ""
                blocks.append(f"{prefix}{part}")

        elif tag == "tbl":
            has_borders = _docx_table_has_borders(child, _qn)
            tbl_text    = _docx_table_to_text(child, _qn, has_borders)
            if tbl_text:
                blocks.append(tbl_text)

    result = "\n".join(blocks)
    result = _EQUALS_PREFIX_RE.sub(r"\1", result)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# LibreOffice .doc conversion
# ─────────────────────────────────────────────────────────────────────────────

def _sniff_zip_office_type(path: Path) -> str:
    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            if "[Content_Types].xml" not in names:
                return "unknown_zip"
            ct = z.read("[Content_Types].xml").decode("utf-8", errors="replace")
            if "wordprocessingml.document.main" in ct:   return "docx"
            if "wordprocessingml.template"       in ct:   return "dotx"
            if "spreadsheetml.sheet.main"        in ct:   return "xlsx"
            if "presentationml.presentation.main" in ct:  return "pptx"
            if "themeManager" in ct or "theme1.xml" in ct: return "theme_only"
            if "word/document.xml" in names:              return "docx"
    except Exception as e:
        logger.debug("_sniff_zip_office_type failed for '%s': %s", path, e)
    return "unknown_zip"


def _detect_doc_type(path: Path) -> str:
    try:
        with open(path, "rb") as f:
            sig = f.read(8)
        if sig[:4] == b"PK\x03\x04":        return _sniff_zip_office_type(path)
        if sig[:2] == b"{\\":               return "rtf"
        if sig[:4] == b"\xd0\xcf\x11\xe0": return "ole2"
    except Exception as e:
        logger.debug("_detect_doc_type failed for '%s': %s", path, e)
    return "unknown"


def _extract_rtf_text(raw_bytes: bytes) -> str:
    try:
        text = raw_bytes.decode("latin-1", errors="replace")
    except Exception:
        return ""
    text = re.sub(
        r"\\'([0-9a-fA-F]{2})",
        lambda m: chr(int(m.group(1), 16)),
        text,
    )
    _SKIP_KW = {
        "pict", "object", "fldinst", "stylesheet", "fonttbl",
        "colortbl", "info", "filetbl", "rsidtbl", "themedata",
        "colorschememapping", "latentstyles",
    }
    _CTRL_RE = re.compile(r"\\([a-z]+)(-?\d+)?\s?")
    out: list[str] = []
    i = depth = 0
    skip_depth: Optional[int] = None
    while i < len(text):
        ch = text[i]
        if ch == "{":
            depth += 1
            m = _CTRL_RE.match(text, i + 1)
            if m and m.group(1) in _SKIP_KW:
                skip_depth = depth
            i += 1
        elif ch == "}":
            if skip_depth is not None and depth == skip_depth:
                skip_depth = None
            depth -= 1
            i += 1
        elif ch == "\\":
            m = _CTRL_RE.match(text, i)
            if m:
                if skip_depth is None:
                    word = m.group(1)
                    if word in ("par", "pard"): out.append("\n")
                    elif word == "line":        out.append("\n")
                    elif word == "tab":         out.append("\t")
                i += len(m.group(0))
            else:
                i += 1
        else:
            if skip_depth is None:
                out.append(ch)
            i += 1
    result = "".join(out)
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def convert_doc_to_docx(path: Path, retries: int = 2) -> tuple:
    last_detail = ""
    for attempt in range(1 + retries):
        try:
            with (
                tempfile.TemporaryDirectory() as _out_dir,
                tempfile.TemporaryDirectory() as _user_dir,
                tempfile.TemporaryDirectory() as _safe_dir,
            ):
                out_dir  = Path(_out_dir)
                user_dir = Path(_user_dir)
                safe_dir = Path(_safe_dir)
                safe_src = safe_dir / "input.doc"
                shutil.copy2(path, safe_src)
                user_uri = (
                    "file:///" + str(user_dir).replace("\\", "/")
                    if _IS_WINDOWS
                    else f"file://{user_dir}"
                )
                result = subprocess.run(
                    [
                        _LIBREOFFICE_EXE, "--headless",
                        f"-env:UserInstallation={user_uri}",
                        "--convert-to", "docx",
                        "--outdir", str(out_dir),
                        str(safe_src),
                    ],
                    capture_output=True, text=True, timeout=90,
                )
                last_detail = (result.stdout + result.stderr).strip()
                if result.returncode != 0:
                    logger.warning(
                        "LibreOffice returned non-zero (%d) for '%s': %s",
                        result.returncode, path, last_detail,
                    )
                    if attempt < retries:
                        continue
                    return None, last_detail

                docx_files = [
                    out_dir / f for f in os.listdir(out_dir)
                    if f.lower().endswith(".docx")
                ]
                if docx_files:
                    final_path = Path(tempfile.mktemp(suffix=".docx"))
                    shutil.copy2(docx_files[0], final_path)
                    return final_path, last_detail

                if attempt < retries:
                    continue

        except Exception as exc:
            last_detail = str(exc)
            logger.warning("convert_doc_to_docx attempt %d failed for '%s': %s", attempt, path, exc)
            if attempt < retries:
                continue

    return None, last_detail


# ─────────────────────────────────────────────────────────────────────────────
# Output formatting
# ─────────────────────────────────────────────────────────────────────────────

def _apply_text_cleaning(
    raw_text: str,
    links: Optional[list],
    x_tol_was_high: bool = False,
) -> str:
    raw_text = collapse_spaced_letters(raw_text)
    raw_text = fix_intraword_spaces(raw_text, x_tol_was_high)
    raw_text = repair_compact_text(raw_text)
    raw_text = _clean_name_line(raw_text)
    if links:
        raw_text = _inject_links_into_text(raw_text, links)
    raw_text = clean_pdf_artifacts(raw_text)
    raw_text = clean_unicode(raw_text)
    return raw_text


def _build_output_lines(
    text: str,
    structured_tables: Optional[list] = None,
) -> tuple[list[str], list[dict]]:
    new_tables: list[dict] = []
    text, new_tables = tables_to_structured(text)
    if structured_tables is not None:
        structured_tables.extend(new_tables)

    text = fix_ocr_spacing(text)
    text = fix_merged_headers(text)
    text = _strip_stray_section_tokens(text)
    text = normalize(text)

    out:    list[str] = []
    buf:    list[str] = []
    in_sec: bool      = False

    for raw_line in text.splitlines():
        pm = _PAGE_MARKER_RE.match(raw_line.strip())
        if pm:
            if buf and buf[-1] != "":
                buf.append("")
            continue

        line = clean_line(raw_line)
        if not line:
            if buf:
                buf.append("")
            continue

        if _STANDALONE_PAGE_NUM_RE.match(line):
            continue

        forced_header = line.startswith(_HEADING_MARKER)
        if forced_header:
            line = line[len(_HEADING_MARKER):].strip()

        if forced_header or is_section_header(line):
            if is_dual_section_artifact(line):
                continue
            out.extend(buf)
            if buf:
                out.append("")
            buf, in_sec = [], True
            header = re.sub(r"\s+", " ", line.strip()).upper()
            header = re.sub(r"[\s:\-–]+$", "", header)
            if out and out[-1] == header:
                continue
            out.append(header)
        else:
            prefix = "  " if in_sec else ""
            buf.append(f"{prefix}{line}")

    out.extend(buf)
    out = _prune_empty_sections(out)
    out = _reorder_sections(out)
    out = _fix_truncated_sublabels(out)
    return out, new_tables


def _strip_stray_section_tokens(text: str) -> str:
    lines, cleaned = text.split("\n"), []
    for line in lines:
        stripped = line.strip()
        if stripped and not is_section_header(stripped):
            line = _INLINE_SECTION_RE.sub("", line).rstrip()
        cleaned.append(line)
    return "\n".join(cleaned)


_PAGE_TAG_SUFFIX_RE     = re.compile(r"\s+\[page\s+\d+\]\s*$", re.IGNORECASE)
_STANDALONE_PAGE_NUM_RE = re.compile(r"^\s*\d{1,3}\s*$")


def _prune_empty_sections(lines: list[str]) -> list[str]:
    cleaned = [_PAGE_TAG_SUFFIX_RE.sub("", line) for line in lines]
    result: list[str] = []
    i = 0
    while i < len(cleaned):
        line = cleaned[i]
        if line and not line.startswith(" ") and is_section_header(line.strip()):
            j = i + 1
            while j < len(cleaned) and cleaned[j] == "":
                j += 1
            if j >= len(cleaned) or (
                cleaned[j]
                and not cleaned[j].startswith(" ")
                and is_section_header(cleaned[j].strip())
            ):
                i = j
                continue
        result.append(line)
        i += 1
    return result


def format_output(
    raw_text: str,
    filename: str,
    links: Optional[list] = None,
    structured_tables: Optional[list] = None,
    x_tol_was_high: bool = False,
    skip_section_formatting: bool = False,
) -> str:
    """
    Format extracted raw text into structured plain text.

    skip_section_formatting=True: used by the row-aware two-column path
    which already produces clean structured text — skips _build_output_lines()
    section-header detection to avoid re-processing already-formatted output.
    """
    raw_text = _apply_text_cleaning(raw_text, links, x_tol_was_high)

    if skip_section_formatting:
        # Light cleanup only — don't run section-header detection again
        raw_text = fix_ocr_spacing(raw_text)
        raw_text = fix_merged_headers(raw_text)
        raw_text = normalize(raw_text)
        out = raw_text.splitlines()
        if links:
            links_block = _format_links_block(links)
            if links_block:
                out.extend(["", "=" * 70, "", links_block])
        out.extend(["", "=" * 70])
        return "\n".join(out)

    out, _ = _build_output_lines(raw_text, structured_tables)

    if links:
        links_block = _format_links_block(links)
        if links_block:
            out.extend(["", "=" * 70, "", links_block])

    out.extend(["", "=" * 70])
    return "\n".join(out)


# ─────────────────────────────────────────────────────────────────────────────
# Corrupted PDF cascade (pdfium fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _try_pdfium_extract(path: Path) -> Optional[str]:
    if not PDFIUM_AVAILABLE:
        return None
    try:
        pdf = pdfium.PdfDocument(str(path))
        pages_text = []
        for i in range(len(pdf)):
            page    = pdf[i]
            textobj = page.get_textpage()
            pages_text.append(textobj.get_text_range())
        pdf.close()
        result = "\n".join(pages_text)
        return result if len(result.strip()) > 50 else None
    except Exception as e:
        logger.debug("_try_pdfium_extract failed for '%s': %s", path, e)
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Helper: detect if this is a "date-label" two-column layout
# (narrow left col ≤ 200px wide used only for date labels)
# vs a "content" two-column layout (wide sidebar with real content)
# ─────────────────────────────────────────────────────────────────────────────

def _is_date_label_layout(col_x: Optional[float], page_width: float = 595.0) -> bool:
    """
    Returns True when the detected column boundary suggests the left column
    is a narrow date-label strip (col_x <= 25% of page width).
    These layouts must use extract_row_aware_two_column() because crop-based
    extraction merges the date into the content text incorrectly.
    """
    if col_x is None:
        return False
    return col_x <= page_width * 0.25


def _probe_date_label_layout(path: Path, page_width: float = 595.0) -> bool:
    """
    Secondary detector: scan the first page for the hallmark of a date-label
    layout — rows where the left column (x0 < 25% of page width) contains
    only date/year tokens and the right column contains employer/role content.

    This fires when detect_layout() returns "single" but the PDF is actually
    a date-label two-column layout (e.g. Anuj Kumar format where pdfplumber's
    word-gap detector misses the narrow column because the gap is < 30px).
    """
    threshold_x = page_width * 0.26   # left col boundary probe
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return False
            # Scan ALL pages — experience section may not be on page 1
            all_words: list = []
            for page in pdf.pages:
                all_words.extend(page.extract_words(x_tolerance=3, y_tolerance=3))
    except Exception as e:
        logger.debug("_probe_date_label_layout failed: %s", e)
        return False

    if not all_words:
        return False

    # Group words by row
    rows: dict = defaultdict(lambda: {"left": [], "right": []})
    for w in all_words:
        key = round(w["top"] / 3) * 3
        if w["x0"] < threshold_x:
            rows[key]["left"].append(w)
        else:
            rows[key]["right"].append(w)

    date_label_rows = 0
    checked_rows    = 0

    _date_token = re.compile(
        r"^(?:\d{4}|Present|Current|"
        r"Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|"
        r"Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|"
        r"Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?"
        r"|-|–)$",
        re.IGNORECASE,
    )
    _employer_token = re.compile(
        r"Employer|Designation|Description|Role|Responsibilities",
        re.IGNORECASE,
    )

    for top in sorted(rows.keys()):
        r = rows[top]
        if not r["left"] or not r["right"]:
            continue
        checked_rows += 1
        left_text  = " ".join(w["text"] for w in r["left"])
        right_text = " ".join(w["text"] for w in r["right"])
        # Left col contains only date tokens; right col has employer-style content
        left_tokens = left_text.split()
        if (
            left_tokens
            and all(_date_token.match(t) for t in left_tokens)
            and _employer_token.search(right_text)
        ):
            date_label_rows += 1

    if checked_rows == 0:
        return False
    # Even 1 confirmed date-label row is sufficient to route correctly
    return date_label_rows >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point  —  v5
# ─────────────────────────────────────────────────────────────────────────────

def parse_resume(
    file_path: Path,
    verbose: bool = True,
) -> str:
    """
    Parse a resume file and return formatted plain-text content.
    Supports: .pdf, .docx, .doc

    v5 changes vs v4.1
    ──────────────────
    NEW  extract_row_aware_two_column() — row-by-row word-grouping extractor
         for PDFs where the left column is a narrow date-label strip.
         Fixes three v4.1 bugs for this layout type:
           1. "Responsibilities:" promoted to standalone section header
           2. Date ranges split across two rows (e.g. "March 2022 -" / "Present")
           3. Double-spaces from PDF bullet glyph gaps
    NEW  _auto_detect_col_boundary() — auto-detects the x-boundary for
         date-label layouts instead of relying on detect_layout()'s col_x.
    NEW  _is_date_label_layout() — routing helper: sends narrow-left-col PDFs
         to the new extractor, wide-sidebar PDFs to the existing crop extractor.
    NEW  format_output(skip_section_formatting=True) — skips section-header
         re-detection for already-structured row-aware output.

    HIGH issues (H-01 to H-05) from v4.1 remain resolved.
    """
    _validate_input_path(file_path)

    ext = file_path.suffix.lower()

    cached = _cache_get(file_path)
    if cached is not None:
        if verbose:
            print(f"[cache hit] {file_path.name}")
        return cached

    if verbose:
        print(f"\n{'─'*60}")
        print(f"File : {file_path.name}")

    raw: str = ""
    links: list = []
    structured_tables: list = []
    script: str = "latin"
    x_tol_was_high: bool = False
    converted: Optional[Path] = None
    # Flag: True when raw text came from extract_row_aware_two_column()
    # so format_output() skips redundant section-header re-detection.
    row_aware_output: bool = False

    # ── PDF ──────────────────────────────────────────────────────────────────
    if ext == ".pdf":
        links = extract_pdf_hyperlinks(file_path)
        if verbose and links:
            print(f"Links: {len(links)} hyperlink(s) found")

        try:
            with pdfplumber.open(file_path) as pdf:
                probe  = pdf.pages[0].extract_text() or "" if pdf.pages else ""
                script = detect_script(probe)
                page_width = pdf.pages[0].width if pdf.pages else 595.0
        except Exception as e:
            logger.debug("Script detection failed for '%s': %s", file_path, e)
            page_width = 595.0

        lang = _ocr_lang_string(script)
        if verbose and script != "latin":
            print(f"Script: {script} → OCR lang={lang}")

        if is_image_based_pdf(file_path):
            if verbose:
                print("Type : image-based PDF → full OCR")
            sidebar_frac = detect_sidebar_from_rects(file_path)
            raw          = ocr_image_based_pdf(file_path, sidebar_frac, lang=lang)
        else:
            col_x, header_end_y, layout = detect_layout(file_path)
            x_tol = auto_x_tolerance(file_path)
            x_tol_was_high = x_tol >= 5

            if verbose:
                cx = int(col_x) if col_x else "—"
                print(f"Type : native-text PDF  layout={layout}  col_x={cx}")
                print(f"       x_tolerance={x_tol} (auto)  [hybrid mode]")

            if layout == "single":
                # Check if pdfplumber missed a narrow date-label column
                if _probe_date_label_layout(file_path, page_width):
                    if verbose:
                        print(f"       → row-aware two-column extractor (date-label probe hit)")
                    raw = extract_row_aware_two_column(file_path)
                    row_aware_output = True
                else:
                    raw = extract_hybrid_pdf(
                        file_path, x_tol, lang=lang,
                        verbose=verbose, is_two_column=False,
                    )
            elif _is_date_label_layout(col_x, page_width):
                # ── NEW v5 path: narrow date-label left column ──────────────
                if verbose:
                    print(f"       → row-aware two-column extractor (date-label layout)")
                raw = extract_row_aware_two_column(file_path)
                row_aware_output = True
            else:
                # ── Legacy path: wide sidebar / content column ──────────────
                raw = extract_two_column(
                    file_path, col_x, header_end_y, lang=lang
                )

            if len(raw.strip()) < 80:
                if verbose:
                    print("       text too short → trying pdfium...")
                pdfium_text = _try_pdfium_extract(file_path)
                if pdfium_text and len(pdfium_text.strip()) >= 80:
                    raw = pdfium_text
                    row_aware_output = False   # pdfium output needs full formatting
                else:
                    if verbose:
                        print("       pdfium empty → full OCR")
                    sidebar_frac = detect_sidebar_from_rects(file_path)
                    raw          = ocr_image_based_pdf(file_path, sidebar_frac, lang=lang)
                    row_aware_output = False

    # ── DOCX ─────────────────────────────────────────────────────────────────
    elif ext == ".docx":
        if not DOCX_AVAILABLE:
            raise RuntimeError("Install python-docx: pip install python-docx")
        if verbose:
            print("Type : DOCX")
        links = extract_docx_hyperlinks(file_path)
        raw   = extract_docx_text(file_path)
        if verbose and links:
            print(f"Links: {len(links)} hyperlink(s) found")

    # ── DOC ──────────────────────────────────────────────────────────────────
    elif ext == ".doc":
        if not DOCX_AVAILABLE:
            raise RuntimeError("Install python-docx: pip install python-docx")

        doc_type = _detect_doc_type(file_path)

        if doc_type in ("docx", "dotx"):
            if verbose:
                print(f"Type : DOC (is actually {doc_type.upper()}) → direct parse")
            try:
                raw   = extract_docx_text(file_path)
                links = extract_docx_hyperlinks(file_path)
            except Exception as e:
                logger.warning(
                    "Direct DOCX parse failed for '%s': %s — trying LibreOffice",
                    file_path, e,
                )
                if verbose:
                    print(f"       python-docx failed ({e}) → LibreOffice...")
                doc_type = "ole2"

        if doc_type == "rtf":
            if verbose:
                print("Type : DOC (RTF) → native extraction")
            raw = _extract_rtf_text(file_path.read_bytes())
            if not raw.strip():
                if verbose:
                    print("       RTF empty → LibreOffice...")
                doc_type = "ole2"

        if doc_type not in ("docx", "dotx", "rtf") or (doc_type == "rtf" and not raw.strip()):
            if verbose:
                print(f"Type : DOC ({doc_type}) → LibreOffice conversion")
            converted, lo_detail = convert_doc_to_docx(file_path)
            if converted:
                try:
                    raw   = extract_docx_text(converted)
                    links = extract_docx_hyperlinks(converted)
                    if verbose:
                        print(f"       converted → {converted.name}")
                except Exception as conv_err:
                    raise RuntimeError(
                        f"Could not parse converted DOCX from '{file_path.name}': {conv_err}"
                    ) from conv_err
            else:
                detail = f" LibreOffice output: {lo_detail}" if lo_detail else ""
                raise RuntimeError(
                    f"Could not parse '{file_path.name}' (format: {doc_type}). "
                    "LibreOffice conversion failed." + detail
                )

    try:
        if not raw.strip():
            raise ValueError(f"No text could be extracted from '{file_path.name}'")

        if verbose:
            print(f"Chars: {len(raw):,}")

        result_text = format_output(
            raw,
            file_path.name,
            links,
            structured_tables,
            x_tol_was_high=x_tol_was_high,
            skip_section_formatting=row_aware_output,   # NEW v5
        )
        _cache_set(file_path, result_text)
        return result_text

    finally:
        if converted is not None and converted.exists():
            try:
                converted.unlink()
            except Exception as e:
                logger.debug(
                    "Could not delete temp converted file '%s': %s", converted, e
                )


# ─────────────────────────────────────────────────────────────────────────────
# Diagnosis utility
# ─────────────────────────────────────────────────────────────────────────────

def diagnose_setup() -> None:
    import shutil as _shutil
    sep = "─" * 60
    print(sep)
    print("Resume Parser")
    print(sep)
    print(f"\nPlatform : {sys.platform}")
    print(f"Python   : {sys.version.split()[0]}")
    print(f"\nLibreOffice: {_LIBREOFFICE_EXE}")
    lo_exists = (
        Path(_LIBREOFFICE_EXE).exists()
        if _IS_WINDOWS
        else bool(_shutil.which(_LIBREOFFICE_EXE))
    )
    print(f"  Exists   : {lo_exists}")
    if lo_exists:
        try:
            r = subprocess.run(
                [_LIBREOFFICE_EXE, "--version"],
                capture_output=True, text=True, timeout=15,
            )
            print(f"  Version  : {r.stdout.strip() or r.stderr.strip()}")
        except Exception as e:
            print(f"  Version  : ERROR — {e}")
    print(f"\nTesseract  : {_TESSERACT_EXE}")
    tess_exists = (
        Path(_TESSERACT_EXE).exists()
        if _IS_WINDOWS
        else bool(_shutil.which(_TESSERACT_EXE))
    )
    print(f"  Exists   : {tess_exists}")
    if tess_exists:
        try:
            r = subprocess.run(
                [_TESSERACT_EXE, "--version"],
                capture_output=True, text=True, timeout=10,
            )
            ver = (r.stdout + r.stderr).splitlines()
            print(f"  Version  : {ver[0] if ver else 'unknown'}")
        except Exception as e:
            print(f"  Version  : ERROR — {e}")
    print(f"\nMax file size : {_MAX_FILE_SIZE_BYTES // (1024*1024)} MB")
    print("\nPython packages:")
    for pkg in ("pdfplumber", "docx", "PIL", "pypdfium2", "pytesseract", "numpy", "cachetools"):
        try:
            import importlib
            importlib.import_module(pkg)
            print(f"  {pkg:<15}: OK")
        except ImportError:
            print(f"  {pkg:<15}: NOT INSTALLED")
    print(f"\n{sep}")


# ─────────────────────────────────────────────────────────────────────────────
# Batch runner
# ─────────────────────────────────────────────────────────────────────────────

def main(
    resume_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None,
) -> dict:
    resume_dir = resume_dir or Path("pdf_file")
    output_dir = output_dir or Path("text_raw")
    output_dir.mkdir(exist_ok=True)

    ok = errors = 0
    error_files: list[str] = []
    results: list[dict] = []

    for file in sorted(resume_dir.glob("*.*")):
        if file.name.startswith("~"):
            continue
        if file.suffix.lower() not in (".pdf", ".docx", ".doc"):
            continue
        status = "OK"
        note   = ""
        try:
            text     = parse_resume(file)
            out_file = output_dir / f"{file.stem}_raw.txt"
            out_file.write_text(text, encoding="utf-8", newline="\n")
            ok += 1
            lines = [l for l in text.splitlines() if l.strip()]
            note = f"{len(lines)} lines, {len(text)} chars"
        except Exception as e:
            logger.error("ERROR [%s]: %s", file.name, e)
            print(f"  ERROR [{file.name}]: {e}")
            status = "ERROR"
            note   = str(e)
            errors += 1
            error_files.append(file.name)
        results.append({"file": file.name, "status": status, "note": note})

    print(f"\n{'─'*60}")
    print(f"Done: {ok} parsed, {errors} errors")
    if error_files:
        print(f"Error files: {error_files}")
    return {"ok": ok, "errors": errors, "error_files": error_files, "results": results}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(levelname)s [%(name)s] %(message)s",
    )
    if len(sys.argv) > 1 and sys.argv[1] == "--diagnose":
        diagnose_setup()
    else:
        main()