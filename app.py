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
    Takes real extracted CV text and the target JD.
    Returns a tailored, enhanced version with up to 30% JD-driven augmentation.
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
You are an elite CV strategist and ATS optimization expert working for a premium career consultancy.

YOUR MANDATE:
Transform the candidate's real CV into a highly targeted document for the job below.
You are allowed — and expected — to ENHANCE up to 30% of the content beyond what is literally in the CV,
provided that every enhancement is PLAUSIBLE and GROUNDED in the candidate's actual role and responsibilities.

ENHANCEMENT RULES (the 30% licence):
A. SKILLS: Add tools, languages, platforms, and methodologies mentioned in the JD that are
   directly adjacent to what the candidate already does.
B. BULLET POINTS: Expand existing bullets by injecting JD keywords, metrics, and tools.
   Example: "managed service tickets" → "Managed and triaged 200+ monthly service tickets via ServiceNow,
   applying ITIL best practices to reduce resolution time by 25%."
C. INTRO: Write a 2-sentence punchy summary mirroring the JD language, using the real background.
D. DO NOT invent entirely new roles, companies, degrees, or certifications that don't exist in the CV.
E. TITLES: You may align job titles to the JD title if functionally equivalent.

CRITICAL — BULLET LIMIT (THIS IS THE MOST IMPORTANT RULE):
- MAXIMUM 3 bullets per job role. NO EXCEPTIONS. Count them. If you have written 3, STOP.
- If a role has many responsibilities, pick the TOP 3 most relevant to the JD.
- Violating this rule makes the CV look unprofessional and spills onto multiple pages.

PROJECTS (MANDATORY):
- Include ALL existing projects from the original CV (rewritten with JD relevance).
- INVENT exactly 2 additional projects. These invented projects must:
  * Use tools, languages, and technologies explicitly mentioned in the JD.
  * Be completely believable given the candidate's real job context (e.g., if they work in IT support at a finance firm, a project could be "Automated SLA Breach Detection" using Python + SQL + Grafana).
  * Sound like something the candidate genuinely could have built in their own time or as a work initiative.
  * Each invented project gets exactly 1 bullet point description.

STRICT FORMAT RULES:
1. No markdown bold (**), no horizontal rules (---), no ### headers.
2. Output ONLY the resume text — zero preamble, zero explanation, zero commentary after the content.
3. Section headers: ALL CAPS exactly (e.g., PROFESSIONAL EXPERIENCE).
4. Bullet points: start with "- " (dash space). MAX 3 per role.
5. Role lines: Title | Company - City | Start - End
6. Skill lines: Category: item1, item2, item3
7. Project lines: Project Name | Tech1, Tech2, Tech3  (2-part pipe only — NO dates)
8. {visa_note}
9. LAYOUT: {layout_note}

---
ORIGINAL CV:
{raw_cv_text}

---
TARGET JOB DESCRIPTION:
{job_description}

---
OUTPUT FORMAT (copy this structure exactly):

NAME
[Candidate Full Name]

CONTACT
[Phone] | [Email] | [LinkedIn if in CV] | [Location]

INTRODUCTION
[Sentence 1. Sentence 2.]

TECHNICAL SKILLS
[Category]: [skill1, skill2, skill3]
[Category]: [skill1, skill2, skill3]
[Category]: [skill1, skill2, skill3]
[Category]: [skill1, skill2, skill3]

PROFESSIONAL EXPERIENCE
[Job Title] | [Company - City] | [Start] - [End]
- [Bullet 1 — MAX 3 TOTAL]
- [Bullet 2]
- [Bullet 3]

[Job Title] | [Company - City] | [Start] - [End]
- [Bullet 1 — MAX 3 TOTAL]
- [Bullet 2]
- [Bullet 3]

[Job Title] | [Company - City] | [Start] - [End]
- [Bullet 1 — MAX 3 TOTAL]
- [Bullet 2]

PROJECTS
[Real project from CV rewritten] | [Tech Stack]
- [1 bullet — JD-relevant description]

[Invented project 1 — believable, JD tools] | [JD Tech Stack]
- [1 bullet — what it does and its impact]

[Invented project 2 — believable, JD tools] | [JD Tech Stack]
- [1 bullet — what it does and its impact]

EDUCATION
[Degree] | [University] | [Year]

