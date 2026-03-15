import streamlit as st
from groq import Groq
from fpdf import FPDF
import os
import re
import io
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# 1. SETUP & CONFIGURATION
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Space Grotesk', sans-serif; }
    .main-header {
        background: linear-gradient(135deg, #0f0c29, #302b63, #24243e);
        padding: 2rem 2.5rem; border-radius: 16px; margin-bottom: 2rem; text-align: center;
    }
    .main-header h1 { color: #fff; font-size: 3rem; font-weight: 700; margin: 0; letter-spacing: -1px; }
    .main-header p { color: rgba(255,255,255,0.6); font-size: 1.1rem; margin: 0.3rem 0 0 0; }
    .step-badge {
        display: inline-block; background: linear-gradient(135deg, #667eea, #764ba2);
        color: white; border-radius: 50%; width: 28px; height: 28px; line-height: 28px;
        text-align: center; font-weight: 700; font-size: 0.85rem; margin-right: 8px;
    }
    .info-box { background: #f0f4ff; border-left: 4px solid #667eea; padding: 0.8rem 1rem; border-radius: 0 8px 8px 0; margin: 0.5rem 0; font-size: 0.9rem; color: #334; }
    .success-box { background: #f0fff4; border-left: 4px solid #38a169; padding: 0.8rem 1rem; border-radius: 0 8px 8px 0; margin: 0.5rem 0; font-size: 0.9rem; color: #276749; }
    .warning-box { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 0.8rem 1rem; border-radius: 0 8px 8px 0; margin: 0.5rem 0; font-size: 0.9rem; color: #78350f; }
    .stButton>button { border-radius: 8px; font-weight: 600; transition: all 0.2s; }
</style>
""", unsafe_allow_html=True)

GROQ_MODEL = "llama-3.3-70b-versatile"


def init_ai():
    try:
        api_key = st.secrets["GROQ_API_KEY"]
        return Groq(api_key=api_key)
    except KeyError:
        st.error("🚨 API Key Missing. Add 'GROQ_API_KEY' to Streamlit Secrets.")
        return None
    except Exception as e:
        st.error(f"🚨 Could not initialise Groq client: {e}")
        return None


# ==============================================================================
# 2. CV PARSING
# ==============================================================================

def extract_text_from_pdf(file_bytes: bytes) -> str:
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
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(file_bytes))
        for page in reader.pages:
            text += (page.extract_text() or "") + "\n"
    except Exception as e:
        st.error(f"Could not parse PDF: {e}")
    return text


def extract_text_from_docx(file_bytes: bytes) -> str:
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
# 3. AI — Tailor CV
# ==============================================================================

def enforce_bullet_limit(text: str, max_bullets: int = 3) -> str:
    lines = text.split('\n')
    result = []
    bullet_count = 0
    current_cap = max_bullets

    for line in lines:
        stripped = line.strip()
        if not stripped:
            bullet_count = 0
            result.append(line)
            continue
        if stripped.startswith('##COMPANY##'):
            bullet_count = 0
            current_cap = max_bullets
            result.append(line)
            continue
        if '|' in stripped and not stripped.startswith('-'):
            parts = [p.strip() for p in stripped.split('|')]
            bullet_count = 0
            if len(parts) >= 3:
                current_cap = max_bullets
            elif len(parts) == 2:
                is_date = bool(re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', parts[1]))
                current_cap = max_bullets if is_date else 1
            result.append(line)
            continue
        if (stripped.isupper() and len(stripped) > 3
                and '|' not in stripped
                and not any(c.isdigit() for c in stripped)):
            bullet_count = 0
            current_cap = max_bullets
            result.append(line)
            continue
        if stripped.startswith('-') and len(stripped) > 1:
            bullet_count += 1
            if bullet_count > current_cap:
                continue
            result.append(line)
            continue
        result.append(line)
    return '\n'.join(result)


def fix_company_markers(text: str) -> str:
    """
    Normalise ALL variants the AI produces to: ##COMPANY## Name
    Handles: COMPANYFoo, COMPANY Foo, ##COMPANYFoo, ##COMPANY##Foo, ##COMPANY## Foo
    """
    company_re = re.compile(
        r'^(?:#{0,4}\s*COMPANY\s*#{0,4}\s*)',
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


def split_sidebar_main(text: str):
    """
    Robustly split CV text into sidebar and main content.
    Strategy:
      1. Try [SIDEBAR_START] / [MAIN_START] markers.
      2. Fall back to splitting at PROFESSIONAL EXPERIENCE.
      3. Sidebar = everything before first experience section.
    """
    # Clean up marker variants
    text = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")

    # Find where PROFESSIONAL EXPERIENCE (or just EXPERIENCE) begins
    exp_match = re.search(r'^PROFESSIONAL EXPERIENCE|^EXPERIENCE', text, re.MULTILINE)
    if exp_match:
        sidebar = text[:exp_match.start()].strip()
        main    = text[exp_match.start():].strip()
    else:
        # Last resort: split at first ##COMPANY## marker
        comp_match = re.search(r'^##COMPANY##', text, re.MULTILINE)
        if comp_match:
            sidebar = text[:comp_match.start()].strip()
            main    = text[comp_match.start():].strip()
        else:
            sidebar = ""
            main    = text.strip()

    return sidebar, main


def tailor_cv(groq_client: Groq, raw_cv_text: str, job_description: str, style: str = "Global") -> str:
    visa_note = (
        "Extract Visa Status and Nationality from the CV if present; include in CONTACT section."
        if style == "Global"
        else "Do NOT include Visa Status, Nationality, or Photo."
    )

    layout_note = (
        "The PDF renderer splits content by scanning for 'PROFESSIONAL EXPERIENCE' as the divider. "
        "Everything BEFORE that section becomes the sidebar (Contact, Introduction, Skills, Education, Certifications). "
        "Everything FROM 'PROFESSIONAL EXPERIENCE' onward becomes the main column. "
        "Do NOT output [SIDEBAR_START] or [MAIN_START] markers — just follow the section order exactly."
        if style == "Global"
        else "Single column, clean ATS-friendly layout."
    )

    prompt = f"""
You are an elite CV strategist. Output ONLY the resume content. No explanations, no commentary.
Start directly with the candidate's full name on the first line.

=== CRITICAL MARKER RULES ===
COMPANY BLOCK — write EXACTLY (two hashes, COMPANY, two hashes, space, name):
##COMPANY## Morgan Stanley - Mumbai

Sub-role under company (TWO parts only — Title | Dates):
Software Engineer | 06/2024 - Present

Flat role (THREE parts — Title | Company - City | Dates):
Technical Support | Reliance Industries - Mumbai | 08/2022 - 12/2023

Rules:
- ##COMPANY## must have a space after the second ##
- Never write COMPANYFoo or ##COMPANYFoo
- No extra text on the ##COMPANY## line

=== RULE 1: PROMOTION STACKING ===
For any company with 2+ years OR multiple roles:
  - One ##COMPANY## line, then roles most-recent-first.
  - If only 1 title over 2+ yrs: create 2-3 plausible internal promotions, split dates proportionally.
  - Each sub-role: 2-3 bullets.
For companies < 2 years, single role: use flat 3-part pipe. Max 3 bullets.

=== RULE 2: BULLETS ===
Every bullet: JD keyword + specific tool + metric (%, users, time) + past-tense verb.
Never copy original wording. HARD LIMIT: 3 bullets per role max.

=== RULE 3: SKILLS + INTRO ===
Introduction: MAX 2 sentences, MAX 30 words. No fluff.
Skills: MAX 4 categories, MAX 5 items each. Most JD-relevant first.
Never invent companies, degrees, or certifications.

=== RULE 4: PROJECTS ===
Rewrite real projects. Add exactly 2 invented ones using JD tools.
Each project: exactly 1 bullet. Format: Name | Tech1, Tech2

=== SECTION ORDER (NEVER CHANGE) ===
NAME
CONTACT
INTRODUCTION
TECHNICAL SKILLS
PROFESSIONAL EXPERIENCE
PROJECTS
EDUCATION
CERTIFICATIONS

=== FORMAT RULES ===
1. No ** bold, no ### headers, no --- dividers.
2. Section headers: ALL CAPS, no punctuation.
3. Intro: plain paragraph (no bullet, no colon).
4. Skills: Category: item1, item2 (colon, no dash)
5. Projects: Name | Tech1, Tech2 (2-part pipe, no dates)
6. {visa_note}
7. {layout_note}

---
ORIGINAL CV:
{raw_cv_text}

---
TARGET JOB DESCRIPTION:
{job_description}

---
OUTPUT:
"""

    try:
        response = groq_client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=4096,
            temperature=0.7,
        )
        raw = response.choices[0].message.content.strip()
        raw = fix_company_markers(raw)
        return enforce_bullet_limit(raw, max_bullets=3)
    except Exception as e:
        return f"Error generating content: {e}"


# ==============================================================================
# 4. PDF BUILDER
# ==============================================================================

def sanitize(text: str) -> str:
    replacements = {
        '\u2013': '-', '\u2014': '-', '\u2012': '-', '\u2015': '-', '\u2212': '-',
        '\u2018': "'", '\u2019': "'", '\u201a': "'", '\u201c': '"', '\u201d': '"',
        '\u201e': '"', '\u00ab': '"', '\u00bb': '"',
        '\u2022': '-', '\u2023': '-', '\u25cf': '-', '\u2219': '-', '\u00b7': '-',
        '\u2026': '...',
        '\u00a0': ' ', '\u202f': ' ', '\u2009': ' ',
        '\u200b': '', '\u200c': '', '\u200d': '', '\ufeff': '',
        '\u2192': '->', '\u2190': '<-', '\u21d2': '=>',
        '\u00d7': 'x', '\u00f7': '/', '\u00b0': ' deg',
        '\u00ae': '(R)', '\u00a9': '(C)', '\u2122': '(TM)',
        '\u20ac': 'EUR', '\u00a3': 'GBP', '\u00a5': 'JPY',
        '\u00bd': '1/2', '\u00bc': '1/4', '\u00be': '3/4',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    text = re.sub(r'\*{1,3}([^*]*)\*{1,3}', r'\1', text)
    text = re.sub(r'#{1,6}\s?', '', text)
    text = re.sub(r'^---+$', '', text, flags=re.MULTILINE)
    text = re.sub(r'`{1,3}[^`]*`{1,3}', '', text)
    text = text.encode('latin-1', errors='replace').decode('latin-1')
    return text


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
    raw = pdf.output(dest='S')
    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    return raw.encode('latin-1', errors='replace')


def _build_global_pdf(pdf: FPDF, text: str, photo_path: str = None, photo_size: int = 52):
    # ── Layout constants ──────────────────────────────────────────────────────
    SIDEBAR_W    = 72
    SIDEBAR_X    = 6
    SIDEBAR_TW   = SIDEBAR_W - SIDEBAR_X - 4
    MAIN_X       = SIDEBAR_W + 6
    PAGE_W       = 210
    RIGHT_MARGIN = 9
    MAIN_W       = PAGE_W - MAIN_X - RIGHT_MARGIN
    PAGE_H       = 297

    NAVY         = (18,  40,  76)
    GOLD         = (180, 148,  80)
    SIDEBAR_TEXT = (220, 220, 220)
    SIDEBAR_DIM  = (160, 160, 160)
    WHITE        = (255, 255, 255)
    BLACK        = (10,  10,  10)
    DARK_GREY    = (50,  50,  50)
    MID_GREY     = (100, 100, 100)

    # ── Navy sidebar background + gold top bar ────────────────────────────────
    pdf.set_fill_color(*NAVY)
    pdf.rect(0, 0, SIDEBAR_W, PAGE_H, 'F')
    pdf.set_fill_color(*GOLD)
    pdf.rect(0, 0, PAGE_W, 3, 'F')

    # ── Split sidebar / main robustly ─────────────────────────────────────────
    sidebar_text, main_text = split_sidebar_main(text)

    SKIP_WORDS = {"NAME", "CONTACT", "INTRODUCTION"}

    # ════════════════════════════════════════════════════════════════════════
    # SIDEBAR
    # ════════════════════════════════════════════════════════════════════════
    cur_y = 8

    # Profile photo
    if photo_path and os.path.exists(photo_path):
        try:
            img  = Image.open(photo_path).convert("RGBA")
            size = min(img.size)
            img  = ImageOps.fit(img, (size, size), centering=(0.5, 0.25))
            mask = Image.new('L', (size, size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
            circle = Image.new('RGBA', (size, size), (0, 0, 0, 0))
            circle.paste(img, mask=mask)
            bg = Image.new('RGB', (size, size), (18, 40, 76))
            bg.paste(circle, mask=circle.split()[3])
            circ_path = "temp_circle_photo.png"
            bg.save(circ_path, "PNG")
            photo_x = (SIDEBAR_W - photo_size) / 2
            pdf.image(circ_path, x=photo_x, y=cur_y, w=photo_size)
            cur_y += photo_size + 4
            try: os.remove(circ_path)
            except: pass
        except Exception:
            pass

    # Gold divider under photo
    pdf.set_draw_color(*GOLD)
    pdf.set_line_width(0.6)
    pdf.line(SIDEBAR_X, cur_y, SIDEBAR_W - 4, cur_y)
    pdf.set_line_width(0.2)
    cur_y += 4
    pdf.set_xy(SIDEBAR_X, cur_y)

    # Find name = first non-empty, non-skip, non-pipe, non-bullet line
    name_line = ""
    for l in sidebar_text.split('\n'):
        s = l.strip()
        if s and s not in SKIP_WORDS and '|' not in s and not s.startswith('-'):
            name_line = s
            break

    sidebar_intro_lines = 0
    in_intro = False

    for raw_line in sidebar_text.split('\n'):
        line = raw_line.strip()
        if pdf.get_y() > PAGE_H - 8:
            break
        if not line:
            pdf.set_xy(SIDEBAR_X, min(pdf.get_y() + 1.0, PAGE_H - 8))
            continue
        if line in SKIP_WORDS:
            if line == "INTRODUCTION":
                in_intro = True
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
            in_intro = False
            continue

        # ── Section header ────────────────────────────────────────────────────
        if (line.isupper() and 3 < len(line) < 35
                and line not in SKIP_WORDS
                and '|' not in line
                and not any(c.isdigit() for c in line)):
            in_intro = False
            sidebar_intro_lines = 0
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

        # ── Skill line "Category: item1, item2" ──────────────────────────────
        if ":" in line and not line.startswith("-"):
            in_intro = False
            colon_idx = line.index(":")
            cat = line[:colon_idx].strip()
            det = line[colon_idx + 1:].strip()
            if cat and det and len(cat.split()) <= 4:
                pdf.set_x(SIDEBAR_X)
                pdf.set_font("Arial", 'B', 7)
                pdf.set_text_color(*GOLD)
                lw = min(pdf.get_string_width(cat + ": ") + 1, SIDEBAR_TW - 2)
                pdf.cell(lw, 4, cat + ": ", ln=0)
                pdf.set_font("Arial", '', 7)
                pdf.set_text_color(*SIDEBAR_TEXT)
                pdf.multi_cell(SIDEBAR_TW - lw, 4, det, align='L')
                pdf.ln(0.2)
                continue

        # ── Bullet (certs, etc.) ──────────────────────────────────────────────
        if line.startswith("-"):
            in_intro = False
            pdf.set_x(SIDEBAR_X + 2)
            pdf.set_font("Arial", '', 7.5)
            pdf.set_text_color(*SIDEBAR_TEXT)
            pdf.multi_cell(SIDEBAR_TW - 2, 4, "- " + line[1:].lstrip(), align='L')
            continue

        # ── Pipe line (contact details like phone | email) ────────────────────
        if "|" in line:
            in_intro = False
            parts = [p.strip() for p in line.split("|")]
            for part in parts:
                if part:
                    pdf.set_x(SIDEBAR_X)
                    pdf.set_font("Arial", '', 7.5)
                    pdf.set_text_color(*SIDEBAR_DIM)
                    pdf.multi_cell(SIDEBAR_TW, 4, part, align='C')
            continue

        # ── Plain text (intro sentences, location, etc.) ──────────────────────
        if in_intro and sidebar_intro_lines < 2:
            display = line[:120] + ('...' if len(line) > 120 else '')
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", '', 7.5)
            pdf.set_text_color(*SIDEBAR_DIM)
            pdf.multi_cell(SIDEBAR_TW, 4, display, align='L')
            sidebar_intro_lines += 1
        else:
            # Contact details, location, education lines etc.
            pdf.set_x(SIDEBAR_X)
            pdf.set_font("Arial", '', 7.5)
            pdf.set_text_color(*SIDEBAR_DIM)
            pdf.multi_cell(SIDEBAR_TW, 4, line, align='C')

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

        # Section header
        if (line.isupper() and len(line) < 40
                and '|' not in line
                and not any(c.isdigit() for c in line)):
            pdf.ln(4)
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

        # Pipe line
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(2)
            pdf.set_x(MAIN_X)

            if len(parts) >= 3:
                # Flat role: Title | Company - City | Dates
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
                is_date = bool(re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', p1))
                if is_date:
                    # Sub-role under ##COMPANY##
                    pdf.set_x(MAIN_X + 2)
                    pdf.set_font("Arial", 'B', 9.5)
                    pdf.set_text_color(*DARK_GREY)
                    tw = min(pdf.get_string_width(p0) + 2, MAIN_W * 0.72)
                    pdf.cell(tw, 4.5, p0, ln=0)
                    pdf.set_font("Arial", 'I', 9)
                    pdf.set_text_color(*MID_GREY)
                    pdf.cell(MAIN_W - tw - 2, 4.5, p1, ln=1, align='R')
                else:
                    # Project: Name | Tech Stack
                    proj_name  = p0
                    tech_stack = p1
                    pdf.set_font("Arial", 'B', 10)
                    pdf.set_text_color(*NAVY)
                    pdf.set_x(MAIN_X)
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
            pdf.multi_cell(MAIN_W - 3, 4.5, "- " + line[1:].lstrip(), align='L')
            continue

        # Regular text
        pdf.set_x(MAIN_X)
        pdf.set_font("Arial", size=9)
        pdf.set_text_color(*DARK_GREY)
        pdf.multi_cell(MAIN_W, 4.5, line, align='L')


def _build_india_pdf(pdf: FPDF, text: str):
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

    pdf.set_auto_page_break(auto=True, margin=MARGIN)
    pdf.set_left_margin(MARGIN)
    pdf.set_right_margin(MARGIN)
    pdf.set_top_margin(MARGIN)
    pdf.set_y(MARGIN)

    text  = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
    lines = [l.rstrip() for l in text.split("\n")]

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
    intro_mode      = False
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

        if not name_printed and line == name_line:
            pdf.set_font("Arial", "B", 20)
            pdf.set_text_color(*BLACK)
            pdf.set_x(MARGIN)
            pdf.cell(TEXT_W, 9, line.title(), ln=True, align="C")
            name_printed = True
            continue

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

        if line == "INTRODUCTION":
            intro_mode = True
            pdf.ln(2)
            continue

        if intro_mode:
            if (line.isupper() and len(line) > 3 and "|" not in line) or line.startswith("##"):
                intro_mode = False
            else:
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", "I", 9)
                pdf.set_text_color(*DARK_GREY)
                pdf.multi_cell(TEXT_W, 4.8, line, align="L")
                continue

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

        if (line.isupper() and 3 < len(line) <= 35
                and "|" not in line
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
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

        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            pdf.ln(2.5)
            if len(parts) >= 3:
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
                is_date = bool(re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', p1))
                if is_date:
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

        if line.startswith("- ") or line.startswith("-"):
            content = line[1:].lstrip()
            x_pos = BULLET_X + 3 if in_experience else BULLET_X
            w     = BULLET_W - 3 if in_experience else BULLET_W
            pdf.set_font("Arial", "", 9.5)
            pdf.set_text_color(*BLACK)
            pdf.set_x(x_pos)
            pdf.multi_cell(w, 4.5, "- " + content, align="L")
            continue

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

groq_client = init_ai()

for key, default in {
    "raw_cv_text": "",
    "tailored_content": "",
    "cv_filename": "",
    "photo_size": 52,
}.items():
    if key not in st.session_state:
        st.session_state[key] = default

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
            )
            st.session_state.photo_size = photo_size

with col2:
    st.markdown("#### <span class='step-badge'>3</span> Paste Job Description", unsafe_allow_html=True)
    job_desc = st.text_area(
        "Job Description",
        height=340,
        placeholder="Paste the full job description here...",
        label_visibility="collapsed"
    )

st.markdown("---")
col_btn, col_info = st.columns([1, 2])
with col_btn:
    generate_btn = st.button("✨ Tailor My CV", type="primary", use_container_width=True)
with col_info:
    st.markdown('<div class="info-box"><b>What this does:</b> Rewrites your real experience using JD keywords, reorders skills by relevance, and crafts a targeted summary.</div>', unsafe_allow_html=True)

if generate_btn:
    if not st.session_state.raw_cv_text:
        st.error("Please upload your CV first.")
    elif not job_desc.strip():
        st.error("Please paste a Job Description.")
    elif groq_client is None:
        st.error("AI not connected. Check your GROQ_API_KEY in Secrets.")
    else:
        with st.spinner("Tailoring your CV... ~15 seconds."):
            st.session_state.tailored_content = tailor_cv(
                groq_client,
                st.session_state.raw_cv_text,
                job_desc,
                style=style_choice
            )

if st.session_state.tailored_content:
    st.markdown("---")
    st.markdown("#### <span class='step-badge'>4</span> Review & Edit the Tailored Draft", unsafe_allow_html=True)
    st.markdown('<div class="warning-box">⚠️ Always review before downloading. Check dates, titles, and facts.</div>', unsafe_allow_html=True)

    edited = st.text_area(
        "Tailored CV Content",
        value=st.session_state.tailored_content,
        height=580,
        label_visibility="collapsed"
    )
    st.session_state.tailored_content = edited

    col_pdf, _ = st.columns([1, 2])
    with col_pdf:
        render_btn = st.button("📄 Render PDF", type="secondary", use_container_width=True)

    if render_btn:
        with st.spinner("Building your PDF..."):
            photo_path = None
            if uploaded_photo:
                photo_path = "temp_profile_photo.jpg"
                with open(photo_path, "wb") as f:
                    f.write(uploaded_photo.getbuffer())

            pdf_bytes = build_pdf(
                st.session_state.tailored_content,
                style_choice,
                photo_path=photo_path,
                photo_size=st.session_state.photo_size
            )

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

st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#888;font-size:0.8rem;'>BeTheJack · Tailors real CVs to real jobs · No fabrication, ever.</div>",
    unsafe_allow_html=True
)
