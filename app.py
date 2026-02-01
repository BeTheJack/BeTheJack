import streamlit as st
import google.generativeai as genai
from fpdf import FPDF
import os
import re
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# CONFIGURATION
# ==============================================================================
# Ideally, move this to st.secrets for security
API_KEY = "AIzaSyBQoA5kCYBSZCjPO9IyQXoHDoYuq1JUIh8"

# ==============================================================================
# BeTheJack (v66.0 - Jack of all Trades Edition)
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

def generate_content(model, raw_data, jd, style="Dubai"):
    
    if style == "India":
        visa_instruction = "Do NOT include Visa Status, Nationality, or Photo."
        layout_instruction = "Single Column 'Jake Resume'. Limit to 2-3 bullets."
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
        layout_instruction = "2-Column Sidebar style. Sidebar: Contact/Intro/Skills/Certs/Edu. Main: Experience/Projects."
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
        # === INDIA LAYOUT (FIXED) ===
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

    # SAVE TO BYTES
    return pdf.output(dest='S').encode('latin-1')

# ==============================================================================
# STREAMLIT UI
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

st.title("🃏 BeTheJack")
st.markdown("### (Jack of all Trades)")

# Initialize AI
try:
    genai.configure(api_key=API_KEY)
    model = genai.GenerativeModel("models/gemini-1.5-flash")
except:
    st.error("API Key Error")

# SESSION STATE
if "generated_content" not in st.session_state:
    st.session_state.generated_content = ""

# INPUTS
col1, col2 = st.columns(2)

with col1:
    st.subheader("1. Your Skeleton")
    default_about = """NAME: Uday Katare
PHONE: +91 8401213607
EMAIL: udaykatare1@gmail.com
LINKEDIN: linkedin.com/in/udaykatare
LOCATION: Dubai, UAE
VISA: Tourist Visa
NATIONALITY: Indian

EDUCATION:
Bachelor of Computer Applications | North Maharashtra University | 2021

WORK HISTORY:
Technology Specialist | Morgan Stanley (Z&A Infotek) | Dec 2023 - Present
Senior Technical Site Coordinator | Reliance Industries | Aug 2022 - Dec 2023
Technical Support Executive | Tech Mahindra | Oct 2021 - Apr 2022

CERTIFICATIONS:
- ITIL 4 Foundation
- Microsoft Excel Advanced"""
    about_me = st.text_area("About Me (Edit freely)", value=default_about, height=300)

with col2:
    st.subheader("2. Target Job")
    job_desc = st.text_area("Paste Job Description (JD) here", height=300, placeholder="Paste the JD here...")

# SETTINGS
st.subheader("3. Select Mode")
mode = st.radio("Choose Layout:", ["Dubai (Photo, Sidebar)", "India (Jake Style, 1-Page)"])
style_choice = "Dubai" if "Dubai" in mode else "India"

# IMAGE UPLOADER
uploaded_photo = None
if style_choice == "Dubai":
    uploaded_photo = st.file_uploader("Upload Profile Photo (Optional)", type=['jpg', 'jpeg', 'png'])

# ==============================================================================
# STEP 1: GENERATE DRAFT
# ==============================================================================
if st.button("STEP 1: GENERATE DRAFT", type="primary"):
    if not job_desc:
        st.error("Please paste a Job Description first!")
    else:
        with st.spinner("Hallucinating new identity..."):
            st.session_state.generated_content = generate_content(model, about_me, job_desc, style=style_choice)
            st.success("Draft Generated! Edit it below before rendering.")

# ==============================================================================
# STEP 2: EDIT DRAFT
# ==============================================================================
if st.session_state.generated_content:
    st.subheader("4. Edit Draft (Important!)")
    st.info("💡 You can edit text, fix typos, or add lines here. The PDF will look exactly like this.")
    
    # Text Area updates session state automatically
    edited_content = st.text_area("Resume Content Editor", value=st.session_state.generated_content, height=600)
    st.session_state.generated_content = edited_content

    # ==========================================================================
    # STEP 3: RENDER PDF
    # ==========================================================================
    if st.button("STEP 2: RENDER PDF", type="secondary"):
        with st.spinner("Building PDF..."):
            # Save Photo
            photo_filename = "photo.jpg"
            if uploaded_photo:
                with open(photo_filename, "wb") as f:
                    f.write(uploaded_photo.getbuffer())
            elif os.path.exists(photo_filename):
                os.remove(photo_filename)

            # Build
            pdf_bytes = build_pdf(st.session_state.generated_content, style_choice, photo_path=photo_filename if uploaded_photo else None)
            
            # Download
            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:20]) if job_desc else "Resume"
            st.success("PDF Ready!")
            st.download_button(
                label="📥 Download PDF",
                data=pdf_bytes,
                file_name=f"CV_{style_choice}_{safe_title}.pdf",
                mime="application/pdf"
            )
