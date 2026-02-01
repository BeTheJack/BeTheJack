import streamlit as st
import google.generativeai as genai
from fpdf import FPDF
import os
import re
import base64
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# 1. SETUP & CONNECTION (Auto-Hunter Logic)
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

def init_ai():
    # 1. Get Key (Secrets or Hardcoded Fallback)
    api_key = None
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        pass
        
    if not api_key:
        # Emergency fallback to your provided key
        api_key = "AIzaSyBQoA5kCYBSZCjPO9IyQXoHDoYuq1JUIh8"

    if not api_key:
        st.error("🚨 Critical Error: No API Key found.")
        return None, None

    # 2. Hunt for a working model
    try:
        genai.configure(api_key=api_key)
        
        # List all available models for this key
        all_models = list(genai.list_models())
        target_model_name = None
        
        # Priority list (Try these first)
        priorities = ['gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
        
        # 1. Check for priorities
        for p in priorities:
            for m in all_models:
                if p in m.name and 'generateContent' in m.supported_generation_methods:
                    target_model_name = m.name
                    break
            if target_model_name: break
            
        # 2. If no priority, grab ANY compatible model
        if not target_model_name:
            for m in all_models:
                if 'gemini' in m.name and 'generateContent' in m.supported_generation_methods:
                    target_model_name = m.name
                    break
        
        if target_model_name:
            return genai.GenerativeModel(target_model_name), target_model_name
        else:
            st.error("No text-generation models found for this API Key.")
            return None, None

    except Exception as e:
        st.error(f"Connection Failed: {e}")
        return None, None

# ==============================================================================
# 2. CORE LOGIC
# ==============================================================================
class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'unifontsubset'):
            self.unifontsubset = False

