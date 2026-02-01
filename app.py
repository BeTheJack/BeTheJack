import streamlit as st
import google.generativeai as genai
from fpdf import FPDF
import os
import re
import base64
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# CONFIGURATION & SETUP
# ==============================================================================
def init_ai():
    """Securely connects to AI using Secrets and finds a working model."""
    api_key = None
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
    except:
        # Fallback for local testing if secrets not set (NOT RECOMMENDED FOR PROD)
        # api_key = "YOUR_KEY_HERE" 
        pass

    if not api_key:
        st.error("🚨 API Key Missing! Please add 'GOOGLE_API_KEY' to .streamlit/secrets.toml")
        return None, None

    genai.configure(api_key=api_key)
    
    # Priority list for models to avoid 404s
    target_models = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-pro']
    
    try:
        available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        for target in target_models:
            if target in available_models:
                return genai.GenerativeModel(target), target
        # Fallback
        for m in available_models:
            if 'gemini' in m: return genai.GenerativeModel(m), m
    except Exception as e:
        st.error(f"AI Connection Error: {e}")
        return None, None
    return None, None

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

# ==============================================================================
# CONTENT GENERATOR
# ==============================================================================
def generate_content(model, raw_data, jd, style="Dubai"):
    
    if style == "India":
        visa_instruction = "Do NOT include Visa Status, Nationality, or Photo."
        output_structure = """
        NAME
        [Name]
        
        [Phone] | [Email] | [LinkedIn] | [Location]
        
        INTRODUCTION
        [Short 2 line summary]
        
        PROFESSIONAL EXPERIENCE
        [Target JD Title] | [Current Company] | [Recent Dates]
        - [Strategic bullet (Fabricated based on JD)]
        - [Impact bullet (Fabricated based on JD)]
        - [Task bullet (Fabricated based on JD)]
        
        [Senior Title] | [Previous Company] | [Older Dates]
        - [Ownership bullet (Fabricated based on JD)]
        - [Execution bullet (Fabricated based on JD)]
        
        [Junior Title] | [Oldest Company] | [Oldest Dates]
        - [Support bullet]
        
        PROJECTS
        [Project Name] | [Tech Stack]
        - [Invented Project Description]
        
        TECHNICAL SKILLS
        - [Category]: [Skills]
        - [Category]: [Skills]
        
        EDUCATION
        [Degree], [University] | [Year]
        
        CERTIFICATIONS
        - [Cert 1]
        """
    else:
        visa_instruction = "Extract Visa Status and Nationality from SKELETON DATA and put in CONTACT section."
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
    5. **VISA/PHOTO:** {visa_instruction}
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

# ==============================================================================
# PDF BUILDER (DUBAI & INDIA LOGIC RESTORED)
# ==============================================================================
def build_pdf(text, style, photo_path=None):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    if style == "Dubai":
        # === DUBAI LAYOUT ===
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
        
        # Photo Processing
        sidebar_y_start = 20
        if photo_path and os.path.exists(photo_path):
            processed_img = crop_circle_image(photo_path)
            pdf.image(processed_img, 15, 10, 40)
            sidebar_y_start = 65 
            if processed_img == "temp_circle.png":
                try: os.remove("temp_circle.png")
                except: pass
        
        # Sidebar Render
        pdf.set_xy(5, sidebar_y_start); pdf.set_text_color(50, 50, 50)
        pdf.set_right_margin(210 - 70 + 5) 
        
        for line in sanitize_text(sidebar_text).split('\n'):
            line = line.strip()
            if not line: continue
            if line == "NAME": continue
            
            if "Uday" in line and len(line) < 30 and pdf.get_y() < 90:
                 pdf.set_font("Arial", 'B', 18); pdf.set_text_color(0, 45, 95)
                 pdf.set_x(5)
                 pdf.multi_cell(60, 8, line, align='C'); pdf.ln(3); pdf.set_text_color(50, 50, 50); continue

            if line.isupper() and len(line) < 25:
                pdf.ln(5); pdf.set_x(5); pdf.set_font("Arial", 'B', 9); pdf.set_text_color(0, 45, 95)
                pdf.cell(60, 5, line, ln=True, border='B'); pdf.set_text_color(50, 50, 50); pdf.set_font("Arial", size=8); pdf.ln(1)
            
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

        # Main Render
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

    else:
        # === INDIA LAYOUT (FIXED & RESTORED) ===
        pdf.set_font("Times", size=10)
        text = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
        lines = sanitize_text(text).split('\n')
        pdf.set_y(10)

        for line in lines:
            line = line.strip()
            if not line: continue
            
            if "Uday" in line and len(line) < 30:
                pdf.set_font("Times", 'B', 22)
                pdf.cell(0, 8, line, ln=True, align='C')
                pdf.ln(6) 
                pdf.set_font("Times", size=10)
                continue
            
            if "@" in line or "|" in line and len(line) < 100:
                pdf.cell(0, 5, line, ln=True, align='C')
                pdf.ln(2)
                continue
                
            if line.isupper() and len(line) < 40 and "UNIVERSITY" not in line:
                pdf.ln(5)
                pdf.set_font("Times", 'B', 11)
                pdf.cell(0, 6, line, ln=True, border='B')
                pdf.set_font("Times", size=10)
                pdf.ln(2)
                continue
                
            if "|" in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    p1 = parts[0].strip(); p2 = parts[1].strip(); p3 = parts[2].strip() if len(parts) > 2 else ""
                    pdf.ln(4)
                    if p3: # Job
                        pdf.set_font("Times", 'B', 11)
                        pdf.cell(130, 5, p2, ln=0, align='L')
                        pdf.set_font("Times", 'I', 11)
                        pdf.cell(0, 5, p3, ln=1, align='R')
                        pdf.set_font("Times", 'I', 11)
                        pdf.cell(0, 5, p1, ln=True, align='L')
                    else: # Project
                        pdf.set_font("Times", 'B', 11)
                        pdf.cell(130, 5, p1, ln=0, align='L')
                        pdf.set_font("Times", 'I', 11)
                        pdf.cell(0, 5, p2, ln=1, align='R')
                    pdf.set_font("Times", size=10)
                    continue

            if line.startswith("-"):
                pdf.set_x(10)
                pdf.multi_cell(0, 5, f"{line}", align='L')
                continue
                
            pdf.multi_cell(0, 5, line, align='L')

    return pdf.output(dest='S').encode('latin-1')

