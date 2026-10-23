"""LinkedIn DOM automation for Job Search, Job Description Extraction, and Easy Apply Modals."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

from playwright.async_api import Page

from .browser_manager import BrowserSessionManager
from .profile_store import CandidateProfileStore

WORKPLACE_CODES = {
    "onsite": "1",
    "on-site": "1",
    "remote": "2",
    "hybrid": "3",
}

DATE_POSTED_CODES = {
    "24h": "r86400",
    "day": "r86400",
    "week": "r604800",
    "month": "r2592000",
}


class LinkedInAutomator:
    """High-level Playwright controller for LinkedIn Jobs and Easy Apply workflows."""

    def __init__(
        self,
        browser_manager: Optional[BrowserSessionManager] = None,
        profile_store: Optional[CandidateProfileStore] = None,
    ) -> None:
        self.browser = browser_manager or BrowserSessionManager()
        self.profile = profile_store or CandidateProfileStore()

    async def check_session_status(self) -> Dict[str, Any]:
        """Check browser connection and whether the current session is authenticated on LinkedIn."""
        page = await self.browser.get_page()
        current_url = page.url
        if "linkedin.com" not in current_url and not current_url.startswith("file://"):
            await page.goto("https://www.linkedin.com/jobs/", wait_until="domcontentloaded", timeout=30000)
            current_url = page.url

        title = await page.title()
        is_logged_in = not any(
            marker in current_url.lower() for marker in ("/login", "/authwall", "uas/login")
        )
        return {
            "connection_type": self.browser.connection_type,
            "current_url": current_url,
            "page_title": title,
            "logged_in": is_logged_in,
        }

    def build_search_url(
        self,
        keywords: str,
        location: str = "",
        easy_apply_only: bool = True,
        workplace_type: Optional[str] = None,
        date_posted: Optional[str] = None,
    ) -> str:
        """Construct the LinkedIn Jobs search URL with appropriate query parameters."""
        params = [f"keywords={quote_plus(keywords.strip())}"]
        if location.strip():
            params.append(f"location={quote_plus(location.strip())}")
        if easy_apply_only:
            params.append("f_AL=true")
        if workplace_type and workplace_type.lower().strip() in WORKPLACE_CODES:
            params.append(f"f_WT={WORKPLACE_CODES[workplace_type.lower().strip()]}")
        if date_posted and date_posted.lower().strip() in DATE_POSTED_CODES:
            params.append(f"f_TPR={DATE_POSTED_CODES[date_posted.lower().strip()]}")
        return f"https://www.linkedin.com/jobs/search/?{'&'.join(params)}"

    async def search_jobs(
        self,
        keywords: str,
        location: str = "",
        easy_apply_only: bool = True,
        workplace_type: Optional[str] = None,
        date_posted: Optional[str] = None,
        limit: int = 15,
        custom_url: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Navigate to LinkedIn Jobs search and extract matching job cards."""
        page = await self.browser.get_page()
        target_url = custom_url or self.build_search_url(
            keywords=keywords,
            location=location,
            easy_apply_only=easy_apply_only,
            workplace_type=workplace_type,
            date_posted=date_posted,
        )
        await page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1200)

        jobs = await self.extract_job_cards(page, limit=limit)
        return {
            "search_url": page.url,
            "count": len(jobs),
            "jobs": jobs,
        }

    async def extract_job_cards(self, page: Page, limit: int = 15) -> List[Dict[str, Any]]:
        """Extract job cards from the current LinkedIn Jobs search page."""
        js_extract = """
        (maxItems) => {
            const selectors = [
                'li[data-occludable-job-id]',
                'div.job-card-container[data-job-id]',
                'div.base-card[data-entity-urn*="jobPosting"]'
            ];
            let cards = [];
            for (const sel of selectors) {
                const found = Array.from(document.querySelectorAll(sel));
                if (found.length > 0) {
                    cards = found;
                    break;
                }
            }
            return cards.slice(0, maxItems).map(card => {
                const jobId = (
                    card.getAttribute('data-occludable-job-id') ||
                    card.getAttribute('data-job-id') ||
                    (card.getAttribute('data-entity-urn') || '').split(':').pop() ||
                    ''
                ).trim();
                const titleEl = card.querySelector('.job-card-list__title, .artdeco-entity-lockup__title, .base-search-card__title, a.job-card-container__link');
                const companyEl = card.querySelector('.job-card-container__primary-description, .artdeco-entity-lockup__subtitle, .base-search-card__subtitle');
                const locEl = card.querySelector('.job-card-container__metadata-item, .artdeco-entity-lockup__caption, .job-search-card__location');
                const linkEl = card.querySelector('a[href*="/jobs/view/"], a.job-card-container__link, a.base-card__full-link');
                const cardText = card.innerText || '';
                const isEasyApply = /easy apply/i.test(cardText);
                const rawTitle = titleEl ? titleEl.innerText.trim().split('\\n')[0] : '';
                return {
                    job_id: jobId,
                    title: rawTitle,
                    company: companyEl ? companyEl.innerText.trim() : '',
                    location: locEl ? locEl.innerText.trim() : '',
                    easy_apply: isEasyApply,
                    url: linkEl ? linkEl.href : (jobId ? `https://www.linkedin.com/jobs/view/${jobId}/` : '')
                };
            });
        }
        """
        return await page.evaluate(js_extract, limit)

    async def get_job_details(self, job_id_or_url: str) -> Dict[str, Any]:
        """Navigate to a job posting and extract its full description and Easy Apply status."""
        page = await self.browser.get_page()
        target = job_id_or_url.strip()
        if not target.startswith(("http://", "https://", "file://")):
            job_id = re.sub(r"\D", "", target)
            target = f"https://www.linkedin.com/jobs/view/{job_id}/"

        if page.url != target:
            await page.goto(target, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1000)

        details = await page.evaluate(
            """
            () => {
                const titleEl = document.querySelector(
                    '.job-details-jobs-unified-top-card__job-title, h1.t-24, h1.top-card-layout__title, h1'
                );
                const companyEl = document.querySelector(
                    '.job-details-jobs-unified-top-card__company-name, .topcard__org-name-link, .job-details-company'
                );
                const descEl = document.querySelector(
                    '#job-details, .jobs-description__content, .jobs-box__html-content, .show-more-less-html__markup'
                );
                const applyBtn = document.querySelector(
                    'button.jobs-apply-button, button[aria-label*="Easy Apply"]'
                );
                return {
                    title: titleEl ? titleEl.innerText.trim() : '',
                    company: companyEl ? companyEl.innerText.trim() : '',
                    description: descEl ? descEl.innerText.trim() : '',
                    easy_apply_available: Boolean(applyBtn && /easy apply/i.test(applyBtn.innerText || applyBtn.getAttribute('aria-label') || '')),
                    url: window.location.href
                };
            }
            """
        )
        return details

    async def start_easy_apply(self, job_id_or_url: Optional[str] = None) -> Dict[str, Any]:
        """Click the 'Easy Apply' button on the job page and inspect the opened modal."""
        page = await self.browser.get_page()
        if job_id_or_url:
            await self.get_job_details(job_id_or_url)

        modal_locator = page.locator(
            "div.jobs-easy-apply-modal, div[data-test-modal-id='easy-apply-modal'], div[role='dialog'].artdeco-modal"
        )
        if await modal_locator.count() == 0 or not await modal_locator.first.is_visible():
            apply_btn = page.locator(
                "button.jobs-apply-button, button[aria-label*='Easy Apply']"
            ).first
            if await apply_btn.count() == 0:
                raise RuntimeError("No 'Easy Apply' button found on the current page.")
            await apply_btn.click()
            await page.wait_for_timeout(800)

        return await self.inspect_easy_apply_modal()

    async def inspect_easy_apply_modal(self) -> Dict[str, Any]:
        """Inspect all form fields, validation errors, and action buttons inside the active Easy Apply modal."""
        page = await self.browser.get_page()
        state = await page.evaluate(
            """
            () => {
                const modal = document.querySelector(
                    'div.jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], div[role="dialog"].artdeco-modal'
                );
                if (!modal) {
                    return { modal_open: false };
                }

                const headerEl = modal.querySelector('h2, h3, .artdeco-modal__header');
                const progressEl = modal.querySelector('progress, [role="progressbar"]');
                const progressValue = progressEl ? (progressEl.getAttribute('value') || progressEl.getAttribute('aria-valuenow')) : null;

                const fields = [];
                const seenIds = new Set();

                // 1. Text, number, tel, email, textarea inputs & selects
                const controls = modal.querySelectorAll('input:not([type="hidden"]):not([type="radio"]):not([type="checkbox"]):not([type="file"]), textarea, select');
                controls.forEach((el, idx) => {
                    const id = el.id || el.name || `field_${idx}`;
                    if (seenIds.has(id)) return;
                    seenIds.add(id);

                    let labelText = '';
                    if (el.id) {
                        const lbl = modal.querySelector(`label[for="${CSS.escape(el.id)}"]`);
                        if (lbl) labelText = lbl.innerText.trim();
                    }
                    if (!labelText) {
                        const parentLbl = el.closest('label') || (el.parentElement && el.parentElement.querySelector('label'));
                        if (parentLbl) labelText = parentLbl.innerText.trim();
                    }
                    if (!labelText) {
                        labelText = el.getAttribute('aria-label') || el.getAttribute('placeholder') || id;
                    }
                    labelText = labelText.replace(/\\n+/g, ' ').trim();

                    const tag = el.tagName.toLowerCase();
                    const type = tag === 'select' ? 'select' : (tag === 'textarea' ? 'textarea' : (el.type || 'text'));
                    const options = tag === 'select'
                        ? Array.from(el.options).map(o => o.text.trim()).filter(Boolean)
                        : null;

                    fields.push({
                        field_id: id,
                        selector: el.id ? `#${CSS.escape(el.id)}` : (el.name ? `${tag}[name="${CSS.escape(el.name)}"]` : ''),
                        label: labelText,
                        type: type,
                        required: el.required || el.getAttribute('aria-required') === 'true' || /\\*/.test(labelText),
                        value: el.value || '',
                        options: options
                    });
                });

                // 2. Radio fieldsets
                const fieldsets = modal.querySelectorAll('fieldset');
                fieldsets.forEach((fs, idx) => {
                    const radios = Array.from(fs.querySelectorAll('input[type="radio"]'));
                    if (radios.length === 0) return;
                    const legend = fs.querySelector('legend, span[data-test-form-builder-radio-button-form-component__title]');
                    const labelText = (legend ? legend.innerText : fs.innerText.split('\\n')[0]).replace(/\\n+/g, ' ').trim();
                    const name = radios[0].name || `radio_group_${idx}`;
                    const options = radios.map(r => {
                        const rl = r.id ? fs.querySelector(`label[for="${CSS.escape(r.id)}"]`) : r.closest('label');
                        return rl ? rl.innerText.trim() : r.value;
                    });
                    const checked = radios.find(r => r.checked);
                    let checkedVal = '';
                    if (checked) {
                        const rl = checked.id ? fs.querySelector(`label[for="${CSS.escape(checked.id)}"]`) : checked.closest('label');
                        checkedVal = rl ? rl.innerText.trim() : checked.value;
                    }
                    fields.push({
                        field_id: name,
                        selector: `fieldset input[name="${CSS.escape(name)}"]`,
                        label: labelText,
                        type: 'radio',
                        required: true,
                        value: checkedVal,
                        options: options
                    });
                });

                // 3. File upload inputs (Resume / Cover Letter)
                const fileInputs = modal.querySelectorAll('input[type="file"]');
                fileInputs.forEach((fl, idx) => {
                    fields.push({
                        field_id: fl.id || `file_upload_${idx}`,
                        selector: fl.id ? `#${CSS.escape(fl.id)}` : 'input[type="file"]',
                        label: fl.getAttribute('aria-label') || 'Upload Resume / Document',
                        type: 'file',
                        required: false,
                        value: '',
                        options: null
                    });
                });

                // 4. Action buttons in modal footer
                const buttons = Array.from(modal.querySelectorAll('footer button, button.artdeco-button--primary')).map(b => {
                    return (b.innerText || b.getAttribute('aria-label') || '').trim();
                }).filter(Boolean);

                const errors = Array.from(modal.querySelectorAll('.artdeco-inline-feedback--error, [role="alert"]'))
                    .map(e => e.innerText.trim())
                    .filter(Boolean);

                const readyToSubmit = buttons.some(b => /submit application/i.test(b));

                return {
                    modal_open: true,
                    step_header: headerEl ? headerEl.innerText.trim().split('\\n')[0] : '',
                    progress: progressValue,
                    fields: fields,
                    buttons: buttons,
                    validation_errors: errors,
                    ready_to_submit: readyToSubmit
                };
            }
            """
        )

        # Annotate each field with suggested profile value if currently empty
        if state.get("modal_open"):
            for fld in state.get("fields", []):
                fld["suggested_from_profile"] = self.profile.match_question(
                    fld["label"], fld["type"], fld.get("options")
                )
        return state

    async def fill_easy_apply_step(
        self,
        answers: Optional[Dict[str, str]] = None,
        auto_fill_from_profile: bool = True,
        upload_resume: bool = False,
        advance_step: bool = True,
    ) -> Dict[str, Any]:
        """Fill fields in the current Easy Apply modal step and optionally click Next/Review (never auto-submits)."""
        page = await self.browser.get_page()
        state = await self.inspect_easy_apply_modal()
        if not state.get("modal_open"):
            raise RuntimeError("Easy Apply modal is not currently open.")

        answers = answers or {}
        filled_actions: List[Dict[str, str]] = []

        for fld in state.get("fields", []):
            f_type = fld["type"]
            f_id = fld["field_id"]
            label = fld["label"]

            # Determine desired value: explicit answers override profile suggestions
            desired: Optional[str] = None
            for k, v in answers.items():
                if k == f_id or k.lower() == label.lower() or k.lower() in label.lower():
                    desired = str(v)
                    break

            if desired is None and auto_fill_from_profile:
                # Only overwrite empty fields or select placeholders
                current_val = (fld.get("value") or "").strip()
                if not current_val or current_val.lower().startswith("select"):
                    desired = fld.get("suggested_from_profile")

            if f_type == "file":
                resume_path = desired or (
                    self.profile.data.get("resume_path") if upload_resume else None
                )
                if resume_path and Path(resume_path).expanduser().exists():
                    file_loc = page.locator(fld["selector"]).first
                    await file_loc.set_input_files(str(Path(resume_path).expanduser().resolve()))
                    filled_actions.append({"field": label, "value": str(resume_path)})
                continue

            if desired is None or desired == "":
                continue

            if f_type in ("text", "tel", "email", "number", "url", "textarea"):
                loc = page.locator(fld["selector"]).first
                if await loc.count() > 0:
                    await loc.fill(desired)
                    filled_actions.append({"field": label, "value": desired})

            elif f_type == "select":
                loc = page.locator(fld["selector"]).first
                if await loc.count() > 0:
                    best_opt = self.profile._pick_best_option(desired, fld.get("options"))
                    try:
                        await loc.select_option(label=best_opt)
                    except Exception:
                        await loc.select_option(value=best_opt)
                    filled_actions.append({"field": label, "value": best_opt})

            elif f_type == "radio":
                best_opt = self.profile._pick_best_option(desired, fld.get("options"))
                await page.evaluate(
                    """
                    ({ name, targetOption }) => {
                        const modal = document.querySelector(
                            'div.jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], div[role="dialog"].artdeco-modal'
                        );
                        if (!modal) return;
                        const radios = Array.from(modal.querySelectorAll(`input[type="radio"][name="${CSS.escape(name)}"]`));
                        for (const r of radios) {
                            const lbl = r.id ? modal.querySelector(`label[for="${CSS.escape(r.id)}"]`) : r.closest('label');
                            const text = lbl ? lbl.innerText.trim() : r.value;
                            if (text.toLowerCase() === targetOption.toLowerCase() || r.value.toLowerCase() === targetOption.toLowerCase()) {
                                r.click();
                                r.checked = true;
                                r.dispatchEvent(new Event('change', { bubbles: true }));
                                break;
                            }
                        }
                    }
                    """,
                    {"name": f_id, "targetOption": best_opt},
                )
                filled_actions.append({"field": label, "value": best_opt})

        advanced_to_next = False
        if advance_step and not state.get("ready_to_submit"):
            # Click 'Next' or 'Review' button, NEVER 'Submit application'
            clicked = await page.evaluate(
                """
                () => {
                    const modal = document.querySelector(
                        'div.jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], div[role="dialog"].artdeco-modal'
                    );
                    if (!modal) return null;
                    const buttons = Array.from(modal.querySelectorAll('footer button, button.artdeco-button--primary'));
                    for (const btn of buttons) {
                        const txt = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                        if (/^(next|continue|review)/i.test(txt) && !/submit/i.test(txt)) {
                            btn.click();
                            return txt;
                        }
                    }
                    return null;
                }
                """
            )
            if clicked:
                advanced_to_next = True
                await page.wait_for_timeout(600)

        next_state = await self.inspect_easy_apply_modal()
        return {
            "filled_fields": filled_actions,
            "advanced_step": advanced_to_next,
            "current_modal_state": next_state,
        }

    async def autofill_until_review(
        self,
        job_id_or_url: Optional[str] = None,
        custom_answers: Optional[Dict[str, str]] = None,
        max_steps: int = 8,
    ) -> Dict[str, Any]:
        """Start Easy Apply and walk through form steps using profile data, pausing at the final 'Submit application' button."""
        await self.start_easy_apply(job_id_or_url=job_id_or_url)
        steps_completed = 0
        all_filled: List[Dict[str, str]] = []

        for _ in range(max_steps):
            state = await self.inspect_easy_apply_modal()
            if not state.get("modal_open"):
                break

            step_res = await self.fill_easy_apply_step(
                answers=custom_answers,
                auto_fill_from_profile=True,
                advance_step=not state.get("ready_to_submit"),
            )
            all_filled.extend(step_res["filled_fields"])
            steps_completed += 1

            new_state = step_res["current_modal_state"]
            if (
                new_state.get("ready_to_submit")
                or new_state.get("validation_errors")
                or not step_res["advanced_step"]
            ):
                return {
                    "steps_processed": steps_completed,
                    "filled_fields": all_filled,
                    "paused_for_human_confirmation": bool(new_state.get("ready_to_submit")),
                    "modal_state": new_state,
                }

        final_state = await self.inspect_easy_apply_modal()
        return {
            "steps_processed": steps_completed,
            "filled_fields": all_filled,
            "paused_for_human_confirmation": bool(final_state.get("ready_to_submit")),
            "modal_state": final_state,
        }

    async def submit_easy_apply(self, confirm_submit: bool = False) -> Dict[str, Any]:
        """Click the final 'Submit application' button ONLY when confirm_submit=True."""
        state = await self.inspect_easy_apply_modal()
        if not state.get("modal_open"):
            raise RuntimeError("Easy Apply modal is not open.")
        if not state.get("ready_to_submit"):
            return {
                "submitted": False,
                "reason": "Modal is not on the final 'Submit application' step yet.",
                "modal_state": state,
            }

        if not confirm_submit:
            return {
                "submitted": False,
                "awaiting_human_confirmation": True,
                "message": (
                    "Application is ready to submit. Please ask the user for confirmation first, "
                    "then call submit_easy_apply(confirm_submit=True) or click 'Submit application' in Chrome."
                ),
                "modal_state": state,
            }

        page = await self.browser.get_page()
        clicked = await page.evaluate(
            """
            () => {
                const modal = document.querySelector(
                    'div.jobs-easy-apply-modal, div[data-test-modal-id="easy-apply-modal"], div[role="dialog"].artdeco-modal'
                );
                if (!modal) return false;
                const buttons = Array.from(modal.querySelectorAll('footer button, button.artdeco-button--primary'));
                for (const btn of buttons) {
                    const txt = (btn.innerText || btn.getAttribute('aria-label') || '').trim();
                    if (/submit application/i.test(txt)) {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }
            """
        )
        await page.wait_for_timeout(800)
        return {
            "submitted": bool(clicked),
            "message": "Application submitted on LinkedIn." if clicked else "Submit button could not be clicked.",
        }
