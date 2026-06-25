"""
Daily News Briefing App
Streamlit application that fetches RSS feeds from premium sources,
filters for India and frontier‑tech topics, and tries to retrieve full
article text using multiple extraction methods: bpc‑fetch, newspaper3k,
trafilatura, with fallback to RSS summary.
"""

import streamlit as st
import feedparser
import requests
import subprocess
import shutil
import time
import logging
import io
import base64
import re
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from fpdf import FPDF
from email.utils import parsedate_to_datetime

# Optional imports with graceful handling
try:
    from newspaper import Article
    HAS_NEWSPAPER = True
except ImportError:
    HAS_NEWSPAPER = False

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False

# ------------------------------
# Logging configuration
# ------------------------------
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ------------------------------
# Constants
# ------------------------------
# Keywords for filtering – split into India indicators and tech keywords
# Expanded to capture new manufacturing corridors, critical conglomerates, and policy frameworks
INDIA_KEYWORDS = [
    "india", "indian", "delhi", "mumbai", "bengaluru", "bangalore", "hyderabad", 
    "chennai", "assam", "gujarat", "dholera", "tata", "reliance", "jio", 
    "pli scheme", "meity", "india semiconductor mission", "ism"
]

# Categorized to catch specific hardware constraints, cutting-edge software paradigms, and regulatory traps
TECH_KEYWORDS = [
    # Frontier AI Execution & Software Shifts
    "ai", "artificial intelligence", "vibecoding", "vibe-coding", "ai agent", 
    "token-based billing", "token consumption", "compute cost", "frontier model",
    
    # The Semiconductor Crunch & Advanced Hardware Architecture
    "semiconductor", "chip", "osat", "advanced packaging", "foundry", "fab", 
    "dram", "nand flash", "hbm", "high-bandwidth memory", "1-nm", "2-nm", "logic chip",
    
    # Tech Supply Chain Equipment & Advanced Materials
    "electronics", "electrostatic chuck", "ceramics coating", "additive manufacturing", 
    "3d printed battery", "solid-state battery", "quantum", "biotech", "space",
    
    # Geopolitical Friction & Tech Regulation
    "export control", "bis", "bureau of industry and security", "deemed export", 
    "technology transfer", "technological sovereignty", "jailbreak risk"
]

# RSS feeds – premium sources with working feeds for India and tech news
SOURCES = [
    {
        "name": "The Wall Street Journal",
        "feed_url": "https://feeds.a.dj.com/rss/RSSWorldNews.xml"
    },
    {
        "name": "Financial Times",
        "feed_url": "https://www.ft.com/?format=rss"
    },
    {
        "name": "Bloomberg",
        "feed_url": "https://feeds.bloomberg.com/markets/news.rss"
    },
    {
        "name": "Nikkei Asia",
        "feed_url": "https://asia.nikkei.com/rss/feed/nar"
    }
]

# Timeout settings (seconds)
REQUEST_TIMEOUT = 15
BPC_FETCH_TIMEOUT = 30

# ------------------------------
# Helper functions
# ------------------------------
def is_bpc_fetch_available() -> bool:
    """Return True if bpc‑fetch is installed and reachable."""
    return shutil.which("bpc-fetch") is not None

