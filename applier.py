import asyncio
import random
import logging
import re
import html as html_module
import sys
import time
from pathlib import Path
from playwright.async_api import Page, Locator
import json 
import httpx

# #region agent log
_DEBUG_LOG_PATH = Path(__file__).resolve().parent / "debug-a0f361.log"


def _debug_log(
    hypothesis_id: str,
    location: str,
    message: str,
    data: dict | None = None,
    run_id: str = "run",
) -> None:
    try:
        payload = {
            "sessionId": "a0f361",
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data or {},
            "timestamp": int(time.time() * 1000),
            "runId": run_id,
        }
        with open(_DEBUG_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")
    except OSError:
        pass
# #endregion

# Clean execution tracking
logger = logging.getLogger("Applier")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Flip to True when you are ready to actually submit applications.
ENABLE_SUBMIT = True
# Internshala text areas reject essay-length paste; keep answers concise.
MAX_ANSWER_CHARS = 900


def sanitize_answer_text(text: str) -> str:
    """Strip HTML/markdown noise and normalize whitespace for plain-text form fields."""
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


# Whole-label phrases to skip (not substring tokens like "available").
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
)


def _label_matches_skip_phrase(label: str, phrases: tuple[str, ...]) -> bool:
    lower = label.lower()
    return any(phrase in lower for phrase in phrases)


