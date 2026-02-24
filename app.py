import json
import zipfile
from io import BytesIO
from pathlib import Path
import streamlit as st

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
      "patient_label": "...",
      "case": { ... }
    }
  ]
}

For EACH case, fully populate these keys (even if not provided; invent plausible patient-specific values):
- age, gender, height_cm, weight_kg, asa
- procedure_name, procedure, position, duration_hours, npo_since, npo_hours, ebl_ml
- allergies, past_surgical_history, routine_meds
- pmh dict with keys: cv, resp, endo, gi_gu, cns, hep, extremities, other
- ros dict with keys: cv, resp, gi_gu, cns, hep, extremities, other (tailor to comorbidities)
- preop_vs dict: bp, hr, rr, temp, spo2 (tailored; not identical across cases)
- airway_device and airway dict: mallampati, thyromental_distance, tmj_problems, dentition, airway_description
- preop_meds_doses, induction_meds_doses, maintenance_meds_doses, med_considerations (tailor to scenario)
- labs dict: cbc, chem, coags, ekg, echo, cxr, hcg, type_and_cross, blood_type, other_studies

Use plausible simulated values for school use. Do not include real identifiers.

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
    Prefer the already-computed Word-tag (uppercase) value if present/non-empty,
    otherwise fall back to the legacy-derived value.
    """
    v = case.get(tag_key)
    if v is not None and str(v).strip() != "":
        return str(v)
    return _s(legacy_value)


def build_tag_values(case: dict) -> dict:
    """
    Build dict of Word content control tag -> value.
    Prefer uppercase Word-tag keys from JSON; fall back to legacy keys/structures.
    """
    tag_values = {}

    # Legacy nested dicts
    vs = case.get("preop_vs") or {}
    labs = case.get("labs") or {}
    aw = case.get("airway") or {}
    pmh = case.get("pmh") or {}
    ros = case.get("ros") or {}

    # Core (PATIENT_NAME is a Word Tag but your GPT now uses it for STUDENT NAME)
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
    # Prefer explicit Word tag; else construct something sensible from legacy
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

    # Med blocks
    tag_values["PREOP_MEDS_DOSES"] = _prefer(case, "PREOP_MEDS_DOSES", case.get("preop_meds_doses"))
    tag_values["INDUCTION_MEDS_DOSES"] = _prefer(case, "INDUCTION_MEDS_DOSES", case.get("induction_meds_doses"))
    tag_values["MAINTENANCE_MEDS_DOSES"] = _prefer(case, "MAINTENANCE_MEDS_DOSES", case.get("maintenance_meds_doses"))
    tag_values["MEDICATION_CONSIDERATIONS_INTERACTIONS"] = _prefer(case, "MEDICATION_CONSIDERATIONS_INTERACTIONS", case.get("med_considerations"))

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

    # PMH / ROS (note template typo support PHM_CV)
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

    # IMPORTANT: pass through ANY additional uppercase tags that exist in the JSON
    # so you don't have to hardcode every tag mapping here.
    for k, v in case.items():
        if not isinstance(k, str):
            continue
        if k.isupper() and k not in tag_values:
            if v is not None and str(v).strip() != "":
                tag_values[k] = str(v)

    # Ensure strings
    return {str(k): _s(v) for k, v in tag_values.items()}


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


with st.expander("📌 Instructions (Start Here)", expanded=True):
    st.markdown("### How to use this app")
    st.markdown(
        "1. **Generate `case_batch.json`** using either:\n"
        f"   - **MTSA Care Plan Filler GPT:** {GPT_LINK}\n"
        "   - **Any LLM:** copy the prompt below and paste your patient cases\n"
        "2. **Paste the JSON** into the box in this app.\n"
        "3. Click **Generate DOCX ZIP**.\n"
        "4. Download the ZIP — it contains one filled DOCX per patient.\n\n"
        "**Tip:** Do not include real patient identifiers (school use only)."
    )

    st.markdown("### Copy/paste prompt for any LLM")
    st.code(PROMPT_TEMPLATE, language="text")


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


st.subheader("Paste case_batch.json")
raw = st.text_area("Paste JSON here", height=260, placeholder='{ "cases": [ ... ] }')

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
        batch = json.loads(raw)
        assert isinstance(batch, dict) and "cases" in batch and isinstance(batch["cases"], list)
    except Exception as e:
        st.error(f"Invalid JSON: {e}")
        st.stop()

    zip_bytes = render_batch_to_zip(template_bytes, batch)
    st.success("Generated ZIP.")
    st.download_button(
        "Download filled DOCX files (ZIP)",
        data=zip_bytes,
        file_name="filled_docs.zip",
        mime="application/zip",
    )
