import streamlit as st
from groq import Groq
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
    import os
    try:
        api_key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        api_key = ""
    if not api_key:
        api_key = os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        st.error("🚨 API Key Missing. Set GROQ_API_KEY in environment variables or Streamlit Secrets.")
        return False
    try:
        # Validate by creating client — doesn't make a network call
        client = Groq(api_key=api_key)
        # Store in session state so tailor_cv can access it
        st.session_state["_groq_client"] = client
        return True
    except Exception as e:
        st.error(f"🚨 AI init failed: {e}")
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

def get_groq_client():
    """Retrieve the Groq client — falls back to creating a new one if session state missing."""
    import os
    client = st.session_state.get("_groq_client")
    if client:
        return client
    # Fallback: rebuild from env
    key = ""
    try:
        key = st.secrets.get("GROQ_API_KEY", "")
    except Exception:
        pass
    if not key:
        key = os.environ.get("GROQ_API_KEY", "")
    return Groq(api_key=key) if key else None


def get_best_model() -> str:
    """
    Returns the best available Groq model for CV generation.
    Priority: llama-3.3-70b (best quality) → llama-3.1-70b → llama3-70b → 8b fallback.
    Groq model names: https://console.groq.com/docs/models
    """
    client = get_groq_client()
    if not client:
        return "llama-3.3-70b-versatile"
    try:
        available = [m.id for m in client.models.list().data]
        priorities = [
            "llama-3.3-70b-versatile",
            "llama-3.1-70b-versatile",
            "llama3-70b-8192",
            "llama-3.1-8b-instant",
            "llama3-8b-8192",
        ]
        for p in priorities:
            if p in available:
                return p
        # Fallback: first llama model found
        for m in available:
            if "llama" in m.lower():
                return m
    except Exception:
        pass
    return "llama-3.3-70b-versatile"


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
    Converts any COBLOCK/COMPANY line to ##COMPANY## Name.
    Handles all variants Llama produces.
    """
    pattern = re.compile(
        r'^[#*\s]*(?:COBLOCK|COMPANY)[#*:\-\s]*(.+)$',
        re.IGNORECASE
    )
    SECTION_KEYWORDS = {
        'PROFESSIONAL EXPERIENCE', 'TECHNICAL SKILLS', 'SKILLS',
        'PROJECTS', 'EDUCATION', 'CERTIFICATIONS', 'CONTACT',
        'INTRODUCTION', 'SUMMARY', 'NAME'
    }
    result = []
    for line in text.split('\n'):
        s = line.strip()                              # strip whitespace
        s_clean = re.sub(r'\*+', '', s).strip()       # strip markdown bold
        m = pattern.match(s_clean)
        if m:
            name = m.group(1).strip().lstrip('#*:- ')
            if name and name.upper() not in SECTION_KEYWORDS:
                result.append(f'##COMPANY## {name}')  # always clean, no leading spaces
                continue
        if s.startswith('##COMPANY##'):
            name = s[len('##COMPANY##'):].strip()
            result.append(f'##COMPANY## {name}' if name else '')
            continue
        result.append(line)
    return '\n'.join(result)


def fix_bullet_markers(text: str) -> str:
    """
    Converts > bullet prefix from prompt to - prefix that the PDF builder expects.
    Also strips any leftover markdown bold/italic from bullet text.
    """
    result = []
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('> ') or stripped == '>':
            content = stripped[1:].lstrip()
            # Clean markdown from bullet text
            content = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', content)
            result.append('- ' + content)
        else:
            # Clean markdown from non-bullet lines too
            cleaned = re.sub(r'\*{1,2}([^*]+)\*{1,2}', r'\1', line)
            result.append(cleaned)
    return '\n'.join(result)


def tailor_cv(raw_cv_text: str, job_description: str, style: str = "Global") -> str:
    """
    Takes real extracted CV text and the target JD.
    Returns a tailored, enhanced version with up to 30% JD-driven augmentation.
    """
    client     = get_groq_client()
    model_name = get_best_model()

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
You are a senior CV writer who has placed candidates at top firms for 15 years. You write compelling, detailed resumes that read as if the candidate wrote them — confident and specific, never corporate-robotic.

THE GOLDEN RULE OF THIS CV:
Every bullet tells a mini story: what you did + how + the result. Aim for 15-25 words per bullet.
Bullets must feel like a person wrote them, not a bot. Specific details make them human.

BANNED AI WORDS — never use these:
spearheaded, leveraged, utilized, adept at, results-driven, dynamic, proven track record, synergies,
cutting-edge, innovative solutions, streamlined, orchestrated, demonstrating, showcasing, encompassing,
proficient, expertise in, robust, scalable, seamlessly, holistic, actionable

USE THESE INSTEAD:
built, ran, managed, cut, grew, set up, led, helped, delivered, improved, created,
handled, drove, fixed, worked on, reduced, increased, wrote, designed, deployed, trained,
coordinated, launched, developed, maintained, resolved

INTRO — must sound like the person typed it themselves:
GOOD example: "I've spent 4 years in IT support at companies like Morgan Stanley and Reliance, mostly dealing with M365, ServiceNow and Python automation. I enjoy building scripts and knowledge tools that actually save teams time."
BAD example: "Results-driven IT professional with expertise in knowledge management."
BAD example: "Proficient in Microsoft 365 environment."
Write 2 sentences max. First: what they do, how long, where. Second: what they enjoy or are good at. Max 45 words total.

BULLET EXAMPLES — this is the quality level required:
GOOD: "Managed the full knowledge base for 3 product teams, cut article review time by 30% by writing Python scripts that flagged stale content automatically"
GOOD: "Ran the OneDrive migration for 850 users across 3 offices, handling all communications, testing and post-cutover support over 6 weeks"
BAD: "Managed knowledge base lifecycle with product owners"
BAD: "Resolved L2 escalations from frontline teams"
Every bullet must be 15-25 words with a specific number and real context.

COMPANY BLOCK FORMAT — use EXACTLY this marker (one word, no symbols):
COBLOCK Morgan Stanley - Mumbai

Sub-role under COBLOCK (title | dates, two parts only):
Technology Analyst | 12/2023 - Present

Flat single role (title | company | dates, three parts):
Technical Support | Reliance Industries - Mumbai | 08/2022 - 12/2023

BULLETS — use > as the prefix:
> Managed the full knowledge base lifecycle with product owners, cut article review time by 30% using Python automation

RULES:
1. COBLOCK for any company with 2+ years or multiple roles
   - If only 1 title for 2+ years: invent 2-3 believable promotions, split dates proportionally
   - 2-3 bullets per sub-role, each 15-25 words
2. Flat 3-part pipe for short single-role companies, up to 3 bullets
3. Every bullet: specific action + real context + concrete number. Sound natural, not corporate.
4. Skills: 4 categories, 4-5 items each, JD-relevant order
5. Intro: human, specific, conversational — see examples above
6. Projects: keep all real ones (rewritten) + 2 invented using JD tools, 1 bullet each
7. ALL bullets use > prefix. Never use - as bullet prefix.
8. Never invent companies, degrees, or certifications.
9. Enhance up to 30% — add JD-adjacent tools/skills that are plausible given the real experience.
10. {visa_note}
11. {layout_note}

SECTION ORDER (never change):
NAME > CONTACT > INTRODUCTION > TECHNICAL SKILLS > PROFESSIONAL EXPERIENCE > PROJECTS > EDUCATION > CERTIFICATIONS

FORMAT RULES:
- No ** bold markers
- No ### headers  
- No --- dividers
- Section headers: ALL CAPS
- Skill lines: Category: item1, item2, item3  (colon format, no > prefix)
- Project lines: Name | Tech1, Tech2  (two-part pipe, no dates)
- ALL other list items use > prefix

---
ORIGINAL CV:
{raw_cv_text}

---
TARGET JOB DESCRIPTION:
{job_description}

---
OUTPUT (follow exactly):

NAME
[Full Name]

CONTACT
[Phone] | [Email] | [Location]

INTRODUCTION
[2 human, specific sentences. First: experience summary. Second: what you like/are good at. Under 40 words.]

TECHNICAL SKILLS
[Category]: [item1, item2, item3, item4]
[Category]: [item1, item2, item3, item4]
[Category]: [item1, item2, item3, item4]
[Category]: [item1, item2, item3, item4]

PROFESSIONAL EXPERIENCE

COBLOCK [Company Name - City]
[Most Recent Role] | [Start] - [End]
> [specific action + context + number, 15-25 words]
> [specific action + context + number, 15-25 words]
> [specific action + context + number, 15-25 words]
[Previous Role] | [Start] - [End]
> [specific action + context + number]
> [specific action + context + number]
[Earliest Role] | [Start] - [End]
> [specific action + context + number]
> [specific action + context + number]

[Flat Title] | [Company - City] | [Start] - [End]
> [specific action + context + number, 15-25 words]
> [specific action + context + number]
> [specific action + context + number]

PROJECTS
[Real project name from CV, rewritten] | [Tech1, Tech2]
> [what it does + specific outcome, 15-20 words]

[Give this a real believable project name based on JD tools — e.g. "ServiceNow Ticket Router" or "SharePoint Intranet Rebuild"] | [JD tools]
> [what it does + specific metric, 15-20 words]

[Give this a different real believable project name — e.g. "Python SLA Monitor" or "M365 Onboarding Automation"] | [JD tools]
> [what it does + specific metric, 15-20 words]

EDUCATION
[Degree] | [University] | [Year]

CERTIFICATIONS
> [Cert 1]
> [Cert 2]
"""
    import time
    last_err = None
    for attempt in range(3):
        try:
            response = client.chat.completions.create(
                model=model_name,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "You are a professional resume writer. "
                            "Output ONLY the resume content — no commentary, no markdown formatting, no explanations. "
                            "Write naturally and specifically. Avoid all corporate buzzwords. "
                            "Never use placeholder text like [Project Name] or [Invented Project] — "
                            "always write the actual content."
                        )
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                temperature=0.85,
                max_tokens=6000,
            )
            raw = response.choices[0].message.content
            raw = fix_company_markers(raw)
            raw = fix_bullet_markers(raw)
            return enforce_bullet_limit(raw, max_bullets=3)
        except Exception as e:
            last_err = e
            err_str = str(e)
            # Rate limit — wait and retry
            if "429" in err_str or "rate" in err_str.lower() or "limit" in err_str.lower():
                wait = (attempt + 1) * 15
                st.warning(f"⏳ Rate limit hit — retrying in {wait}s... (attempt {attempt+1}/3)")
                time.sleep(wait)
            else:
                break
    return f"Error generating content: {last_err}"


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


