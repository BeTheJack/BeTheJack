import streamlit as st
import google.generativeai as genai
from fpdf import FPDF
import os
import re
import json
from PIL import Image, ImageOps, ImageDraw

# ==============================================================================
# 1. SETUP & SECURITY
# ==============================================================================
st.set_page_config(page_title="BeTheJack", page_icon="🃏", layout="wide")

def init_ai():
    # Attempt to load key from Streamlit Secrets
    try:
        api_key = st.secrets["GOOGLE_API_KEY"]
        genai.configure(api_key=api_key)
        return True
    except:
        st.error("🚨 API Key Missing. Admin: Add 'GOOGLE_API_KEY' to Streamlit Secrets.")
        return False

# ==============================================================================
# 2. HELPER FUNCTIONS
# ==============================================================================
class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not hasattr(self, 'unifontsubset'):
            self.unifontsubset = False

def get_best_model():
    try:
        available = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
        priorities = ['models/gemini-1.5-flash', 'models/gemini-1.5-pro', 'models/gemini-pro']
        for p in priorities:
            if p in available: return p
        return "models/gemini-pro"
    except: return "models/gemini-pro"

def sanitize_text(text):
    replacements = {'\u2022': '-', '\u2013': '-', '\u2014': '-', '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '…': '...'}
    for k, v in replacements.items(): text = text.replace(k, v)
    text = text.replace("**", "").replace("---", "").replace("###", "")
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
# 3. CONTENT GENERATION
# ==============================================================================
def generate_content(raw_data, jd, style="Global"):
    model_name = get_best_model()
    model = genai.GenerativeModel(model_name)
    
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

def build_pdf(text, style, photo_path=None):
    pdf = PDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=False)
    
    if style == "Global":
        pdf.set_font("Arial", size=10)
        sidebar_text = ""; main_text = ""
        if "[SIDEBAR_START]" in text and "[MAIN_START]" in text:
            parts = text.split("[MAIN_START]")
            sidebar_text = parts[0].replace("[SIDEBAR_START]", "").strip()
            main_text = parts[1].strip()
        elif "PROFESSIONAL EXPERIENCE" in text:
            parts = text.split("PROFESSIONAL EXPERIENCE")
            sidebar_text = parts[0].replace("[SIDEBAR_START]", "").strip()
            main_text = "PROFESSIONAL EXPERIENCE\n" + parts[1].strip()
        else: main_text = text; sidebar_text = "Parse Error"

        pdf.set_fill_color(240, 242, 245); pdf.rect(0, 0, 70, 297, 'F')
        
        sidebar_y_start = 20
        if photo_path and os.path.exists(photo_path):
            processed_img = crop_circle_image(photo_path)
            pdf.image(processed_img, 15, 10, 40)
            sidebar_y_start = 65 
            if processed_img == "temp_circle.png":
                try: os.remove("temp_circle.png")
                except: pass
        
        pdf.set_xy(5, sidebar_y_start); pdf.set_text_color(50, 50, 50)
        pdf.set_right_margin(210 - 70 + 5) 
        for line in sanitize_text(sidebar_text).split('\n'):
            line = line.strip()
            if not line: continue
            if line == "NAME": continue
            if "Uday" in line and len(line) < 30 and pdf.get_y() < 90:
                 pdf.set_font("Arial", 'B', 18); pdf.set_text_color(0, 45, 95); pdf.set_x(5); pdf.multi_cell(60, 8, line, align='C'); pdf.ln(3); pdf.set_text_color(50, 50, 50); continue
            if line.isupper() and len(line) < 25:
                pdf.ln(5); pdf.set_x(5); pdf.set_font("Arial", 'B', 9); pdf.set_text_color(0, 45, 95); pdf.cell(60, 5, line, ln=True, border='B'); pdf.set_text_color(50, 50, 50); pdf.set_font("Arial", size=8); pdf.ln(1)
            elif line.startswith("-") and ":" in line:
                parts = line.split(":", 1); cat = parts[0].replace("-", "").strip() + ":"; det = parts[1].strip()
                pdf.set_x(5); pdf.set_font("Arial", 'B', 8.5); pdf.write(4.5, cat + " "); pdf.set_font("Arial", '', 8.5); pdf.write(4.5, det); pdf.ln(5) 
            else:
                pdf.set_x(5); pdf.set_font("Arial", size=(8 if "@" in line else 9)); pdf.multi_cell(60, 4.5, line, align='L') 

        pdf.set_right_margin(10); pdf.set_xy(75, 20); pdf.set_text_color(0, 0, 0)
        for line in sanitize_text(main_text).split('\n'):
            line = line.strip()
            if not line: continue
            pdf.set_x(75)
            if pdf.get_y() > 280: pdf.add_page(); pdf.set_fill_color(240, 242, 245); pdf.rect(0, 0, 70, 297, 'F'); pdf.set_xy(75, 20); pdf.set_font("Arial", size=9)
            if line in ["PROFESSIONAL EXPERIENCE", "PROJECTS"]:
                if pdf.get_y() > 60: pdf.ln(5)
                else: pdf.ln(2)
                pdf.set_x(75); pdf.set_font("Arial", 'B', 12); pdf.set_text_color(0, 45, 95); pdf.cell(125, 8, line, ln=True, border='B'); pdf.set_text_color(0, 0, 0); pdf.ln(3)
            elif "|" in line and "University" not in line: 
                 parts = line.split('|')
                 if len(parts) >= 2:
                     p1 = parts[0].strip(); p2 = parts[1].strip(); p3 = parts[2].strip() if len(parts) > 2 else ""
                     pdf.ln(3); pdf.set_x(75); pdf.set_font("Arial", 'B', 10)
                     if p3: pdf.cell(125, 5, p2, ln=True); pdf.set_x(75); pdf.set_font("Arial", 'I', 10); pdf.set_text_color(80, 80, 80); pdf.cell(125, 5, f"{p1}  --  {p3}", ln=True)
                     else: pdf.cell(125, 5, p1, ln=True); pdf.set_x(75); pdf.set_font("Arial", 'I', 10); pdf.set_text_color(80, 80, 80); pdf.multi_cell(125, 5, f"Tech: {p2}", align='L')
                     pdf.set_text_color(0, 0, 0); continue
            elif line.startswith("-"): pdf.set_x(75); pdf.set_font("Arial", size=9); pdf.multi_cell(125, 4.5, f"  {line}", align='L') 
            else: pdf.set_x(75); pdf.set_font("Arial", size=9); pdf.multi_cell(125, 4.5, line, align='L')

    else:
        pdf.set_font("Times", size=10)
        text = text.replace("[SIDEBAR_START]", "").replace("[MAIN_START]", "")
        lines = sanitize_text(text).split('\n')
        pdf.set_y(10)
        for line in lines:
            line = line.strip()
            if not line: continue
            if "Uday" in line and len(line) < 30: pdf.set_font("Times", 'B', 22); pdf.cell(0, 8, line, ln=True, align='C'); pdf.ln(6); pdf.set_font("Times", size=10); continue
            if "@" in line or "|" in line and len(line) < 100: pdf.cell(0, 5, line, ln=True, align='C'); pdf.ln(2); continue
            if line.isupper() and len(line) < 40 and "UNIVERSITY" not in line: pdf.ln(5); pdf.set_font("Times", 'B', 11); pdf.cell(0, 6, line, ln=True, border='B'); pdf.set_font("Times", size=10); pdf.ln(2); continue
            if "|" in line:
                parts = line.split('|')
                if len(parts) >= 2:
                    p1 = parts[0].strip(); p2 = parts[1].strip(); p3 = parts[2].strip() if len(parts) > 2 else ""
                    pdf.ln(4)
                    if p3: pdf.set_font("Times", 'B', 11); pdf.cell(130, 5, p2, ln=0, align='L'); pdf.set_font("Times", 'I', 11); pdf.cell(0, 5, p3, ln=1, align='R'); pdf.set_font("Times", 'I', 11); pdf.cell(0, 5, p1, ln=True, align='L')
                    else: pdf.set_font("Times", 'B', 11); pdf.cell(130, 5, p1, ln=0, align='L'); pdf.set_font("Times", 'I', 11); pdf.cell(0, 5, p2, ln=1, align='R')
                    pdf.set_font("Times", size=10); continue
            if line.startswith("-"): pdf.set_x(10); pdf.multi_cell(0, 5, f"{line}", align='L'); continue
            pdf.multi_cell(0, 5, line, align='L')
    return pdf.output(dest='S').encode('latin-1')