class FormInspector:
    """Handles all read-only operations on the browser DOM."""
    def __init__(self, page: Page, selectors: dict):
        self.page = page
        self.selectors = selectors

    async def is_already_applied(self) -> bool:
        selector = self.selectors.get("already_applied_indicator")
        if not selector:
            return False
        return await self.page.locator(selector).count() > 0

    async def trigger_form(self, actor: "HumanActor | None" = None) -> bool:
        selector = self.selectors.get("apply_now_button")
        btn = self.page.locator(selector)
        if await btn.count() == 0:
            return False
        if actor:
            await actor.human_click(btn.first)
        else:
            await btn.first.click()
        await actor.pause(1.8, 3.2) if actor else await asyncio.sleep(2.0)
        return True

    async def _resolve_field_label(self, input_el: Locator) -> str:
        clean_label = await input_el.evaluate("""element => {
            const container = element.closest('.form-group, .assessment_question_container');
            if (!container) return '';

            const labelElement = container.querySelector('label, .assessment_question, .control-label, .question-heading');
            if (labelElement) {
                const clone = labelElement.cloneNode(true);
                const noise = clone.querySelectorAll('.badge, .text-muted, .help-block, span, .chars_remaining');
                noise.forEach(n => n.remove());
                return clone.innerText.trim();
            }

            let sibling = element.previousElementSibling;
            if (sibling && sibling.innerText && sibling.innerText.trim()) {
                return sibling.innerText.trim();
            }
            return '';
        }""")
        return " ".join(clean_label.split()).strip()

    async def extract_questions(self) -> list[dict]:
        """Collect labeled, visible text fields only (no raw DOM index mapping)."""
        input_selector = self.selectors.get("form_text_inputs")
        locator = self.page.locator(input_selector)
        count = await locator.count()

        questions = []
        skip_log = []

        for idx in range(count):
            field = locator.nth(idx)
            if not await field.is_visible():
                skip_log.append({"idx": idx, "reason": "hidden"})
                continue

            clean_text = await self._resolve_field_label(field)
            if not clean_text:
                logger.warning(f"Label resolved to blank string at input index {idx}. Skipping field processing.")
                skip_log.append({"idx": idx, "reason": "blank_label"})
                continue

            if _label_matches_skip_phrase(clean_text, TEXT_FIELD_SKIP_PHRASES) or "apply now" in clean_text.lower():
                logger.info(f"Skipping irrelevant field frame at input index {idx}: '{clean_text[:40]}...'")
                skip_log.append({"idx": idx, "reason": "skip_phrase", "label": clean_text[:60]})
                continue

            questions.append({"raw_text": clean_text})

        # #region agent log
        _debug_log(
            "H2-H3",
            "applier.py:extract_questions",
            "extracted visible text questions",
            {"count": len(questions), "labels": [q["raw_text"][:50] for q in questions], "skipped": skip_log},
        )
        # #endregion
        return questions

    async def count_visible_text_fields(self) -> int:
        input_selector = self.selectors.get("form_text_inputs")
        locator = self.page.locator(input_selector)
        visible_text = 0
        for idx in range(await locator.count()):
            if await locator.nth(idx).is_visible():
                visible_text += 1
        return visible_text

    async def count_raw_mcq_inputs(self) -> int:
        return await self.page.evaluate(
            """() => document.querySelectorAll(
                "input[type='checkbox'], input[type='radio']"
            ).length"""
        )

    async def extract_mcq_questions(self) -> list[dict]:
        """
        Extracts checkbox and radio groups, collecting all sibling choices 
        by their form name attribute to provide complete option context.
        """
        mcq_groups = await self.page.evaluate("""() => {
            const inputs = Array.from(document.querySelectorAll("input[type='checkbox'], input[type='radio']"));
            const groups = {};
            
            inputs.forEach(input => {
                const groupKey = input.name || input.closest('.form-group, .assessment_question_container')?.className || 'unnamed_group';
                
                if (!groups[groupKey]) {
                    const container = input.closest('.form-group, .assessment_question_container, .assessment_question');
                    let labelText = '';
                    if (container) {
                        const labelEl = container.querySelector('label, .assessment_question, .question-heading, .control-label');
                        if (labelEl) {
                            const clone = labelEl.cloneNode(true);
                            const noise = clone.querySelectorAll('.badge, .text-muted, .help-block, span, .chars_remaining');
                            noise.forEach(n => n.remove());
                            labelText = clone.innerText.trim();
                        }
                    }
                    
                    groups[groupKey] = {
                        name: input.name || '',
                        raw_text: labelText || 'Select an option:',
                        options: []
                    };
                }
                
                if (input.value) {
                    groups[groupKey].options.push(input.value.trim());
                }
            });
            return Object.values(groups);
        }""")
        
        cleaned_mcqs = []

        for g in mcq_groups:
            text = " ".join(g["raw_text"].split()).strip()
            if not g["options"]:
                continue
            if _label_matches_skip_phrase(text, MCQ_SKIP_PHRASES):
                continue
            if len(g["options"]) == 1 and g["options"][0].lower() in {"on", "off"}:
                continue
            cleaned_mcqs.append({
                "name": g["name"],
                "raw_text": text,
                "options": list(dict.fromkeys(g["options"])),
            })

        # #region agent log
        _debug_log(
            "H4",
            "applier.py:extract_mcq_questions",
            "extracted mcq groups",
            {"count": len(cleaned_mcqs), "questions": [m["raw_text"][:50] for m in cleaned_mcqs]},
        )
        # #endregion
        return cleaned_mcqs

    async def verify_submission_success(self) -> bool:
        """Require a positive on-page success signal; never infer success from a missing Submit btn."""
        signals: dict[str, bool] = {}

        if await self.is_already_applied():
            signals["already_applied"] = True
            # #region agent log
            _debug_log("H1", "applier.py:verify_submission_success", "verified", signals)
            # #endregion
            return True

        success_phrases = (
            "text=Application submitted",
            "text=Successfully applied",
            "text=already applied",
            "text=Already applied",
            ".applied_notification",
        )
        for phrase in success_phrases:
            found = await self.page.locator(phrase).count() > 0
            signals[f"phrase:{phrase}"] = found
            if found:
                # #region agent log
                _debug_log("H1", "applier.py:verify_submission_success", "verified", signals)
                # #endregion
                return True

        error_selectors = (
            ".error:visible, .alert-danger:visible, .form-error:visible, "
            ".has-error:visible, .invalid-feedback:visible"
        )
        has_errors = await self.page.locator(error_selectors).count() > 0
        signals["validation_errors"] = has_errors
        if has_errors:
            # #region agent log
            _debug_log("H1", "applier.py:verify_submission_success", "rejected", signals)
            # #endregion
            return False

        submit_selector = self.selectors.get("final_submit_button")
        submit_visible = bool(
            submit_selector and await self.page.locator(submit_selector).count() > 0
        )
        signals["submit_still_visible"] = submit_visible
        # #region agent log
        _debug_log("H1", "applier.py:verify_submission_success", "rejected_no_positive_signal", signals)
        # #endregion
        return False


