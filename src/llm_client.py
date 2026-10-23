"""
Gemini LLM client for generating QA test cases from reconstructed
selection content (one or more document nodes), using structured
output validated against the TestCaseList Pydantic schema.

Retry/failure policy (documented, not just implemented):
  1. Call Gemini once, requesting JSON matching TestCaseList's schema.
  2. Parse and validate the response with Pydantic.
  3. If validation fails (malformed JSON, wrong types, missing
     fields, or fewer than 3 test cases), retry ONCE with the
     validation error appended to the prompt as a correction note.
  4. If the retry also fails, raise LLMGenerationError with details.
     The caller surfaces this as a clear HTTP error -- this module
     never silently returns partial/invalid data or fabricates
     fallback test cases.

Requires a GEMINI_API_KEY environment variable. If missing,
generate_test_cases() raises LLMGenerationError immediately with a
clear message, rather than letting the SDK fail deeper in the stack.
"""

import json
import os

from pydantic import ValidationError

from schemas import TestCaseList


class LLMGenerationError(Exception):
    pass


PROMPT_TEMPLATE = """You are a QA engineer writing test cases for a medical device user manual.

Device: CardioTrack CT-200 Home Blood Pressure Monitor
Selection: {selection_label}

Relevant manual content:
{content}

Write 3 to 5 concrete QA test cases a tester could execute to verify the behavior described above is implemented correctly. Each test case needs: a short title, preconditions, an ordered list of steps, an expected result, and a priority (high, medium, or low).

Base the test cases ONLY on the content given above. Do not invent behavior not described in the text. If the selection spans multiple sections, you may write test cases that span their combined behavior, not just one section in isolation.
"""


def _build_prompt(selection_label, content, correction_note=None):
    prompt = PROMPT_TEMPLATE.format(selection_label=selection_label, content=content)
    if correction_note:
        prompt += (
            f"\n\nIMPORTANT: Your previous response was invalid: {correction_note}\n"
            f"Please strictly follow the required JSON schema this time."
        )
    return prompt


def _call_gemini(prompt):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise LLMGenerationError(
            "GEMINI_API_KEY environment variable is not set. "
            "Set it in a .env file at the project root to use test-case generation."
        )

    from google import genai

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": TestCaseList,
        },
    )
    return response.text


def generate_test_cases(selection_label, content):
    """
    Returns a list of validated test case dicts (matching the
    TestCase schema). Raises LLMGenerationError on unrecoverable
    failure after one retry.
    """
    prompt = _build_prompt(selection_label, content)
    last_error = None

    for attempt in range(2):
        try:
            raw_text = _call_gemini(prompt)
        except LLMGenerationError:
            raise
        except Exception as exc:
            last_error = f"Gemini API call failed: {exc}"
            prompt = _build_prompt(selection_label, content, correction_note=str(exc))
            continue

        try:
            parsed = json.loads(raw_text)
            validated = TestCaseList.model_validate(parsed)
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = f"Response failed schema validation: {exc}"
            prompt = _build_prompt(selection_label, content, correction_note=str(exc))
            continue

        if len(validated.test_cases) < 3:
            last_error = f"Only {len(validated.test_cases)} test cases returned, need 3-5."
            prompt = _build_prompt(selection_label, content, correction_note=last_error)
            continue

        return [tc.model_dump() for tc in validated.test_cases]

    raise LLMGenerationError(
        f"LLM failed to produce valid structured output after 2 attempts. Last error: {last_error}"
    )