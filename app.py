import json
import zipfile
from io import BytesIO
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components  # ✅ ADDED

from utils_docx import fill_docx_content_controls_bytes

st.set_page_config(page_title="MTSA Care Plan Filler", layout="wide")
st.title("MTSA Care Plan Filler (DOCX Generator)")

DEFAULT_TEMPLATE_PATH = Path("assets/MTSA_2024_CarePlan_custom.docx")

GPT_LINK = "https://chatgpt.com/g/g-698e0cea59908191959eada445d19b4c-mtsa-care-plan-filler"

PROMPT_TEMPLATE = """You are generating anesthesia care plan batch JSON for an MTSA template filler.
Return ONLY valid JSON (no markdown, no extra text).

Output format:
{
  "cases": [
    {
      "case_id": "001",
      "patient_label": "Case 001",
      "case": { ... }
    }
  ]
}

CRITICAL:
- If you have >3 cases, output ONLY the first 3 as a complete JSON object. I will request the next batch.
- Keep values concise (2–12 words), no long paragraphs.
- Include BOTH legacy snake_case fields AND all required uppercase Word Tag fields.

REFERENCES must cite only:
- Nagelhout. Nurse Anesthesia
- Miller. Miller’s Anesthesia

Here are my cases:
(Paste Pt 1... Pt N... here)
"""


def load_default_template() -> bytes | None:
    if DEFAULT_TEMPLATE_PATH.exists():
        return DEFAULT_TEMPLATE_PATH.read_bytes()
    return None


def safe_name(s: str) -> str:
    keep = "-_(). "
    return "".join(c for c in s if c.isalnum() or c in keep).strip()


def _s(v) -> str:
    return "" if v is None else str(v)


def _prefer(case: dict, tag_key: str, legacy_value) -> str:
    v = case.get(tag_key)
    if v is not None and str(v).strip() != "":
        return str(v)
    return _s(legacy_value)


def build_tag_values(case: dict) -> dict:
    tag_values = {}

    vs = case.get("preop_vs") or {}
    labs = case.get("labs") or {}
    aw = case.get("airway") or {}
    pmh = case.get("pmh") or {}
    ros = case.get("ros") or {}

    tag_values["PATIENT_NAME"] = _prefer(case, "PATIENT_NAME", case.get("patient_name"))
    tag_values["AGE"] = _prefer(case, "AGE", case.get("age"))
    tag_values["GENDER"] = _prefer(case, "GENDER", case.get("gender"))
    tag_values["HEIGHT_CM"] = _prefer(case, "HEIGHT_CM", case.get("height_cm"))
    tag_values["WEIGHT_KG"] = _prefer(case, "WEIGHT_KG", case.get("weight_kg"))

    tag_values["PROCEDURE_NAME"] = _prefer(case, "PROCEDURE_NAME", case.get("procedure_name") or case.get("procedure"))
    tag_values["PROCEDURE_DESCRIPTION"] = _prefer(case, "PROCEDURE_DESCRIPTION", case.get("procedure"))

    tag_values["ALLERGIES"] = _prefer(case, "ALLERGIES", case.get("allergies"))
    tag_values["PAST_SURGICAL_HISTORY"] = _prefer(case, "PAST_SURGICAL_HISTORY", case.get("past_surgical_history"))
    tag_values["ROUTINE_MEDICATIONS"] = _prefer(case, "ROUTINE_MEDICATIONS", case.get("routine_meds"))

    legacy_npo = None
    if case.get("npo_hours") is not None:
        legacy_npo = f"NPO {case.get('npo_hours')} hours"
    elif case.get("npo_since"):
        legacy_npo = f"NPO since {case.get('npo_since')}"
    tag_values["NPO_STATUS"] = _prefer(case, "NPO_STATUS", legacy_npo)

    tag_values["PREOP_BP"] = _prefer(case, "PREOP_BP", vs.get("bp"))
    tag_values["PREOP_HR"] = _prefer(case, "PREOP_HR", vs.get("hr"))
    tag_values["PREOP_RR"] = _prefer(case, "PREOP_RR", vs.get("rr"))
    tag_values["PREOP_TEMP"] = _prefer(case, "PREOP_TEMP", vs.get("temp"))
    tag_values["PREOP_SPO2"] = _prefer(case, "PREOP_SPO2", vs.get("spo2"))

    for k, v in case.items():
        if isinstance(k, str) and k.isupper() and k not in tag_values:
            if v is not None and str(v).strip() != "":
                tag_values[k] = str(v)

    return {str(k).strip(): _s(v) for k, v in tag_values.items()}


# -----------------------
# Instructions section
# -----------------------
with st.expander("📌 Instructions (Start Here)", expanded=True):

    st.markdown("### 📺 Video Tutorial")
    components.html(
        """
        <div style="position: relative; padding-bottom: 56.25%; height: 0; margin-bottom: 20px;">
          <iframe
            src="https://www.loom.com/embed/435af2f49c50411fa88f2aa5fcbbcce1"
            frameborder="0"
            allowfullscreen
            style="position: absolute; top: 0; left: 0; width: 100%; height: 100%;">
          </iframe>
        </div>
        """,
        height=420,
    )

    st.markdown("### How to use this app")
    st.markdown(
        "1. Generate batch JSON using either:\n"
        f"   - **MTSA Care Plan Filler GPT:** {GPT_LINK}\n"
        "   - **Any LLM:** copy the prompt below\n"
        "2. Paste the JSON into the box in this app.\n"
        "   - You may paste **multiple JSON batches back-to-back**.\n"
        "3. Click **Generate DOCX ZIP**.\n"
        "4. Download the ZIP — one filled DOCX per case.\n\n"
        "**Tip:** Do not include real patient identifiers (school use only)."
    )

    st.markdown("### Copy/paste prompt for any LLM")
    st.code(PROMPT_TEMPLATE, language="text")
  