class LLMResponseSynthesizer:
    def __init__(self, base_url: str = "http://localhost:11434", model: str = "llama3.2"):
        self.base_url = f"{base_url}/api/generate"
        self.model = model
        self.timeout_config = httpx.Timeout(None)

    async def generate_response(self, prompt: str, context: str) -> str:
        """Executes targeted first-person context responses with strict structural guardrails."""
        system_instructions = (
            "You are Ayush Sharma answering an internship application question. "
            "Write plain text only: no HTML, no Markdown, no <br>, no bullet lists, no headers. "
            "Use 2-4 short sentences (under 80 words). Start with proper capitalization (I, not i). "
            "Answer only from the resume context; do not invent details. "
            "Ignore ollama_base_url and any JSON keys in the context."
        )

        payload = {
            "model": self.model,
            "prompt": f"Instructions:\n{system_instructions}\n\nContext:\n{context}\n\nQuestion:\n{prompt}",
            "stream": False
        }

        async with httpx.AsyncClient(timeout=self.timeout_config) as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
                raw = response.json().get("response", "").strip()
                return sanitize_answer_text(raw)
            except Exception as e:
                logger.error(f"Inference pipeline failure: {e}")
                return ""

    async def generate_mcq_response(self, prompt: str, options: list[str], context: str) -> str:
        """Forces the local model to perform clean single-option classification from context context."""
        options_block = "\n".join([f"- {opt}" for opt in options])
        system_instructions = (
            "You are Ayush Sharma answering a multiple-choice question. "
            "Analyze your context, skills, and experience to pick the single truest choice. "
            "You MUST reply with exactly one item from the provided options list verbatim. "
            "Do not add punctuation, explanations, markdown wrappers, or extra dialogue."
        )
        
        payload = {
            "model": self.model,
            "prompt": f"Instructions:\n{system_instructions}\n\nContext:\n{context}\n\nQuestion:\n{prompt}\n\nOptions:\n{options_block}\n\nSelection:",
            "stream": False
        }
        
        async with httpx.AsyncClient(timeout=self.timeout_config) as client:
            try:
                response = await client.post(self.base_url, json=payload)
                response.raise_for_status()
                ans = response.json().get("response", "").strip()
                return ans.strip('"\'')
            except Exception as e:
                logger.error(f"MCQ option classification failure: {e}")
                return ""

    async def match_responses(self, prompts: list[str], context: str) -> dict[str, str]:
        """Processes prompts sequentially to prevent CPU processing thrash."""
        results = {}
        for prompt in prompts:
            logger.info(f"Processing inference task for prompt: '{prompt[:40]}...'")
            resp = await self.generate_response(prompt, context)
            results[prompt] = resp if resp else "Please refer to my resume for relevant experience."
        return results