# ==============================================================================
# UI
# ==============================================================================
st.title("🃏 BeTheJack")
st.markdown("### (Jack of all Trades)")

# Connect AI
ai_connected = init_ai()

# Session State for About Me
if "about_me_text" not in st.session_state:
    st.session_state.about_me_text = "NAME: \nPHONE: \nEMAIL: \nLINKEDIN: \nLOCATION: \nVISA: \nNATIONALITY: \n\nEDUCATION:\nDegree | University | Year\n\nWORK HISTORY:\nRole | Company | Dates\nRole | Company | Dates\n\nCERTIFICATIONS:\n- Cert 1"

if "generated_content" not in st.session_state:
    st.session_state.generated_content = ""

# INPUTS
col1, col2 = st.columns(2)
with col1:
    st.subheader("1. Your Skeleton")
    
    # === NEW: LOAD BUTTON IN MAIN UI ===
    with st.expander("📂 Click to Load Saved Profile"):
        uploaded_file = st.file_uploader("Upload Profile (JSON)", type=["json", "txt"], label_visibility="collapsed")
        if uploaded_file is not None:
            try:
                data = json.load(uploaded_file)
                st.session_state.about_me_text = data.get("about_me", "")
                st.success("✅ Profile Loaded! Check the box below.")
            except:
                st.error("Invalid file.")

    # TEXT AREA (Linked to Session State)
    about_me = st.text_area("Details", value=st.session_state.about_me_text, height=300, key="about_me_input")
    
    # Sync manual edits
    if about_me != st.session_state.about_me_text:
        st.session_state.about_me_text = about_me

    # SAVE BUTTON
    profile_json = json.dumps({"about_me": st.session_state.about_me_text})
    st.download_button("💾 Save This Profile", data=profile_json, file_name="my_profile.json", mime="application/json")

