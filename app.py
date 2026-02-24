import json
import zipfile
from io import BytesIO
from pathlib import Path
import streamlit as st

from utils_docx import fill_docx_content_controls_bytes

st.set_page_config(page_title="MTSA Care Plan Filler", layout="wide")
st.title("MTSA Care Plan Filler (DOCX Generator)")

DEFAULT_TEMPLATE_PATH = Path("assets/MTSA_2024_CarePlan_custom.docx")

# 🔧 CHANGE THIS ONCE: paste your GPT share link here
GPT_LINK = GPT_LINK = "https://chatgpt.com/g/g-698e0cea59908191959eada445d19b4c-mtsa-care-plan-filler"

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

def build_tag_values(case: dict) -> dict:
    """
    Map JSON -> Word content control tags (must match your template tags).
    Add more mappings here if your template has additional tags.
    """
    tag_values = {}

    # Core
    tag_values["PATIENT_NAME"] = str(case.get("patient_name", ""))
    tag_values["AGE"] = str(case.get("age", ""))
    tag_values["GENDER"] = str(case.get("gender", ""))
    tag_values["HEIGHT_CM"] = str(case.get("height_cm", ""))
    tag_values["WEIGHT_KG"] = str(case.get("weight_kg", ""))
    tag_values["PROCEDURE_NAME"] = str(case.get("procedure_name", case.get("procedure", "")))

    tag_values["ALLERGIES"] = str(case.get("allergies", ""))
    tag_values["PAST_SURGICAL_HISTORY"] = str(case.get("past_surgical_history", ""))
    tag_values["ROUTINE_MEDICATIONS"] = str(case.get("routine_meds", ""))
    tag_values["NPO_STATUS"] = str(case.get("npo_since", ""))

    # Preop VS
    vs = case.get("preop_vs", {}) or {}
    tag_values["PREOP_BP"] = str(vs.get("bp", ""))
    tag_values["PREOP_HR"] = str(vs.get("hr", ""))
    tag_values["PREOP_RR"] = str(vs.get("rr", ""))
    tag_values["PREOP_TEMP"] = str(vs.get("temp", ""))
    tag_values["PREOP_SPO2"] = str(vs.get("spo2", ""))

    # Med blocks
    tag_values["PREOP_MEDS_DOSES"] = str(case.get("preop_meds_doses", ""))
    tag_values["INDUCTION_MEDS_DOSES"] = str(case.get("induction_meds_doses", ""))
    tag_values["MAINTENANCE_MEDS_DOSES"] = str(case.get("maintenance_meds_doses", ""))
    tag_values["MEDICATION_CONSIDERATIONS_INTERACTIONS"] = str(case.get("med_considerations", ""))

    # Airway
    tag_values["AIRWAY_DEVICE"] = str(case.get("airway_device", ""))
    aw = case.get("airway", {}) or {}
    tag_values["MALLAMPATI_CLASS"] = str(aw.get("mallampati", ""))
    tag_values["THYROMENTAL_DISTANCE"] = str(aw.get("thyromental_distance", ""))
    tag_values["TMJ_PROBLEMS"] = str(aw.get("tmj_problems", ""))
    tag_values["DENTITION_STATUS"] = str(aw.get("dentition", ""))
    tag_values["AIRWAY_DESCRIPTION"] = str(aw.get("airway_description", ""))

    # Labs
    labs = case.get("labs", {}) or {}
    tag_values["CBC_RESULTS"] = str(labs.get("cbc", ""))
    tag_values["CHEM_RESULTS"] = str(labs.get("chem", ""))
    tag_values["COAGS_RESULTS"] = str(labs.get("coags", ""))
    tag_values["EKG_RESULTS"] = str(labs.get("ekg", ""))
    tag_values["ECHO_RESULTS"] = str(labs.get("echo", ""))
    tag_values["CXR_RESULTS"] = str(labs.get("cxr", ""))
    tag_values["HCG_RESULTS"] = str(labs.get("hcg", ""))
    tag_values["TYPE_AND_CROSS"] = str(labs.get("type_and_cross", ""))
    tag_values["BLOOD_TYPE"] = str(labs.get("blood_type", ""))
    tag_values["OTHER_STUDIES"] = str(labs.get("other_studies", ""))

    # PMH
    pmh = case.get("pmh", {}) or {}
    tag_values["PMH_CV"] = str(pmh.get("cv", ""))
    tag_values["PMH_RESP"] = str(pmh.get("resp", ""))
    tag_values["PMH_GI_GU"] = str(pmh.get("gi_gu", ""))
    tag_values["PMH_CNS"] = str(pmh.get("cns", ""))
    tag_values["PMH_HEP"] = str(pmh.get("hep", ""))
    tag_values["PMH_EXTREMITIES"] = str(pmh.get("extremities", ""))
    tag_values["PMH_OTHER"] = str(pmh.get("other", ""))
    tag_values["PHM_CV"] = tag_values["PMH_CV"]  # template typo support

    # ROS
    ros = case.get("ros", {}) or {}
    tag_values["ROS_CV"] = str(ros.get("cv", ""))
    tag_values["ROS_RESP"] = str(ros.get("resp", ""))
    tag_values["ROS_GI_GU"] = str(ros.get("gi_gu", ""))
    tag_values["ROS_CNS"] = str(ros.get("cns", ""))
    tag_values["ROS_HEP"] = str(ros.get("hep", ""))
    tag_values["ROS_EXTREMITIES"] = str(ros.get("extremities", ""))
    tag_values["ROS_OTHER"] = str(ros.get("other", ""))

    return tag_values

def render_batch_to_zip(template_bytes: bytes, batch: dict) -> bytes:
    cases = batch["cases"]
    mem = BytesIO()
    with zipfile.ZipFile(mem, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for item in cases:
            case_id = str(item.get("case_id", "000"))
            label = safe_name(item.get("patient_label", f"Case {case_id}")) or f"Case {case_id}"
            case = item.get("case", {})
            tag_values = build_tag_values(case)
            out_docx = fill_docx_content_controls_bytes(template_bytes, tag_values)
            filename = f"{case_id} - {label}.docx"
            z.writestr(filename, out_docx)
    return mem.getvalue()

# -----------------------
# Instructions section
# -----------------------
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
