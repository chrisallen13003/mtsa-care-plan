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
    """
    Prefer already-computed uppercase Word-tag values if present, else fall back to legacy-derived values.
    """
    v = case.get(tag_key)
    if v is not None and str(v).strip() != "":
        return str(v)
    return _s(legacy_value)


def build_tag_values(case: dict) -> dict:
    """
    Build dict of Word content control tag -> value.
    Prefer uppercase Word-tag keys from JSON; fall back to legacy keys/structures.
    Also pass through any additional uppercase tags present in the JSON.
    """
    tag_values = {}

    vs = case.get("preop_vs") or {}
    labs = case.get("labs") or {}
    aw = case.get("airway") or {}
    pmh = case.get("pmh") or {}
    ros = case.get("ros") or {}

    # Core / identifiers (PATIENT_NAME is student name per your pipeline)
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

    # NPO
    legacy_npo = None
    if case.get("npo_hours") is not None:
        legacy_npo = f"NPO {case.get('npo_hours')} hours"
    elif case.get("npo_since"):
        legacy_npo = f"NPO since {case.get('npo_since')}"
    tag_values["NPO_STATUS"] = _prefer(case, "NPO_STATUS", legacy_npo)

    # Preop VS
    tag_values["PREOP_BP"] = _prefer(case, "PREOP_BP", vs.get("bp"))
    tag_values["PREOP_HR"] = _prefer(case, "PREOP_HR", vs.get("hr"))
    tag_values["PREOP_RR"] = _prefer(case, "PREOP_RR", vs.get("rr"))
    tag_values["PREOP_TEMP"] = _prefer(case, "PREOP_TEMP", vs.get("temp"))
    tag_values["PREOP_SPO2"] = _prefer(case, "PREOP_SPO2", vs.get("spo2"))

    # Airway
    tag_values["AIRWAY_DEVICE"] = _prefer(case, "AIRWAY_DEVICE", case.get("airway_device"))
    tag_values["MALLAMPATI_CLASS"] = _prefer(case, "MALLAMPATI_CLASS", aw.get("mallampati"))
    tag_values["THYROMENTAL_DISTANCE"] = _prefer(case, "THYROMENTAL_DISTANCE", aw.get("thyromental_distance"))
    tag_values["TMJ_PROBLEMS"] = _prefer(case, "TMJ_PROBLEMS", aw.get("tmj_problems"))
    tag_values["DENTITION_STATUS"] = _prefer(case, "DENTITION_STATUS", aw.get("dentition"))
    tag_values["AIRWAY_DESCRIPTION"] = _prefer(case, "AIRWAY_DESCRIPTION", aw.get("airway_description"))

    # Meds
    tag_values["PREOP_MEDS_DOSES"] = _prefer(case, "PREOP_MEDS_DOSES", case.get("preop_meds_doses"))
    tag_values["INDUCTION_MEDS_DOSES"] = _prefer(case, "INDUCTION_MEDS_DOSES", case.get("induction_meds_doses"))
    tag_values["MAINTENANCE_MEDS_DOSES"] = _prefer(case, "MAINTENANCE_MEDS_DOSES", case.get("maintenance_meds_doses"))
    tag_values["MEDICATION_CONSIDERATIONS_INTERACTIONS"] = _prefer(
        case, "MEDICATION_CONSIDERATIONS_INTERACTIONS", case.get("med_considerations")
    )

    # Labs/studies
    tag_values["CBC_RESULTS"] = _prefer(case, "CBC_RESULTS", labs.get("cbc"))
    tag_values["CHEM_RESULTS"] = _prefer(case, "CHEM_RESULTS", labs.get("chem"))
    tag_values["COAGS_RESULTS"] = _prefer(case, "COAGS_RESULTS", labs.get("coags"))
    tag_values["EKG_RESULTS"] = _prefer(case, "EKG_RESULTS", labs.get("ekg"))
    tag_values["ECHO_RESULTS"] = _prefer(case, "ECHO_RESULTS", labs.get("echo"))
    tag_values["CXR_RESULTS"] = _prefer(case, "CXR_RESULTS", labs.get("cxr"))
    tag_values["HCG_RESULTS"] = _prefer(case, "HCG_RESULTS", labs.get("hcg"))
    tag_values["TYPE_AND_CROSS"] = _prefer(case, "TYPE_AND_CROSS", labs.get("type_and_cross"))
    tag_values["BLOOD_TYPE"] = _prefer(case, "BLOOD_TYPE", labs.get("blood_type"))
    tag_values["OTHER_STUDIES"] = _prefer(case, "OTHER_STUDIES", labs.get("other_studies"))

    # PMH/ROS (support template typo PHM_CV)
    tag_values["PHM_CV"] = _prefer(case, "PHM_CV", pmh.get("cv"))
    tag_values["PMH_RESP"] = _prefer(case, "PMH_RESP", pmh.get("resp"))
    tag_values["PMH_GI_GU"] = _prefer(case, "PMH_GI_GU", pmh.get("gi_gu"))
    tag_values["PMH_CNS"] = _prefer(case, "PMH_CNS", pmh.get("cns"))
    tag_values["PMH_HEP"] = _prefer(case, "PMH_HEP", pmh.get("hep"))
    tag_values["PMH_EXTREMITIES"] = _prefer(case, "PMH_EXTREMITIES", pmh.get("extremities"))
    tag_values["PMH_OTHER"] = _prefer(case, "PMH_OTHER", pmh.get("other"))

    tag_values["ROS_CV"] = _prefer(case, "ROS_CV", ros.get("cv"))
    tag_values["ROS_RESP"] = _prefer(case, "ROS_RESP", ros.get("resp"))
    tag_values["ROS_GI_GU"] = _prefer(case, "ROS_GI_GU", ros.get("gi_gu"))
    tag_values["ROS_CNS"] = _prefer(case, "ROS_CNS", ros.get("cns"))
    tag_values["ROS_HEP"] = _prefer(case, "ROS_HEP", ros.get("hep"))
    tag_values["ROS_EXTREMITIES"] = _prefer(case, "ROS_EXTREMITIES", ros.get("extremities"))
    tag_values["ROS_OTHER"] = _prefer(case, "ROS_OTHER", ros.get("other"))

    # Pass-through any additional uppercase tags present in JSON (covers your full Tag list)
    for k, v in case.items():
        if isinstance(k, str) and k.isupper() and k not in tag_values:
            if v is not None and str(v).strip() != "":
                tag_values[k] = str(v)

    # Ensure strings and normalize keys
    return {str(k).strip(): _s(v) for k, v in tag_values.items()}


