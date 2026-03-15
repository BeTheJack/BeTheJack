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
# 3. AI — Tailor CV content to JD
# ==============================================================================

def get_best_model():
    try:
        # Current Gemini models — 2.0/2.5 family
        priorities = [
            'models/gemini-2.0-flash',
            'models/gemini-2.0-flash-lite',
            'models/gemini-2.5-flash-preview-05-20',
            'models/gemini-2.5-pro-preview-05-06',
            'models/gemini-1.5-flash',
            'models/gemini-1.5-pro',
        ]
        available = [
            m.name for m in genai.list_models()
            if 'generateContent' in m.supported_generation_methods
        ]
        for p in priorities:
            if p in available:
                return p
        # Fallback: first available gemini model
        for m in available:
            if 'gemini' in m.lower():
                return m
    except Exception:
        pass
    return "models/gemini-2.0-flash"


def enforce_bullet_limit(text: str, max_bullets: int = 3) -> str:
    """
    Enforces bullet caps per role block.
    - Sub-role 2-part pipe lines (under ##COMPANY##): cap 3.
    - Normal 3-part pipe flat roles: cap 3.
    - 2-part pipe project lines: cap 1.
    - Blank lines reset the counter between roles.
    """
    lines = text.split('\n')
    result = []
    bullet_count = 0
    current_cap  = max_bullets

    for line in lines:
        stripped = line.strip()

        # Blank line → reset counter
        if not stripped:
            bullet_count = 0
            result.append(line)
            continue

        # ##COMPANY## header → reset
        if stripped.startswith('##COMPANY##'):
            bullet_count = 0
            current_cap  = max_bullets
            result.append(line)
            continue

        # Pipe line → determine cap by number of parts
        if '|' in stripped and not stripped.startswith('-'):
            parts = [p.strip() for p in stripped.split('|')]
            bullet_count = 0
            if len(parts) >= 3:
                current_cap = max_bullets   # flat role: 3 bullets
            elif len(parts) == 2:
                # Is p1 a date? → sub-role (cap 3). Otherwise project (cap 1).
                import re as _re
                is_date = bool(_re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', parts[1]))
                current_cap = max_bullets if is_date else 1
            result.append(line)
            continue

        # Section header → reset
        if (stripped.isupper() and len(stripped) > 3
                and '|' not in stripped
                and not any(c.isdigit() for c in stripped)):
            bullet_count = 0
            current_cap  = max_bullets
            result.append(line)
            continue

        # Bullet line → enforce cap
        if stripped.startswith('-') and len(stripped) > 1:
            bullet_count += 1
            if bullet_count > current_cap:
                continue   # silently drop excess
            result.append(line)
            continue

        # Everything else → keep
        result.append(line)

    return '\n'.join(result)


def fix_company_markers(text: str) -> str:
    """
    Post-processor: normalises any AI company header variant to ##COMPANY## Name.
    The AI produces: 'COMPANYFoo', 'COMPANY Foo', '##COMPANYFoo', '##COMPANY##Foo' etc.
    All are mapped to '##COMPANY## Foo Bar - City'.
    """
    # Catches ALL variants: 'COMPANYFoo', 'COMPANY Foo', '##COMPANYFoo', '##COMPANY## Foo'
    company_re = re.compile(
        r'^(?:#+\s*COMPANY\s*#+\s*|#+\s*COMPANY\s*|COMPANY\s*)',
        re.IGNORECASE
    )
    result = []
    for line in text.split('\n'):
        s = line.strip()
        m = company_re.match(s)
        if m:
            name = s[m.end():].strip()
            result.append(f'##COMPANY## {name}' if name else line)
        else:
            result.append(line)
    return '\n'.join(result)


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
You are an elite CV strategist. Output ONLY the resume. No explanations, no commentary, nothing before NAME or after the last certification.

=== CRITICAL MARKER RULES — READ CAREFULLY ===
The PDF renderer uses exact string matching. One wrong character breaks the layout.

COMPANY BLOCK MARKER — write EXACTLY this (two hashes, the word COMPANY, two hashes, space, then name):
##COMPANY## Morgan Stanley - Mumbai

A role UNDER a company block — write EXACTLY this (just Title | Dates, TWO parts only):
Software Engineer | 06/2024 - Present

A FLAT role (single tenure < 2 yrs) — THREE parts:
Technical Support | Reliance Industries - Mumbai | 08/2022 - 12/2023

DO NOT write "##COMPANY##Morgan Stanley" (no space after ##).
DO NOT write "COMPANYMorgan Stanley" (missing hashes).
DO NOT add any other text on the ##COMPANY## line.

=== RULE 1: PROMOTION STACKING ===
For any company with 2+ years OR multiple sub-roles:
  - One ##COMPANY## line, then list roles underneath most-recent-first.
  - If only 1 title for 2+ yrs: invent 2-3 plausible internal promotions.
  - Split the real total tenure dates proportionally across invented roles.
  - Each sub-role gets 2-3 bullets (NOT 1 — make it substantial).

For companies with < 2 years and one role: use flat 3-part pipe. Max 3 bullets.

=== RULE 2: BULLET TRANSFORMATION ===
Every bullet must: use JD keywords + specific tools, include a metric (%, users, tickets, time),
open with past-tense action verb. Completely rewrite — never copy original wording.
HARD LIMIT: 3 bullets per sub-role max, 3 bullets per flat role. Count. Stop.

=== RULE 3: SKILLS + INTRO (KEEP SHORT) ===
Introduction: MAX 2 sentences, MAX 30 words total. Punchy, no fluff.
Skills: MAX 4 categories, MAX 4-5 items per category. Most JD-relevant first.
Never invent companies, degrees, or certifications.

=== RULE 4: PROJECTS ===
Rewrite all real projects. Add exactly 2 invented ones using JD tools.
Each project: exactly 1 bullet. Format: Name | Tech1, Tech2 (2-part pipe, NO dates).

=== SECTION ORDER — NEVER CHANGE THIS ORDER ===
NAME → CONTACT → INTRODUCTION → TECHNICAL SKILLS → PROFESSIONAL EXPERIENCE → PROJECTS → EDUCATION → CERTIFICATIONS

=== FORMAT RULES ===
1. No ** bold, no ### headers, no --- dividers.
2. Section headers: ALL CAPS, no extra punctuation.
3. Intro: plain paragraph text (no bullet, no colon, no header prefix).
4. Skill lines: Category: item1, item2  (colon, no dash prefix)
5. Project lines: Name | Tech1, Tech2  (2-part pipe, NO dates)
6. {visa_note}
7. {layout_note}

---
ORIGINAL CV:
{raw_cv_text}

---
TARGET JOB DESCRIPTION:
{job_description}

---
OUTPUT (copy structure exactly, maintain section order):

NAME
[Full Name]

CONTACT
[Phone] | [Email] | [Location]

INTRODUCTION
[2 sentences. Plain text. No bullets. No bold. Just sentences.]

TECHNICAL SKILLS
[Category]: [skill1, skill2, skill3]
[Category]: [skill1, skill2, skill3]
[Category]: [skill1, skill2, skill3]

PROFESSIONAL EXPERIENCE

##COMPANY## [Company Name - City]
[Most Senior Role] | [Start] - [End]
- [bullet with JD keyword + metric]
- [bullet with JD tool + outcome]
- [bullet with ownership/impact]
[Mid Role] | [Start] - [End]
- [bullet + metric]
- [bullet + tool]
[Junior Role] | [Start] - [End]
- [bullet]
- [bullet]

[Flat Title] | [Company - City] | [Start] - [End]
- [bullet]
- [bullet]
- [bullet]

[Flat Title] | [Company - City] | [Start] - [End]
- [bullet]
- [bullet]

PROJECTS
[Real project name] | [Tech Stack]
- [1 bullet]

[Invented project 1] | [JD tech]
- [1 bullet with metric]

[Invented project 2] | [JD tech]
- [1 bullet with metric]

EDUCATION
[Degree] | [University] | [Year]

CERTIFICATIONS
- [Cert 1]
- [Cert 2]
"""

    try:
        response = model.generate_content(prompt)
        raw = response.text
        raw = fix_company_markers(raw)
        return enforce_bullet_limit(raw, max_bullets=3)
    except Exception as e:
        return f"Error generating content: {e}"


# ==============================================================================
# 4. PDF BUILDER
# ==============================================================================


def sanitize(text: str) -> str:
    """
    Converts AI-generated Unicode text into FPDF-safe Latin-1 text.
    Maps every known problematic character explicitly before the final encode.
    Uses 'replace' as final fallback so it NEVER raises an exception.
    """
    # Explicit character mappings — covers everything Gemini commonly outputs
    replacements = {
        # Dashes & hyphens
        '\u2013': '-',   # en dash
        '\u2014': '-',   # em dash
        '\u2012': '-',   # figure dash
        '\u2015': '-',   # horizontal bar
        '\u2212': '-',   # minus sign
        # Quotes
        '\u2018': "'",   # left single quote
        '\u2019': "'",   # right single quote
        '\u201a': "'",   # single low-9 quote
        '\u201c': '"',   # left double quote
        '\u201d': '"',   # right double quote
        '\u201e': '"',   # double low-9 quote
        '\u00ab': '"',   # left angle quote
        '\u00bb': '"',   # right angle quote
        # Bullets & symbols
        '\u2022': '-',   # bullet
        '\u2023': '-',   # triangular bullet
        '\u25cf': '-',   # black circle
        '\u2219': '-',   # bullet operator
        '\u00b7': '-',   # middle dot
        # Ellipsis
        '\u2026': '...',
        # Spaces
        '\u00a0': ' ',   # non-breaking space
        '\u202f': ' ',   # narrow no-break space
        '\u2009': ' ',   # thin space
        '\u200b': '',    # zero-width space (remove)
        '\u200c': '',    # zero-width non-joiner (remove)
        '\u200d': '',    # zero-width joiner (remove)
        '\ufeff': '',    # BOM (remove)
        # Arrows (common in AI output)
        '\u2192': '->',
        '\u2190': '<-',
        '\u21d2': '=>',
        # Other common symbols
        '\u00d7': 'x',   # multiplication sign
        '\u00f7': '/',   # division sign
        '\u00b0': ' deg',
        '\u00ae': '(R)',
        '\u00a9': '(C)',
        '\u2122': '(TM)',
        '\u20ac': 'EUR',
        '\u00a3': 'GBP',
        '\u00a5': 'JPY',
        # Fractions
        '\u00bd': '1/2',
        '\u00bc': '1/4',
        '\u00be': '3/4',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)

    # Strip markdown artifacts the AI sometimes adds
    text = re.sub(r'\*{1,3}([^*]*)\*{1,3}', r'\1', text)  # remove **bold** / *italic*
    text = re.sub(r'#{1,6}\s?', '', text)                   # remove ### headers
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)  # remove --- dividers
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)          # remove `code` blocks

    # Final encode: replace any remaining non-Latin-1 chars with '?'
    # This NEVER raises — worst case a rare char becomes '?'
    text = text.encode('latin-1', errors='replace').decode('latin-1')
    return text


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

    # pdf.output(dest='S') returns a bytearray in fpdf 1.x, or bytes in fpdf2.
    # Handle both safely.
    raw = pdf.output(dest='S')
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    # Legacy fpdf 1.x returns a latin-1 string
    return raw.encode('latin-1', errors='replace')


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

    sidebar_intro_lines = 0   # count intro sentences rendered — cap at 2

    for raw_line in sidebar_text.split('\n'):
        line = raw_line.strip()
        if pdf.get_y() > PAGE_H - 8:
            break
        if not line:
            pdf.set_xy(SIDEBAR_X, min(pdf.get_y() + 1.0, PAGE_H - 8))
            continue
        if line in SKIP_WORDS:
            continue

        # ── Name ─────────────────────────────────────────────────────────────
        if line == name_line:
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 13)
            pdf.set_text_color(*WHITE)
            pdf.multi_cell(SIDEBAR_TW, 6.5, line.upper(), align='C')
            uy = pdf.get_y() + 1
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(SIDEBAR_X + 4, uy, SIDEBAR_W - 8, uy)
            pdf.set_line_width(0.2)
            pdf.ln(3)
            continue

        # ── Section header (ALL CAPS, not a skip word, no digits) ────────────
        if (line.isupper() and 3 < len(line) < 30
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            sidebar_intro_lines = 0  # reset intro counter on new section
            pdf.ln(3)
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 7.5)
            pdf.set_text_color(*GOLD)
            pdf.cell(SIDEBAR_TW, 4.5, line, ln=True)
            ry = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.4)
            pdf.line(SIDEBAR_X, ry, SIDEBAR_W - 4, ry)
            pdf.set_line_width(0.2)
            pdf.ln(1.5)
            continue

        # ── Skill line "Category: item1, item2" (no dash prefix) ─────────────
        if ":" in line and not line.startswith("-"):
            colon_idx = line.index(":")
            cat = line[:colon_idx].strip()
            det = line[colon_idx + 1:].strip()
            if cat and det and len(cat.split()) <= 4:
                pdf.set_x(SIDEBAR_X)
                pdf.set_font("Arial", 'B', 7)
                pdf.set_text_color(*GOLD)
                lw = min(pdf.get_string_width(cat + ": ") + 1, SIDEBAR_TW - 4)
                pdf.cell(lw, 4, cat + ": ", ln=0)
                pdf.set_font("Arial", '', 7)
                pdf.set_text_color(*SIDEBAR_TEXT)
                pdf.multi_cell(SIDEBAR_TW - lw, 4, det, align='L')
                pdf.ln(0.2)
                continue

        # ── Skill bullet "- Category: items" ─────────────────────────────────
        if line.startswith("-") and ":" in line:
            cat_part, _, det_part = line.partition(":")
            cat = cat_part.replace("-", "").strip()
            det = det_part.strip()
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", 'B', 7)
            pdf.set_text_color(*GOLD)
            label_w = min(pdf.get_string_width(cat + ": ") + 1, SIDEBAR_TW - 6)
            pdf.cell(label_w, 4, cat + ": ", ln=0)
            pdf.set_font("Arial", '', 7)
            pdf.set_text_color(*SIDEBAR_TEXT)
            pdf.multi_cell(SIDEBAR_TW - label_w, 4, det, align='L')
            pdf.ln(0.2)
            continue

        # ── Bullet (certs list) ───────────────────────────────────────────────
        if line.startswith("-"):
            pdf.set_x(SIDEBAR_X + 2)
            pdf.set_font("Arial", '', 7.5)
            pdf.set_text_color(*SIDEBAR_TEXT)
            pdf.multi_cell(SIDEBAR_TW - 2, 4, "\x95 " + line[1:].lstrip(), align='L')
            continue

        # ── Regular sidebar text (intro sentences, contact, education) ────────
        # Cap intro at 2 sentences to prevent sidebar overflow
        if sidebar_intro_lines < 2:
            # Truncate to first sentence if very long
            display = line[:120] + ('...' if len(line) > 120 else '')
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", size=7.5)
            pdf.set_text_color(*SIDEBAR_DIM)
            pdf.multi_cell(SIDEBAR_TW, 4, display, align='L')
            sidebar_intro_lines += 1
        else:
            # Still render non-intro text (contact details, education etc.)
            # but skip if it looks like more intro prose (long sentences)
            if len(line) < 50 or '|' in line or '@' in line or any(c.isdigit() for c in line[:8]):
                pdf.set_x(SIDEBAR_X)
                pdf.set_font("Arial", size=7.5)
                pdf.set_text_color(*SIDEBAR_DIM)
                pdf.multi_cell(SIDEBAR_TW, 4, line, align='L')

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

    in_exp_global = False

    for raw_line in main_text.split('\n'):
        line = raw_line.strip()
        if not line:
            if pdf.get_y() < PAGE_H - 6:
                pdf.set_xy(MAIN_X, pdf.get_y() + 1.5)
            continue
        if pdf.get_y() > PAGE_H - 12:
            _new_page()

        # Section header
        if (line.isupper() and len(line) < 40
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            in_exp_global = ("EXPERIENCE" in line)
            pdf.ln(5)
            pdf.set_x(MAIN_X)
            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(*NAVY)
            pdf.cell(MAIN_W, 6, line, ln=True)
            ry = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.5)
            pdf.line(MAIN_X, ry, MAIN_X + MAIN_W, ry)
            pdf.set_line_width(0.2)
            pdf.set_text_color(*BLACK)
            pdf.ln(3)
            continue

        # ##COMPANY## header
        if line.startswith("##COMPANY##"):
            company_name = line.replace("##COMPANY##", "").strip()
            if pdf.get_y() > PAGE_H - 18:
                _new_page()
            else:
                pdf.ln(4)
            pdf.set_x(MAIN_X)
            pdf.set_font("Arial", 'B', 11)
            pdf.set_text_color(*NAVY)
            pdf.cell(MAIN_W, 5.5, company_name.upper(), ln=True)
            ry = pdf.get_y()
            pdf.set_draw_color(*GOLD)
            pdf.set_line_width(0.4)
            pdf.line(MAIN_X, ry, MAIN_X + MAIN_W * 0.6, ry)
            pdf.set_line_width(0.2)
            pdf.set_text_color(*BLACK)
            pdf.ln(1.5)
            continue

        # Pipe line: 3-part=flat role, 2-part=sub-role or project
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(3)
            pdf.set_x(MAIN_X)

            if len(parts) >= 3:
                title, company, dates = parts[0], parts[1], parts[2]
                pdf.set_font("Arial", 'B', 11)
                pdf.set_text_color(*NAVY)
                pdf.cell(MAIN_W, 5.5, company.upper(), ln=True)
                pdf.set_x(MAIN_X)
                pdf.set_font("Arial", 'B', 9.5)
                pdf.set_text_color(*DARK_GREY)
                title_w = MAIN_W * 0.65
                pdf.cell(title_w, 4.5, title, ln=0)
                pdf.set_font("Arial", 'I', 9)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(MAIN_W - title_w, 4.5, dates, ln=1, align='R')

            elif len(parts) == 2:
                p0, p1 = parts[0], parts[1]
                import re as _re
                is_date = bool(_re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', p1))
                if is_date:
                    pdf.set_x(MAIN_X + 2)
                    pdf.set_font("Arial", 'B', 9.5)
                    pdf.set_text_color(*DARK_GREY)
                    tw = min(pdf.get_string_width(p0) + 2, MAIN_W * 0.72)
                    pdf.cell(tw, 4.5, p0, ln=0)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.cell(MAIN_W - tw - 2, 4.5, p1, ln=1, align='R')
                else:
                    proj_name = p0
                    tech_stack = p1
                    pdf.set_font("Arial", 'B', 10)
                    name_w = pdf.get_string_width(proj_name) + 2
                    pdf.set_font("Arial", 'I', 9)
                    tech_w = pdf.get_string_width(tech_stack) + 2
                    if name_w + tech_w + 4 <= MAIN_W:
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

        # Bullet
        if line.startswith("-"):
            pdf.set_x(MAIN_X + 3)
            pdf.set_font("Arial", size=9)
            pdf.set_text_color(*DARK_GREY)
            pdf.multi_cell(MAIN_W - 3, 4.5, "\x95 " + line[1:].lstrip(), align='L')
            continue

        # Regular text
        pdf.set_x(MAIN_X)
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(*DARK_GREY)
        pdf.multi_cell(MAIN_W, 4.5, line, align='L')


def _build_india_pdf(pdf: FPDF, text: str):
    """
    Jake Resume ATS layout.
    KEY FIX: set_auto_page_break(True) so multi_cell / content naturally
    flows to page 2. Section header orphan prevention: if < 30mm left,
    start a new page before printing the header.
    """
    MARGIN   = 12.7
    PAGE_W   = 210
    PAGE_H   = 297
    TEXT_W   = PAGE_W - 2 * MARGIN
    BULLET_X = MARGIN + 4
    BULLET_W = TEXT_W - 4

    BLACK     = (0,   0,   0)
    DARK_GREY = (50,  50,  50)
    MID_GREY  = (110, 110, 110)

    SKIP_WORDS = {"NAME", "CONTACT", "SIDEBAR_START", "MAIN_START"}
    # INTRODUCTION is NOT skipped — it's rendered as a paragraph below contact

    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.set_left_margin(MARGIN)
    pdf.set_right_margin(MARGIN)
    pdf.set_top_margin(MARGIN)
    pdf.set_y(MARGIN)

    text  = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
    lines = [l.rstrip() for l in text.split("\n")]

    # Pre-pass: identify name and contact lines
    name_line = ""
    for l in lines:
        s = l.strip()
        if s and s not in SKIP_WORDS and s != "INTRODUCTION" and "|" not in s and not s.startswith("-"):
            name_line = s
            break

    contact_line = ""
    for l in lines:
        s = l.strip()
        if "@" in s or s.startswith("+") or re.search(r"\d{7,}", s):
            if s != name_line:
                contact_line = s
                break

    name_printed    = False
    contact_printed = False
    intro_mode      = False   # True when we're collecting intro paragraph lines
    in_experience   = False

    def draw_rule(thickness=0.35):
        pdf.set_draw_color(*BLACK)
        pdf.set_line_width(thickness)
        pdf.line(MARGIN, pdf.get_y(), MARGIN + TEXT_W, pdf.get_y())
        pdf.set_line_width(0.2)

    def space_left():
        return PAGE_H - MARGIN - pdf.get_y()

    for raw_line in lines:
        line = raw_line.strip()

        if not line:
            if name_printed:
                pdf.ln(1.0)
            continue

        if line in SKIP_WORDS:
            continue

        # NAME
        if not name_printed and line == name_line:
            # Always Title Case — handles "UDAY KATARE", "uday katare", or "Uday Katare"
            display_name = line.title()
            pdf.set_font("Arial", "B", 20)
            pdf.set_text_color(*BLACK)
            pdf.set_x(MARGIN)
            pdf.cell(TEXT_W, 9, display_name, ln=True, align="C")
            name_printed = True
            continue

        # CONTACT
        if name_printed and not contact_printed and line == contact_line:
            pdf.set_font("Arial", "", 9)
            pdf.set_text_color(*DARK_GREY)
            pdf.set_x(MARGIN)
            pdf.multi_cell(TEXT_W, 4.5, line, align="C")
            pdf.set_draw_color(*MID_GREY)
            pdf.set_line_width(0.25)
            pdf.line(MARGIN, pdf.get_y() + 0.5, MARGIN + TEXT_W, pdf.get_y() + 0.5)
            pdf.set_line_width(0.2)
            pdf.ln(3.5)
            contact_printed = True
            continue

        # INTRODUCTION keyword → enter intro mode
        if line == "INTRODUCTION":
            intro_mode = True
            pdf.ln(2)
            continue

        # Intro paragraph lines — render as small italic text, exit mode on next section header
        if intro_mode:
            # Exit intro mode when hitting a new ALL-CAPS section or ## marker
            if (line.isupper() and len(line) > 3 and "|" not in line) or line.startswith("##"):
                intro_mode = False
                # Fall through to render this line normally (don't skip it)
            else:
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", "I", 9)
                pdf.set_text_color(*DARK_GREY)
                pdf.multi_cell(TEXT_W, 4.8, line, align="L")
                continue

        # ##COMPANY## HEADER — promotion-stacked company block
        if line.startswith("##COMPANY##"):
            company_name = line.replace("##COMPANY##", "").strip()
            if space_left() < 45:
                pdf.add_page()
                pdf.set_y(MARGIN)
            else:
                pdf.ln(4)
            pdf.set_x(MARGIN)
            pdf.set_font("Arial", "B", 11)
            pdf.set_text_color(*BLACK)
            pdf.cell(TEXT_W, 6, company_name.upper(), ln=True)
            draw_rule(0.5)
            pdf.ln(1.5)
            continue

        # SECTION HEADER
        if (line.isupper()
                and 3 < len(line) <= 35
                and "|" not in line
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            # Track experience section
            in_experience = ("EXPERIENCE" in line)
            if space_left() < 45:
                pdf.add_page()
                pdf.set_y(MARGIN)
            else:
                pdf.ln(5)
            pdf.set_x(MARGIN)
            pdf.set_font("Arial", "B", 10.5)
            pdf.set_text_color(*BLACK)
            pdf.cell(TEXT_W, 5, line, ln=True, align="L")
            draw_rule(0.35)
            pdf.ln(2.5)
            continue

        # ── ROLE / PROJECT PIPE LINE ──────────────────────────────────────────
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(2.5)

            if len(parts) >= 3:
                # 3-part: Title | Company - City | Dates  (flat role)
                title, company, dates = parts[0], parts[1], parts[2]
                pdf.set_font("Arial", "B", 10.5)
                pdf.set_text_color(*BLACK)
                tw = min(pdf.get_string_width(title) + 2, TEXT_W * 0.74)
                pdf.set_x(MARGIN)
                pdf.cell(tw, 5, title, ln=0)
                pdf.set_font("Arial", "I", 9.5)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(TEXT_W - tw, 5, dates, ln=1, align="R")
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", "I", 9.5)
                pdf.set_text_color(*DARK_GREY)
                pdf.cell(TEXT_W, 4.5, company, ln=True)

            elif len(parts) == 2:
                p0, p1 = parts[0], parts[1]
                # Is p1 a date range? Check for year digits or "Present"
                is_date = bool(re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec',
                    p1
                ))
                if is_date:
                    # Sub-role under ##COMPANY## header: "Title | Start - End"
                    ROLE_X = MARGIN + 3
                    ROLE_W = TEXT_W - 3
                    pdf.set_font("Arial", "B", 10)
                    pdf.set_text_color(*BLACK)
                    tw = min(pdf.get_string_width(p0) + 2, ROLE_W * 0.74)
                    pdf.set_x(ROLE_X)
                    pdf.cell(tw, 5, p0, ln=0)
                    pdf.set_font("Arial", "I", 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.cell(ROLE_W - tw, 5, p1, ln=1, align="R")
                else:
                    # Project: "Name | Tech Stack"
                    proj_name  = p0
                    tech_stack = p1
                    pdf.set_font("Arial", "B", 10.5)
                    name_w = pdf.get_string_width(proj_name) + 2
                    pdf.set_font("Arial", "I", 9)
                    tech_w = pdf.get_string_width(tech_stack) + 2
                    pdf.set_x(MARGIN)
                    if name_w + tech_w + 4 <= TEXT_W:
                        gap_w = TEXT_W - name_w - tech_w
                        pdf.set_font("Arial", "B", 10.5)
                        pdf.set_text_color(*BLACK)
                        pdf.cell(name_w, 5, proj_name, ln=0)
                        pdf.cell(gap_w, 5, "", ln=0)
                        pdf.set_font("Arial", "I", 9)
                        pdf.set_text_color(*MID_GREY)
                        pdf.cell(tech_w, 5, tech_stack, ln=1, align="R")
                    else:
                        pdf.set_font("Arial", "B", 10.5)
                        pdf.set_text_color(*BLACK)
                        pdf.multi_cell(TEXT_W, 5, proj_name, align="L")
                        pdf.set_x(MARGIN)
                        pdf.set_font("Arial", "I", 9)
                        pdf.set_text_color(*MID_GREY)
                        pdf.multi_cell(TEXT_W, 4.5, tech_stack, align="L")
            else:
                pdf.set_font("Arial", "B", 10.5)
                pdf.set_text_color(*BLACK)
                pdf.set_x(MARGIN)
                pdf.cell(TEXT_W, 5, parts[0], ln=True)

            pdf.set_text_color(*BLACK)
            continue

        # SKILL LINE
        if ":" in line and not line.startswith("-"):
            colon_idx = line.index(":")
            cat = line[:colon_idx].strip()
            det = line[colon_idx + 1:].strip()
            if cat and det and len(cat.split()) <= 5:
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", "B", 9.5)
                pdf.set_text_color(*BLACK)
                lw = min(pdf.get_string_width(cat + ":  ") + 1, TEXT_W * 0.40)
                pdf.cell(lw, 4.5, cat + ": ", ln=0)
                pdf.set_font("Arial", "", 9.5)
                pdf.multi_cell(TEXT_W - lw, 4.5, det, align="L")
                continue

        # BULLET
        if line.startswith("- ") or line.startswith("-"):
            content = line[1:].lstrip()
            # Extra indent inside experience block (under sub-roles)
            x_pos = BULLET_X + 3 if in_experience else BULLET_X
            w     = BULLET_W - 3 if in_experience else BULLET_W
            pdf.set_font("Arial", "", 9.5)
            pdf.set_text_color(*BLACK)
            pdf.set_x(x_pos)
            pdf.multi_cell(w, 4.5, "\x95 " + content, align="L")
            continue

        # REGULAR TEXT
        pdf.set_font("Arial", "", 9.5)
        pdf.set_text_color(*BLACK)
        pdf.set_x(MARGIN)
        pdf.multi_cell(TEXT_W, 4.5, line, align="L")


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
