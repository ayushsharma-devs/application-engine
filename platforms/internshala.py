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
from contextlib import contextmanager  # Added for the stopwatch tracker
from pathlib import Path
from playwright.async_api import Page, Locator
from .base import BasePlatformAdapter
import extractor

logger = logging.getLogger("Orchestrator.Internshala")

# --- CORE UTILITIES PRESERVED FROM YOUR APPLIER.PY ---
ENABLE_SUBMIT = True  # Set to True so it actually submits the forms now!


def sanitize_answer_text(text: str) -> str:
    if not text:
        return text

    # 1. Unescape first to catch encoded blocks
    text = html_module.unescape(text)

    # 2. Drop explicit tags
    text = re.sub(r"<br\s*/?\s*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"</?p[^>]*>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)

    # 3. Force change all variants of newlines into standard spaces
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")

    # 4. Collapse multiple inline spaces down to a single space
    text = re.sub(r"[ \t]+", " ", text)

    return text.strip()


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


# --- TELEMETRY ENGINE FOR PIPELINE PERFORMANCE METRICS ---
class ApplicationTelemetry:
    def __init__(self, application_id: str):
        self.application_id = application_id
        self.metrics = {
            "application_id": application_id,
            "total_time": 0.0,
            "browser_navigation_time": 0.0,
            "llm_mcq_time": 0.0,
            "llm_text_time": 0.0,
            "dom_interaction_time": 0.0,
            "status": "Pending",
        }
        self._start_time = None

    def start(self):
        self._start_time = time.perf_counter()

    def stop(self, status: str = "Success"):
        if self._start_time:
            self.metrics["total_time"] = round(
                time.perf_counter() - self._start_time, 2
            )
            self.metrics["status"] = status
            self._save_metrics()

    @contextmanager
    def track(self, metric_key: str):
        """Yields execution control and records precision intervals to the metrics profile."""
        start = time.perf_counter()
        try:
            yield
        finally:
            duration = time.perf_counter() - start
            self.metrics[metric_key] = round(
                self.metrics.get(metric_key, 0.0) + duration, 2
            )

    def _save_metrics(self, filename="pipeline_metrics.jsonl"):
        """Appends structured run metrics safely to a localized jsonl schema."""
        try:
            with open(filename, "a", encoding="utf-8") as f:
                f.write(json.dumps(self.metrics) + "\n")
            logger.info(
                f"📊 Metrics saved for {self.application_id}: {self.metrics['total_time']}s total execution."
            )
        except Exception as e:
            logger.error(f"Failed to record performance block telemetry: {e}")


