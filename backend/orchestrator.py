# orchestrator.py
import asyncio
import random
import json
import logging
from pathlib import Path
from playwright.async_api import async_playwright, BrowserContext, Page

from config import Settings
import memory as memory
# Dynamically pull our modern platform adapter map
from platforms.internshala import InternshalaAdapter
#from platforms.linkedin import LinkedInAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Orchestrator")

MAX_APPLICATIONS_PER_RUN = Settings.MAX_APPLICATIONS
APPLICATION_COOLDOWN_SECONDS = (45.0, 120.0)
PAGE_SCAN_COOLDOWN_SECONDS = (2.5, 6.0)

APPLY_ELIGIBLE_STATUSES = {
    "Discovered", "Submit_Failed", "Filled_Not_Submitted", "Incomplete_Form", "Manual_Review"
}

# Mapping string keys to their concrete execution adapters
ADAPTER_REGISTRY = {
    "internshala": InternshalaAdapter(),
   # "linkedin": LinkedInAdapter()
}

STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  if (!window.chrome) { window.chrome = { runtime: {} }; }
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
})();
"""

async def launch_stealth_context(p) -> BrowserContext:
    viewport_width = random.randint(1240, 1440)
    viewport_height = random.randint(760, 900)
    return await p.chromium.launch_persistent_context(
        user_data_dir="./automation_session",
        headless=False,
        viewport={"width": viewport_width, "height": viewport_height},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        locale="en-US",
        timezone_id="Asia/Kolkata",
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox", "--start-maximized"],
        ignore_default_args=["--enable-automation"],
    )

async def run_discovery_phase(page: Page, adapter: any, vault: dict, target_platform: str, search_base_url: str):
    logger.info(f"Starting Discovery Phase for platform: {target_platform.upper()}...")
    new_discoveries = 0

    for current_page_num in range(1, 4):
        # Dynamically build paginated URLs depending on the specific search endpoint configuration
        target_url = f"{search_base_url}/page-{current_page_num}/" if current_page_num > 1 else search_base_url
        logger.info(f"Routing context to search index: {target_url}")
        
        try:
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(1.0, 2.5))

            # DELEGATION: Let the adapter figure out how to scrape its own DOM framework
            batch_listings = await adapter.extract_jobs(page, current_page_num)
            logger.info(f"Adapter returned {len(batch_listings)} tech slots.")

            for job in batch_listings:
                if not memory.is_duplicate(job["id"], vault):
                    vault[job["id"]] = job
                    new_discoveries += 1
                    logger.info(f" -> NEW CAPTURE: {job['role']} at {job['company']} (ID: {job['id']})")

            await asyncio.sleep(random.uniform(*PAGE_SCAN_COOLDOWN_SECONDS))
        except Exception as e:
            logger.error(f"Encountered scraping exception handling index loop: {e}")

    if new_discoveries > 0:
        logger.info(f"Committed {new_discoveries} updates to memory vault.")
        memory.save_vault(vault, target_platform)

async def run_application_phase(page: Page, adapter: any, vault: dict, target_platform: str):
    logger.info("Initializing Automated Application Pipeline Phase...")
    
    context_file = Path("backend\profile_context.json")
    profile_data = {}
    if context_file.exists():
        try:
            profile_data = json.loads(context_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.error("Profile context parsing failed.")
    else:
        import resume_parser
        RESUME_INPUT = Settings.RESUME_INPUT
    
        OUTPUT_TXT = "backend/resume_context.txt"
        OUTPUT_JSON = "backend/profile_context.json"

        try:
            cleaned_profile = resume_parser.extract_and_clean_resume(RESUME_INPUT)
            resume_parser.export_context(cleaned_profile, OUTPUT_TXT, OUTPUT_JSON)
        
            print("\n--- Context Preview ---")
        # Print the first 300 characters to verify structure looks clean
            print(cleaned_profile[:300] + "...\n-----------------------")
        
        except Exception as e:
            print(f"❌ Script failed: {e}")
    profile_data["ollama_base_url"] = Settings.OLLAMA_HOST
    applications_attempted = 0

    for job_id, job_data in vault.items():
        if job_data.get("status") not in APPLY_ELIGIBLE_STATUSES:
            continue

        if applications_attempted >= MAX_APPLICATIONS_PER_RUN:
            logger.info(f"Reached safety run limit threshold ({MAX_APPLICATIONS_PER_RUN}). Halting execution.")
            break

        logger.info(f"Routing adapter execution loop directly to: {job_data['detail_url']}")
        
        # DELEGATION: The orchestrator just hands over control to the adapter
        result_status = await adapter.apply(page, job_data["detail_url"], profile_data)
        
        job_data["status"] = result_status
        memory.save_vault(vault, target_platform)
        applications_attempted += 1

        logger.info(f"Pipeline item processed with execution status: {result_status}")

        if applications_attempted < MAX_APPLICATIONS_PER_RUN:
            cooldown = random.uniform(*APPLICATION_COOLDOWN_SECONDS)
            logger.info(f"Throttling script execution timeline loop for {cooldown:.1f}s...")
            await asyncio.sleep(cooldown)

async def main():
    # 1. Changed to a list layout to seamlessly execute entire context blocks sequentially
    target_platforms = Settings.TARGET_PLATFORMS 
    
    # Define platform entry search points (Kept exactly as you laid it out)
    search_urls = {
        "internshala": Settings.SEARCH_URL_INTERNSHALA,
        "linkedin": "https://www.linkedin.com/jobs/search/?keywords=Full%20Stack%20Developer&location=Noida"
    }

    async with async_playwright() as p:
        # Launch browser context once to maximize resource efficiency across cycles
        context = await launch_stealth_context(p)
        page = context.pages[0] if context.pages else await context.new_page()

        # Iterate through our targeted execution sequence loop cleanly
        for target_platform in target_platforms:
            logger.info(f"=== Beginning pipeline transaction block for: {target_platform.upper()} ===")

            # Fetch platform specific engine rules from registry
            adapter = ADAPTER_REGISTRY.get(target_platform)
            if not adapter:
                logger.error(f"Selected runtime platform adapter '{target_platform}' is not valid. Skipping framework segment...")
                continue

            # Load matching localized cache layer records via your memory model
            vault = memory.load_vault(target_platform)
            logger.info(f"State engine ready. Offline database for {target_platform} holds {len(vault)} items.")

            # Extract target search path safely 
            search_url = search_urls.get(target_platform)
            if not search_url:
                logger.warning(f"No entry target URL specified for platform '{target_platform}'. Skipping phase initialization...")
                continue

            try:
                # Execute unified, decoupled phase pipelines smoothly (dependencies preserved exactly)
                await run_discovery_phase(page, adapter, vault, target_platform, search_url)
                await run_application_phase(page, adapter, vault, target_platform)
                
                # Dynamic pacing throttler between platform handoffs to mimic organic browsing heuristics
                logger.info(f"Gracefully finalized transaction block for {target_platform}. Cooling down before next context shift...")
                await asyncio.sleep(random.uniform(5.0, 12.0))

            except Exception as e:
                logger.error(f"Fatal crash encountered inside {target_platform} operational loop: {str(e)}")
                continue

        logger.info("Automation pipeline finished all scheduled execution blocks gracefully. Standing by...")
        await asyncio.sleep(5.0)

if __name__ == "__main__":
    if not Settings.validate_workspace():
        exit(1)
    asyncio.run(main())