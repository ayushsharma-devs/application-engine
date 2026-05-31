# platforms/internshala.py
import asyncio
from multiprocessing import context
import random
import logging
import re
import html as html_module
import sys
import time
import json
import httpx
from pathlib import Path
from playwright.async_api import Page, Locator
from .base import BasePlatformAdapter
import extractor

logger = logging.getLogger("Orchestrator.Internshala")

# --- CORE UTILITIES PRESERVED FROM YOUR APPLIER.PY ---
ENABLE_SUBMIT = True  # Set to True so it actually submits the forms now!
MAX_ANSWER_CHARS = 900


def sanitize_answer_text(text: str) -> str:
    if not text:
        return text
    text = re.sub(r"<br\s*/?\s*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p[^>]*>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_module.unescape(text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    lines = [line.strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line).strip()
    if len(text) > MAX_ANSWER_CHARS:
        text = text[:MAX_ANSWER_CHARS].rsplit(" ", 1)[0].rstrip(".,;") + "..."
    return text


TEXT_FIELD_SKIP_PHRASES = (
    "upload cv",
    "upload resume",
    "upload your resume",
    "attach resume",
    "custom resume",
    "confirm your availability",
)

MCQ_SKIP_PHRASES = (
    "upload cv",
    "upload resume",
    "bookmark",
    "confirm your availability",
    "add this to my bookmark",
    "bookmark",
    "your resume",
    "resume",
)


def _label_matches_skip_phrase(label: str, phrases: tuple[str, ...]) -> bool:
    lower = label.lower()
    return any(phrase in lower for phrase in phrases)


# --- ADAPTER DEFINITION MATCHING YOUR NEW PIPELINE ---
class InternshalaAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(platform_key="internshala")
        # Explicitly handling the Quill editor and ignoring hidden textareas
        self.selectors = {
            "apply_now_button": "a#apply_now_button, button:has-text('Apply now')",
            "already_applied_indicator": "button:has-text('Applied'), .already-applied-status",
            "form_text_inputs": "textarea:not([style*='display: none']), input[type='text'], .ql-editor",
            
            # FIXED: Targets the interactive elements directly, using the strict ID "submit" seen in your dev tools
            "final_submit_button": "input#submit, .submit_button_container input, button:has-text('Submit'), input[type='submit']",
            
            "job_description": ".job-description, .profile_detail, .job_summary_container ",
        }
    def build_dense_context(self, profile_dict: dict, job_description: str) -> str:
        # 1. Extract and clean your resume (Keep 100% of it intact)
        profile_text = profile_dict.get("candidate_profile", "")
        if isinstance(profile_text, dict):
            profile_text = profile_text.get("candidate_profile", str(profile_text))
        elif not profile_text:
            profile_text = str(profile_dict)
        clean_profile = re.sub(r'\s+', ' ', profile_text).strip()
        
        # 2. Clean up initial whitespaces in the job description
        clean_job = re.sub(r'\s+', ' ', job_description).strip()
        clean_job_lower = clean_job.lower()
        
        # 3. Define the exact boilerplate headers Internshala injects
        boilerplate_anchors = [
            "perks:", 
            "activity on internshala:", 
            "view full job description"
        ]
        
        # Find the earliest occurrence of any boilerplate anchor
        cutoff_index = len(clean_job)
        for anchor in boilerplate_anchors:
            idx = clean_job_lower.find(anchor)
            if idx != -1 and idx < cutoff_index:
                cutoff_index = idx
                
        # Slice the job description right before the fluff starts
        clean_job = clean_job[:cutoff_index].strip()

        # 4. Dynamic Link Extraction via Regex (Stays completely private)
        github_match = re.search(r'(https?://)?(www\.)?github\.com/[a-zA-Z0-9-_./]+', clean_profile)
        linkedin_match = re.search(r'(https?://)?(www\.)?linkedin\.com/[a-zA-Z0-9-_./]+', clean_profile)
        
        github_url = github_match.group(0) if github_match else "Not provided"
        linkedin_url = linkedin_match.group(0) if linkedin_match else "Not provided"
        
        if github_url != "Not provided" and not github_url.startswith("http"):
            github_url = "https://" + github_url
        if linkedin_url != "Not provided" and not linkedin_url.startswith("http"):
            linkedin_url = "https://" + linkedin_url

        # 5. Build the token-dense payload
        dense_context = (
            f"CANDIDATE SKILLS & EXPERIENCE:\n{clean_profile}\n\n"
            f"JOB REQUIREMENTS:\n{clean_job}\n\n"
            f"DYNAMIC_LINKS:\n- GITHUB_LINK: {github_url}\n- LINKEDIN_LINK: {linkedin_url}"
        )
        return dense_context
    async def extract_jobs(self, page: Page, current_page_num: int) -> list[dict]:
        await extractor.auto_scroll_page(page)
        return await extractor.extract_page_listings(
            page, {"selectors": self.selectors}
        )
    
    async def apply(self, page: Page, detail_url: str, profile_data: dict) -> str:
        logger.info(f"Navigating pipeline stream to target link: {detail_url}")

        ollama_url = profile_data.get("ollama_base_url", "http://127.0.0.1:11434")
        synthesizer = LLMResponseSynthesizer(base_url=ollama_url)

        try:
            await page.goto(detail_url, wait_until="domcontentloaded", timeout=45000)

            # Simulate human idle reading behavior
            await self._human_idle_read_page(page)

            # Check if job was already processed previously
            if (
                await page.locator(self.selectors["already_applied_indicator"]).count()
                > 0
            ):
                logger.info("Target job slot already exhibits an 'Applied' state.")
                return "Execution_Success"

            # Trigger initial form entry
            apply_now_btn = page.locator(self.selectors["apply_now_button"]).first
            if await apply_now_btn.count() == 0:
                return "Execution_Error"

            await apply_now_btn.click()
            await asyncio.sleep(2.5)  # Let modal view fully render

            # Extract job data to compile LLM context payload
            job_desc_loc = page.locator(self.selectors["job_description"])
            job_desc = (
                " ".join((await job_desc_loc.first.inner_text()).split()).strip()
                if await job_desc_loc.count() > 0
                else "Not specified on page."
            )

            clean_profile = {
                k: v
                for k, v in profile_data.items()
                if k not in ["selectors", "ollama_base_url", "platform_name"]
            }
            context_string = self.build_dense_context(clean_profile,job_desc)
               

            # --- FLAT DOM EXECUTION PIPELINE ---
            logger.info("Processing flat evaluation logic frame...")

            # 1. Scrape all visible inputs simultaneously
            mcq_questions = await self._extract_visible_mcqs(page)
            text_questions = await self._extract_visible_text_questions(page)

            # 2. Phase A: Process MCQs (Human behavior preference)
            if mcq_questions:
                logger.info(f"Processing {len(mcq_questions)} MCQ field(s) first.")
                for mcq in mcq_questions:
                    selected_option = await synthesizer.generate_mcq_response(
                        prompt=mcq["raw_text"],
                        options=mcq["options"],
                        context=context_string,
                    )

                    matched_option = next(
                        (
                            opt
                            for opt in mcq["options"]
                            if opt.lower() in selected_option.lower()
                            or selected_option.lower() in opt.lower()
                        ),
                        None,
                    )
                    final_choice = (
                        matched_option if matched_option else mcq["options"][0]
                    )

                    # ROUTING LOGIC: Split between Dropdowns and Radio/Checkboxes
                    if mcq.get("is_select", False):
                        await self._handle_dropdown_humanized(
                            mcq["name"], final_choice, page
                        )
                    else:
                        await self._handle_radio_checkbox_humanized(
                            mcq["name"], final_choice, page
                        )

                    await asyncio.sleep(0.8)

            # 3. Phase B: Process Open Text Fields
            if text_questions:
                logger.info(f"Processing {len(text_questions)} text field(s).")
                prompt_list = [q["raw_text"] for q in text_questions]
                
                llm_results = await synthesizer.match_responses(
                    prompts=prompt_list, context=context_string
                )

                for q in text_questions:
                    ans_text = llm_results.get(q["raw_text"], "Please refer to resume.")
                    await self._clear_and_type_humanized(q["element"], ans_text, page)
                    await asyncio.sleep(random.uniform(0.3, 0.6))

            # 4. Finalization
            return await self._finalize_submission_pass(page)

        except Exception as e:
            logger.error(
                f"Pipeline transaction failed on target page: {e}", exc_info=True
            )
            return "Execution_Error"

    # --- REPLICATED APPLIER ROUTINES ---

    async def _extract_visible_text_questions(self, page: Page) -> list[dict]:
        locator = page.locator(self.selectors["form_text_inputs"])
        questions = []
        for idx in range(await locator.count()):
            field = locator.nth(idx)
            if not await field.is_visible():
                continue
            clean_text = await self._resolve_field_label(field)
            if not clean_text or _label_matches_skip_phrase(
                clean_text, TEXT_FIELD_SKIP_PHRASES
            ):
                continue
            questions.append({"raw_text": clean_text, "element": field})
        return questions

    async def _extract_visible_mcqs(self, page: Page) -> list[dict]:
        mcq_groups = await page.evaluate(
            """() => {
            const inputs = Array.from(document.querySelectorAll("input[type='checkbox'], input[type='radio'], select"));
            const groups = {};
            
            inputs.forEach(input => {
                const groupKey = input.name || input.id || 'unnamed_group';
                
                if (!groups[groupKey]) {
                    // FIX 1: Crawl UP the DOM tree until we actually hit the question heading
                    let current = input.parentElement;
                    let labelEl = null;
                    while (current && current !== document.body) {
                        labelEl = current.querySelector('.assessment_question, .question-heading');
                        if (labelEl) break;
                        current = current.parentElement;
                    }
                    
                    let labelText = '';
                    if (labelEl) {
                        const clone = labelEl.cloneNode(true);
                        clone.querySelectorAll('.badge, .text-muted, span').forEach(n => n.remove());
                        labelText = clone.innerText.trim();
                    }
                    
                    groups[groupKey] = {
                        name: input.name || input.id || '',
                        raw_text: labelText || 'Select an option:',
                        options: [],
                        is_select: input.tagName.toLowerCase() === 'select'
                    };
                }
                
                // FIX 2: Properly extract human-readable option text via the 'for' attribute
                if (input.tagName.toLowerCase() === 'select') {
                    Array.from(input.options).forEach(opt => {
                        if (opt.value && opt.text && opt.text.trim()) {
                            groups[groupKey].options.push(opt.text.trim());
                        }
                    });
                } else {
                    let optionText = input.value; 
                    if (input.id) {
                        // Look for a sibling label linked by ID (Internshala's pattern)
                        const linkedLabel = document.querySelector(`label[for="${input.id}"]`);
                        if (linkedLabel) optionText = linkedLabel.innerText;
                    }
                    // Fallback to parent wrapper if 'for' isn't used
                    if (optionText === input.value) {
                        const parentLabel = input.closest('label');
                        if (parentLabel) optionText = parentLabel.innerText;
                    }
                    groups[groupKey].options.push(optionText.trim());
                }
            });
            
            return Object.values(groups);
        }"""
        )

        cleaned_mcqs = []
        for g in mcq_groups:
            text = " ".join(g["raw_text"].split()).strip().lower()
            name_attr = g.get("name", "").lower()

            # 1. The Attribute Check (Backend fallback)
            if "availability" in name_attr:
                continue

            # 2. The Visual Text Check (Your skip phrases)
            if not g["options"] or _label_matches_skip_phrase(text, MCQ_SKIP_PHRASES):
                continue

            cleaned_mcqs.append(
                {
                    "name": g["name"],
                    "raw_text": text,
                    "options": list(dict.fromkeys(g["options"])),
                    "is_select": g.get("is_select", False),
                }
            )

        return cleaned_mcqs

    async def _resolve_field_label(self, input_el: Locator) -> str:
        clean_label = await input_el.evaluate(
            """element => {
            const container = element.closest('.form-group, .assessment_question_container');
            if (!container) return '';
            const labelElement = container.querySelector('label, .assessment_question, .control-label');
            if (labelElement) {
                const clone = labelElement.cloneNode(true);
                clone.querySelectorAll('.badge, .text-muted, span').forEach(n => n.remove());
                return clone.innerText.trim();
            }
            let sibling = element.previousElementSibling;
            if (sibling && sibling.innerText && sibling.innerText.trim()) return sibling.innerText.trim();
            return '';
        }"""
        )
        return " ".join(clean_label.split()).strip()

    async def _clear_and_type_humanized(self, element: Locator, text: str, page: Page):
        await element.scroll_into_view_if_needed()
        await element.click()
        select_all = "Meta+A" if sys.platform == "darwin" else "Control+A"
        await page.keyboard.press(select_all)
        await page.keyboard.press("Backspace")

        chunk_size = random.randint(4, 9)
        for offset in range(0, len(text), chunk_size):
            chunk = text[offset : offset + chunk_size]
            await element.press_sequentially(chunk, delay=random.uniform(35, 90))
            if random.random() < 0.1:
                await asyncio.sleep(random.uniform(0.2, 0.5))

    async def _handle_dropdown_humanized(
        self, name_attribute: str, selected_option: str, page: Page
    ) -> bool:
        """Handles native selects and Chosen.js custom UI dropdowns."""
        try:
            select_loc = page.locator(
                f'select[name="{name_attribute}"], select[id="{name_attribute}"]'
            ).first

            if await select_loc.count() > 0:
                is_hidden = not await select_loc.is_visible()

                if is_hidden:
                    logger.info(
                        f"Hidden select detected for '{name_attribute}'. Engaging Chosen.js UI interaction."
                    )
                    select_id = await select_loc.get_attribute("id")

                    if select_id:
                        chosen_container = page.locator(f"#{select_id}_chosen")
                    else:
                        chosen_container = select_loc.locator(
                            "xpath=following-sibling::div[contains(@class, 'chosen-container')]"
                        ).first

                    if await chosen_container.count() > 0:
                        await chosen_container.scroll_into_view_if_needed()
                        await chosen_container.locator("a.chosen-single").click()
                        await asyncio.sleep(random.uniform(0.3, 0.6))

                        option_target = chosen_container.locator(
                            f"ul.chosen-results li:text-is('{selected_option}')"
                        ).first
                        if await option_target.count() == 0:
                            option_target = chosen_container.locator(
                                f"ul.chosen-results li:has-text('{selected_option}')"
                            ).first

                        if (
                            await option_target.count() > 0
                            and await option_target.is_visible()
                        ):
                            await option_target.click()
                            return True
                        else:
                            logger.warning(
                                f"Chosen UI option '{selected_option}' not found. Bailing out."
                            )
                            await page.keyboard.press("Escape")
                            return False
                else:
                    await select_loc.scroll_into_view_if_needed()
                    await select_loc.select_option(label=selected_option)
                    return True
            return False

        except Exception as e:
            logger.error(f"Failed to interact with Dropdown '{name_attribute}': {e}")
            return False

    async def _handle_radio_checkbox_humanized(
        self, name_attribute: str, selected_option: str, page: Page
    ) -> bool:
        """Handles standard radio buttons and checkboxes, bypassing label interception."""
        try:
            # 1. Target the exact input element
            input_target = page.locator(
                f'input[name="{name_attribute}"][value="{selected_option}"]'
            ).first
            if await input_target.count() == 0:
                input_target = page.locator(f'input[value="{selected_option}"]').first

            if await input_target.count() > 0:
                await input_target.scroll_into_view_if_needed()

                # Fast return if it's already selected (prevents toggling off a checkbox)
                if await input_target.is_checked():
                    return True

                # STRATEGY A: Find and click the linked label based on the input's ID
                input_id = await input_target.get_attribute("id")
                if input_id:
                    label_target = page.locator(f'label[for="{input_id}"]').first
                    if (
                        await label_target.count() > 0
                        and await label_target.is_visible()
                    ):
                        await label_target.click()
                        return True

                # STRATEGY B: Check if the input is wrapped inside a label tag and click the parent
                parent_label = input_target.locator("xpath=ancestor::label").first
                if await parent_label.count() > 0 and await parent_label.is_visible():
                    await parent_label.click()
                    return True

                # STRATEGY C: Brute force the click if Playwright is still complaining about interception
                logger.info(
                    f"Standard clicks blocked for '{name_attribute}'. Forcing click."
                )
                await input_target.click(force=True)
                return True

            # 2. Complete Fallback: Try just finding the text anywhere in a label
            fallback_label = page.locator(f'label:has-text("{selected_option}")').first
            if await fallback_label.count() > 0:
                await fallback_label.scroll_into_view_if_needed()
                await fallback_label.click()
                return True

            return False

        except Exception as e:
            logger.error(
                f"Failed to interact with Radio/Checkbox '{name_attribute}': {e}"
            )
            return False

    async def _human_idle_read_page(self, page: Page):
        for _ in range(random.randint(1, 2)):
            delta = random.randint(90, 200) * random.choice((1, -1))
            await page.mouse.wheel(0, delta)
            await asyncio.sleep(random.uniform(0.4, 1.0))

    async def _finalize_submission_pass(self, page: Page) -> str:
        if not ENABLE_SUBMIT:
            logger.info("Dry-run configured. Skipping definitive submit call.")
            return "Execution_Success"

        submit_btn = page.locator(self.selectors["final_submit_button"]).first
        
        try:
            await submit_btn.wait_for(state="visible", timeout=3000)
        except Exception:
            logger.error("Submit button not found or not visible.")
            return "Execution_Error"

        await submit_btn.scroll_into_view_if_needed()
        await asyncio.sleep(1.0)
        await submit_btn.click()
        logger.info("Submit button clicked. Verification loop initiated...")

        # Robust loop using Regex matching for any variation of success text
        for attempt in range(6):
            await asyncio.sleep(1.5)
            
            # Using clean Playwright regex matching for "applied" or "submitted"
            success_indicators = page.locator("text=/applied|submitted|success/i")
            
            if await success_indicators.count() > 0:
                logger.info("Submission verified via on-page success text elements.")
                return "Execution_Success"

            # Dynamic URL verification fallback during the loop 
            # (catches dashboard redirects AND applications path redirects)
            current_url = page.url.lower()
            if any(path in current_url for path in ["dashboard", "applications", "applied"]):
                logger.info(f"Submission verified via URL redirect target: {page.url}")
                return "Execution_Success"

        # Final sanity check on the URL if text matching completely timing out
        current_url = page.url.lower()
        if any(path in current_url for path in ["dashboard", "applications", "applied"]):
            logger.info("Submission verified via post-loop URL analysis.")
            return "Execution_Success"

        logger.error("Failed to verify submission success frames or redirect states.")
        return "Execution_Error"

    # [Keep the rest of your class methods (_extract_visible_text_questions, _extract_visible_mcqs, etc.) exactly as they are]




class LLMResponseSynthesizer:
    # Explicitly requesting the 3b model parameter to avoid accidentally loading 8b\
    
    def __init__(
        self, base_url: str = "http://localhost:11434", model: str = "llama3.2:3b"
    ):
        base_url = base_url.rstrip("/")
        self.base_url = (
            f"{base_url}/api/generate"
            if not base_url.endswith("/api/generate")
            else base_url
        )
        self.model = model
        self.timeout_config = httpx.Timeout(
            connect=10.0, read=300.0, write=10.0, pool=10.0
        )
   
    async def generate_response(self, prompt: str, context: str) -> str:
        system_instructions = """
        You are an advanced AI assistant acting strictly as Ayush Sharma, answering a specific application question for a technical internship.

        CRITICAL INSTRUCTIONS & CONSTRAINTS:
        - Output raw, unformatted plain text ONLY. No Markdown, no HTML, no lists.
        - LENGTH: strictly under 100 words.
        - FACTUALITY: Base technical answers strictly on the `candidate_profile`.
        - WILLINGNESS & LOGISTICS: If the question asks if you are "okay with", "comfortable with", or willing to comply with operational requirements (like WFH, using specific software, shifts, or relocation), ALWAYS answer affirmatively (e.g., "Yes, I am completely comfortable with this requirement and am ready to comply.")
        - SPECIAL: If asked about stipend, availability, or immediate joining, answer affirmatively.
       
        """
        payload = {
            "model": self.model,
            "prompt": f"Instructions:\n{system_instructions}\n\nContext:\n{context}\n\nQuestion:\n{prompt}",
            "stream": False,
            "options": {
                "temperature": 0.2,       # Keeps text generation creative but highly focused
                "num_predict": 120,       # Hard-stops the LLM after ~100 words so it physically cannot yap
                "top_k": 40
            }
        }
        async with httpx.AsyncClient(timeout=self.timeout_config) as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "").strip()
                sanitize_answer_text(raw)
                return raw # Assuming you handle sanitize_answer_text elsewhere
            except httpx.HTTPStatusError as e:
                # This will print the actual Ollama error (e.g., "model not found")
                print(f"API Error: {e.response.text}")
                return ""
            except Exception as e:
                print(f"Text Error: {e}")
                return ""

    async def generate_mcq_response(
        self, prompt: str, options: list[str], context: str
    ) -> str:
        options_block = "\n".join([f"- {opt}" for opt in options])
        
        # Completely rewritten for JSON mode
        system_instructions = ("""
            "You are a rigid data-extraction bot. Analyze the context and select the EXACT truest choice from the options list. "
            "You MUST output valid JSON only. Format: {\"selected_option\": \"exact text from options\"}."
            - WILLINGNESS & LOGISTICS: If the question asks if you are "okay with", "comfortable with", or willing to comply with operational requirements (like WFH, using specific software, shifts, or relocation), ALWAYS answer affirmatively (e.g., "Yes, I am completely comfortable with this requirement and am ready to comply.")
            """
               )
        
        payload = {
            "model": self.model,
            "prompt": f"Instructions:\n{system_instructions}\n\nContext:\n{context}\n\nQuestion:\n{prompt}\n\nOptions:\n{options_block}",
            "stream": False,
            "format": "json",             # <--- THE MAGIC BULLET for MCQs
            "options": {
                "temperature": 0.0,       # 0.0 = Absolute deterministic logic, zero creativity, maximum speed
                "num_predict": 40         # JSON output only needs about 15-30 tokens total
            }
        }
        
        async with httpx.AsyncClient(timeout=self.timeout_config) as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "").strip()
                
                # Safely parse the JSON to get exactly what we need
                parsed_data = json.loads(raw)
                ans = parsed_data.get("selected_option", "")
                
                # Fallback: if it hallucinates an option, grab the first real one
                if ans not in options and len(options) > 0:
                    return options[0]
                    
                return ans
            except httpx.HTTPStatusError as e:
                # This will print the actual Ollama error (e.g., "model not found")
                print(f"API Error: {e.response.text}")
                return ""
            except Exception as e:
                print(f"MCQ Error: {e}")
                return ""

    async def match_responses(self, prompts: list[str], context: str) -> dict[str, str]:
        results = {}
        # Keep this sequential (for loop). Do not use asyncio.gather here.
        # Sending multiple requests to local Ollama simultaneously will cause 
        # RAM/VRAM swapping and instantly throttle your machine.
        for prompt in prompts:
            resp = await self.generate_response(prompt, context)
            if resp:
                results[prompt] = resp
        return results