def display_pdf(pdf_bytes):
    base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
    pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800" type="application/pdf"></iframe>'
    st.markdown(pdf_display, unsafe_allow_html=True)

# ==============================================================================
# STREAMLIT UI (RESTORED TO CLASSIC 2-COL INPUT)
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

st.title("🃏 BeTheJack")
st.markdown("### (Jack of all Trades)")

# Init AI
model, model_name = init_ai()
if model:
    st.sidebar.success(f"System Online: {model_name}")

# Session State
if "generated_content" not in st.session_state: st.session_state.generated_content = ""
if "pdf_bytes" not in st.session_state: st.session_state.pdf_bytes = None

# INPUTS
col1, col2 = st.columns(2)

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
    about_me = st.text_area("About Me", value=default_about, height=300)

with col2:
    st.subheader("2. Target Job")
    job_desc = st.text_area("Paste JD Here", height=300)

# SETTINGS
st.subheader("3. Select Mode")
mode = st.radio("Choose Layout:", ["Dubai (Photo, Sidebar)", "India (Jake Style, 1-Page)"])
style_choice = "Dubai" if "Dubai" in mode else "India"

uploaded_photo = None
if style_choice == "Dubai":
    uploaded_photo = st.file_uploader("Upload Profile Photo (Optional)", type=['jpg', 'jpeg', 'png'])

# ==============================================================================
# ACTION BUTTON
# ==============================================================================
if st.button("🚀 GENERATE DRAFT", type="primary"):
    if not job_desc:
        st.error("Please paste a Job Description first!")
    elif not model:
        st.error("AI not connected. Check API Key.")
    else:
        with st.spinner("Hallucinating new identity..."):
            st.session_state.generated_content = generate_content(model, about_me, job_desc, style=style_choice)
            # Auto-render
            photo_filename = "photo.jpg"
            if uploaded_photo:
                with open(photo_filename, "wb") as f: f.write(uploaded_photo.getbuffer())
            elif os.path.exists(photo_filename): os.remove(photo_filename)
            st.session_state.pdf_bytes = build_pdf(st.session_state.generated_content, style_choice, photo_path=photo_filename if uploaded_photo else None)

# ==============================================================================
# SPLIT SCREEN EDITOR
# ==============================================================================
if st.session_state.generated_content:
    st.markdown("---")
    col_edit, col_view = st.columns([1, 1])
    
    with col_edit:
        st.subheader("📝 Live Editor")
        edited_text = st.text_area("Edit text here -> updates PDF", value=st.session_state.generated_content, height=800)
        st.session_state.generated_content = edited_text
        
        if st.button("🔄 UPDATE PREVIEW"):
            photo_filename = "photo.jpg"
            st.session_state.pdf_bytes = build_pdf(st.session_state.generated_content, style_choice, photo_path=photo_filename if uploaded_photo else None)
            st.rerun()

    with col_view:
        st.subheader("📄 PDF Preview")
        if st.session_state.pdf_bytes:
            display_pdf(st.session_state.pdf_bytes)
            
            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:20]) if job_desc else "Resume"
            st.download_button(
                label="💾 DOWNLOAD PDF",
                data=st.session_state.pdf_bytes,
                file_name=f"BeTheJack_{safe_title}.pdf",
                mime="application/pdf",
                type="primary"
            )