class HumanActor:
    """Simulates natural pointer, keyboard, and reading behavior to reduce bot fingerprints."""
    _SELECT_ALL = "Meta+A" if sys.platform == "darwin" else "Control+A"

    def __init__(self, page: Page, selectors: dict, inspector: FormInspector | None = None):
        self.page = page
        self.selectors = selectors
        self.inspector = inspector

    async def pause(self, min_s: float = 0.3, max_s: float = 1.0) -> None:
        await asyncio.sleep(random.uniform(min_s, max_s))

    async def _move_pointer_to(self, x: float, y: float) -> None:
        await self.page.mouse.move(x, y, steps=random.randint(10, 24))

    async def _move_pointer_to_element(self, element: Locator) -> None:
        box = await element.bounding_box()
        if not box:
            return
        x = box["x"] + box["width"] * random.uniform(0.25, 0.75)
        y = box["y"] + box["height"] * random.uniform(0.25, 0.75)
        await self._move_pointer_to(x, y)

    async def human_click(self, element: Locator) -> None:
        await element.scroll_into_view_if_needed()
        await self.pause(0.15, 0.55)
        await self._move_pointer_to_element(element)
        await self.pause(0.05, 0.2)
        await element.click(delay=random.randint(60, 180), timeout=8000)

    async def idle_read_page(self) -> None:
        """Short scroll-and-pause bursts that mimic skimming a listing before acting."""
        passes = random.randint(1, 3)
        for _ in range(passes):
            delta = random.randint(90, 280) * random.choice((1, 1, -1))
            await self.page.mouse.wheel(0, delta)
            await self.pause(0.7, 2.1)

    async def clear_and_type(self, element: Locator, text: str) -> None:
        await element.scroll_into_view_if_needed()
        await self.pause(0.25, 0.7)
        await self.human_click(element)

        await self.page.keyboard.press(self._SELECT_ALL)
        await self.pause(0.04, 0.12)
        await self.page.keyboard.press("Backspace")
        await self.pause(0.1, 0.25)

        chunk_size = random.randint(3, 8)
        for offset in range(0, len(text), chunk_size):
            chunk = text[offset : offset + chunk_size]
            delay = random.uniform(45, 110)
            await element.press_sequentially(chunk, delay=delay, timeout=0)
            if random.random() < 0.12:
                await self.pause(0.25, 0.85)

        await self.pause(0.2, 0.55)

    async def check_mcq_option(self, name_attribute: str, selected_option: str) -> bool:
        """Selects a choice via label or natural click — avoids force-check and DOM injection."""
        try:
            direct_selector = f'input[name="{name_attribute}"][value="{selected_option}"]'
            target = self.page.locator(direct_selector).first

            if await target.count() == 0:
                target = self.page.locator(f'input[value="{selected_option}"]').first
            if await target.count() == 0:
                return False

            await target.scroll_into_view_if_needed()
            await self.pause(0.35, 0.9)

            input_id = await target.get_attribute("id")
            if input_id:
                label = self.page.locator(f'label[for="{input_id}"]')
                if await label.count() > 0:
                    await self.human_click(label.first)
                    await self.pause(0.35, 0.75)
                    return True

            parent_label = target.locator("xpath=ancestor::label[1]")
            if await parent_label.count() > 0:
                await self.human_click(parent_label.first)
                await self.pause(0.35, 0.75)
                return True

            await self.human_click(target)
            await self.pause(0.35, 0.75)
            return True
        except Exception as e:
            logger.error(f"Failed to select option '{selected_option}' for '{name_attribute}': {e}")
            return False

    async def populate_form(self, answers_by_label: dict[str, str]) -> bool:
        """Fill visible fields by matching question label at fill time (re-query DOM each run)."""
        try:
            input_selector = self.selectors.get("form_text_inputs")
            locator = self.page.locator(input_selector)
            filled_labels: list[str] = []

            for idx in range(await locator.count()):
                field = locator.nth(idx)
                if not await field.is_visible():
                    continue

                if not self.inspector:
                    continue
                label = await self.inspector._resolve_field_label(field)
                if not label or label not in answers_by_label:
                    continue

                await self.clear_and_type(field, answers_by_label[label])
                filled_labels.append(label[:50])
                await self.pause(0.4, 1.2)

            # #region agent log
            _debug_log(
                "H3",
                "applier.py:populate_form",
                "fill complete",
                {"requested": list(answers_by_label.keys()), "filled": filled_labels},
            )
            # #endregion
            return len(filled_labels) == len(answers_by_label)
        except Exception as e:
            logger.error(f"HumanActor inputs interrupted: {e}")
            # #region agent log
            _debug_log("H3", "applier.py:populate_form", "fill failed", {"error": str(e)})
            # #endregion
            return False

    async def trigger_submission(self) -> bool:
        """Clicks submit when enabled. Returns True if the click was attempted."""
        if not ENABLE_SUBMIT:
            logger.info("Dry-run: form filled but submit skipped (ENABLE_SUBMIT=False).")
            return False

        submit_selector = self.selectors.get("final_submit_button")
        if not submit_selector:
            logger.warning("No final_submit_button selector configured.")
            return False

        submit_btn = self.page.locator(submit_selector)
        if await submit_btn.count() == 0:
            logger.warning("Submit button not visible on page.")
            return False

        await submit_btn.first.scroll_into_view_if_needed()
        await self.pause(0.8, 2.0)
        await self.human_click(submit_btn.first)
        await self.pause(2.0, 4.0)
        logger.info("Submit button clicked.")
        return True

