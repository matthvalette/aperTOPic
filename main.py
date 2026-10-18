import os
import json
import asyncio
import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
from openai import AsyncOpenAI

load_dotenv()

app = FastAPI(
    title="OpenParlData & Apertus Multilingual RAG Backend",
    description="Topic Classification & RAG API for Swiss Parliamentary Affairs"
)

# Load Apertus API Key & Base URL from .env
APERTUS_API_KEY = os.getenv("APERTUS_API_KEY", "keera_skLeR2kr5HgoJxQCg6P9GbxJor22ap9MHsgYKOp2H-|L2Y")
APERTUS_BASE_URL = os.getenv("APERTUS_BASE_URL", "https://api.apertus.swiss/v1")

# Async OpenAI Client configured with your Apertus endpoint credentials
apertus_client = AsyncOpenAI(
    api_key=APERTUS_API_KEY,
    base_url=APERTUS_BASE_URL,
    timeout=45.0,
    max_retries=3
)

OPENPARL_API_BASE = "https://api.openparldata.ch/v1"

# Concurrency semaphore to avoid rate-limit drops on the Apertus endpoint
SEMAPHORE = asyncio.Semaphore(5)

class TopicResult(BaseModel):
    affair_id: str
    title: str
    language: str
    primary_topic: str
    is_digitalisation: bool = Field(description="Matches DVS scope (Digital Administration Switzerland)")
    confidence_score: float = Field(description="Value between 0.0 and 1.0")
    key_passage_evidence: str = Field(description="Direct quote backing decision")
    explanation: str = Field(description="Neutral rationale explaining topic tag")

class RAGResponse(BaseModel):
    query: str
    filter_language: str
    total_found: int
    classified_affairs: List[TopicResult]

def extract_text(field) -> str:
    """Helper to unwrap multilingual dictionary objects or raw strings safely."""
    if isinstance(field, dict):
        return str(field.get("fr") or field.get("de") or field.get("it") or next(iter(field.values()), ""))
    if field is None:
        return ""
    return str(field)

async def fetch_all_openparldata(query: str, target_lang: str = "all") -> List[dict]:
    """Fetch matching affairs from OpenParlData API with pagination handling."""
    all_affairs = []
    page = 1
    page_size = 20

    async with httpx.AsyncClient() as client:
        while True:
            params = {
                "search": query,
                "search_mode": "boolean",
                "limit": page_size,
                "page": page
            }
            if target_lang != "all":
                params["lang"] = target_lang

            try:
                response = await client.get(
                    f"{OPENPARL_API_BASE}/affairs/",
                    params=params,
                    timeout=15.0
                )
                
                if response.status_code != 200:
                    break

                data = response.json()
                items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

                if not items:
                    break

                all_affairs.extend(items)

                if len(items) < page_size or page >= 5:
                    break

                page += 1
            except Exception as e:
                print(f"Fetch error on page {page}: {e}")
                break

    return all_affairs

async def classify_with_apertus_async(affair: dict, topics: List[str]) -> TopicResult:
    """Async classification call using your active Apertus API key."""
    affair_id = extract_text(affair.get("id")) or "N/A"
    title = extract_text(affair.get("title")) or "Untitled"
    raw_summary = extract_text(affair.get("summary") or affair.get("text")) or title
    
    truncated_summary = raw_summary[:1200]
    lang = extract_text(affair.get("language")) or "de"

    system_prompt = (
        "You are a neutral Swiss political data analyst using the Apertus LLM. "
        "Analyze parliamentary documents in German, French, Italian, or Romansh. "
        "Classify the text into standard or ad-hoc topics and return structured JSON."
    )

    user_prompt = f"""
Analyze this Swiss parliamentary affair:
- ID: {affair_id}
- Title: {title}
- Language: {lang}
- Text snippet: {truncated_summary}

Target Topics: {', '.join(topics)}

Return ONLY a valid JSON object matching this schema:
{{
    "affair_id": "{affair_id}",
    "title": "{title}",
    "language": "{lang}",
    "primary_topic": "Best match from target topics or 'Other'",
    "is_digitalisation": true,
    "confidence_score": 0.95,
    "key_passage_evidence": "exact short quote backing decision",
    "explanation": "1-2 sentence neutral justification"
}}
"""

    async with SEMAPHORE:
        try:
            response = await apertus_client.chat.completions.create(
                model="swiss-ai/Apertus-v1.5-8B",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.1,
                response_format={"type": "json_object"}
            )
            content = response.choices[0].message.content
            parsed = json.loads(content)
            return TopicResult(**parsed)
        except Exception as err:
            return TopicResult(
                affair_id=affair_id,
                title=title,
                language=lang,
                primary_topic="Unclassified",
                is_digitalisation="digital" in (title + " " + truncated_summary).lower(),
                confidence_score=0.5,
                key_passage_evidence=truncated_summary[:100],
                explanation=f"Processed with default fallback due to API/Parsing error: {str(err)}"
            )

@app.get("/api/v1/search_and_classify", response_model=RAGResponse)
async def search_and_classify(
    query: str = Query(..., description="Query term"),
    topics: str = Query("Digitalisation, Energy, Economy, Health, Environment"),
    language: str = Query("all", description="Language filter: 'all', 'de', 'fr', 'it', or 'rm'")
):
    target_lang = language.lower().strip()
    
    # Fetch matching affairs from OpenParlData API
    affairs = await fetch_all_openparldata(query, target_lang=target_lang)
    
    # Fallback search if zero initial hits
    if not affairs and target_lang == "all":
        fallback_terms = ["digital", "numérique", "internet", "strategie"]
        for term in fallback_terms:
            affairs = await fetch_all_openparldata(term, target_lang=target_lang)
            if affairs:
                break

    # Client-side language check
    if target_lang != "all":
        affairs = [a for a in affairs if extract_text(a.get("language")).lower() == target_lang]

    if not affairs:
        return RAGResponse(
            query=query,
            filter_language=target_lang,
            total_found=0,
            classified_affairs=[]
        )

    target_topics = [t.strip() for t in topics.split(",")]
    
    # Process affairs concurrently using Apertus
    tasks = [classify_with_apertus_async(a, target_topics) for a in affairs]
    results = await asyncio.gather(*tasks)
    
    results_list = list(results)
    results_list.sort(key=lambda x: x.confidence_score, reverse=True)

    return RAGResponse(
        query=query,
        filter_language=target_lang,
        total_found=len(results_list),
        classified_affairs=results_list
    )