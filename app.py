import streamlit as st
import google.generativeai as genai
from fpdf import FPDF
import os
import re
import json
import io
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

# Custom CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: 'Space Grotesk', sans-serif;
    }

    .main-header {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 2rem;
        text-align: center;
    }
    .main-header h1 {
        color: #fff;
        font-size: 3rem;
        font-weight: 700;
        margin: 0;
        letter-spacing: -1px;
    }
    .main-header p {
        color: rgba(255,255,255,0.6);
        font-size: 1.1rem;
        margin: 0.3rem 0 0 0;
    }

    .step-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea, #764ba2);
        color: white;
        border-radius: 50%;
        width: 28px;
        height: 28px;
        line-height: 28px;
        text-align: center;
        font-weight: 700;
        font-size: 0.85rem;
        margin-right: 8px;
    }

    .info-box {
        background: #f0f4ff;
        border-left: 4px solid #667eea;
        padding: 0.8rem 1rem;
        border-radius: 0 8px 8px 0;
        margin: 0.5rem 0;
        font-size: 0.9rem;
        color: #334;
    }

    .success-box {
        background: #f0fff4;
        border-left: 4px solid #38a169;
        padding: 0.8rem 1rem;
        border-radius: 0 8px 8px 0;
        margin: 0.5rem 0;
        font-size: 0.9rem;
        color: #276749;
    }

    .warning-box {
        background: #fffbeb;
        border-left: 4px solid #f59e0b;
        padding: 0.8rem 1rem;
        border-radius: 0 8px 8px 0;
        margin: 0.5rem 0;
        font-size: 0.9rem;
        color: #78350f;
    }

    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s;
    }

    .diff-added { color: #16a34a; background: #f0fdf4; padding: 2px 4px; border-radius: 3px; }
    .diff-changed { color: #d97706; background: #fffbeb; padding: 2px 4px; border-radius: 3px; }
</style>
""", unsafe_allow_html=True)


def init_ai():
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        return True
    except Exception as e:
        st.error(f"🚨 API Key Missing. Add 'GOOGLE_API_KEY' to Streamlit Secrets. ({e})")
        return False


# ==============================================================================
# 2. CV PARSING — Extract real data from uploaded CV
# ==============================================================================

def extract_text_from_pdf(file_bytes: bytes) -> str:
    """Extract text from PDF using pdfplumber (best for layout) with pypdf fallback."""
    text = ""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
        if text.strip():
            return text
    except Exception:
        pass

    # Fallback: pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
    except Exception as e:
        st.error(f"Could not parse PDF: {e}")
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
    """Extract text from DOCX."""
    try:
        import docx
        doc = docx.Document(io.BytesIO(file_bytes))
        lines = []
        for para in doc.paragraphs:
            if para.text.strip():
                lines.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_text = " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
                if row_text:
                    lines.append(row_text)
        return "\n".join(lines)
    except Exception as e:
        st.error(f"Could not parse DOCX: {e}")
        return ""


def parse_cv_file(uploaded_file) -> str:
    """Route to the correct parser based on file type."""
    file_bytes = uploaded_file.read()
    name = uploaded_file.name.lower()
    if name.endswith(".pdf"):
        return extract_text_from_pdf(file_bytes)
    elif name.endswith(".docx") or name.endswith(".doc"):
        return extract_text_from_docx(file_bytes)
    elif name.endswith(".txt"):
        return file_bytes.decode("utf-8", errors="replace")
    else:
        st.warning("Unsupported file type. Please upload PDF, DOCX, or TXT.")
        return ""


# ==============================================================================
# 3. AI — Tailor CV content to JD WITHOUT fabrication
# ==============================================================================

def get_best_model():
    try:
        priorities = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro']
        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for p in priorities:
            if p in available:
                return p
        for m in available:
            if 'gemini' in m:
                return m
    except Exception:
        pass
    return "models/gemini-1.5-flash"


def tailor_cv(raw_cv_text: str, job_description: str, style: str = "Global") -> str:
    """
    Takes REAL extracted CV text and the target JD.
    Returns a tailored version — no fabrication, only rewording/reprioritising.
    """
    model = genai.GenerativeModel(get_best_model())

    visa_note = (
        "Extract Visa Status and Nationality from the CV if present; include in CONTACT section."
        if style == "Global"
        else "Do NOT include Visa Status, Nationality, or Photo."
    )

    layout_note = (
        "Use a two-column layout marker: write [SIDEBAR_START] before the sidebar section "
        "(Contact, Introduction, Skills, Certifications, Education) and [MAIN_START] before "
        "the main section (Experience, Projects)."
        if style == "Global"
        else "Single column, clean ATS-friendly layout."
    )

    prompt = f"""
You are a professional CV consultant and expert ATS optimizer.

YOUR STRICT RULES:
1. **NO FABRICATION** — every fact, date, company, role, skill, and achievement must come directly from the ORIGINAL CV. Do not invent anything.
2. **REWORD & REFRAME** — rewrite bullet points using keywords and language from the JD. Prioritise experience that matches the JD requirements.
3. **REORDER** — bring the most JD-relevant skills and experiences to the top. Remove or de-emphasise irrelevant points.
4. **SUMMARY** — write a concise 2-sentence professional summary that bridges the candidate's real background with the JD's requirements.
5. **KEYWORDS** — naturally weave JD keywords into existing bullet points where they genuinely apply.
6. **TITLES** — if the candidate's old title is functionally equivalent to the JD title (e.g. "Software Developer" → "Software Engineer"), you may update the title to match. Otherwise keep the original.
7. **FORMATTING** — no markdown bold (**), no horizontal rules (---), no headers with ###.
8. **LENGTH** — aim for a concise 1-page output.
9. **BULLET LIMIT** — max 3 bullets per role.
10. **VISA/PHOTO** — {visa_note}

LAYOUT: {layout_note}

---
ORIGINAL CV:
{raw_cv_text}

---
TARGET JOB DESCRIPTION:
{job_description}

---
OUTPUT FORMAT:
NAME
[Candidate Name]

CONTACT
[Phone] | [Email] | [LinkedIn if present] | [Location]
[Visa/Nationality if Global style]

INTRODUCTION
[2-sentence tailored summary using only real background]

TECHNICAL SKILLS
[Reordered skills — most JD-relevant first]
- Category: skill1, skill2, skill3

PROFESSIONAL EXPERIENCE
[Most Recent Role Title] | [Company] | [Dates]
- [Rewritten bullet using JD keywords — based on real responsibility]
- [Impact-focused bullet — real achievement reworded]
- [Task bullet — real work reframed for JD]

[Previous Role Title] | [Company] | [Dates]
- [Real responsibility rewritten with JD language]
- [Real achievement reframed]

EDUCATION
[Degree], [University] | [Year]

CERTIFICATIONS
- [Real cert 1]
- [Real cert 2 if any]

PROJECTS (if any in original CV)
[Project Name] | [Tech Stack from CV]
- [Real project description rewritten to highlight JD relevance]
"""

    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error generating content: {e}"


# ==============================================================================
# 4. PDF BUILDER
# ==============================================================================

def sanitize(text: str) -> str:
    replacements = {
        '\u2022': '-', '\u2013': '-', '\u2014': '-',
        '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
        '…': '...', '\u00a0': ' ',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r'\*+', '', text)
    text = re.sub(r'#{1,6}\s?', '', text)
    text = text.replace('---', '')
    return text.encode('latin-1', 'replace').decode('latin-1')


def crop_to_circle(image_path: str) -> str:
    try:
        img = Image.open(image_path).convert("RGB")
        size = min(img.size)
        img = ImageOps.fit(img, (size, size), centering=(0.5, 0.5))
        mask = Image.new('L', img.size, 0)
        ImageDraw.Draw(mask).ellipse((0, 0) + img.size, fill=255)
        img.putalpha(mask)
        out_path = "temp_circle_photo.png"
        img.save(out_path)
        return out_path
    except Exception:
        return image_path


class PDF(FPDF):
    pass


def build_pdf(content: str, style: str, photo_path: str = None) -> bytes:
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    content = sanitize(content)

    if style == "Global":
        _build_global_pdf(pdf, content, photo_path)
    else:
        _build_india_pdf(pdf, content)

    return pdf.output(dest='S').encode('latin-1')


def _build_global_pdf(pdf: FPDF, text: str, photo_path: str = None):
    """
    Two-column sidebar layout.
    KEY FIX: Every multi_cell / cell call explicitly sets x AND uses a fixed width
    so text never escapes its column boundary.
    """
    # ── Layout constants ────────────────────────────────────────────────────
    SIDEBAR_X    = 5          # left padding inside sidebar
    SIDEBAR_W    = 67         # total sidebar column width (mm)
    SIDEBAR_TW   = SIDEBAR_W - SIDEBAR_X - 4   # usable text width inside sidebar = 58 mm
    MAIN_X       = SIDEBAR_W + 7               # main column starts at 74 mm
    PAGE_W       = 210
    RIGHT_MARGIN = 8
    MAIN_W       = PAGE_W - MAIN_X - RIGHT_MARGIN  # usable main text width = 128 mm
    PAGE_H       = 297

    ACCENT    = (0, 55, 120)
    LIGHT_BG  = (235, 240, 250)
    DARK_TEXT = (30, 30, 30)

    # ── Background & accent strip ────────────────────────────────────────────
    pdf.set_fill_color(*LIGHT_BG)
    pdf.rect(0, 0, SIDEBAR_W, PAGE_H, 'F')
    pdf.set_fill_color(*ACCENT)
    pdf.rect(0, 0, 4, PAGE_H, 'F')

    # ── Split content at markers ─────────────────────────────────────────────
    sidebar_text = ""
    main_text    = text
    if "[SIDEBAR_START]" in text and "[MAIN_START]" in text:
        parts        = text.split("[MAIN_START]", 1)
        sidebar_text = parts[0].replace("[SIDEBAR_START]", "").strip()
        main_text    = parts[1].strip()
    elif "PROFESSIONAL EXPERIENCE" in text:
        idx          = text.find("PROFESSIONAL EXPERIENCE")
        sidebar_text = text[:idx].strip()
        main_text    = text[idx:].strip()

    # ────────────────────────────────────────────────────────────────────────
    # HELPER: write a multi_cell that is ALWAYS anchored to a fixed x and width
    # ────────────────────────────────────────────────────────────────────────
    def sidebar_cell(txt, h=4.5, align='L'):
        """Write a cell pinned to the sidebar column."""
        if pdf.get_y() > PAGE_H - 10:
            return
        pdf.set_x(SIDEBAR_X)
        pdf.multi_cell(SIDEBAR_TW, h, txt, align=align)

    def main_cell(txt, h=4.5, align='L'):
        """Write a cell pinned to the main column."""
        if pdf.get_y() > PAGE_H - 10:
            return
        pdf.set_x(MAIN_X)
        pdf.multi_cell(MAIN_W, h, txt, align=align)

    # ════════════════════════════════════════════════════════════════════════
    # SIDEBAR
    # ════════════════════════════════════════════════════════════════════════
    cur_y = 14

    # Optional circular photo
    if photo_path and os.path.exists(photo_path):
        circ = crop_to_circle(photo_path)
        pdf.image(circ, x=13, y=cur_y, w=42)
        cur_y += 50
        if circ != photo_path:
            try: os.remove(circ)
            except: pass

    pdf.set_xy(SIDEBAR_X, cur_y)
    pdf.set_text_color(*DARK_TEXT)

    # Find the candidate name (first non-empty non-"NAME" line)
    name_line = next(
        (l.strip() for l in sidebar_text.split('\n')
         if l.strip() and l.strip() != 'NAME'),
        ''
    )

    for raw_line in sidebar_text.split('\n'):
        line = raw_line.strip()
        if pdf.get_y() > PAGE_H - 9:
            break
        if not line:
            pdf.set_xy(SIDEBAR_X, min(pdf.get_y() + 2, PAGE_H - 9))
            continue
        if line == 'NAME':
            continue

        # ── Candidate name ──────────────────────────────────────────────────
        if line == name_line:
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 15)
            pdf.set_text_color(*ACCENT)
            pdf.multi_cell(SIDEBAR_TW, 7, line, align='C')
            pdf.set_text_color(*DARK_TEXT)
            pdf.ln(2)
            continue

        # ── Section header (ALL CAPS, short) ────────────────────────────────
        if line.isupper() and len(line) < 30:
            pdf.ln(4)
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 8)
            pdf.set_text_color(*ACCENT)
            # Draw a coloured underline bar manually so we control width
            pdf.cell(SIDEBAR_TW, 5, line, ln=True, border='B')
            pdf.set_text_color(*DARK_TEXT)
            pdf.set_font("Arial", size=8)
            pdf.ln(1)
            continue

        # ── Skill bullet  "- Category: item1, item2" ────────────────────────
        if line.startswith("-") and ":" in line:
            cat_part, _, det_part = line.partition(":")
            cat = cat_part.replace("-", "").strip()
            det = det_part.strip()
            # Write category bold + detail normal, all within sidebar width
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 7.5)
            # Use cell for the label (no wrap needed — it's short)
            label_w = pdf.get_string_width(cat + ": ") + 1
            # Clamp label width so it never overflows
            label_w = min(label_w, SIDEBAR_TW - 4)
            pdf.cell(label_w, 4.5, cat + ": ", ln=0)
            pdf.set_font("Arial", '', 7.5)
            # Remaining width for the detail text
            remaining_w = SIDEBAR_TW - label_w
            pdf.multi_cell(remaining_w, 4.5, det, align='L')
            pdf.ln(0.5)
            continue

        # ── Regular text (contact, intro, education, certs) ─────────────────
        pdf.set_x(SIDEBAR_X)
        pdf.set_font("Arial", size=8)
        pdf.multi_cell(SIDEBAR_TW, 4.5, line, align='L')

    # ════════════════════════════════════════════════════════════════════════
    # MAIN COLUMN
    # ════════════════════════════════════════════════════════════════════════
    pdf.set_xy(MAIN_X, 14)
    pdf.set_text_color(0, 0, 0)

    def _new_page():
        pdf.add_page()
        pdf.set_fill_color(*LIGHT_BG)
        pdf.rect(0, 0, SIDEBAR_W, PAGE_H, 'F')
        pdf.set_fill_color(*ACCENT)
        pdf.rect(0, 0, 4, PAGE_H, 'F')
        pdf.set_xy(MAIN_X, 14)

    for raw_line in main_text.split('\n'):
        line = raw_line.strip()
        if not line:
            if pdf.get_y() < PAGE_H - 6:
                pdf.set_xy(MAIN_X, pdf.get_y() + 1.5)
            continue
        if pdf.get_y() > PAGE_H - 12:
            _new_page()

        # ── Section header ───────────────────────────────────────────────────
        if line.isupper() and len(line) < 40:
            pdf.ln(4)
            pdf.set_x(MAIN_X)
            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(*ACCENT)
            pdf.cell(MAIN_W, 6, line, ln=True, border='B')
            pdf.set_text_color(0, 0, 0)
            pdf.ln(2)
            continue

        # ── Role / Project header line:  "Title | Company | Dates" ──────────
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(3)
            pdf.set_x(MAIN_X)
            if len(parts) >= 3:
                title, company, dates = parts[0], parts[1], parts[2]
                # Title (bold) + Dates (italic, right-aligned) on one line
                pdf.set_font("Arial", 'B', 10)
                title_w  = MAIN_W * 0.62
                dates_w  = MAIN_W * 0.38
                pdf.set_x(MAIN_X)
                pdf.cell(title_w, 5, title[:45], ln=0)      # truncate if extreme
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(dates_w, 5, dates, ln=1, align='R')
                # Company on next line
                pdf.set_x(MAIN_X)
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(60, 60, 60)
                pdf.cell(MAIN_W, 4.5, company, ln=True)
            elif len(parts) == 2:
                pdf.set_font("Arial", 'B', 10)
                pdf.set_x(MAIN_X)
                pdf.cell(MAIN_W * 0.65, 5, parts[0][:45], ln=0)
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(80, 80, 80)
                pdf.cell(MAIN_W * 0.35, 5, parts[1], ln=1, align='R')
            else:
                pdf.set_font("Arial", 'B', 10)
                pdf.set_x(MAIN_X)
                pdf.multi_cell(MAIN_W, 5, line, align='L')
            pdf.set_text_color(0, 0, 0)
            continue

        # ── Bullet point ─────────────────────────────────────────────────────
        if line.startswith("-"):
            pdf.set_x(MAIN_X + 3)
            pdf.set_font("Arial", size=9)
            pdf.multi_cell(MAIN_W - 3, 4.5, line, align='L')
            continue

        # ── Regular paragraph text ───────────────────────────────────────────
        pdf.set_x(MAIN_X)
        pdf.set_font("Arial", size=9)
        pdf.multi_cell(MAIN_W, 4.5, line, align='L')


def _build_india_pdf(pdf: FPDF, text: str):
    """
    Jake's Resume-inspired ATS layout — the most recognised, most forked
    single-column resume template used at FAANG / top tech companies.

    Rules faithfully followed:
    • 0.5-inch (12.7mm) margins all sides
    • Name: 24pt Bold, centred, black
    • Contact bar: 9pt, centred, separator " | "
    • Section header: 11pt Bold, ALL CAPS, full-width bottom border, small gap below
    • Role row: "Title (bold 10.5) ............. Dates (italic 10, right-aligned)"
    • Company row: italic 10pt, left-aligned, slight grey
    • Bullet: 10pt, 5mm left indent, "bullet character + space + text", wrapped
    • Tight vertical rhythm: 4.5pt line height for bullets, 5pt for headers
    • Body font: Arial (Calibri-equivalent — ATS safe, clean)
    """

    # ── Constants (Jake's exact proportions converted to mm) ─────────────────
    MARGIN      = 12.7          # 0.5 inch
    PAGE_W      = 210
    PAGE_H      = 297
    TEXT_W      = PAGE_W - 2 * MARGIN          # 184.6 mm
    BULLET_INDENT = MARGIN + 4                 # 16.7 mm
    BULLET_W      = TEXT_W - 4                # slightly narrower for wrapping

    BLACK       = (0, 0, 0)
    DARK_GREY   = (55, 55, 55)
    MID_GREY    = (90, 90, 90)

    # ── Page setup ───────────────────────────────────────────────────────────
    pdf.set_left_margin(MARGIN)
    pdf.set_right_margin(MARGIN)
    pdf.set_top_margin(MARGIN)
    pdf.set_y(MARGIN)

    text  = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
    lines = text.split('\n')

    # Pre-pass: find the name (first non-empty, non-header, non-"NAME" line)
    name_line = next(
        (l.strip() for l in lines
         if l.strip() and l.strip() != "NAME" and not l.strip().isupper()),
        ""
    )
    name_done    = False
    contact_done = False   # first contact bar right after name

    def draw_section_rule():
        """Draw a thin full-width line — the Jake's Resume section divider."""
        x = MARGIN
        y = pdf.get_y()
        pdf.set_draw_color(0, 0, 0)
        pdf.set_line_width(0.4)
        pdf.line(x, y, x + TEXT_W, y)
        pdf.set_line_width(0.2)   # reset

    for raw_line in lines:
        line = raw_line.strip()

        # Hard page limit for 1-page mode
        if pdf.get_y() > PAGE_H - MARGIN - 4:
            break

        # ── Skip markers & "NAME" keyword ────────────────────────────────────
        if not line or line == "NAME":
            if line == "" and name_done:
                pdf.ln(1.5)
            continue

        # ── CANDIDATE NAME ────────────────────────────────────────────────────
        if not name_done and line == name_line:
            pdf.set_font("Arial", 'B', 24)
            pdf.set_text_color(*BLACK)
            pdf.set_x(MARGIN)
            pdf.cell(TEXT_W, 10, line, ln=True, align='C')
            name_done = True
            continue

        # ── CONTACT BAR (line right after name — has | or @ or phone chars) ──
        if name_done and not contact_done:
            if "|" in line or "@" in line or "+" in line:
                pdf.set_font("Arial", '', 9)
                pdf.set_text_color(*DARK_GREY)
                pdf.set_x(MARGIN)
                pdf.cell(TEXT_W, 5, line, ln=True, align='C')
                pdf.ln(1)
                contact_done = True
                continue

        # ── SECTION HEADER (ALL CAPS short line) ─────────────────────────────
        if line.isupper() and 2 < len(line) < 40 and "|" not in line:
            pdf.ln(4)
            pdf.set_x(MARGIN)
            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(*BLACK)
            # Print the label
            pdf.cell(TEXT_W, 5.5, line, ln=True, align='L')
            # Draw rule immediately below
            draw_section_rule()
            pdf.ln(2.5)
            continue

        # ── ROLE / PROJECT HEADER  "Title | Company | Dates" ─────────────────
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(3)
            pdf.set_x(MARGIN)

            if len(parts) >= 3:
                title, company, dates = parts[0], parts[1], parts[2]

                # Row 1: Title (bold) + Dates (italic, right)
                pdf.set_font("Arial", 'B', 10.5)
                pdf.set_text_color(*BLACK)
                title_w = pdf.get_string_width(title) + 1
                title_w = min(title_w, TEXT_W * 0.72)
                pdf.set_x(MARGIN)
                pdf.cell(title_w, 5, title, ln=0, align='L')
                # Fill remaining width with dates right-aligned
                dates_w = TEXT_W - title_w
                pdf.set_font("Arial", 'I', 10)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(dates_w, 5, dates, ln=1, align='R')

                # Row 2: Company (italic, dark grey)
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", 'I', 10)
                pdf.set_text_color(*DARK_GREY)
                pdf.cell(TEXT_W, 4.5, company, ln=True, align='L')

            elif len(parts) == 2:
                # Could be "Project Name | Tech Stack"
                pdf.set_font("Arial", 'B', 10.5)
                pdf.set_text_color(*BLACK)
                label_w = TEXT_W * 0.65
                pdf.cell(label_w, 5, parts[0], ln=0, align='L')
                pdf.set_font("Arial", 'I', 10)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(TEXT_W - label_w, 5, parts[1], ln=1, align='R')
            else:
                pdf.set_font("Arial", 'B', 10.5)
                pdf.set_text_color(*BLACK)
                pdf.cell(TEXT_W, 5, parts[0], ln=True, align='L')

            pdf.set_text_color(*BLACK)
            continue

        # ── BULLET POINT ──────────────────────────────────────────────────────
        if line.startswith("-"):
            # Replace leading dash with a proper bullet character
            bullet_text = "\x95 " + line[1:].lstrip()   # chr(0x95) = •  in cp1252/latin-1
            pdf.set_font("Arial", '', 10)
            pdf.set_text_color(*BLACK)
            pdf.set_x(BULLET_INDENT)
            pdf.multi_cell(BULLET_W, 4.5, bullet_text, align='L')
            continue

        # ── REGULAR TEXT (summaries, skill lines without dash, etc.) ─────────
        pdf.set_font("Arial", '', 10)
        pdf.set_text_color(*BLACK)
        pdf.set_x(MARGIN)
        pdf.multi_cell(TEXT_W, 4.5, line, align='L')


# ==============================================================================
# 5. UI
# ==============================================================================

st.markdown("""
<div class="main-header">
    <h1>🃏 BeTheJack</h1>
    <p>Upload your real CV → tailor it to any job — no BS, no fabrication.</p>
</div>
""", unsafe_allow_html=True)

ai_connected = init_ai()

# Session state
for key, default in {
    "raw_cv_text": "",
    "tailored_content": "",
    "cv_filename": "",
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ──────────────────────────────────────────────
# STEP 1 + 2 — Upload & JD
# ──────────────────────────────────────────────
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.markdown("#### <span class='step-badge'>1</span> Upload Your CV", unsafe_allow_html=True)
    st.markdown('<div class="info-box">Supported: PDF, DOCX, TXT — your real CV, not a template.</div>', unsafe_allow_html=True)

    uploaded_cv = st.file_uploader(
        "Drop your CV here",
        type=["pdf", "docx", "doc", "txt"],
        label_visibility="collapsed"
    )

    if uploaded_cv:
        if uploaded_cv.name != st.session_state.cv_filename:
            with st.spinner("Reading your CV..."):
                extracted = parse_cv_file(uploaded_cv)
                st.session_state.raw_cv_text = extracted
                st.session_state.cv_filename = uploaded_cv.name
                st.session_state.tailored_content = ""

        if st.session_state.raw_cv_text:
            st.markdown('<div class="success-box">✅ CV parsed successfully!</div>', unsafe_allow_html=True)
            with st.expander("👁️ Preview extracted text"):
                st.text(st.session_state.raw_cv_text[:3000] + ("..." if len(st.session_state.raw_cv_text) > 3000 else ""))
        else:
            st.error("Could not extract text. Is the CV a scanned image? Try a text-based PDF or DOCX.")

    st.markdown("---")
    st.markdown("#### <span class='step-badge'>2</span> Select Layout", unsafe_allow_html=True)
    mode = st.radio(
        "Layout style",
        ["🌍 Global — Sidebar + Photo", "🇮🇳 ATS — Jake's Resume Style (Single Column)"],
        label_visibility="collapsed"
    )
    style_choice = "Global" if "Global" in mode else "India"

    uploaded_photo = None
    if style_choice == "Global":
        uploaded_photo = st.file_uploader("Upload Profile Photo (optional)", type=['jpg', 'jpeg', 'png'])


with col2:
    st.markdown("#### <span class='step-badge'>3</span> Paste Job Description", unsafe_allow_html=True)
    job_desc = st.text_area(
        "Job Description",
        height=340,
        placeholder="Paste the full job description here...\n\nThe more detail you provide, the better the tailoring.",
        label_visibility="collapsed"
    )

# ──────────────────────────────────────────────
# GENERATE BUTTON
# ──────────────────────────────────────────────
st.markdown("---")
col_btn, col_info = st.columns([1, 2])
with col_btn:
    generate_btn = st.button("✨ Tailor My CV", type="primary", use_container_width=True)

with col_info:
    st.markdown("""
    <div class="info-box">
    <b>What this does:</b> Rewrites your real experience using JD keywords, reorders skills by relevance,
    and crafts a targeted summary — <em>all based only on what's already in your CV</em>.
    </div>
    """, unsafe_allow_html=True)

if generate_btn:
    if not st.session_state.raw_cv_text:
        st.error("Please upload your CV first.")
    elif not job_desc.strip():
        st.error("Please paste a Job Description.")
    elif not ai_connected:
        st.error("AI not connected. Check your API key in Secrets.")
    else:
        with st.spinner("Tailoring your CV to the job description... this takes ~15 seconds."):
            st.session_state.tailored_content = tailor_cv(
                st.session_state.raw_cv_text,
                job_desc,
                style=style_choice
            )

# ──────────────────────────────────────────────
# EDIT + RENDER
# ──────────────────────────────────────────────
if st.session_state.tailored_content:
    st.markdown("---")
    st.markdown("#### <span class='step-badge'>4</span> Review & Edit the Tailored Draft", unsafe_allow_html=True)
    st.markdown('<div class="warning-box">⚠️ Always review before downloading. Check dates, titles, and facts are still accurate.</div>', unsafe_allow_html=True)

    edited = st.text_area(
        "Tailored CV Content",
        value=st.session_state.tailored_content,
        height=580,
        label_visibility="collapsed"
    )
    st.session_state.tailored_content = edited

    col_pdf, col_dl = st.columns([1, 2])
    with col_pdf:
        render_btn = st.button("📄 Render PDF", type="secondary", use_container_width=True)

    if render_btn:
        with st.spinner("Building your PDF..."):
            photo_path = None
            if uploaded_photo:
                photo_path = "temp_profile_photo.jpg"
                with open(photo_path, "wb") as f:
                    f.write(uploaded_photo.getbuffer())

            pdf_bytes = build_pdf(st.session_state.tailored_content, style_choice, photo_path=photo_path)

            if photo_path and os.path.exists(photo_path):
                try: os.remove(photo_path)
                except: pass

            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:25]) if job_desc else "Resume"
            filename = f"CV_{style_choice}_{safe_title}.pdf"

        st.success("✅ PDF is ready!")
        st.download_button(
            label="📥 Download PDF",
            data=pdf_bytes,
            file_name=filename,
            mime="application/pdf",
            use_container_width=True
        )

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#888;font-size:0.8rem;'>BeTheJack · Tailors real CVs to real jobs · No fabrication, ever.</div>",
    unsafe_allow_html=True
)