def sanitize_text(text):
    replacements = {'\u2022': '-', '\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '…': '...'}
    for k, v in replacements.items(): text = text.replace(k, v)
    text = text.replace("**", "") 
    text = text.replace("---", "")
    text = text.replace("###", "")
    return text.encode('latin-1', 'replace').decode('latin-1')

def crop_circle_image(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        mask = Image.new('L', img.size, 0)
        draw = ImageDraw.Draw(mask)
        draw.ellipse((0, 0) + img.size, fill=255)
        output = ImageOps.fit(img, mask.size, centering=(0.5, 0.5))
        output.putalpha(mask)
        output.save("temp_circle.png")
        return "temp_circle.png"
    except: return image_path

def generate_content(model, raw_data, jd):
    output_structure = """
    [SIDEBAR_START]
    NAME
    [Name]
    
    CONTACT
    [Phone] | [Email] | [LinkedIn] | [Location]
    [Visa/Nationality]
    
    INTRODUCTION
    [Strictly 2 sentences max]
    
    TECHNICAL SKILLS
    - [Category]: [Skills]
    - [Category]: [Skills]
    - [Category]: [Skills]
    
    CERTIFICATIONS
    - [Cert 1]
    
    EDUCATION
    [Degree], [University] | [Year]
    
    [MAIN_START]
    PROFESSIONAL EXPERIENCE
    [Target JD Title] | [Current Company] | [Recent Dates]
    - [Strategic bullet (Fabricated based on JD)]
    - [Impact bullet (Fabricated based on JD)]
    - [Task bullet (Fabricated based on JD)]
    
    [Senior Title] | [Previous Company] | [Older Dates]
    - [Ownership bullet (Fabricated based on JD)]
    - [Execution bullet (Fabricated based on JD)]
    - [Task bullet (Fabricated based on JD)]
    
    PROJECTS
    [Project Name] | [Tech Stack]
    - [Invented Project Description based on JD]
    
    [Project Name] | [Tech Stack]
    - [Invented Project Description based on JD]
    """

    prompt = f"""
    ROLE: Elite Resume Strategist.
    OBJECTIVE: Flesh out SKELETON HISTORY to match TARGET JD perfectly.
    INPUTS:
    - TARGET JD: {jd}
    - SKELETON DATA: {raw_data}
    
    CRITICAL INSTRUCTIONS:
    1. **PURE FABRICATION:** Invent responsibilities based strictly on JD requirements.
    2. **CAREER LADDER:** Rename skeleton titles (Junior -> Senior -> Target JD Title).
    3. **NO HEADLINE:** Do NOT add a headline or target role at the top.
    4. **PROJECTS:** INVENT 2 dummy projects.
    5. **VISA/PHOTO:** Extract Visa/Nationality from SKELETON DATA if present.
    6. **FORMATTING:** No markdown lines (---) or bolding (**).
    7. **LENGTH:** 1 Page maximum. 
    8. **BULLET LIMIT:** MAX 3 BULLETS per job.
    
    OUTPUT FORMAT (Strict):
    {output_structure}
    """
    
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Error: {e}"

def build_pdf(text, photo_path=None):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    pdf.set_font("Arial", size=10)
    
    # Parse
    sidebar_text = ""; main_text = ""
    if "[SIDEBAR_START]" in text and "[MAIN_START]" in text:
        parts = text.split("[MAIN_START]")
        sidebar_text = parts[0].replace("[SIDEBAR_START]", "").strip()
        main_text = parts[1].strip()
    elif "PROFESSIONAL EXPERIENCE" in text:
        parts = text.split("PROFESSIONAL EXPERIENCE")
        sidebar_text = parts[0].replace("[SIDEBAR_START]", "").strip()
        main_text = "PROFESSIONAL EXPERIENCE\n" + parts[1].strip()
    else:
        main_text = text; sidebar_text = "Parse Error"

    # Sidebar BG
    pdf.set_fill_color(240, 242, 245); pdf.rect(0, 0, 70, 297, 'F')
    
    # Photo Logic
    sidebar_y_start = 20
    if photo_path and os.path.exists(photo_path):
        processed_img = crop_circle_image(photo_path)
        pdf.image(processed_img, 15, 10, 40)
        sidebar_y_start = 65 
        if processed_img == "temp_circle.png":
            try: os.remove("temp_circle.png")
            except: pass
    
    # === SIDEBAR RENDER ===
    pdf.set_xy(5, sidebar_y_start); pdf.set_text_color(50, 50, 50)
    pdf.set_right_margin(210 - 70 + 5) 
    
    for line in sanitize_text(sidebar_text).split('\n'):
        line = line.strip()
        if not line: continue
        if line == "NAME": continue
        
        # Name
        if "Uday" in line and len(line) < 30 and pdf.get_y() < 90:
                pdf.set_font("Arial", 'B', 18); pdf.set_text_color(0, 45, 95)
                pdf.set_x(5)
                pdf.multi_cell(60, 8, line, align='C'); pdf.ln(3); pdf.set_text_color(50, 50, 50); continue

        # Headers
        if line.isupper() and len(line) < 25:
            pdf.ln(5); pdf.set_x(5); pdf.set_font("Arial", 'B', 9); pdf.set_text_color(0, 45, 95)
            pdf.cell(60, 5, line, ln=True, border='B'); pdf.set_text_color(50, 50, 50); pdf.set_font("Arial", size=8); pdf.ln(1)
        
        # Skills
        elif line.startswith("-") and ":" in line:
            parts = line.split(":", 1)
            cat = parts[0].replace("-", "").strip() + ":"
            det = parts[1].strip()
            pdf.set_x(5); pdf.set_font("Arial", 'B', 8.5)
            pdf.write(4.5, cat + " ")
            pdf.set_font("Arial", '', 8.5)
            pdf.write(4.5, det)
            pdf.ln(5) 
        else:
            pdf.set_x(5)
            if "@" in line or "LinkedIn" in line: pdf.set_font("Arial", size=8)
            else: pdf.set_font("Arial", size=9)
            pdf.multi_cell(60, 4.5, line, align='L') 

    # === MAIN RENDER ===
    pdf.set_right_margin(10)
    pdf.set_xy(75, 20); pdf.set_text_color(0, 0, 0)
    
    for line in sanitize_text(main_text).split('\n'):
        line = line.strip()
        if not line: continue
        
        pdf.set_x(75)
        if pdf.get_y() > 280:
            pdf.add_page(); pdf.set_fill_color(240, 242, 245); pdf.rect(0, 0, 70, 297, 'F'); pdf.set_xy(75, 20); pdf.set_font("Arial", size=9)

        if line in ["PROFESSIONAL EXPERIENCE", "PROJECTS"]:
            if pdf.get_y() > 60: pdf.ln(5)
            else: pdf.ln(2)
            pdf.set_x(75); pdf.set_font("Arial", 'B', 12); pdf.set_text_color(0, 45, 95)
            pdf.cell(125, 8, line, ln=True, border='B'); pdf.set_text_color(0, 0, 0); pdf.ln(3)

        elif "|" in line and "University" not in line: 
                parts = line.split('|')
                if len(parts) >= 2:
                    p1 = parts[0].strip(); p2 = parts[1].strip(); p3 = parts[2].strip() if len(parts) > 2 else ""
                    pdf.ln(3); pdf.set_x(75); pdf.set_font("Arial", 'B', 10)
                    if p3: # Job
                        pdf.cell(125, 5, p2, ln=True)
                        pdf.set_x(75); pdf.set_font("Arial", 'I', 10); pdf.set_text_color(80, 80, 80)
                        pdf.cell(125, 5, f"{p1}  --  {p3}", ln=True)
                    else: # Project
                        pdf.cell(125, 5, p1, ln=True)
                        pdf.set_x(75); pdf.set_font("Arial", 'I', 10); pdf.set_text_color(80, 80, 80)
                        pdf.multi_cell(125, 5, f"Tech: {p2}", align='L')
                    pdf.set_text_color(0, 0, 0); continue

        elif line.startswith("-"):
            pdf.set_x(75); pdf.set_font("Arial", size=9); pdf.multi_cell(125, 4.5, f"  {line}", align='L') 
        else:
            pdf.set_x(75); pdf.set_font("Arial", size=9); pdf.multi_cell(125, 4.5, line, align='L')

    return pdf.output(dest='S').encode('latin-1')

def display_pdf(pdf_bytes):
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# ==============================================================================
# 3. UI
# ==============================================================================
st.title("🃏 BeTheJack")
st.markdown("### (Jack of all Trades)")

# Connect AI (With Auto-Hunter)
model, model_name = init_ai()
if model:
    st.toast(f"Connected to: {model_name}", icon="⚡")

# Session State
if "generated_content" not in st.session_state: st.session_state.generated_content = ""
if "pdf_bytes" not in st.session_state: st.session_state.pdf_bytes = None

# INPUTS
col1, col2 = st.columns(2)
with col1:
    st.subheader("1. Skeleton")
    default_about = """NAME: 
PHONE: 
EMAIL: 
LINKEDIN: 
LOCATION: 
VISA: 
NATIONALITY: 

EDUCATION:
Degree | University | Year

WORK HISTORY:
Role | Company | Dates
Role | Company | Dates

CERTIFICATIONS:
- Cert 1"""
    about_me = st.text_area("Details", value=default_about, height=300)

with col2:
    st.subheader("2. Target")
    job_desc = st.text_area("Job Description", height=300)

uploaded_photo = st.file_uploader("Photo (Optional)", type=['jpg', 'jpeg', 'png'])

# GENERATE BUTTON
if st.button("🚀 GENERATE DRAFT", type="primary"):
    if not job_desc:
        st.error("No JD provided!")
    elif not model:
        st.error("AI Connection Failed.")
    else:
        with st.spinner("Fabricating Identity..."):
            st.session_state.generated_content = generate_content(model, about_me, job_desc)
            # Render first pass
            photo_filename = "photo.jpg"
            if uploaded_photo:
                with open(photo_filename, "wb") as f: f.write(uploaded_photo.getbuffer())
            elif os.path.exists(photo_filename): os.remove(photo_filename)
            st.session_state.pdf_bytes = build_pdf(st.session_state.generated_content, photo_path=photo_filename if uploaded_photo else None)

# PREVIEW & EDIT
if st.session_state.generated_content:
    st.markdown("---")
    c1, c2 = st.columns(2)
    
    with c1:
        st.subheader("📝 Edit Text")
        edited_text = st.text_area("Live Editor", value=st.session_state.generated_content, height=800)
        st.session_state.generated_content = edited_text
        
        if st.button("🔄 REFRESH PDF"):
            photo_filename = "photo.jpg"
            st.session_state.pdf_bytes = build_pdf(st.session_state.generated_content, photo_path=photo_filename if uploaded_photo else None)
            st.rerun()

    with c2:
        st.subheader("📄 Preview")
        if st.session_state.pdf_bytes:
            display_pdf(st.session_state.pdf_bytes)
            
            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:20]) if job_desc else "Resume"
            st.download_button(
                label="📥 DOWNLOAD PDF",
                data=st.session_state.pdf_bytes,
                file_name=f"BeTheJack_{safe_title}.pdf",
                mime="application/pdf",
                type="primary"
            )
