# Similar cases: how to turn a document into searches

Goal: for a document being classified, find affairs on the same issue in any parliament and language, so a person
can compare topics with cases that people already labelled.

## Setup

- 42 documents: 16 federal affairs (texts in German, French or Italian; motions, postulates, interpellations,
  initiatives, question time, a Federal Council bill) and 26 cantonal affairs from SG, TG, VD, GE, NE, JU, VS, FR,
  TI, GR and BE (content from their PDFs). Split by a hash: 20 dev (used to design the prompt), 22 test (untouched).
- Search: OpenParlData `/affairs/`, titles only (`search_scope=metadata`, about 0.2 s per query; full text takes
  about 17 s), `search_mode=natural`, which requires every query word in a title and returns the newest hits first.
- Judge: Jev, one Noul per candidate: "does it deal with the same specific issue?", with the document as state.
  All candidates any method found for a document are judged together. Affairs with the same title in the same
  parliament (identical motions, resubmissions) count once.
- Judge check: 40 pairs labelled by hand, blind to the score. Jev agrees on "same issue" in 82% of pairs (rank
  correlation 0.80). It never rated an unrelated pair above 0.38; related-field pairs average 0.40.

## Methods

| Method | What Apertus (70B) writes |
|---|---|
| m1 title → translate | nothing new: the title goes to the existing /search translator |
| m2 request → translate | a one-line request from the document, then the existing /search translator |
| m4 subjects → queries | 1-3 subjects, 2 queries per subject and language |
| m6 strict queries | queries of one or two words per language |
| m5 keywords + builder | title words per language; queries built from hit counts |
| **m7 keywords v2 + builder** | the same, asking for the word forms titles use and synonyms (chosen) |

## Results (held-out test, 22 documents)

| Method | Queries with no hit | Similar cases found (p ≥ 0.5) | Documents with ≥ 3 | P@5 | P@10 |
|---|---|---|---|---|---|
| m1 title → translate | 74% | 0.7 | 9% | 14% | 7% |
| m2 request → translate | 92% | 0.7 | 9% | 10% | 7% |
| m4 subjects → queries | 78% | 3.7 | 27% | – | – |
| m6 strict queries | 20% | 6.9 | 55% | 53% | 41% |
| m5 keywords + builder | 37% | 11.1 | 77% | 71% | 56% |
| **m7 keywords v2 + builder** | 29% | **13.5** | **86%** | **79%** | **64%** |
| all methods pooled (ceiling) | | | | 85% | 70% |

P@k: share of the k cases shown first (after Jev ranking) that the judge rates as the same issue. On the dev half
m7 reaches P@5 94% and P@10 86%; every method scores lower on the test half, m7 keeps its lead.

## Why the chosen method works

Asked for queries, Apertus writes phrases ("révision pratique demandes d'asile femmes afghanes"). The search needs
every word in a title, so most phrases match nothing: 74-92% of queries in m1, m2 and m4 return no affair. Asking
for single title words instead, and building the queries in code from how many titles each word matches, fixes this:

- a word matching at most 60 titles is specific: searched alone, all hits kept;
- the first two words name the subject: searched alone even when broad, newest 30 hits;
- broad words among the first four are paired (two words must both be in the title);
- procedural words (motion, Kanton, …) are dropped, German ß is written ss.

Asking for the word forms titles use (Afghaninnen next to afghanische Frauen, Westast next to Westumfahrung) and
for synonyms added 2-4 similar cases per document over m5.

## Is the judge right? Cross-validation (80 pairs, 8 documents)

The top hits of title search and of full-text search were judged three ways:

| Comparison | Agreement | Cohen's kappa |
|---|---|---|
| Jev on the candidate title (the measure above) vs Jev on title + text | 90% | 0.78 |
| Jev on title + text vs Apertus 70B on both texts (an independent model) | 92% | 0.84 |
| Jev on the candidate title vs Apertus 70B on both texts | 88% | 0.73 |

All three call 51 of the 80 pairs similar, so there is no bias in one direction. Seeing the candidate's text does
not rescue full-text hits: 15-17 of their top 40 are similar for every judge, against 34-36 for title search.
Independent of any model: similar federal cases share their human Curia subject areas with the source with a
Jaccard of 0.48 (test) and 0.57 (dev), against 0.09 for random pairs of federal affairs.

## One human-style query instead of title words

Tested on request: Apertus reads the whole document and writes one short query, which runs through the existing
/search pipeline (translator, OpenParlData, Jev relevance ranking), then reranked by Jev similarity to the document.

| Query | Search scope | P@5 dev | P@5 test |
|---|---|---|---|
| 1-3 words (q4) | titles | 44% | – |
| 1-3 words (q4) | everything | 64% | – |
| one subject word + 2 fallbacks (q9) | titles | 75% | 41% |
| one subject word + 2 fallbacks (q9) | everything | 56% | 17% |
| 2-3 co-occurring words, tuned by hit count (q10) | everything | 44% | – |
| title words + hit-count builder (chosen, m7) | titles | 94% | 79% |

Why one word fails on full text: OpenParlData returns matches newest first without ranking, and full text includes
budgets and reports. "Polycom" is in 35 titles but in 1,359 affairs overall; the affairs about Polycom were at
positions 113, 124 and 131 of the full-text list, beyond the 20 per query /search keeps. The API offers no relevance
sort (`sort_by=rank`, `relevance`, `score`, `ts_rank` are rejected).

The experiment also found a bug in the existing translator: Apertus often adds a stray `}` after its JSON, and the
parser then discarded the translation (19 of 189 answers, 10%) and searched the raw request. Fixed.

## Cost and speed

One Apertus call (about 5 s), 20-40 title searches (about 1 s), Jev on about 180 candidates (about 30k input
tokens, about $0.001, 1-2 s). About 6-9 s per document in total.