class ApplicationPipeline:
    def __init__(self, page: Page, platform_config: dict, profile_data: dict):
        self.page = page
        self.config = platform_config
        self.profile_data = profile_data  
        selectors = platform_config.get("selectors", {})
        
        self.inspector = FormInspector(page, selectors)
        ollama_url = profile_data.get("ollama_base_url", "http://localhost:11434") if isinstance(profile_data, dict) else "http://localhost:11434"
        self.synthesizer = LLMResponseSynthesizer(base_url=ollama_url)
        self.actor = HumanActor(page, selectors, inspector=self.inspector)

    async def apply_to_job(self, job_url: str) -> str:
        platform = self.config.get("platform_name", "Unknown_Platform")
        logger.info(f"Navigating pipeline stream to target link: {job_url}")
        
        try:
            await self.page.goto(job_url, wait_until="domcontentloaded", timeout=45000)
            await self.actor.idle_read_page()
            await self.actor.pause(1.5, 3.5)

            if await self.inspector.is_already_applied():
                logger.info(f"[{platform}] Match skipped: Position already marked 'Applied'.")
                return "Already_Applied"

            if not await self.inspector.trigger_form(self.actor):
                logger.warning(f"[{platform}] Application layout structure was unreachable.")
                return "Form_Trigger_Failed"

            context_string = json.dumps(self.profile_data) if isinstance(self.profile_data, dict) else str(self.profile_data)

            # 1. Gather both text and descriptive multiple choice inputs
            questions = await self.inspector.extract_questions()
            mcq_questions = await self.inspector.extract_mcq_questions()
            visible_text_count = await self.inspector.count_visible_text_fields()
            raw_mcq_count = await self.inspector.count_raw_mcq_inputs()

            if not questions and not mcq_questions:
                if visible_text_count == 0 and raw_mcq_count == 0:
                    logger.info("Resume-only form detected (no extra questions). Proceeding to submit.")
                    # #region agent log
                    _debug_log(
                        "H5",
                        "applier.py:apply_to_job",
                        "resume_only_submit",
                        {"visible_text": visible_text_count, "mcqs": raw_mcq_count},
                    )
                    # #endregion
                    return await self._finalize_application()

                logger.warning(
                    f"Form has {visible_text_count} visible text field(s) and/or MCQs "
                    f"but none were extracted — refusing empty submit."
                )
                # #region agent log
                _debug_log(
                    "H5",
                    "applier.py:apply_to_job",
                    "blocked_empty_submit",
                    {"visible_text": visible_text_count, "mcqs": raw_mcq_count},
                )
                # #endregion
                return "Incomplete_Form"

            # 2. Complete descriptive text fields if present
            if questions:
                prompt_list = [q["raw_text"] for q in questions]
                llm_results = await self.synthesizer.match_responses(prompts=prompt_list, context=context_string)

                answers_by_label: dict[str, str] = {}
                for q in questions:
                    text = q["raw_text"]
                    raw_answer = llm_results.get(text, "Please refer to my resume for relevant experience.")
                    answers_by_label[text] = sanitize_answer_text(raw_answer)

                success = await self.actor.populate_form(answers_by_label)
                if not success:
                    return "Manual_Review"

            # 3. Complete context-based option selection if present
            if mcq_questions:
                for mcq in mcq_questions:
                    logger.info(f"Evaluating MCQ: '{mcq['raw_text'][:40]}...' Options Count: {len(mcq['options'])}")
                    selected_option = await self.synthesizer.generate_mcq_response(
                        prompt=mcq["raw_text"],
                        options=mcq["options"],
                        context=context_string,
                    )

                    matched_option = None
                    for opt in mcq["options"]:
                        if opt.lower() in selected_option.lower() or selected_option.lower() in opt.lower():
                            matched_option = opt
                            break

                    if matched_option:
                        logger.info(f"Selecting option match: '{matched_option}'")
                        await self.actor.check_mcq_option(mcq["name"], matched_option)
                    else:
                        logger.warning(f"LLM choice output outside constraints ('{selected_option}'). Using structural fallback.")
                        await self.actor.check_mcq_option(mcq["name"], mcq["options"][0])

            return await self._finalize_application()

        except Exception as e:
            logger.error(f"Pipeline transaction failed on target page: {e}", exc_info=True)
            return "Execution_Error"

    async def _finalize_application(self) -> str:
        clicked = await self.actor.trigger_submission()
        if not ENABLE_SUBMIT:
            return "Filled_Not_Submitted"
        if not clicked:
            return "Submit_Button_Missing"

        for attempt in range(6):
            await self.actor.pause(1.0, 1.5)
            if await self.inspector.verify_submission_success():
                logger.info("Submission verified on page.")
                return "Applied"
            logger.info(f"Waiting for submission confirmation (attempt {attempt + 1}/6)...")

        logger.warning("Submit clicked but form still appears open or has validation errors.")
        return "Submit_Failed"