def fetch_feed(source: Dict) -> List[Dict]:
    """
    Fetch and parse an RSS feed.
    Returns a list of article dicts with keys: title, link, summary, published, published_parsed.
    If the feed fails, returns an empty list.
    """
    articles = []
    try:
        response = requests.get(source["feed_url"], timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        feed = feedparser.parse(response.content)
        for entry in feed.entries:
            # Extract summary (fallback to description if available)
            summary = entry.get("summary", entry.get("description", ""))
            # Clean HTML tags from summary (basic)
            summary = re.sub(r"<[^>]+>", "", summary)
            
            # Extract published date in multiple formats
            published_str = entry.get("published", entry.get("pubDate", ""))
            published_parsed = entry.get("published_parsed", None)
            
            articles.append({
                "title": entry.get("title", "No title"),
                "link": entry.get("link", ""),
                "summary": summary,
                "published": published_str,
                "published_parsed": published_parsed,
                "source": source["name"]
            })
    except Exception as e:
        st.warning(f"Could not fetch feed from {source['name']}: {e}")
        logger.warning(f"Feed error for {source['name']}: {e}")
    return articles

def filter_articles(articles: List[Dict]) -> List[Dict]:
    """
    Keep only articles that match BOTH criteria:
    1. Must contain at least one India indicator (india, indian, city names, etc.)
    2. Must contain at least one tech keyword (AI, semiconductor, cybersecurity, etc.)
    Returns filtered list.
    """
    filtered = []
    for art in articles:
        text = (art["title"] + " " + art["summary"]).lower()
        
        # Check for India keyword (OR logic within India indicators)
        has_india = any(kw in text for kw in INDIA_KEYWORDS)
        
        # Check for tech keyword (OR logic within tech keywords)
        has_tech = any(kw in text for kw in TECH_KEYWORDS)
        
        # Include only if BOTH conditions are met
        if has_india and has_tech:
            filtered.append(art)
    
    return filtered

def get_full_text_via_bpc(url: str) -> Optional[str]:
    """
    Attempt to retrieve the full article text using bpc‑fetch.
    Returns the text if successful, else None.
    Includes one retry on failure.
    """
    if not is_bpc_fetch_available():
        return None
    for attempt in range(2):  # try once, then retry once
        try:
            result = subprocess.run(
                ["bpc-fetch", url],
                capture_output=True,
                text=True,
                timeout=BPC_FETCH_TIMEOUT
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f"✅ bpc-fetch succeeded for {url}")
                return result.stdout.strip()
            else:
                # If stdout is empty or error, wait before retry
                if attempt == 0:
                    time.sleep(2)
        except subprocess.TimeoutExpired:
            logger.warning(f"bpc‑fetch timeout for {url}")
            if attempt == 0:
                time.sleep(2)
        except Exception as e:
            logger.warning(f"bpc‑fetch error for {url}: {e}")
            if attempt == 0:
                time.sleep(2)
    return None

def get_full_text_via_newspaper(url: str) -> Optional[str]:
    """
    Attempt to retrieve the full article text using newspaper3k.
    Returns the text if successful, else None.
    """
    if not HAS_NEWSPAPER:
        logger.debug("newspaper3k not installed, skipping")
        return None
    
    try:
        article = Article(url)
        article.download()
        article.parse()
        
        if article.text and len(article.text.strip()) > 50:
            logger.info(f"✅ newspaper3k succeeded for {url}")
            return article.text
    except Exception as e:
        logger.warning(f"newspaper3k error for {url}: {e}")
    
    return None

def get_full_text_via_trafilatura(url: str) -> Optional[str]:
    """
    Attempt to retrieve the full article text using trafilatura.
    Returns the text if successful, else None.
    """
    if not HAS_TRAFILATURA:
        logger.debug("trafilatura not installed, skipping")
        return None
    
    try:
        downloaded = trafilatura.fetch_url(url)
        if downloaded:
            extracted = trafilatura.extract(downloaded)
            if extracted and len(extracted.strip()) > 50:
                logger.info(f"✅ trafilatura succeeded for {url}")
                return extracted
    except Exception as e:
        logger.warning(f"trafilatura error for {url}: {e}")
    
    return None


def get_article_content(article: Dict) -> Tuple[str, bool, str]:
    """
    Attempt to get full article text with fallback chain:
    1. bpc‑fetch
    2. newspaper3k
    3. trafilatura
    4. RSS summary
    
    Returns (content, is_full_text, extraction_method) where:
    - is_full_text: True if full article was extracted
    - extraction_method: String indicating which method succeeded
    """
    url = article.get("link")
    if not url:
        # No link, fallback to summary
        summary = article.get("summary", article["title"])
        return summary, False, "Summary (no URL)"
    
    # Chain 1: bpc‑fetch
    full_text = get_full_text_via_bpc(url)
    if full_text:
        return full_text, True, "bpc-fetch"
    
    # Chain 2: newspaper3k
    full_text = get_full_text_via_newspaper(url)
    if full_text:
        return full_text, True, "newspaper3k"
    
    # Chain 3: trafilatura
    full_text = get_full_text_via_trafilatura(url)
    if full_text:
        return full_text, True, "trafilatura"
    
    # Chain 4: RSS summary (fallback)
    summary = article.get("summary")
    if summary:
        logger.info(f"Falling back to RSS summary for {url}")
        return summary, False, "RSS Summary"
    
    # Last resort: just title
    return f"{article['title']}\n(Full text not available.)", False, "Title only"

def parse_article_date(article: Dict) -> Optional[datetime]:
    """
    Parse the article's publish date.
    Tries published_parsed (feedparser native format) first,
    then falls back to parsing the published string.
    Returns datetime or None if unparseable.
    """
    # Try the parsed version first (most reliable)
    if article.get("published_parsed"):
        try:
            return datetime(*article["published_parsed"][:6])
        except Exception as e:
            logger.debug(f"Could not parse published_parsed: {e}")
    
    # Try parsing the string version
    published_str = article.get("published", "")
    if published_str:
        try:
            return parsedate_to_datetime(published_str)
        except Exception as e:
            logger.debug(f"Could not parse published string '{published_str}': {e}")
    
    return None

def filter_articles_by_date(articles: List[Dict], days_back: int) -> List[Dict]:
    """
    Filter articles to include only those published within the last N days.
    days_back=0 means today only, days_back=7 means last 7 days, etc.
    """
    if days_back == 0:
        # Today only
        cutoff_date = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        cutoff_date = datetime.now() - timedelta(days=days_back)
    
    filtered = []
    for art in articles:
        pub_date = parse_article_date(art)
        
        # If we can't parse the date, include it (better safe than sorry)
        if pub_date is None:
            logger.warning(f"Could not parse date for article: {art['title'][:50]}")
            filtered.append(art)
            continue
        
        # Make both aware for comparison (use UTC if needed)
        if pub_date.tzinfo is None:
            pub_date = pub_date.replace(tzinfo=None)
        
        if pub_date >= cutoff_date:
            filtered.append(art)
    
    return filtered

# ------------------------------
# PDF Generation with Unicode sanitisation
# ------------------------------
class PDF(FPDF):
    def header(self):
        self.set_font("Arial", "B", 12)
        self.cell(0, 10, "Daily News Briefing", ln=True, align="C")
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Arial", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")

