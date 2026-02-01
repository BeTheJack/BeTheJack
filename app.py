import streamlit as st
import google.generativeai as genai
from fpdf import FPDF
import os
import re
import base64
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# CONFIGURATION
# ==============================================================================
# ⚠️ REPLACE WITH YOUR PRIVATE KEY
API_KEY = "AIzaSyC8Co0tB6iL9I2Ny8YzQuwwCmbgPuyc3o0" 

# ==============================================================================
# BeTheJack (v71.0 - Stable Flash Edition)
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
# STREAMLIT UI
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

# HEADER
st.title("🃏 BeTheJack")
st.markdown("### (Jack of all Trades)")

# Init AI (HARDCODED TO FLASH 1.5)
try:
    genai.configure(api_key=API_KEY)
    # FORCE GEMINI 1.5 FLASH (Most Stable/Free Model)
    target_model_name = "models/gemini-1.5-flash"
    model = genai.GenerativeModel(target_model_name)
    st.success(f"⚡ System Online: {target_model_name}")
except:
    st.error("⚠️ API Key Error. Please update app.py")

# Session State
if "generated_content" not in st.session_state: st.session_state.generated_content = ""
if "pdf_bytes" not in st.session_state: st.session_state.pdf_bytes = None

# === CONFIGURATION PANEL (TOP) ===
with st.expander("🛠️ CONFIGURATION PANEL (Click to Expand/Collapse)", expanded=True):
    col1, col2, col3 = st.columns([1.5, 1.5, 1])
    
    with col1:
        st.subheader("1. Your Skeleton")
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
- Cert 1
- Cert 2"""
        about_me = st.text_area("Your Details", value=default_about, height=250)
        
    with col2:
        st.subheader("2. Target Job")
        job_desc = st.text_area("Target JD", height=250, placeholder="Paste JD here...")
        
    with col3:
        st.subheader("3. Assets")
        uploaded_photo = st.file_uploader("Profile Photo", type=['jpg', 'jpeg', 'png'])
        st.info("💡 Photo is optional. Layout auto-adjusts.")
        
    if st.button("🚀 GENERATE DRAFT", type="primary", use_container_width=True):
        if not job_desc:
            st.warning("Please paste a Job Description!")
        else:
            with st.spinner("Fabricating new identity..."):
                st.session_state.generated_content = generate_content(model, about_me, job_desc)
                # Auto-render initial PDF
                photo_filename = "photo.jpg"
                if uploaded_photo:
                    with open(photo_filename, "wb") as f: f.write(uploaded_photo.getbuffer())
                elif os.path.exists(photo_filename): os.remove(photo_filename)
                
                st.session_state.pdf_bytes = build_pdf(st.session_state.generated_content, photo_path=photo_filename if uploaded_photo else None)


# === MAIN WORKSPACE ===
if st.session_state.generated_content:
    st.markdown("---")
    col_edit, col_view = st.columns([1, 1])
    
    with col_edit:
        st.subheader("📝 Live Editor")
        edited_text = st.text_area("Edit text here -> updates PDF", value=st.session_state.generated_content, height=800)
        st.session_state.generated_content = edited_text
        
        if st.button("🔄 UPDATE PREVIEW", use_container_width=True):
            photo_filename = "photo.jpg"
            st.session_state.pdf_bytes = build_pdf(st.session_state.generated_content, photo_path=photo_filename if uploaded_photo else None)
            st.rerun()

    with col_view:
        st.subheader("📄 PDF Preview")
        if st.session_state.pdf_bytes:
            display_pdf(st.session_state.pdf_bytes)
            
            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:20]) if job_desc else "Resume"
            st.download_button(
                label="💾 DOWNLOAD FINAL PDF",
                data=st.session_state.pdf_bytes,
                file_name=f"BeTheJack_{safe_title}.pdf",
                mime="application/pdf",
                use_container_width=True,
                type="primary"
            )
else:
    st.info("👆 Configure your details above and click 'GENERATE DRAFT' to start.")
