import asyncio
import random
import hashlib
from datetime import datetime
from playwright.async_api import Page
from config import Settings

async def auto_scroll_page(page: Page):
    """Forces vertical scrolling steps to hydrate lazy-loaded elements on the page."""
    for _ in range(3):
        await page.evaluate("window.scrollBy(0, window.innerHeight * 0.75);")
        await asyncio.sleep(random.uniform(0.6, 1.2))
    await page.evaluate("window.scrollTo(0, 0);")
    await asyncio.sleep(0.5)

async def extract_page_listings(page: Page, config: dict) -> list:
    """Evaluates page DOM entirely within the browser context in a single IPC execution step

    to maximize processing velocity and remove cross-process async loops.
    """
    # 1. Ship selectors to the browser context for ultra-low latency parsing
    try:
        raw_elements = await page.evaluate("""(cfg) => {
            const cards = document.querySelectorAll(cfg.selectors.card_container);
            return Array.from(cards).map(card => {
                const titleNode = card.querySelector(cfg.selectors.job_title);
                const compNode = card.querySelector(cfg.selectors.company_name);
                const stipendNode = cfg.selectors.stipend ? card.querySelector(cfg.selectors.stipend) : null;
                const durationNode = cfg.selectors.duration ? card.querySelector(cfg.selectors.duration) : null;
                
                return {
                    title: titleNode ? titleNode.innerText : null,
                    company: compNode ? compNode.innerText : null,
                    href: titleNode ? titleNode.getAttribute('href') : null,
                    stipend: stipendNode ? stipendNode.innerText : 'Unspecified',
                    duration: durationNode ? durationNode.innerText : 'Not Listed'
                };
            });
        }""", config)
    except Exception as e:
        print(f"[{config.get('platform_name')} Extractor Error] Browser DOM evaluation crashed: {e}")
        return []

    # 2. Process, clean, and filter data instantly in memory using Python
    extracted_batch = []
    whitelist_keywords = {"stack", "web", "developer", "engineer", "backend", "frontend", "mern", "pern", "python", "fastapi", "php", "laravel", "javascript"}
    blacklist_keywords= Settings.BLACK_LISTKEYWORDS
    base_url = config.get("base_url", "").rstrip("/")
    platform_name = config.get("platform_name", "Unknown")

    for item in raw_elements:
        # Guard clause: Ensure essential data was returned from the DOM execution context
        if not item["title"] or not item["company"]:
            continue
            
        title = " ".join(item["title"].split())
        stipend_raw=item.get("stipend") or "Unspecified"
        stipend_clean = " ".join(stipend_raw.split()).strip()
        stipend_lower=stipend_clean.lower()
        combined_target_text = f"{title.lower()} {stipend_clean.lower()}"
        # Rule A: Check explicit keywords
        if any(bad_word in combined_target_text for bad_word in blacklist_keywords):
            continue 

        # Rule B: If the stipend field is empty, completely missing, or just a standalone "0"
        if not stipend_clean or stipend_lower in ["0", "₹0", "rs 0", "$0"]:
            continue
            
      
        # Supercharge checking optimization by utilizing a set intersection check instead of an open loop
        title_words = set(title.lower().replace("/", " ").split())
        if not title_words.intersection(whitelist_keywords):
            continue

        # Clean URL and handle relative vs absolute paths
        href = item["href"] or ""
        detail_url = href if href.startswith("http") else f"{base_url}{href}"
        
        # Handle platform-specific ID calculation parsing or fallback hashing safely
        if "-at-" in detail_url:
            job_id = detail_url.split("-at-")[-1].replace("/", "").strip()
        elif detail_url:
            job_id = hashlib.md5(detail_url.encode('utf-8')).hexdigest()[:12]
        else:
            continue

        extracted_batch.append({
            "id": job_id,
            "platform": platform_name,
            "role": title,
            "company": " ".join(item["company"].split()).replace("Actively hiring", "").strip(),
            "location": "Remote / WFH",
            "stipend": stipend_clean,
            "duration": " ".join(item["duration"].split()).strip(),
            "detail_url": detail_url,
            "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "Discovered"
        })

    return extracted_batch