def _clean_latin(text: str) -> str:
    """Replace non-latin-1 characters with their closest ASCII equivalent or remove them."""
    # Replace common punctuation that cause problems
    replacements = {
        '\u2013': '-',  # en dash
        '\u2014': '--', # em dash
        '\u2018': "'",  # left single quote
        '\u2019': "'",  # right single quote
        '\u201c': '"',  # left double quote
        '\u201d': '"',  # right double quote
        '\u2022': '*',  # bullet
        '\u2026': '...' # ellipsis
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    # Remove any remaining characters outside latin-1 by replacing them with '?'
    return text.encode('latin-1', errors='replace').decode('latin-1')

def generate_pdf(articles: List[Dict], date_str: str) -> Optional[bytes]:
    """
    Generate a PDF from the list of filtered articles.
    Returns the PDF as bytes, or None if an error occurs.
    """
    try:
        pdf = PDF()
        pdf.add_page()
        pdf.set_font("Arial", "B", 16)
        clean_date = _clean_latin(date_str)
        pdf.cell(0, 10, f"Daily News Briefing - {clean_date}", ln=True, align="C")
        pdf.ln(10)

        for idx, art in enumerate(articles, 1):
            # Clean the text for each field
            source = _clean_latin(art['source'])
            title = _clean_latin(art['title'])
            content = _clean_latin(art.get("content", "No content available."))
            is_full = art.get("is_full", False)
            extraction_method = art.get("extraction_method", "Unknown")

            pdf.set_font("Arial", "B", 12)
            pdf.cell(0, 8, f"{idx}. {source}", ln=True)
            pdf.set_font("Arial", "B", 11)
            pdf.cell(0, 8, f"Headline: {title}", ln=True)
            pdf.set_font("Arial", "", 10)
            # Multi-cell for content (auto-wraps)
            pdf.multi_cell(0, 5, content)
            
            # Show extraction method
            pdf.set_font("Arial", "I", 9)
            method_str = _clean_latin(extraction_method)
            if not is_full:
                pdf.cell(0, 5, f"({method_str})", ln=True)
            else:
                pdf.cell(0, 5, f"(Full text via {method_str})", ln=True)
            pdf.ln(5)

        # Return PDF as bytes
        pdf_output = pdf.output(dest="S")
        # Handle both bytes and string returns from different fpdf versions
        if isinstance(pdf_output, bytes):
            return pdf_output
        else:
            return pdf_output.encode("latin-1")
    except Exception as e:
        st.error(f"PDF generation failed: {e}")
        logger.error(f"PDF generation error: {e}")
        return None

# ------------------------------
# Streamlit App
# ------------------------------
def main():
    st.set_page_config(page_title="Daily News Briefing", layout="wide")
    
    # Professional header with date
    today = datetime.now().strftime("%d %B %Y").lstrip("0").replace(" 0", " ")  # Format: "17 June 2026"
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown(f"<h3 style='text-align: center; margin-bottom: 5px;'>{today}</h3>", unsafe_allow_html=True)
    
    st.markdown("<h1 style='text-align: center; margin-top: 0;'>Daily Global News Briefing</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center; color: gray; margin-top: -15px;'>India & Frontier Tech news from premium sources</p>", unsafe_allow_html=True)
    st.divider()

    # Sidebar controls
    st.sidebar.header("⚙️ Controls")
    date_option = st.sidebar.radio(
        "Date range",
        ["Today", "Last 3 days", "Last 7 days"],
        index=0
    )
    if date_option == "Today":
        days_back = 0
    elif date_option == "Last 3 days":
        days_back = 3
    else:
        days_back = 7

    refresh = st.sidebar.button("🔄 Refresh News", use_container_width=True)
    
    # Optional dependency warnings
    with st.sidebar:
        st.markdown("---")
        st.markdown("**Optional Tools:**")
        if not HAS_NEWSPAPER:
            st.caption("⚠️ Install newspaper3k for better extraction")
        if not HAS_TRAFILATURA:
            st.caption("⚠️ Install trafilatura for better extraction")
        bpc_available = is_bpc_fetch_available()
        if not bpc_available:
            st.caption("⚠️ Install bpc-fetch via npm for better extraction")
    
    # Fetch and process articles on refresh or if not in session
    if refresh or "articles_with_content" not in st.session_state:
        with st.spinner("Fetching and processing articles..."):
            # Fetch feeds
            all_articles = []
            for source in SOURCES:
                fetched = fetch_feed(source)
                all_articles.extend(fetched)
            
            st.info(f"Fetched {len(all_articles)} articles from {len(SOURCES)} sources")
            
            # Filter by keywords (India AND tech)
            filtered = filter_articles(all_articles)
            st.info(f"Found {len(filtered)} articles matching India + tech keywords")
            
            # Filter by date range
            date_filtered = filter_articles_by_date(filtered, days_back)
            st.info(f"Found {len(date_filtered)} articles within date range ({date_option})")

            # For each article, try to get full text with extraction chain
            articles_with_content = []
            progress_bar = st.progress(0)
            total = len(date_filtered)
            
            for i, art in enumerate(date_filtered):
                content, is_full, extraction_method = get_article_content(art)
                art["content"] = content
                art["is_full"] = is_full
                art["extraction_method"] = extraction_method
                articles_with_content.append(art)
                progress_bar.progress((i + 1) / total if total > 0 else 1.0)
            
            st.session_state["articles_with_content"] = articles_with_content
            st.success(f"✅ Found {len(articles_with_content)} relevant articles ready for display.")
            st.rerun()

    # Display articles in professional format (like the PDF)
    articles = st.session_state.get("articles_with_content", [])
    if not articles:
        st.info("No articles match your criteria. Try adjusting the date range or refreshing later.")
    else:
        for idx, art in enumerate(articles, 1):
            # Source name (prominent)
            st.markdown(f"<p style='font-size: 14px; font-weight: bold; color: #333; margin-bottom: 2px;'>{art['source'].upper()}</p>", unsafe_allow_html=True)
            
            # Headline (prominent)
            st.markdown(f"<h3 style='margin: 5px 0; line-height: 1.3;'>{art['title']}</h3>", unsafe_allow_html=True)
            
            # Metadata row
            col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
            with col1:
                st.caption(f"📅 {art.get('published', 'N/A')}")
            with col2:
                if art['is_full']:
                    st.caption("✅ Full text")
                else:
                    st.caption("📄 Summary")
            with col3:
                st.caption(f"via {art.get('extraction_method', 'Unknown')}")
            with col4:
                if art['link']:
                    st.caption(f"[Read →]({art['link']})")
            
            # Article content
            st.markdown(art.get("content", "No content available."))
            
            # Separator between articles
            st.divider()

        # PDF download section
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 1])
        with col2:
            if st.button("📥 Download PDF Briefing", use_container_width=True):
                date_str = datetime.now().strftime("%Y-%m-%d")
                pdf_bytes = generate_pdf(articles, date_str)
                if pdf_bytes:
                    b64 = base64.b64encode(pdf_bytes).decode()
                    href = f'<a href="data:application/pdf;base64,{b64}" download="briefing_{date_str}.pdf" style="text-decoration: none;"><button style="width: 100%; padding: 10px;">📄 Download PDF</button></a>'
                    st.markdown(href, unsafe_allow_html=True)
                else:
                    st.error("Could not generate PDF. Please check the logs.")

if __name__ == "__main__":
    main()