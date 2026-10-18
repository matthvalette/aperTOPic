import streamlit as st
import requests

st.set_page_config(page_title="Swiss Parliamentary Apertus RAG", layout="wide")

st.title("aperTOPic")
st.subheader("Multilingual Topic Classification for OpenParlData.ch")

# Query and topic inputs
query = st.text_input("Enter Query or Ad-hoc Topic (e.g. 'cybersecurity', 'e-ID', 'santé'):", "digitalisation")
topics_str = st.text_input("Candidate Topics (comma-separated):", "Digitalisation, Energy, Economy, Health, Environment")

# Language Selection Dropdown
language_options = {
    "All Languages": "all",
    "German (de)": "de",
    "French (fr)": "fr",
    "Italian (it)": "it",
    "Romansh (rm)": "rm"
}

selected_language_label = st.selectbox(
    "Select Language Filter:",
    options=list(language_options.keys())
)
selected_language_code = language_options[selected_language_label]

if st.button("Run Search & Apertus Classification"):
    with st.spinner("Fetching all documents from OpenParlData & processing with Apertus..."):
        try:
            res = requests.get(
                "http://127.0.0.1:8000/api/v1/search_and_classify",
                params={
                    "query": query,
                    "topics": topics_str,
                    "language": selected_language_code
                },
                proxies={"http": None, "https": None},  # Bypasses local proxy settings
    timeout=120.0
            )
            data = res.json()
            
            st.success(f"Found {data['total_found']} affairs | Filter Language: {data['filter_language'].upper()}")
            
            if data['total_found'] == 0:
                st.info("No matching documents found for your search criteria.")
            else:
                for affair in data["classified_affairs"]:
                    with st.expander(f"{affair['title']} — [{affair['primary_topic']}] (Score: {affair['confidence_score']})"):
                        st.write(f"**Affair ID:** {affair['affair_id']}")
                        st.write(f"**Language:** {affair['language'].upper()}")
                        st.write(f"**Digitalisation Scope (DVS):** {'Yes' if affair['is_digitalisation'] else 'No'}")
                        st.write(f"**Evidence Passage:** *\"{affair['key_passage_evidence']}\"*")
                        st.write(f"**Apertus Neutral Justification:** {affair['explanation']}")
                        
        except Exception as e:
            st.error(f"Error connecting to backend: {e}. Make sure main.py is running on port 8000.")