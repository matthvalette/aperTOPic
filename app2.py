import streamlit as st

# 1. Page Configuration & Custom CSS for High Visibility
st.set_page_config(page_title="OpenData Classifier", layout="wide")

st.markdown("""
<style>
    /* Light Theme Core */
    .stApp {
        background-color: #f8fafc;
        color: #0f172a;
    }
    
    /* Input Labels and Headers */
    .stMarkdown, p, h1, h2, h3, h4, label {
        color: #0f172a !important;
    }

    /* Text Inputs & Selectboxes */
    .stTextInput > div > div > input {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border-radius: 8px;
        border: 1px solid #cbd5e1 !important;
    }
    
    /* Radio Button Labels */
    .stRadio label {
        color: #0f172a !important;
    }

    /* File Uploader styling */
    section[data-testid="stFileUploadDropzone"] {
        background-color: #ffffff !important;
        border: 1px dashed #94a3b8 !important;
    }
    section[data-testid="stFileUploadDropzone"] span {
        color: #475569 !important;
    }

    /* Teal Button Styling */
    .stButton > button {
        background-color: #0d9488 !important;
        color: #ffffff !important;
        font-weight: 600;
        border-radius: 8px;
        border: none;
        width: 100%;
    }
    .stButton > button:hover {
        background-color: #0f766e !important;
    }

    /* Card Container with High Contrast Text */
    .card {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 18px;
        border-radius: 10px;
        margin-bottom: 12px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.05);
    }
    .card-title {
        font-weight: 600;
        font-size: 16px;
        color: #0f172a !important;
    }
    .card-file {
        font-size: 12px;
        color: #64748b !important;
        margin-bottom: 8px;
    }
    .card-snippet {
        font-size: 13px;
        color: #334155 !important;
    }
</style>
""", unsafe_allow_html=True)

# Initialize in-memory session state store for labeled files
if "files" not in st.session_state:
    st.session_state.files = [
        {
            "id": 1,
            "title": "Motion: Digitale Transformation der Bundesverwaltung",
            "file": "affair_23.3000.pdf",
            "lang": "DE",
            "label": "Digitalisation / DVS",
            "snippet": "Digitalisation transformation vorantreiben for bundesverwaltung..."
        },
        {
            "id": 2,
            "title": "Digitalisation des processus administratifs",
            "file": "proces_admin_canton_zh.pdf",
            "lang": "FR",
            "label": "Digitalisation / DVS",
            "snippet": "Digitalisation des processus administratifs suided as Digitalisation..."
        },
        {
            "id": 3,
            "title": "Rapporto sulla sanità pubblica e modernizzazione",
            "file": "sanita_pubblica_2024.pdf",
            "lang": "IT",
            "label": "Health Care",
            "snippet": "Proposta per la modernizzazione e la gestione sanitaria..."
        }
    ]

# Header Bar
col_logo, col_nav = st.columns([3, 1])
with col_logo:
    st.markdown("### **OpenData** <span style='color:#64748b; font-size:14px;'>AI Topic Classifier</span>", unsafe_allow_html=True)
with col_nav:
    st.markdown("<p style='text-align: right; color:#334155;'><b>DE</b> | <b>FR</b> | <b>IT</b></p>", unsafe_allow_html=True)

st.divider()

# Two-Column Layout
left_col, right_col = st.columns([1, 1.2], gap="large")

# -------------------------------------------------------------
# LEFT COLUMN: Add File to Label
# -------------------------------------------------------------
with left_col:
    st.subheader("Add File to Label")
    
    uploaded_file = st.file_uploader("Upload File", type=["pdf", "txt", "docx"])
    doc_title = st.text_input("Document Title", placeholder="e.g., Motion: Digitalisation Strategy")
    doc_lang = st.radio("Language", ["DE", "FR", "IT"], horizontal=True)
    doc_label = st.text_input("Assign Label", placeholder="e.g., Digitalisation / DVS, Health Care")
    
    if st.button("Assign Label to File"):
        if uploaded_file and doc_label:
            new_entry = {
                "id": len(st.session_state.files) + 1,
                "title": doc_title if doc_title else uploaded_file.name,
                "file": uploaded_file.name,
                "lang": doc_lang,
                "label": doc_label,
                "snippet": "Document uploaded and labeled successfully."
            }
            st.session_state.files.insert(0, new_entry)
            st.success(f"Assigned '{doc_label}' to {uploaded_file.name}!")
        else:
            st.warning("Please upload a file and enter a label.")

# -------------------------------------------------------------
# RIGHT COLUMN: Searchable Document List
# -------------------------------------------------------------
with right_col:
    st.subheader("Labeled Files")
    
    # Search bar
    search_query = st.text_input("Search files, labels, or languages...", placeholder="Type to filter...")
    
    # Filter files based on search term
    filtered_files = st.session_state.files
    if search_query:
        q = search_query.lower()
        filtered_files = [
            f for f in st.session_state.files
            if q in f["title"].lower() or q in f["label"].lower() or q in f["file"].lower() or q in f["lang"].lower()
        ]
        
    st.caption(f"Showing {len(filtered_files)} file(s)")
    
    # Display cards with high-contrast text
    for item in filtered_files:
        st.markdown(f"""
        <div class="card">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <span style="background-color:#e2e8f0; color:#0f172a; padding:2px 8px; border-radius:4px; font-size:12px; font-weight:bold;">{item['lang']}</span>
                <span style="background-color:#ccfbf1; color:#0f766e; padding:2px 10px; border-radius:12px; font-size:12px; font-weight:600;">{item['label']}</span>
            </div>
            <div class="card-title">{item['title']}</div>
            <div class="card-file">📁 {item['file']}</div>
            <div class="card-snippet">{item['snippet']}</div>
        </div>
        """, unsafe_allow_html=True)