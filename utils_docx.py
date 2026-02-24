from __future__ import annotations
import zipfile
from lxml import etree
from io import BytesIO

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NSMAP = {"w": W_NS}

def iter_word_xml_parts(zipf: zipfile.ZipFile):
    for name in zipf.namelist():
        if name.startswith("word/") and name.endswith(".xml"):
            yield name

def set_sdt_text(sdt, text: str):
    if text is None:
        text = ""

    text_nodes = sdt.findall(".//w:sdtContent//w:t", namespaces=NSMAP)

    if not text_nodes:
        content = sdt.find(".//w:sdtContent", namespaces=NSMAP)
        if content is None:
            return
        p = etree.Element(f"{{{W_NS}}}p")
        r = etree.SubElement(p, f"{{{W_NS}}}r")
        t = etree.SubElement(r, f"{{{W_NS}}}t")
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        t.text = str(text)
        content.append(p)
        return

    text_nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    text_nodes[0].text = str(text)
    for n in text_nodes[1:]:
        n.text = ""

def fill_docx_content_controls_bytes(template_bytes: bytes, tag_values: dict[str, str]) -> bytes:
    zin_fp = BytesIO(template_bytes)
    out_fp = BytesIO()

    with zipfile.ZipFile(zin_fp, "r") as zin:
        parts = set(iter_word_xml_parts(zin))
        with zipfile.ZipFile(out_fp, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                data = zin.read(item.filename)

                if item.filename in parts:
                    try:
                        xml = etree.fromstring(data)
                    except Exception:
                        zout.writestr(item, data)
                        continue

                    for sdt in xml.findall(".//w:sdt", namespaces=NSMAP):
                        tag_el = sdt.find(".//w:tag", namespaces=NSMAP)
                        if tag_el is None:
                            continue
                        tag = tag_el.get(f"{{{W_NS}}}val")
                        if not tag:
                            continue
                        if tag in tag_values:
                            set_sdt_text(sdt, str(tag_values[tag]))

                    data = etree.tostring(xml, xml_declaration=True, encoding="UTF-8", standalone="yes")

                zout.writestr(item, data)

    return out_fp.getvalue()