# --- ADAPTER DEFINITION MATCHING YOUR NEW PIPELINE ---
class InternshalaAdapter(BasePlatformAdapter):
    def __init__(self):
        super().__init__(platform_key="internshala")
        self.selectors = {
            "apply_now_button": "a#apply_now_button, button:has-text('Apply now')",
            "already_applied_indicator": "button:has-text('Applied'), .already-applied-status",
            "form_text_inputs": "textarea:not([style*='display: none']), input[type='text'], .ql-editor",
            "final_submit_button": "input#submit, .submit_button_container input, button:has-text('Submit'), input[type='submit']",
            "job_description": ".job-description, .profile_detail, .job_summary_container ",
        }

    def build_dense_context(self, profile_dict: dict, job_description: str) -> str:
        profile_text = profile_dict.get("candidate_profile", "")
        if isinstance(profile_text, dict):
            profile_text = profile_text.get("candidate_profile", str(profile_text))
        elif not profile_text:
            profile_text = str(profile_dict)
        clean_profile = re.sub(r"\s+", " ", profile_text).strip()

        clean_job = re.sub(r"\s+", " ", job_description).strip()
        clean_job_lower = clean_job.lower()

        boilerplate_anchors = [
            "perks:",
            "activity on internshala:",
            "view full job description",
        ]

        cutoff_index = len(clean_job)
        for anchor in boilerplate_anchors:
            idx = clean_job_lower.find(anchor)
            if idx != -1 and idx < cutoff_index:
                cutoff_index = idx

        clean_job = clean_job[:cutoff_index].strip()

        github_match = re.search(
            r"(https?://)?(www\.)?github\.com/[a-zA-Z0-9-_./]+", clean_profile
        )
        linkedin_match = re.search(
            r"(https?://)?(www\.)?linkedin\.com/[a-zA-Z0-9-_./]+", clean_profile
        )

        github_url = github_match.group(0) if github_match else "Not provided"
        linkedin_url = linkedin_match.group(0) if linkedin_match else "Not provided"

        if github_url != "Not provided" and not github_url.startswith("http"):
            github_url = "https://" + github_url
        if linkedin_url != "Not provided" and not linkedin_url.startswith("http"):
            linkedin_url = "https://" + linkedin_url

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

        # Extract internship tracking ID securely from the link target
        try:
            app_id = detail_url.rstrip("/").split("-")[-1].split("?")[0]
        except Exception:
            app_id = f"unknown_{random.randint(1000, 9999)}"

        # Spin up tracking profile block
        telemetry = ApplicationTelemetry(application_id=app_id)
        telemetry.start()

        ollama_url = profile_data.get("ollama_base_url", "http://127.0.0.1:11434")
        synthesizer = LLMResponseSynthesizer(base_url=ollama_url)
        status = "Execution_Error"

        try:
            # 1. Track Browser Navigation and initial rendering
            with telemetry.track("browser_navigation_time"):
                await page.goto(
                    detail_url, wait_until="domcontentloaded", timeout=45000
                )
                await self._human_idle_read_page(page)

                if (
                    await page.locator(
                        self.selectors["already_applied_indicator"]
                    ).count()
                    > 0
                ):
                    logger.info("Target job slot already exhibits an 'Applied' state.")
                    status = "Execution_Success"
                    return status

                apply_now_btn = page.locator(self.selectors["apply_now_button"]).first
                if await apply_now_btn.count() == 0:
                    status = "Execution_Error"
                    return status

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
            context_string = self.build_dense_context(clean_profile, job_desc)

            logger.info("Processing flat evaluation logic frame...")
            mcq_questions = await self._extract_visible_mcqs(page)
            text_questions = await self._extract_visible_text_questions(page)

            # 2. Phase A: Process MCQs via Ollama
            if mcq_questions:
                logger.info(f"Processing {len(mcq_questions)} MCQ field(s) first.")
                with telemetry.track("llm_mcq_time"):
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

                        if mcq.get("is_select", False):
                            await self._handle_dropdown_humanized(
                                mcq["name"], final_choice, page
                            )
                        else:
                            await self._handle_radio_checkbox_humanized(
                                mcq["name"], final_choice, page
                            )

                        await asyncio.sleep(0.8)

            # 3. Phase B: Process Open Text Fields via Ollama
            if text_questions:
                logger.info(f"Processing {len(text_questions)} text field(s).")
                prompt_list = [q["raw_text"] for q in text_questions]

                with telemetry.track("llm_text_time"):
                    llm_results = await synthesizer.match_responses(
                        prompts=prompt_list, context=context_string
                    )

                # 4. Phase C: Track Typing speed / human interaction frames
                with telemetry.track("dom_interaction_time"):
                    for q in text_questions:
                        ans_text = llm_results.get(
                            q["raw_text"], "Please refer to resume."
                        )
                        await self.direct_paste_answer(q["element"], ans_text, page)
                        await asyncio.sleep(random.uniform(0.3, 0.6))

            # 5. Finalization and Verification tracking
            with telemetry.track("dom_interaction_time"):
                status = await self._finalize_submission_pass(page)
            return status

        except Exception as e:
            logger.error(
                f"Pipeline transaction failed on target page: {e}", exc_info=True
            )
            status = "Execution_Error"
            return status
        finally:
            # Absolute confirmation stopwatch capture loop
            telemetry.stop(status=status)

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
                
                if (input.tagName.toLowerCase() === 'select') {
                    Array.from(input.options).forEach(opt => {
                        if (opt.value && opt.text && opt.text.trim()) {
                            groups[groupKey].options.push(opt.text.trim());
                        }
                    });
                } else {
                    let optionText = input.value; 
                    if (input.id) {
                        const linkedLabel = document.querySelector(`label[for="${input.id}"]`);
                        if (linkedLabel) optionText = linkedLabel.innerText;
                    }
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

            if "availability" in name_attr:
                continue

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

    async def direct_paste_answer(self, element, sanitized_text: str, page: Page):
        """
        Instantly injects the sanitized text directly into an extracted DOM element locator,
        perfectly mirroring a human Ctrl+C / Ctrl+V clipboard action.
        """
        # 1. Click the element handle directly to gain focus
        await element.click()

        # 2. Direct fill using the element handle instance
        await element.fill(sanitized_text)

        # 3. Fire a blur event via the global page keyboard instance
        await page.keyboard.press("Tab")

    async def _handle_dropdown_humanized(
        self, name_attribute: str, selected_option: str, page: Page
    ) -> bool:
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
        try:
            input_target = page.locator(
                f'input[name="{name_attribute}"][value="{selected_option}"]'
            ).first
            if await input_target.count() == 0:
                input_target = page.locator(f'input[value="{selected_option}"]').first

            if await input_target.count() > 0:
                await input_target.scroll_into_view_if_needed()

                if await input_target.is_checked():
                    return True

                input_id = await input_target.get_attribute("id")
                if input_id:
                    label_target = page.locator(f'label[for="{input_id}"]').first
                    if (
                        await label_target.count() > 0
                        and await label_target.is_visible()
                    ):
                        await label_target.click()
                        return True

                parent_label = input_target.locator("xpath=ancestor::label").first
                if await parent_label.count() > 0 and await parent_label.is_visible():
                    await parent_label.click()
                    return True

                logger.info(
                    f"Standard clicks blocked for '{name_attribute}'. Forcing click."
                )
                await input_target.click(force=True)
                return True

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

        for attempt in range(6):
            await asyncio.sleep(1.5)

            success_indicators = page.locator("text=/applied|submitted|success/i")
            if await success_indicators.count() > 0:
                logger.info("Submission verified via on-page success text elements.")
                return "Execution_Success"

            current_url = page.url.lower()
            if any(
                path in current_url for path in ["dashboard", "applications", "applied"]
            ):
                logger.info(f"Submission verified via URL redirect target: {page.url}")
                return "Execution_Success"

        current_url = page.url.lower()
        if any(
            path in current_url for path in ["dashboard", "applications", "applied"]
        ):
            logger.info("Submission verified via post-loop URL analysis.")
            return "Execution_Success"

        logger.error("Failed to verify submission success frames or redirect states.")
        return "Execution_Error"


class LLMResponseSynthesizer:
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
        You are an advanced AI assistant acting strictly as Ayush Sharma, a computer science student.

CRITICAL OUTPUT REQUIREMENTS:
1. You MUST output a single, valid JSON object matching the keys provided.
2. Do NOT include ANY HTML tags or Markdown formatting. Use plain text only.
3. Keep each individual answer concise and under 120 words.

SMART FIELD HANDLING RULES:
- FOR PORTFOLIO / WORK SAMPLE FIELDS: If a question asks for a portfolio link, website, or work samples, do NOT just output a raw URL. Instead, provide a multi-line professional pitch structured exactly like this:
  "Main Hub: [Insert Github Link from Context]
  
  Featured Project Highlight:
  - AMM Retriever: A Full-Stack Next.js + FastAPI system engineered with asynchronous data-ingestion pipelines (PyMuPDF) and Rank-BM25 lexical indexing to parse and query massive 1,850+ page aircraft manuals."
  
- FOR TECHNICAL EXPERIENCES: Base technical answers strictly on the candidate profile context.
        - FOR OPERATIONAL LOGISTICS: Always answer affirmatively (willing to relocate, comfortable with shifts, etc.).

        Expected Format:
        {
  "q_0": "Main Hub: https://github.com/ayushsharma-devs\n\nFeatured Project Highlight:\n- AMM Retriever: A Full-Stack Next.js and FastAPI application engineered with asynchronous data-ingestion pipelines using PyMuPDF and Rank-BM25 lexical indexing to parse and query massive 1,850+ page aircraft manuals.",
  "q_1": "I am fully comfortable with the proposed stipend structure, immediate joining timeline, and all operational logistics mentioned for this internship position.",
  "q_2": "Yes, I am completely comfortable with this requirement and am ready to comply with the team's working hours and scheduling protocols."
}
        """
        payload = {
            "model": self.model,
            "prompt": f"Instructions:\n{system_instructions}\n\nContext:\n{context}\n\nQuestion:\n{prompt}",
            "stream": False,
            "options": {"temperature": 0.2, "num_predict": 120, "top_k": 40},
        }
        async with httpx.AsyncClient(timeout=self.timeout_config) as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "").strip()
                sanitize_answer_text(raw)
                return raw
            except httpx.HTTPStatusError as e:
                print(f"API Error: {e.response.text}")
                return ""
            except Exception as e:
                print(f"Text Error: {e}")
                return ""

    async def generate_mcq_response(
        self, prompt: str, options: list[str], context: str
    ) -> str:
        options_block = "\n".join([f"- {opt}" for opt in options])

        system_instructions = (
            "You are a rigid data-extraction bot. Analyze the context and select the EXACT truest choice from the options list. "
            'You MUST output valid JSON only. Format: {"selected_option": "exact text from options"}.'
            '- WILLINGNESS & LOGISTICS: If the question asks if you are "okay with", "comfortable with", or willing to comply with operational requirements (like WFH, using specific software, shifts, or relocation), ALWAYS answer affirmatively.'
        )

        payload = {
            "model": self.model,
            "prompt": f"Instructions:\n{system_instructions}\n\nContext:\n{context}\n\nQuestion:\n{prompt}\n\nOptions:\n{options_block}",
            "stream": False,
            "format": "json",
            "options": {"temperature": 0.0, "num_predict": 40},
        }

        async with httpx.AsyncClient(timeout=self.timeout_config) as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "").strip()

                parsed_data = json.loads(raw)
                ans = parsed_data.get("selected_option", "")

                if ans not in options and len(options) > 0:
                    return options[0]

                return ans
            except httpx.HTTPStatusError as e:
                print(f"API Error: {e.response.text}")
                return ""
            except Exception as e:
                print(f"MCQ Error: {e}")
                return ""

    async def match_responses(self, prompts: list[str], context: str) -> dict[str, str]:
        results = {}
        for prompt in prompts:
            resp = await self.generate_response(prompt, context)
            if resp:
                results[prompt] = resp
        return results