def build_docx(content: str) -> bytes:
    """
    Converts the tailored CV text into a clean, ATS-friendly DOCX file.
    Uses python-docx with professional formatting matching Jake's Resume style.
    Works for both India (single column) and Global (text only, no sidebar) outputs.
    """
    from docx import Document as DocxDocument
    from docx.shared import Pt, Inches, RGBColor
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn
    from docx.oxml import OxmlElement
    import copy

    doc = DocxDocument()

    # ── Page margins: 0.75 inch all sides ────────────────────────────────────
    section = doc.sections[0]
    margin = Inches(0.75)
    section.top_margin    = margin
    section.bottom_margin = margin
    section.left_margin   = margin
    section.right_margin  = margin

    # ── Default paragraph spacing: no space after ────────────────────────────
    style = doc.styles['Normal']
    style.font.name = 'Calibri'
    style.font.size = Pt(10)
    pfmt = style.paragraph_format
    pfmt.space_after  = Pt(0)
    pfmt.space_before = Pt(0)

    def add_para(text='', bold=False, italic=False, size=10, align=WD_ALIGN_PARAGRAPH.LEFT,
                 space_before=0, space_after=2, color=None, indent_left=0):
        p = doc.add_paragraph()
        p.alignment = align
        pf = p.paragraph_format
        pf.space_before = Pt(space_before)
        pf.space_after  = Pt(space_after)
        if indent_left:
            pf.left_indent = Inches(indent_left)
        if text:
            run = p.add_run(text)
            run.bold   = bold
            run.italic = italic
            run.font.size = Pt(size)
            run.font.name = 'Calibri'
            if color:
                run.font.color.rgb = RGBColor(*color)
        return p

    def add_rule(color_hex='000000'):
        """Add a thin horizontal rule under a section header."""
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(0)
        p.paragraph_format.space_after  = Pt(2)
        pPr = p._p.get_or_add_pPr()
        pBdr = OxmlElement('w:pBdr')
        bottom = OxmlElement('w:bottom')
        bottom.set(qn('w:val'), 'single')
        bottom.set(qn('w:sz'), '6')
        bottom.set(qn('w:space'), '1')
        bottom.set(qn('w:color'), color_hex)
        pBdr.append(bottom)
        pPr.append(pBdr)
        return p

    def add_two_col_run(p, left_text, left_bold, right_text, right_italic=True):
        """Add bold left text + italic right text on same paragraph line with tab."""
        p.clear()
        # Tab stop at right margin
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn
        from docx.shared import Inches
        pPr = p._p.get_or_add_pPr()
        tabs = OxmlElement('w:tabs')
        tab = OxmlElement('w:tab')
        tab.set(qn('w:val'), 'right')
        tab.set(qn('w:pos'), '9072')   # 6.3 inches in twentieths of a pt
        tabs.append(tab)
        pPr.append(tabs)
        run_l = p.add_run(left_text)
        run_l.bold = left_bold
        run_l.font.size = Pt(10.5)
        run_l.font.name = 'Calibri'
        run_tab = p.add_run('\t')
        run_tab.font.name = 'Calibri'
        run_r = p.add_run(right_text)
        run_r.italic = right_italic
        run_r.font.size = Pt(9.5)
        run_r.font.name = 'Calibri'
        run_r.font.color.rgb = RGBColor(100, 100, 100)

    # ── Parse and render ──────────────────────────────────────────────────────
    text = content.replace('[SIDEBAR_START]', '').replace('[MAIN_START]', '')
    lines = [l.rstrip() for l in text.split('\n')]

    SKIP_WORDS = {'NAME', 'CONTACT', 'SIDEBAR_START', 'MAIN_START'}
    NAVY = (18, 40, 76)

    # Find name and contact
    name_line = next((l.strip() for l in lines
                      if l.strip() and l.strip() not in SKIP_WORDS
                      and l.strip() != 'INTRODUCTION'
                      and '|' not in l.strip()
                      and not l.strip().startswith('-')), '')
    contact_line = next((l.strip() for l in lines
                         if ('@' in l or l.strip().startswith('+') or
                             re.search(r'\d{7,}', l))
                         and l.strip() != name_line), '')

    name_done    = False
    contact_done = False
    intro_mode   = False
    in_experience = False

    for line in lines:
        line = line.strip()

        if line in SKIP_WORDS:
            continue

        if not line:
            continue

        # NAME
        if not name_done and line == name_line:
            p = add_para(line.title(), bold=True, size=20,
                         align=WD_ALIGN_PARAGRAPH.CENTER,
                         space_before=0, space_after=2)
            name_done = True
            continue

        # CONTACT
        if name_done and not contact_done and line == contact_line:
            add_para(line, italic=False, size=9,
                     align=WD_ALIGN_PARAGRAPH.CENTER,
                     color=(80, 80, 80), space_after=3)
            contact_done = True
            continue

        # INTRODUCTION keyword
        if line == 'INTRODUCTION':
            intro_mode = True
            continue

        # Intro paragraph text
        if intro_mode:
            if (line.isupper() and len(line) > 3 and '|' not in line) or line.startswith('##'):
                intro_mode = False
                # fall through
            else:
                add_para(line, italic=True, size=9, color=(60, 60, 60), space_after=1)
                continue

        # ##COMPANY## header
        if line.startswith('##COMPANY##'):
            company_name = line.replace('##COMPANY##', '').strip()
            in_experience = True
            p = add_para(company_name.upper(), bold=True, size=11,
                         color=NAVY, space_before=8, space_after=0)
            add_rule('000000')
            continue

        # SECTION HEADER
        if (line.isupper() and 3 < len(line) <= 35
                and '|' not in line and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            in_experience = 'EXPERIENCE' in line
            p = add_para(line, bold=True, size=10.5,
                         color=NAVY, space_before=8, space_after=0)
            add_rule('000000')
            continue

        # PIPE LINE: role, sub-role, or project
        if '|' in line and not line.startswith('-'):
            parts = [p.strip() for p in line.split('|')]

            if len(parts) >= 3:
                # Flat role: Title | Company - City | Dates
                title, company, dates = parts[0], parts[1], parts[2]
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(4)
                p.paragraph_format.space_after  = Pt(0)
                add_two_col_run(p, title, True, dates)
                add_para(company, italic=True, size=9.5, color=(60, 60, 60), space_after=1)

            elif len(parts) == 2:
                p0, p1 = parts[0], parts[1]
                is_date = bool(re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', p1))
                if is_date:
                    # Sub-role under ##COMPANY##
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(3)
                    p.paragraph_format.space_after  = Pt(0)
                    p.paragraph_format.left_indent  = Inches(0.15)
                    add_two_col_run(p, p0, True, p1)
                else:
                    # Project: Name | Tech Stack
                    p = doc.add_paragraph()
                    p.paragraph_format.space_before = Pt(3)
                    p.paragraph_format.space_after  = Pt(0)
                    add_two_col_run(p, p0, True, p1)
            continue

        # SKILL LINE "Category: items"
        if ':' in line and not line.startswith('-'):
            colon_idx = line.index(':')
            cat = line[:colon_idx].strip()
            det = line[colon_idx + 1:].strip()
            if cat and det and len(cat.split()) <= 5:
                p = doc.add_paragraph()
                p.paragraph_format.space_before = Pt(0)
                p.paragraph_format.space_after  = Pt(1)
                run_cat = p.add_run(cat + ': ')
                run_cat.bold = True
                run_cat.font.size = Pt(9.5)
                run_cat.font.name = 'Calibri'
                run_det = p.add_run(det)
                run_det.font.size = Pt(9.5)
                run_det.font.name = 'Calibri'
                continue

        # BULLET
        if line.startswith('-'):
            content_text = line[1:].lstrip()
            indent = 0.25 if in_experience else 0.15
            p = doc.add_paragraph(style='Normal')
            p.paragraph_format.space_before = Pt(0)
            p.paragraph_format.space_after  = Pt(1)
            p.paragraph_format.left_indent  = Inches(indent)
            p.paragraph_format.first_line_indent = Inches(-0.15)
            run = p.add_run('\u2022  ' + content_text)
            run.font.size = Pt(9.5)
            run.font.name = 'Calibri'
            continue

        # REGULAR TEXT (intro sentences etc.)
        add_para(line, size=9.5, color=(50, 50, 50), space_after=1)

    # ── Save to bytes ─────────────────────────────────────────────────────────
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)
    return buf.read()


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
    Jake Resume — strict 1-page ATS layout with auto font-size scaling.
    Counts meaningful content lines first, then picks font/spacing preset
    so content fills the page without overflowing or leaving large gaps.
    """
    MARGIN   = 10.0
    PAGE_W   = 210
    PAGE_H   = 297
    TEXT_W   = PAGE_W - 2 * MARGIN
    BOTTOM   = PAGE_H - MARGIN

    BLACK     = (0,   0,   0)
    DARK_GREY = (50,  50,  50)
    MID_GREY  = (110, 110, 110)

    SKIP_WORDS = {"NAME", "CONTACT", "SIDEBAR_START", "MAIN_START"}

    text  = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
    lines = [l.rstrip() for l in text.split("\n")]

    # ── Estimate content density to pick scaling preset ──────────────────────
    meaningful = sum(1 for l in lines if l.strip()
                     and l.strip() not in SKIP_WORDS
                     and l.strip() != "INTRODUCTION")
    # 3 presets: normal (≤55 lines), compact (56-70), tight (71+)
    if meaningful <= 52:
        BODY_PT   = 9.5;  HDR_PT = 10.5; LINE_H = 4.5; SEC_GAP = 5; BLK_GAP = 3
    elif meaningful <= 65:
        BODY_PT   = 9.0;  HDR_PT = 10.0; LINE_H = 4.2; SEC_GAP = 4; BLK_GAP = 2.5
    else:
        BODY_PT   = 8.5;  HDR_PT = 9.5;  LINE_H = 3.8; SEC_GAP = 3; BLK_GAP = 2

    BULLET_X = MARGIN + 3
    BULLET_W = TEXT_W - 3

    # Disable auto page break — manual control
    pdf.set_auto_page_break(auto=False)
    pdf.set_left_margin(MARGIN)
    pdf.set_right_margin(MARGIN)
    pdf.set_top_margin(MARGIN)
    pdf.set_y(MARGIN)

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
    intro_mode      = False
    in_experience   = False

    def fits(needed_mm=5):
        """True if there's enough space left on the page."""
        return pdf.get_y() + needed_mm < BOTTOM

    def draw_rule(thickness=0.3):
        if not fits(1): return
        pdf.set_draw_color(*BLACK)
        pdf.set_line_width(thickness)
        pdf.line(MARGIN, pdf.get_y(), MARGIN + TEXT_W, pdf.get_y())
        pdf.set_line_width(0.2)

    for raw_line in lines:
        line = raw_line.strip()

        # Hard stop — nothing renders past the page bottom
        if not fits(3):
            break

        if not line:
            if name_printed and fits(2):
                pdf.ln(0.8)   # tighter blank line gap
            continue

        if line in SKIP_WORDS:
            continue

        # NAME
        if not name_printed and line == name_line:
            display_name = line.title()
            pdf.set_font("Arial", "B", int(HDR_PT+7))   # 18pt vs 20pt — saves 1.5mm
            pdf.set_text_color(*BLACK)
            pdf.set_x(MARGIN)
            pdf.cell(TEXT_W, 8, display_name, ln=True, align="C")
            name_printed = True
            continue

        # CONTACT
        if name_printed and not contact_printed and line == contact_line:
            pdf.set_font("Arial", "", BODY_PT-1)
            pdf.set_text_color(*DARK_GREY)
            pdf.set_x(MARGIN)
            pdf.multi_cell(TEXT_W, LINE_H-0.5, line, align="C")
            pdf.set_draw_color(*MID_GREY)
            pdf.set_line_width(0.2)
            pdf.line(MARGIN, pdf.get_y() + 0.5, MARGIN + TEXT_W, pdf.get_y() + 0.5)
            pdf.set_line_width(0.2)
            pdf.ln(BLK_GAP-0.5)
            contact_printed = True
            continue

        # INTRODUCTION keyword
        if line == "INTRODUCTION":
            intro_mode = True
            pdf.ln(1)
            continue

        # Intro paragraph
        if intro_mode:
            if (line.isupper() and len(line) > 3 and "|" not in line) or line.startswith("##"):
                intro_mode = False
                # fall through
            else:
                if fits(5):
                    pdf.set_x(MARGIN)
                    pdf.set_font("Arial", "I", BODY_PT-1)
                    pdf.set_text_color(*DARK_GREY)
                    pdf.multi_cell(TEXT_W, LINE_H-0.5, line, align="L")
                continue

        # ##COMPANY## HEADER
        if line.startswith("##COMPANY##"):
            company_name = line.replace("##COMPANY##", "").strip()
            if fits(30):
                pdf.ln(BLK_GAP)
            pdf.set_x(MARGIN)
            pdf.set_font("Arial", "B", HDR_PT)
            pdf.set_text_color(*BLACK)
            pdf.cell(TEXT_W, 5, company_name.upper(), ln=True)
            draw_rule(0.4)
            pdf.ln(0.8)
            continue

        # SECTION HEADER
        if (line.isupper()
                and 3 < len(line) <= 35
                and "|" not in line
                and line not in SKIP_WORDS
                and not any(c.isdigit() for c in line)):
            in_experience = ("EXPERIENCE" in line)
            if fits(30):
                pdf.ln(BLK_GAP)
            pdf.set_x(MARGIN)
            pdf.set_font("Arial", "B", HDR_PT-0.5)
            pdf.set_text_color(*BLACK)
            pdf.cell(TEXT_W, LINE_H, line, ln=True, align="L")
            draw_rule(0.3)
            pdf.ln(BLK_GAP-1)
            continue

        # ROLE / PROJECT PIPE LINE
        if "|" in line and not line.startswith("-"):
            parts = [p.strip() for p in line.split("|")]
            if fits(5):
                pdf.ln(BLK_GAP-1)

            if len(parts) >= 3:
                title, company, dates = parts[0], parts[1], parts[2]
                pdf.set_font("Arial", "B", HDR_PT-0.5)
                pdf.set_text_color(*BLACK)
                tw = min(pdf.get_string_width(title) + 2, TEXT_W * 0.74)
                pdf.set_x(MARGIN)
                pdf.cell(tw, 4.5, title, ln=0)
                pdf.set_font("Arial", "I", BODY_PT-0.5)
                pdf.set_text_color(*MID_GREY)
                pdf.cell(TEXT_W - tw, 4.5, dates, ln=1, align="R")
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", "I", BODY_PT-0.5)
                pdf.set_text_color(*DARK_GREY)
                pdf.cell(TEXT_W, LINE_H-0.5, company, ln=True)

            elif len(parts) == 2:
                p0, p1 = parts[0], parts[1]
                is_date = bool(re.search(
                    r'\d{4}|Present|present|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec', p1))
                if is_date:
                    # Sub-role
                    pdf.set_font("Arial", "B", HDR_PT-0.5)
                    pdf.set_text_color(*BLACK)
                    tw = min(pdf.get_string_width(p0) + 2, TEXT_W * 0.74)
                    pdf.set_x(MARGIN + 2)
                    pdf.cell(tw, 4.5, p0, ln=0)
                    pdf.set_font("Arial", "I", BODY_PT-0.5)
                    pdf.set_text_color(*MID_GREY)
                    pdf.cell(TEXT_W - tw - 2, 4.5, p1, ln=1, align="R")
                else:
                    # Project
                    proj_name, tech_stack = p0, p1
                    pdf.set_font("Arial", "B", HDR_PT-0.5)
                    name_w = pdf.get_string_width(proj_name) + 2
                    pdf.set_font("Arial", "I", BODY_PT-0.5)
                    tech_w = pdf.get_string_width(tech_stack) + 2
                    pdf.set_x(MARGIN)
                    if name_w + tech_w + 4 <= TEXT_W:
                        pdf.set_font("Arial", "B", HDR_PT-0.5)
                        pdf.set_text_color(*BLACK)
                        pdf.cell(name_w, LINE_H, proj_name, ln=0)
                        pdf.cell(TEXT_W - name_w - tech_w, 4.5, "", ln=0)
                        pdf.set_font("Arial", "I", BODY_PT-0.5)
                        pdf.set_text_color(*MID_GREY)
                        pdf.cell(tech_w, LINE_H, tech_stack, ln=1, align="R")
                    else:
                        pdf.set_font("Arial", "B", HDR_PT-0.5)
                        pdf.set_text_color(*BLACK)
                        pdf.multi_cell(TEXT_W, LINE_H, proj_name, align="L")
                        pdf.set_x(MARGIN)
                        pdf.set_font("Arial", "I", BODY_PT-0.5)
                        pdf.set_text_color(*MID_GREY)
                        pdf.multi_cell(TEXT_W, LINE_H-0.5, tech_stack, align="L")
            else:
                pdf.set_font("Arial", "B", HDR_PT-0.5)
                pdf.set_text_color(*BLACK)
                pdf.set_x(MARGIN)
                pdf.cell(TEXT_W, 4.5, parts[0], ln=True)

            pdf.set_text_color(*BLACK)
            continue

        # SKILL LINE  "Category: items"
        if ":" in line and not line.startswith("-"):
            colon_idx = line.index(":")
            cat = line[:colon_idx].strip()
            det = line[colon_idx + 1:].strip()
            if cat and det and len(cat.split()) <= 5:
                pdf.set_x(MARGIN)
                pdf.set_font("Arial", "B", BODY_PT-0.5)
                pdf.set_text_color(*BLACK)
                lw = min(pdf.get_string_width(cat + ":  ") + 1, TEXT_W * 0.38)
                pdf.cell(lw, LINE_H-0.5, cat + ": ", ln=0)
                pdf.set_font("Arial", "", BODY_PT-0.5)
                pdf.multi_cell(TEXT_W - lw, LINE_H-0.5, det, align="L")
                continue

        # BULLET
        if line.startswith("- ") or line.startswith("-"):
            content = line[1:].lstrip()
            x_pos = BULLET_X + 2 if in_experience else BULLET_X
            w     = BULLET_W - 2 if in_experience else BULLET_W
            if fits(4):
                pdf.set_font("Arial", "", BODY_PT-0.5)
                pdf.set_text_color(*BLACK)
                pdf.set_x(x_pos)
                pdf.multi_cell(w, LINE_H-0.5, "\x95 " + content, align="L")
            continue

        # REGULAR TEXT
        if fits(4):
            pdf.set_font("Arial", "", BODY_PT-0.5)
            pdf.set_text_color(*BLACK)
            pdf.set_x(MARGIN)
            pdf.multi_cell(TEXT_W, LINE_H-0.5, line, align="L")


# ==============================================================================
# 5. UI
# ==============================================================================

st.markdown("""
<div class="main-header">
    <h1>🃏 BeTheJack</h1>
    <p>Upload your real CV → tailor it to any job, instantly.</p>
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
        with st.spinner("Tailoring your CV to the job description... this takes ~20 seconds."):
            result = tailor_cv(
                st.session_state.raw_cv_text,
                job_desc,
                style=style_choice
            )
            if result.startswith("Error generating content:"):
                err = result
                if "429" in err or "quota" in err.lower():
                    st.error("⚠️ Gemini API quota exceeded. Options:\n\n"
                             "1. Wait until tomorrow (free tier resets daily)\n"
                             "2. Enable billing at aistudio.google.com — costs ~$0.001 per CV")
                else:
                    st.error(err)
            else:
                st.session_state.tailored_content = result

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

    col_pdf, col_docx, col_spacer = st.columns([1, 1, 1])
    with col_pdf:
        render_btn = st.button("📄 Render PDF", type="secondary", use_container_width=True)
    with col_docx:
        docx_btn = st.button("📝 Download DOCX", type="secondary", use_container_width=True)

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

    if docx_btn:
        with st.spinner("Building your DOCX..."):
            try:
                docx_bytes = build_docx(st.session_state.tailored_content)
                safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:25]) if job_desc else "Resume"
                docx_filename = f"CV_{safe_title}.docx"
                st.success("✅ DOCX is ready!")
                st.download_button(
                    label="📥 Download DOCX",
                    data=docx_bytes,
                    file_name=docx_filename,
                    mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    use_container_width=True
                )
            except Exception as e:
                st.error(f"DOCX generation failed: {e}")

# Footer
st.markdown("---")
st.markdown(
    "<div style='text-align:center;color:#888;font-size:0.8rem;'>BeTheJack · Smart CV tailoring, powered by AI.</div>",
    unsafe_allow_html=True
)