CERTIFICATIONS
- [Cert 1]
- [Cert 2]
"""

    try:
        response = model.generate_content(prompt)
        raw = response.text
        # Safety net: enforce 3-bullet max regardless of what AI produced
        return enforce_bullet_limit(raw, max_bullets=3)
    except Exception as e:
        return f"Error generating content: {e}"


# ==============================================================================
# 4. PDF BUILDER
# ==============================================================================

def enforce_bullet_limit(text: str, max_bullets: int = 3) -> str:
    """
    Post-processing safety net: ensures no role block has more than max_bullets bullets.
    Walks line by line; once a role header is found, counts consecutive bullet lines
    and drops any beyond the limit.
    """
    lines = text.split('\n')
    result = []
    bullet_count = 0

    for line in lines:
        stripped = line.strip()
        # A pipe line that isn't a bullet = new role/project header → reset counter
        if '|' in stripped and not stripped.startswith('-'):
            bullet_count = 0
            result.append(line)
            continue
        # An ALL-CAPS line = section header → reset counter
        if stripped.isupper() and len(stripped) > 3:
            bullet_count = 0
            result.append(line)
            continue
        # Bullet line
        if stripped.startswith('- ') or (stripped.startswith('-') and len(stripped) > 2):
            bullet_count += 1
            if bullet_count > max_bullets:
                continue   # DROP this bullet
            result.append(line)
            continue
        # Everything else (blank lines, text) → reset bullet counter if blank
        if not stripped:
            bullet_count = 0
        result.append(line)

    return '\n'.join(result)
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


def build_pdf(content: str, style: str, photo_path: str = None, photo_size: int = 52) -> bytes:
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)

    content = sanitize(content)

    if style == "Global":
        _build_global_pdf(pdf, content, photo_path, photo_size=photo_size)
    else:
        _build_india_pdf(pdf, content)

    return pdf.output(dest='S').encode('latin-1')


def _build_global_pdf(pdf: FPDF, text: str, photo_path: str = None, photo_size: int = 52):
    """
    Premium two-column sidebar layout inspired by the attached PDF reference.
    Dark navy sidebar, gold accent line, square-ish photo, bold company names in main.

    photo_size: width in mm of the profile photo (user-adjustable, default 52)
    """
    # ── Layout constants ──────────────────────────────────────────────────────
    SIDEBAR_W    = 72
    SIDEBAR_X    = 6           # left text padding
    SIDEBAR_TW   = SIDEBAR_W - SIDEBAR_X - 4   # = 62 mm usable
    MAIN_X       = SIDEBAR_W + 6
    PAGE_W       = 210
    RIGHT_MARGIN = 9
    MAIN_W       = PAGE_W - MAIN_X - RIGHT_MARGIN
    PAGE_H       = 297

    # Colour palette — matches the reference PDF
    NAVY         = (18,  40,  76)   # dark navy sidebar bg
    GOLD         = (180, 148,  80)  # gold accent
    SIDEBAR_TEXT = (220, 220, 220)  # light text on dark bg
    SIDEBAR_DIM  = (160, 160, 160)  # dimmer text (contact details)
    WHITE        = (255, 255, 255)
    BLACK        = (10,  10,  10)
    DARK_GREY    = (50,  50,  50)
    MID_GREY     = (100, 100, 100)

    # ── Full-page navy sidebar background ────────────────────────────────────
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, SIDEBAR_W, PAGE_H, 'F')

    # Gold accent top bar (full width)
    pdf.set_fill_color(*GOLD)
    pdf.rect(0, 0, PAGE_W, 3, 'F')

    # ── Split content ─────────────────────────────────────────────────────────
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

    SKIP_WORDS = {"NAME", "CONTACT", "INTRODUCTION", "SIDEBAR_START", "MAIN_START"}

    # ════════════════════════════════════════════════════════════════════════
    # SIDEBAR
    # ════════════════════════════════════════════════════════════════════════
    cur_y = 8  # start below gold top bar

    # ── Profile photo — CIRCLE crop, centered in sidebar ─────────────────────
    if photo_path and os.path.exists(photo_path):
        try:
            img  = Image.open(photo_path).convert("RGBA")
            size = min(img.size)
            img  = ImageOps.fit(img, (size, size), centering=(0.5, 0.25))
            # Create circular mask
            mask = Image.new('L', (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            circle = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            circle.paste(img, mask=mask)
            # Paste on white bg (FPDF needs RGB)
            bg = Image.new('RGB', (size, size), (18, 40, 76))  # navy bg matches sidebar
            bg.paste(circle, mask=circle.split()[3])
            circ_path = "temp_circle_photo.png"
            bg.save(circ_path, "PNG")
            photo_x = (SIDEBAR_W - photo_size) / 2
            pdf.image(circ_path, x=photo_x, y=cur_y, w=photo_size)
            cur_y += photo_size + 4
            try: os.remove(circ_path)
            except: pass
        except Exception:
            cur_y = 8

    # Gold divider under photo
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.6)
    pdf.line(SIDEBAR_X, cur_y, SIDEBAR_W - 4, cur_y)
    pdf.set_line_width(0.2)
    cur_y += 4

    pdf.set_xy(SIDEBAR_X, cur_y)

    # Find name (first non-skip, non-pipe, non-empty line in sidebar)
    name_line = next(
        (l.strip() for l in sidebar_text.split('\n')
         if l.strip() and l.strip() not in SKIP_WORDS and '|' not in l),
        ''
    )

    for raw_line in sidebar_text.split('\n'):
        line = raw_line.strip()
        if pdf.get_y() > PAGE_H - 8:
            break
        if not line:
            pdf.set_xy(SIDEBAR_X, min(pdf.get_y() + 1.5, PAGE_H - 8))
            continue
        # Skip AI boilerplate markers
        if line in SKIP_WORDS:
            continue

        # ── Name ─────────────────────────────────────────────────────────────
        if line == name_line:
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 14)
            pdf.set_text_color(*WHITE)
            pdf.multi_cell(SIDEBAR_TW, 7, line.upper(), align='C')
            # Gold underline
            uy = pdf.get_y() + 1
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(SIDEBAR_X + 4, uy, SIDEBAR_W - 8, uy)
            pdf.set_line_width(0.2)
            pdf.ln(4)
            continue

        # ── Section header (ALL CAPS, not a skip word, no digits) ────────────
        if (line.isupper() and 3 < len(line) < 30
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            pdf.ln(4)
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 8)
            pdf.set_text_color(*GOLD)
            pdf.cell(SIDEBAR_TW, 5, line, ln=True)
            # Gold rule
            ry = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.4)
            pdf.line(SIDEBAR_X, ry, SIDEBAR_W - 4, ry)
            pdf.set_line_width(0.2)
            pdf.ln(2)
            continue

        # ── Skill bullet "- Category: items" ─────────────────────────────────
        if line.startswith("-") and ":" in line:
            cat_part, _, det_part = line.partition(":")
            cat = cat_part.replace("-", "").strip()
            det = det_part.strip()
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 7.5)
            pdf.set_text_color(*GOLD)
            label_w = min(pdf.get_string_width(cat + ": ") + 1, SIDEBAR_TW - 6)
            pdf.cell(label_w, 4.5, cat + ": ", ln=0)
            pdf.set_font("Arial", '', 7.5)
            pdf.set_text_color(*SIDEBAR_TEXT)
            pdf.multi_cell(SIDEBAR_TW - label_w, 4.5, det, align='L')
            pdf.ln(0.3)
            continue

        # ── Bullet (certs, skills list) ───────────────────────────────────────
        if line.startswith("-"):
            pdf.set_x(SIDEBAR_X + 2)
            pdf.set_font("Arial", '', 8)
            pdf.set_text_color(*SIDEBAR_TEXT)
            pdf.multi_cell(SIDEBAR_TW - 2, 4.5, "\x95 " + line[1:].lstrip(), align='L')
            continue

        # ── Regular sidebar text ──────────────────────────────────────────────
        pdf.set_x(SIDEBAR_X)
        pdf.set_font("Arial", size=8)
        pdf.set_text_color(*SIDEBAR_DIM)
        pdf.multi_cell(SIDEBAR_TW, 4.5, line, align='L')

    # ════════════════════════════════════════════════════════════════════════
    # MAIN COLUMN
    # ════════════════════════════════════════════════════════════════════════
    pdf.set_xy(MAIN_X, 8)
    pdf.set_text_color(*BLACK)

    def _new_page():
        pdf.add_page()
        pdf.set_fill_color(*NAVY)
        pdf.rect(0, 0, SIDEBAR_W, PAGE_H, 'F')
        pdf.set_fill_color(*GOLD)
        pdf.rect(0, 0, PAGE_W, 3, 'F')
        pdf.set_xy(MAIN_X, 8)

    for raw_line in main_text.split('\n'):
        line = raw_line.strip()
        if not line:
            if pdf.get_y() < PAGE_H - 6:
                pdf.set_xy(MAIN_X, pdf.get_y() + 1.5)
            continue
        if pdf.get_y() > PAGE_H - 12:
            _new_page()

        # ── Section header ────────────────────────────────────────────────────
        if (line.isupper() and len(line) < 40
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            pdf.ln(5)
            pdf.set_x(MAIN_X)
            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(*NAVY)
            pdf.cell(MAIN_W, 6, line, ln=True)
            # Gold underline
            ry = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(MAIN_X, ry, MAIN_X + MAIN_W, ry)
            pdf.set_line_width(0.2)
            pdf.set_text_color(*BLACK)
            pdf.ln(3)
            continue

        # ── Role/Project line:  "Title | Company | Dates" ────────────────────
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(3)
            pdf.set_x(MAIN_X)

            if len(parts) >= 3:
                title, company, dates = parts[0], parts[1], parts[2]
                # Company name BOLD large — like reference PDF
                pdf.set_font("Arial", 'B', 11)
                pdf.set_text_color(*NAVY)
                pdf.set_x(MAIN_X)
                pdf.cell(MAIN_W, 5.5, company.upper(), ln=True)
                # Title + Dates on second row
                pdf.set_x(MAIN_X)
                pdf.set_font("Arial", 'B', 9.5)
                pdf.set_text_color(*DARK_GREY)
                title_w = MAIN_W * 0.65
                pdf.cell(title_w, 4.5, title, ln=0)
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(MAIN_W - title_w, 4.5, dates, ln=1, align='R')

            elif len(parts) == 2:
                # Project: "Name | Tech Stack"
                # Measure both — if they fit on one line, keep them; otherwise stack
                proj_name = parts[0]
                tech_stack = parts[1]
                pdf.set_font("Arial", 'B', 10)
                pdf.set_text_color(*NAVY)
                name_w = pdf.get_string_width(proj_name) + 2
                pdf.set_font("Arial", 'I', 9)
                tech_w = pdf.get_string_width(tech_stack) + 2

                if name_w + tech_w + 4 <= MAIN_W:
                    # Fits on one line
                    gap_w = MAIN_W - name_w - tech_w
                    pdf.set_font("Arial", 'B', 10)
                    pdf.set_text_color(*NAVY)
                    pdf.set_x(MAIN_X)
                    pdf.cell(name_w, 5, proj_name, ln=0)
                    pdf.cell(gap_w, 5, "", ln=0)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.cell(tech_w, 5, tech_stack, ln=1, align='R')
                else:
                    # Name too long — put tech on next line
                    pdf.set_font("Arial", 'B', 10)
                    pdf.set_text_color(*NAVY)
                    pdf.set_x(MAIN_X)
                    pdf.multi_cell(MAIN_W, 5, proj_name, align='L')
                    pdf.set_x(MAIN_X)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.multi_cell(MAIN_W, 4.5, tech_stack, align='L')
            else:
                pdf.set_font("Arial", 'B', 10)
                pdf.set_text_color(*NAVY)
                pdf.multi_cell(MAIN_W, 5, parts[0], align='L')

            pdf.set_text_color(*BLACK)
            continue

        # ── Bullet ────────────────────────────────────────────────────────────
        if line.startswith("-"):
            pdf.set_x(MAIN_X + 3)
            pdf.set_font("Arial", size=9)
            pdf.set_text_color(*DARK_GREY)
            pdf.multi_cell(MAIN_W - 3, 4.5, "\x95 " + line[1:].lstrip(), align='L')
            continue

        # ── Regular text ─────────────────────────────────────────────────────
        pdf.set_x(MAIN_X)
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(*DARK_GREY)
        pdf.multi_cell(MAIN_W, 4.5, line, align='L')


def _build_india_pdf(pdf: FPDF, text: str):
    """
    Jake's Resume — production-grade ATS layout.

    ROOT CAUSE FIXES vs previous broken version:
    - "NAME", "CONTACT", "INTRODUCTION" are SKIPPED as section keywords —
      they are AI output artifacts that the PDF should not render as headers.
    - Contact detection is explicit: only triggered by presence of @ or +91 / phone digits.
    - Name detection: first non-empty line after stripping markers, regardless of case.
    - Section headers: ALL CAPS AND length 4–35 chars AND not a skip-word AND no digits.
    - Skills: "Category: values" detected with colon and no leading dash.
    - Bullets: lines starting with "- ".
    - Everything else: plain paragraph text.

    LAYOUT (Jake's Resume spec):
    - 0.5" (12.7mm) margins all sides
    - Name: 20pt Bold, centred
    - Contact: 9pt, centred, thin rule below
    - Section header: 10.5pt Bold ALL CAPS, thin rule immediately below
    - Role line: Title bold left + Dates italic right, Company italic below
    - Bullet: 9.5pt, 4mm indent, • character
    - Skills: Bold category inline + normal detail
    """
    MARGIN   = 12.7
    PAGE_W   = 210
    PAGE_H   = 297
    TEXT_W   = PAGE_W - 2 * MARGIN     # 184.6 mm
    BULLET_X = MARGIN + 4
    BULLET_W = TEXT_W - 4

    BLACK     = (0,   0,   0)
    DARK_GREY = (50,  50,  50)
    MID_GREY  = (110, 110, 110)

    # Words that look like ALL-CAPS headers but are AI boilerplate — skip them
    SKIP_WORDS = {"NAME", "CONTACT", "INTRODUCTION", "SIDEBAR_START", "MAIN_START"}

    pdf.set_left_margin(MARGIN)
    pdf.set_right_margin(MARGIN)
    pdf.set_top_margin(MARGIN)
    pdf.set_y(MARGIN)

    text  = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
    lines = [l.rstrip() for l in text.split('\n')]

    # ── Pre-pass: identify name and contact lines ─────────────────────────────
    # Name = first non-empty line that is NOT a skip word and NOT a pipe line
    name_line = ""
    for l in lines:
        s = l.strip()
        if s and s not in SKIP_WORDS and "|" not in s and not s.startswith("-"):
            name_line = s
            break

    # Contact = first line containing @ or starting with + or 7–10 consecutive digits
    contact_line = ""
    for l in lines:
        s = l.strip()
        if "@" in s or s.startswith("+") or re.search(r'\d{7,}', s):
            if s != name_line:
                contact_line = s
                break

    name_printed    = False
    contact_printed = False

    def draw_rule(thickness=0.35):
        pdf.set_draw_color(*BLACK)
        pdf.set_line_width(thickness)
        pdf.line(MARGIN, pdf.get_y(), MARGIN + TEXT_W, pdf.get_y())
        pdf.set_line_width(0.2)

    for raw_line in lines:
        line = raw_line.strip()

        # ── Page limit ────────────────────────────────────────────────────────
        if pdf.get_y() > PAGE_H - MARGIN - 3:
            break

        # ── Skip blank lines (small spacing) ──────────────────────────────────
        if not line:
            if name_printed:
                pdf.ln(1.0)
            continue

        # ── Skip boilerplate words ─────────────────────────────────────────────
        if line in SKIP_WORDS:
            continue

        # ── NAME ──────────────────────────────────────────────────────────────
        if not name_printed and line == name_line:
            pdf.set_font("Arial", 'B', 20)
            pdf.set_text_color(*BLACK)
            pdf.set_x(MARGIN)
            pdf.cell(TEXT_W, 9, line, ln=True, align='C')
            name_printed = True
            continue

        # ── CONTACT ───────────────────────────────────────────────────────────
        if name_printed and not contact_printed and line == contact_line:
            pdf.set_font("Arial", '', 9)
            pdf.set_text_color(*DARK_GREY)
            pdf.set_x(MARGIN)
            pdf.multi_cell(TEXT_W, 4.5, line, align='C')
            # thin rule below contact
            pdf.set_draw_color(*MID_GREY)
            pdf.set_line_width(0.25)
            pdf.line(MARGIN, pdf.get_y() + 0.5, MARGIN + TEXT_W, pdf.get_y() + 0.5)
            pdf.set_line_width(0.2)
            pdf.ln(3.5)
            contact_printed = True
            continue

        # ── SECTION HEADER ─────────────────────────────────────────────────────
        # ALL CAPS, 4–35 chars, no pipe, no digits, not a skip word
        if (line.isupper()
                and 3 < len(line) <= 35
                and "|" not in line
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            pdf.ln(5)
            pdf.set_x(MARGIN)
            pdf.set_font("Arial", 'B', 10.5)
            pdf.set_text_color(*BLACK)
            pdf.cell(TEXT_W, 5, line, ln=True, align='L')
            draw_rule(0.35)
            pdf.ln(2.5)
            continue

        # ── ROLE / PROJECT PIPE LINE  "Title | Company | Dates" ──────────────
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(2.5)

            if len(parts) >= 3:
                title, company, dates = parts[0], parts[1], parts[2]
                # Row 1: title bold (left) + dates italic (right)
                pdf.set_font("Arial", 'B', 10.5)
                pdf.set_text_color(*BLACK)
                tw = min(pdf.get_string_width(title) + 2, TEXT_W * 0.74)
                pdf.set_x(MARGIN)
                pdf.cell(tw, 5, title, ln=0)
                pdf.set_font("Arial", 'I', 9.5)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(TEXT_W - tw, 5, dates, ln=1, align='R')
                # Row 2: company italic grey
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", 'I', 9.5)
                pdf.set_text_color(*DARK_GREY)
                pdf.cell(TEXT_W, 4.5, company, ln=True)

            elif len(parts) == 2:
                # "Project Name | Tech Stack" — measure before placing
                proj_name  = parts[0]
                tech_stack = parts[1]
                pdf.set_font("Arial", 'B', 10.5)
                name_w = pdf.get_string_width(proj_name) + 2
                pdf.set_font("Arial", 'I', 9)
                tech_w = pdf.get_string_width(tech_stack) + 2

                pdf.set_x(MARGIN)
                if name_w + tech_w + 4 <= TEXT_W:
                    # Both fit on one line
                    gap_w = TEXT_W - name_w - tech_w
                    pdf.set_font("Arial", 'B', 10.5)
                    pdf.set_text_color(*BLACK)
                    pdf.cell(name_w, 5, proj_name, ln=0)
                    pdf.cell(gap_w, 5, "", ln=0)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.cell(tech_w, 5, tech_stack, ln=1, align='R')
                else:
                    # Name too long — stack tech below
                    pdf.set_font("Arial", 'B', 10.5)
                    pdf.set_text_color(*BLACK)
                    pdf.multi_cell(TEXT_W, 5, proj_name, align='L')
                    pdf.set_x(MARGIN)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.multi_cell(TEXT_W, 4.5, tech_stack, align='L')
            else:
                pdf.set_font("Arial", 'B', 10.5)
                pdf.set_text_color(*BLACK)
                pdf.set_x(MARGIN)
                pdf.cell(TEXT_W, 5, parts[0], ln=True)

            pdf.set_text_color(*BLACK)
            continue

        # ── SKILL LINE  "Category: value, value" ─────────────────────────────
        if ":" in line and not line.startswith("-"):
            colon_idx = line.index(":")
            cat = line[:colon_idx].strip()
            det = line[colon_idx + 1:].strip()
            # Only treat as skill if cat is short (< 5 words) and det exists
            if cat and det and len(cat.split()) <= 5:
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", 'B', 9.5)
                pdf.set_text_color(*BLACK)
                lw = min(pdf.get_string_width(cat + ":  ") + 1, TEXT_W * 0.40)
                pdf.cell(lw, 4.5, cat + ": ", ln=0)
                pdf.set_font("Arial", '', 9.5)
                pdf.multi_cell(TEXT_W - lw, 4.5, det, align='L')
                continue

        # ── BULLET POINT ──────────────────────────────────────────────────────
        if line.startswith("- ") or line.startswith("-"):
            content = line[1:].lstrip() if line.startswith("-") else line
            pdf.set_font("Arial", '', 9.5)
            pdf.set_text_color(*BLACK)
            pdf.set_x(BULLET_X)
            pdf.multi_cell(BULLET_W, 4.5, "\x95 " + content, align='L')
            continue

        # ── REGULAR PARAGRAPH TEXT ────────────────────────────────────────────
        pdf.set_font("Arial", '', 9.5)
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
    "photo_size": 52,
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
    photo_size     = st.session_state.photo_size
    if style_choice == "Global":
        uploaded_photo = st.file_uploader("Upload Profile Photo (optional)", type=['jpg', 'jpeg', 'png'])
        if uploaded_photo:
            photo_size = st.slider(
                "📐 Photo size (mm)",
                min_value=35, max_value=68, value=st.session_state.photo_size, step=1,
                help="Adjust how large your profile photo appears in the sidebar"
            )
            st.session_state.photo_size = photo_size


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

            pdf_bytes = build_pdf(st.session_state.tailored_content, style_choice, photo_path=photo_path, photo_size=st.session_state.photo_size)

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
