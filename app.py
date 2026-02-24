import json
import zipfile
from io import BytesIO
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

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
      "patient_label": "Pt 001",
      "case": { ... }
    }
  ]
}

CRITICAL:
- Use simple labels like "Pt 001", "Pt 002". Do NOT generate real names.
- If you have >3 cases, output ONLY the first 3 as a complete JSON object.
- Keep values concise (2–12 words).
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

    # FORCE STUDENT NAME TO GENERIC
    tag_values["PATIENT_NAME"] = "Student"

    tag_values["AGE"] = _prefer(case, "AGE", case.get("age"))
    tag_values["GENDER"] = _prefer(case, "GENDER", case.get("gender"))
    tag_values["HEIGHT_CM"] = _prefer(case, "HEIGHT_CM", case.get("height_cm"))
    tag_values["WEIGHT_KG"] = _prefer(case, "WEIGHT_KG", case.get("weight_kg"))

    tag_values["PROCEDURE_NAME"] = _prefer(case, "PROCEDURE_NAME", case.get("procedure_name") or case.get("procedure"))
    tag_values["PROCEDURE_DESCRIPTION"] = _prefer(case, "PROCEDURE_DESCRIPTION", case.get("procedure"))

    tag_values["ALLERGIES"] = _prefer(case, "ALLERGIES", case.get("allergies"))
    tag_values["PAST_SURGICAL_HISTORY"] = _prefer(case, "PAST_SURGICAL_HISTORY", case.get("past_surgical_history"))
    tag_values["ROUTINE_MEDICATIONS"] = _prefer(case, "ROUTINE_MEDICATIONS", case.get("routine_meds"))

    tag_values["PREOP_BP"] = _prefer(case, "PREOP_BP", vs.get("bp"))
    tag_values["PREOP_HR"] = _prefer(case, "PREOP_HR", vs.get("hr"))
    tag_values["PREOP_RR"] = _prefer(case, "PREOP_RR", vs.get("rr"))
    tag_values["PREOP_TEMP"] = _prefer(case, "PREOP_TEMP", vs.get("temp"))
    tag_values["PREOP_SPO2"] = _prefer(case, "PREOP_SPO2", vs.get("spo2"))

    # Pass through any additional uppercase tags
    for k, v in case.items():
        if isinstance(k, str) and k.isupper() and k not in tag_values:
            if v is not None and str(v).strip() != "":
                tag_values[k] = str(v)

    return {str(k).strip(): _s(v) for k, v in tag_values.items()}


def _extract_json_objects(raw: str) -> list[dict]:
    s = raw.strip()
    if not s:
        return []

    try:
        obj = json.loads(s)
        return [obj]
    except Exception:
        pass

    dec = json.JSONDecoder()
    objs = []
    idx = 0
    n = len(s)

    while idx < n:
        while idx < n and s[idx].isspace():
            idx += 1
        if idx >= n:
            break
        obj, end = dec.raw_decode(s, idx)
        objs.append(obj)
        idx = end

    return objs


def _merge_batches(objs: list[dict]) -> dict:
    all_cases = []
    for o in objs:
        if not isinstance(o, dict) or "cases" not in o or not isinstance(o["cases"], list):
            raise ValueError("Each JSON object must contain a 'cases' list.")
        all_cases.extend(o["cases"])
    return {"cases": all_cases}


def render_batch_to_zip(template_bytes: bytes, batch: dict) -> bytes:
    cases = batch["cases"]
    mem = BytesIO()

    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for item in cases:
            case_id = str(item.get("case_id", "000"))
            case = item.get("case", {}) or {}
            tag_values = build_tag_values(case)

            # FORCE SIMPLE FILENAMES (NO REAL NAMES EVER)
            filename = f"{case_id} - Pt {case_id}.docx"

            out_docx = fill_docx_content_controls_bytes(template_bytes, tag_values)
            z.writestr(filename, out_docx)

    return mem.getvalue()


# -----------------------
# Instructions Section
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

    st.warning(
        "Please review all generated information carefully and edit where necessary. "
        "This tool is for educational use only. If something looks incorrect, "
        "revise your case input and regenerate."
    )

    st.markdown("### How to use this app")
    st.markdown(
        "1. Generate batch JSON using the GPT link below.\n"
        f"2. Paste the JSON into this app.\n"
        "3. Click **Generate DOCX ZIP**.\n"
        "4. Download the ZIP — one DOCX per case.\n"
    )

    st.markdown("### Copy/paste prompt for any LLM")
    st.code(PROMPT_TEMPLATE, language="text")


# -----------------------
# Template Selection
# -----------------------
st.subheader("Template")
default_template_bytes = load_default_template()

template_bytes = None
if default_template_bytes:
    template_bytes = default_template_bytes
    st.success("Using built-in template.")
else:
    st.warning("Template not found in /assets.")


# -----------------------
# JSON Input + Output
# -----------------------
st.subheader("Paste case_batch.json")
raw = st.text_area("Paste JSON here", height=260)

generate = st.button("Generate DOCX ZIP", type="primary", disabled=not raw.strip())

if generate:
    try:
        objs = _extract_json_objects(raw)
        merged = _merge_batches(objs)
    except Exception as e:
        st.error(f"Invalid JSON: {e}")
        st.stop()

    zip_bytes = render_batch_to_zip(template_bytes, merged)

    st.success(f"Generated ZIP with {len(merged['cases'])} case(s).")

    st.download_button(
        "Download filled DOCX files (ZIP)",
        data=zip_bytes,
        file_name="filled_docs.zip",
        mime="application/zip",
    )
