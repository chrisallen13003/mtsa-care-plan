from __future__ import annotations

import zipfile
from io import BytesIO
import xml.etree.ElementTree as ET
from typing import Any, Dict

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}


def iter_word_xml_parts(zipf: zipfile.ZipFile):
    for name in zipf.namelist():
        if name.startswith("word/") and name.endswith(".xml"):
            yield name


def _strip_sdt_locks(sdt: ET.Element) -> None:
    """
    Remove Word content-control lock settings so filled content is editable.
    This targets <w:sdtPr><w:lock w:val="..."/> (and any nested w:lock).
    Safe to call even if no locks exist.
    """
    # Prefer removing direct children under sdtPr (most common)
    sdtPr = sdt.find("./w:sdtPr", NSMAP)
    if sdtPr is not None:
        for lock_el in list(sdtPr.findall("./w:lock", NSMAP)):
            sdtPr.remove(lock_el)

    # Defensive: remove any remaining w:lock elements under this sdt
    # (rare, but harmless to clean)
    for parent in sdt.findall(".//w:lock/..", NSMAP):
        for lock_el in list(parent.findall("./w:lock", NSMAP)):
            parent.remove(lock_el)


def set_sdt_text(sdt: ET.Element, text: str):
    """
    Preserve existing structure. Replace text in w:t nodes inside the content control.
    """
    if text is None:
        text = ""

    text_nodes = sdt.findall(".//w:sdtContent//w:t", NSMAP)

    if not text_nodes:
        content = sdt.find(".//w:sdtContent", NSMAP)
        if content is None:
            return
        p = ET.SubElement(content, f"{{{W_NS}}}p")
        r = ET.SubElement(p, f"{{{W_NS}}}r")
        t = ET.SubElement(r, f"{{{W_NS}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = str(text)
        return

    text_nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_nodes[0].text = str(text)
    for n in text_nodes[1:]:
        n.text = ""


def _safe_get(d: Any, *path: str) -> Any:
    cur = d
    for p in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def _as_str(v: Any) -> str:
    if v is None:
        return ""
    return str(v)


def build_tag_values(case_dict: Dict[str, Any]) -> Dict[str, str]:
    """
    Build a tag_values dict suitable for filling Word content controls.
    This:
      - passes through existing uppercase Tag keys if present
      - and back-fills missing Tag keys from legacy schema (snake_case)
    """
    tag_values: Dict[str, str] = {}

    # 1) Pass-through: include top-level scalars as strings
    for k, v in case_dict.items():
        if isinstance(v, (dict, list)):
            continue
        tag_values[str(k).strip()] = _as_str(v)

    # 2) Back-fill uppercase Tag keys from legacy nested objects if missing/blank.
    preop_vs = case_dict.get("preop_vs") if isinstance(case_dict.get("preop_vs"), dict) else {}
    labs = case_dict.get("labs") if isinstance(case_dict.get("labs"), dict) else {}
    airway = case_dict.get("airway") if isinstance(case_dict.get("airway"), dict) else {}
    pmh = case_dict.get("pmh") if isinstance(case_dict.get("pmh"), dict) else {}
    ros = case_dict.get("ros") if isinstance(case_dict.get("ros"), dict) else {}

    def put_if_missing(tag: str, value: Any):
        t = tag.strip()
        if not tag_values.get(t):  # missing or empty
            s = _as_str(value)
            if s != "":
                tag_values[t] = s

    # Basic demographics / procedure
    put_if_missing("PROCEDURE_NAME", case_dict.get("procedure_name"))
    put_if_missing("PROCEDURE_DESCRIPTION", case_dict.get("procedure"))
    put_if_missing("ALLERGIES", case_dict.get("allergies"))
    put_if_missing("AGE", case_dict.get("age"))
    put_if_missing("GENDER", case_dict.get("gender"))
    put_if_missing("HEIGHT_CM", case_dict.get("height_cm"))
    put_if_missing("WEIGHT_KG", case_dict.get("weight_kg"))
    put_if_missing("ROUTINE_MEDICATIONS", case_dict.get("routine_meds"))
    put_if_missing("PAST_SURGICAL_HISTORY", case_dict.get("past_surgical_history"))

    # NPO
    if isinstance(case_dict.get("npo_hours"), (int, float)) and not tag_values.get("NPO_STATUS"):
        put_if_missing("NPO_STATUS", f"NPO {case_dict.get('npo_hours')} hours")
    put_if_missing("NPO_STATUS", case_dict.get("npo_status"))

    # Preop vitals
    put_if_missing("PREOP_BP", preop_vs.get("bp"))
    put_if_missing("PREOP_HR", preop_vs.get("hr"))
    put_if_missing("PREOP_RR", preop_vs.get("rr"))
    put_if_missing("PREOP_TEMP", preop_vs.get("temp"))
    put_if_missing("PREOP_SPO2", preop_vs.get("spo2"))

    # Airway
    put_if_missing("AIRWAY_DEVICE", case_dict.get("airway_device"))
    put_if_missing("MALLAMPATI_CLASS", airway.get("mallampati"))
    put_if_missing("THYROMENTAL_DISTANCE", airway.get("thyromental_distance"))
    put_if_missing("TMJ_PROBLEMS", airway.get("tmj_problems"))
    put_if_missing("DENTITION_STATUS", airway.get("dentition"))
    put_if_missing("AIRWAY_DESCRIPTION", airway.get("airway_description"))

    # Labs & studies
    put_if_missing("CBC_RESULTS", labs.get("cbc"))
    put_if_missing("CHEM_RESULTS", labs.get("chem"))
    put_if_missing("COAGS_RESULTS", labs.get("coags"))
    put_if_missing("EKG_RESULTS", labs.get("ekg"))
    put_if_missing("ECHO_RESULTS", labs.get("echo"))
    put_if_missing("CXR_RESULTS", labs.get("cxr"))
    put_if_missing("HCG_RESULTS", labs.get("hcg"))
    put_if_missing("TYPE_AND_CROSS", labs.get("type_and_cross"))
    put_if_missing("BLOOD_TYPE", labs.get("blood_type"))
    put_if_missing("OTHER_STUDIES", labs.get("other_studies"))

    # PMH / ROS
    put_if_missing("PHM_CV", pmh.get("cv"))  # template typo PHM_CV
    put_if_missing("PMH_RESP", pmh.get("resp"))
    put_if_missing("PMH_CNS", pmh.get("cns"))
    put_if_missing("PMH_HEP", pmh.get("hep"))
    put_if_missing("PMH_GI_GU", pmh.get("gi_gu"))
    put_if_missing("PMH_EXTREMITIES", pmh.get("extremities"))
    put_if_missing("PMH_OTHER", pmh.get("other"))

    put_if_missing("ROS_CV", ros.get("cv"))
    put_if_missing("ROS_RESP", ros.get("resp"))
    put_if_missing("ROS_CNS", ros.get("cns"))
    put_if_missing("ROS_HEP", ros.get("hep"))
    put_if_missing("ROS_GI_GU", ros.get("gi_gu"))
    put_if_missing("ROS_EXTREMITIES", ros.get("extremities"))
    put_if_missing("ROS_OTHER", ros.get("other"))

    # Meds / considerations
    put_if_missing("PREOP_MEDS_DOSES", case_dict.get("preop_meds_doses"))
    put_if_missing("INDUCTION_MEDS_DOSES", case_dict.get("induction_meds_doses"))
    put_if_missing("MAINTENANCE_MEDS_DOSES", case_dict.get("maintenance_meds_doses"))
    put_if_missing("MEDICATION_CONSIDERATIONS_INTERACTIONS", case_dict.get("med_considerations"))

    # Final normalization
    normalized: Dict[str, str] = {}
    for k, v in tag_values.items():
        kk = str(k).strip()
        vv = "" if v is None else str(v)
        normalized[kk] = vv

    return normalized


def fill_docx_content_controls_bytes(template_bytes: bytes, tag_values: Dict[str, str]) -> bytes:
    """
    Return DOCX bytes with content controls filled where tag matches keys in tag_values.
    Also removes any w:lock in content controls so output is editable.
    Uses ElementTree only (no compiled dependencies).
    """
    zin_fp = BytesIO(template_bytes)
    out_fp = BytesIO()

    # Normalize keys/values to prevent whitespace mismatches
    norm = {str(k).strip(): "" if v is None else str(v) for k, v in tag_values.items()}

    with zipfile.ZipFile(zin_fp, "r") as zin:
        parts = set(iter_word_xml_parts(zin))
        with zipfile.ZipFile(out_fp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if item.filename in parts:
                    try:
                        xml = ET.fromstring(data)
                    except Exception:
                        zout.writestr(item, data)
                        continue

                    # Fill content controls + strip locks
                    for sdt in xml.findall(".//w:sdt", NSMAP):
                        _strip_sdt_locks(sdt)

                        tag_el = sdt.find(".//w:tag", NSMAP)
                        if tag_el is None:
                            continue
                        tag = tag_el.get(f"{{{W_NS}}}val")
                        if not tag:
                            continue

                        tag = tag.strip()
                        if tag in norm:
                            set_sdt_text(sdt, norm[tag])

                    data = ET.tostring(xml, encoding="utf-8", xml_declaration=True)

                zout.writestr(item, data)

    return out_fp.getvalue()


def fill_docx_from_case_bytes(template_bytes: bytes, case_dict: Dict[str, Any]) -> bytes:
    """
    Convenience wrapper: given a case.case dict (legacy + tags), fill the template.
    Also back-fills missing Word tags from legacy values.
    """
    tag_values = build_tag_values(case_dict)
    return fill_docx_content_controls_bytes(template_bytes, tag_values)
