import asyncio
import random
import json
from pathlib import Path
from playwright.async_api import async_playwright

import memory
import extractor

# Cap apply volume per run and space out actions to stay under rate-limit heuristics.
MAX_APPLICATIONS_PER_RUN = 15
APPLICATION_COOLDOWN_SECONDS = (45.0, 120.0)
PAGE_SCAN_COOLDOWN_SECONDS = (2.5, 6.0)

# Jobs in these vault statuses will be picked up by the apply phase.
APPLY_ELIGIBLE_STATUSES = {
    "Discovered",
    "Submit_Failed",
    "Filled_Not_Submitted",
    "Incomplete_Form",
    "Manual_Review",
}


STEALTH_INIT_SCRIPT = """
(() => {
  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
  if (!window.chrome) {
    window.chrome = { runtime: {} };
  }
  Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
  Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
})();
"""

# 1. Central Platform Configuration Registry
PLATFORM_REGISTRY = {
    "internshala": {
        "platform_name": "Internshala",
        "base_url": "https://internshala.com",
        "search_url": "https://internshala.com/internships/work-from-home-full-stack-development-internships-in-noida/fast-response-true/",
        "selectors": {
            "card_container": ".internship_meta",
            "role_title": ".job-title-href",
            "company_name": ".company-name-container, .company_name",
            "stipend": ".stipend_container, .stipend",
            "duration": ".item_body",
            "apply_now_button": "#apply_now_button, button:has-text('Apply now'), .btn:has-text('Apply now')",
            "already_applied_indicator": ".applied_notification, button:has-text('Already applied'), .btn:has-text('Already applied')", 
            "form_question_labels": "div.form-group:has(textarea) label.control-label, div.form-group:has(input[type='text']) label.control-label, .question-heading, .assessment_question",
            "form_text_inputs": "div.form-group textarea.form-control, div.form-group input[type='text'].form-control",
            "final_submit_button": "button:has-text('Submit'), input[type='submit']"
        }
    }
}

async def main():
    # Toggle this single parameter token to instantly switch target runtime profiles
    target_platform = "internshala"
    config = PLATFORM_REGISTRY[target_platform]

    print(f"[System] Initializing Modular Job Scanner for {config['platform_name']}...")
    
    # Load existing database state from parameterized memory layer
    vault = memory.load_vault(target_platform)
    initial_count = len(vault)
    print(f"[System] Memory loaded. Found {initial_count} historic records on disk.")
    
    new_discoveries_count = 0

    async with async_playwright() as p:
        print("[System] Spinning up persistent automation profile environment...")
        viewport_width = random.randint(1240, 1440)
        viewport_height = random.randint(760, 900)

        context = await p.chromium.launch_persistent_context(
            user_data_dir="./automation_session",
            headless=False,
            viewport={"width": viewport_width, "height": viewport_height},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="en-US",
            timezone_id="Asia/Kolkata",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--start-maximized",
            ],
            ignore_default_args=["--enable-automation"],
        )
        await context.add_init_script(STEALTH_INIT_SCRIPT)
        page = context.pages[0] if context.pages else await context.new_page()
        
        base_search_url = config["search_url"]
        
        # Scan through the first 3 pages
        for current_page_num in range(1, 4):
            target_url = f"{base_search_url}/page-{current_page_num}/" if current_page_num > 1 else base_search_url
            print(f"\n[Orchestrator] Routing Browser to Page {current_page_num} on {config['platform_name']}...")
            
            await page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            await asyncio.sleep(random.uniform(1.0, 2.5))

            # Call Extractor module scrolling protocol
            await extractor.auto_scroll_page(page)
            
            # Fetch parsed results from Extractor module
            batch_listings = await extractor.extract_page_listings(page, config)
            print(f"[Orchestrator] Extractor returned {len(batch_listings)} valid tech slots.")
            
            # Process records through Memory module filters
            for job in batch_listings:
                if not memory.is_duplicate(job["id"], vault):
                    vault[job["id"]] = job
                    new_discoveries_count += 1
                    print(f"  -> NEW CAPTURE: {job['role']} at {job['company']} (ID: {job['id']})")
            
            await asyncio.sleep(random.uniform(*PAGE_SCAN_COOLDOWN_SECONDS))
            if random.random() < 0.2:
                await asyncio.sleep(random.uniform(4.0, 9.0))
            
        # Commit updates to disk via memory module if any new records were added
        if new_discoveries_count > 0:
            print(f"\n[Orchestrator] Found {new_discoveries_count} new unique positions.")
            memory.save_vault(vault, target_platform)
        else:
            print("\n[Orchestrator] Scan complete. No new unique internships discovered.")
        
        # ──────────────────────────────────────────────────────────────────
        # APPLICATION PHASE WITH INTEGRATED DYNAMIC CONTEXT LOADING
        # ──────────────────────────────────────────────────────────────────
        print("\n[Orchestrator] Initializing Application Pipeline Phase...")
        from applier import ApplicationPipeline

        # Resolve context file parameters securely 
        context_file = Path("profile_context.json")
        if context_file.exists():
            print(f"[Orchestrator] Loading parsed resume profile context from: {context_file}")
            profile_data = json.loads(context_file.read_text(encoding="utf-8"))
        else:
            print(f"[Warning] Context target '{context_file}' was missing. Operating with an empty profile layer.")
            profile_data = {}

        # Append connection configuration properties programmatically 
        # This keeps it safely outside your resume text block so the LLM won't break character
        profile_data["ollama_base_url"] = "http://localhost:11434"

        # Instantiate the coordinator pipeline using the loaded data payload
        pipeline = ApplicationPipeline(page, config, profile_data)

        applications_attempted = 0
        for job_id, job_data in vault.items():
            
            if job_data.get("status") not in APPLY_ELIGIBLE_STATUSES:
                print(f"[Orchestrator] Skipping job {job_id} with status {job_data['status']}.")

                continue
            if applications_attempted >= MAX_APPLICATIONS_PER_RUN:
                print(f"[Orchestrator] Reached per-run apply cap ({MAX_APPLICATIONS_PER_RUN}). Stopping apply phase.")
                break

            

            print(f"[Orchestrator] Navigating to apply: {job_data['detail_url']}")

            result_status = await pipeline.apply_to_job(job_data["detail_url"])

            job_data["status"] = result_status
            memory.save_vault(vault, target_platform)
            applications_attempted += 1

            print(f"[Orchestrator] Pipeline process status returned: {result_status}")

            if applications_attempted < MAX_APPLICATIONS_PER_RUN:
                cooldown = random.uniform(*APPLICATION_COOLDOWN_SECONDS)
                print(f"[Orchestrator] Cooling down {cooldown:.0f}s before next application...")
                await asyncio.sleep(cooldown)
                
        print("\n[System] Orchestration workflow finished. Standing by...")
        await asyncio.sleep(15.0)
if __name__ == "__main__":
    asyncio.run(main())