with col2:
    st.subheader("2. Target Job")
    job_desc = st.text_area("Paste Job Description (JD)", height=300)

st.subheader("3. Select Mode")
mode = st.radio("Choose Layout:", ["Global (Photo, Sidebar)", "India (Jake Style, 1-Page)"])
style_choice = "Global" if "Global" in mode else "India"

uploaded_photo = None
if style_choice == "Global": uploaded_photo = st.file_uploader("Upload Profile Photo (Optional)", type=['jpg', 'jpeg', 'png'])

if st.button("STEP 1: GENERATE DRAFT", type="primary"):
    if not job_desc: st.error("Please paste a Job Description first!")
    elif not ai_connected: st.error("AI not connected. Check Secrets.")
    else:
        with st.spinner("Hallucinating new identity..."):
            st.session_state.generated_content = generate_content(st.session_state.about_me_text, job_desc, style=style_choice)
            st.success("Draft Generated!")

if st.session_state.generated_content:
    st.subheader("4. Edit Draft (Important!)")
    edited_content = st.text_area("Resume Content Editor", value=st.session_state.generated_content, height=600)
    st.session_state.generated_content = edited_content
    if st.button("STEP 2: RENDER PDF", type="secondary"):
        with st.spinner("Building PDF..."):
            photo_filename = "photo.jpg"
            if uploaded_photo:
                with open(photo_filename, "wb") as f: f.write(uploaded_photo.getbuffer())
            elif os.path.exists(photo_filename): os.remove(photo_filename)
            pdf_bytes = build_pdf(st.session_state.generated_content, style_choice, photo_path=photo_filename if uploaded_photo else None)
            safe_title = re.sub(r'[^a-zA-Z0-9]', '_', job_desc[:20]) if job_desc else "Resume"
            st.success("PDF Ready!")
            st.download_button(label="📥 Download PDF", data=pdf_bytes, file_name=f"CV_{style_choice}_{safe_title}.pdf", mime="application/pdf")