def _extract_json_objects(raw: str) -> list[dict]:
    """
    Accept either:
      - one JSON object: {"cases":[...]}
      - multiple JSON objects pasted back-to-back:
          {"cases":[...]}
          {"cases":[...]}
          {"cases":[...]}
    Returns list of parsed dicts.
    """
    s = raw.strip()
    if not s:
        return []

    # Fast path: single JSON object
    try:
        obj = json.loads(s)
        return [obj]
    except Exception:
        pass

    # Multi-object parse using JSONDecoder raw_decode
    dec = json.JSONDecoder()
    objs: list[dict] = []
    idx = 0
    n = len(s)
    while idx < n:
        # skip whitespace
        while idx < n and s[idx].isspace():
            idx += 1
        if idx >= n:
            break
        obj, end = dec.raw_decode(s, idx)
        objs.append(obj)
        idx = end
    return objs


def _merge_batches(objs: list[dict]) -> dict:
    """
    Merge multiple {"cases":[...]} objects into one.
    """
    all_cases: list[dict] = []
    for o in objs:
        if not isinstance(o, dict) or "cases" not in o or not isinstance(o["cases"], list):
            raise ValueError("Each JSON object must be a dict with a 'cases' list.")
        all_cases.extend(o["cases"])
    return {"cases": all_cases}


def render_batch_to_zip(template_bytes: bytes, batch: dict) -> bytes:
    cases = batch["cases"]
    mem = BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for item in cases:
            case_id = str(item.get("case_id", "000"))
            label = safe_name(item.get("patient_label", f"Case {case_id}")) or f"Case {case_id}"
            case = item.get("case", {}) or {}
            tag_values = build_tag_values(case)
            out_docx = fill_docx_content_controls_bytes(template_bytes, tag_values)
            filename = f"{case_id} - {label}.docx"
            z.writestr(filename, out_docx)
    return mem.getvalue()


# -----------------------
# Instructions section
# -----------------------
with st.expander("📌 Instructions (Start Here)", expanded=True):
    st.markdown("### 📺 Video tutorial")
    components.html(
        """
        <div style="position: relative; padding-bottom: 56.25%; height: 0; margin-bottom: 16px;">
          <iframe
            src="https://www.loom.com/embed/435af2f49c50411fa88f2aa5fcbbcce1"
            frameborder="0"
            webkitallowfullscreen
            mozallowfullscreen
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


# -----------------------
# Template selection
# -----------------------
st.subheader("Template")
default_template_bytes = load_default_template()

use_default = False
if default_template_bytes:
    use_default = st.toggle("Use built-in MTSA template (recommended)", value=True)

template_bytes = None
if use_default and default_template_bytes:
    template_bytes = default_template_bytes
    st.success("Using built-in template.")
else:
    up = st.file_uploader("Upload a template DOCX (optional)", type=["docx"])
    if up:
        template_bytes = up.read()
        st.success("Using uploaded template.")
    else:
        st.warning("No template selected yet.")


# -----------------------
# JSON input + output
# -----------------------
st.subheader("Paste case_batch.json (one or multiple batches)")
raw = st.text_area(
    "Paste JSON here",
    height=260,
    placeholder='{ "cases": [ ... ] }\n{ "cases": [ ... ] }\n{ "cases": [ ... ] }',
)

col1, col2 = st.columns([1, 1])
with col1:
    generate = st.button("Generate DOCX ZIP", type="primary", disabled=not raw.strip())
with col2:
    st.caption("Output is DOCX-only (ZIP).")

if generate:
    if not template_bytes:
        st.error("Template not found. Add the DOCX to /assets in GitHub or upload one.")
        st.stop()

    try:
        objs = _extract_json_objects(raw)
        if not objs:
            raise ValueError("No JSON found.")
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
