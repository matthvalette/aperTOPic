# Parliament topics

Multilingual search and topic classification for Swiss parliamentary affairs, built on
[OpenParlData](https://openparldata.ch), [Apertus](https://huggingface.co/swiss-ai) and
[TypeSafe Jev](https://docs.typesafe.ai). Made for the Hack Apertus challenge
"Topic classification for Swiss parliaments".

It does three things:

1. **Search in every language.** Write a request in any language. Apertus turns it into short
   title-style queries in German, French, Italian and Romansh, OpenParlData runs them, and the
   hits are merged per affair. Optionally Jev ranks them by relevance.
2. **Topic probabilities.** Give an OpenParlData link or id, a document link, a Curia Vista link,
   an uploaded file or plain text. Jev returns a probability for every topic of the chosen
   label set, and the topics above a threshold.
3. **Evaluation.** Run Jev over the labelled federal affairs and get precision, recall, F1 and
   more, per language and per subject area.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in TYPESAFE_API_KEY and APERTUS_API_KEY
```

Download the labelled data (about 360 MB) into `data/`, which git ignores:

```bash
wget -r -np -nH -e robots=off --reject "index.html*" -P data https://files.openparldata.ch/hackapertus/
curl --create-dirs -o data/exports/bodies.ndjson.gz https://files.openparldata.ch/exports/bodies.ndjson.gz  # parliament names
```

Elsewhere on disk? Set `DATA_DIR` and `BODIES_FILE` in `.env`; relative paths are resolved
against this folder.

## Run the API

```bash
uv run uvicorn parltopics.api.main:app --reload
```

- Test console (UI): http://127.0.0.1:8000/ui
- Interactive API documentation: http://127.0.0.1:8000/docs

### Test console

A small page served by the same app, so the API keys stay on the server. The **Search** tab
shows the queries Apertus wrote per language and the merged hits, each with a link to
OpenParlData and a button that sends it to the classifier. The **Classify** tab takes a link
or id, pasted text or a file, lets you pick label sets and add ad-hoc topics, and draws one
probability bar per topic with the threshold marked.

Deep links run on load, which is handy for demos:

- `/ui/?q=artificial intelligence in public administration` (add `&rank=0` to skip ranking)
- `/ui/?ref=https://openparldata.ch/item/affairs/70435&taxonomies=curia_subject_areas,aps_topics`

| Endpoint | What it does |
|---|---|
| `GET /health` | Which features are configured |
| `GET /taxonomies` | The label sets and how many topics each has |
| `GET /taxonomies/{id}` | Every topic of one label set |
| `GET /parliaments` | Names behind body keys such as `261` (city of Zürich) |
| `POST /search` | Multilingual search |
| `POST /classify` | Topic probabilities for a link, an id or text |
| `POST /classify/upload` | Topic probabilities for a PDF, DOCX, HTML or text file |
| `POST /similar` | Similar cases in every parliament and language, with the labels people gave them |
| `POST /similar/upload` | The same for a PDF, DOCX, HTML or text file |

### Similar cases

The Classify tab also shows similar cases and a "Your labels" card: Jev's assigned topics as chips you can
remove, every other topic to add, and the topics similar cases carry as one-click suggestions.

How it works: Apertus reads the document and lists, per language, the words titles on the same subject
contain. The service searches each word that matches at most 60 titles on its own, the two words naming the
subject even when broader, and pairs of broad words. Affairs with the same title in one parliament are merged,
Jev rates how close each is to the document, and the cases come with their Curia Vista subject areas, St. Gallen
and Thurgau subjects or PolitMonitor tag. On 22 held-out documents, 79% of the five cases shown first deal with
the same issue; summarising the document for the /search translator instead reaches 10%. Details:
`evaluation_runs/20261019_similar_cases/report.md`.

```bash
curl -X POST localhost:8000/similar -H 'Content-Type: application/json' \
  -d '{"reference": "https://openparldata.ch/item/affairs/227121", "max_results": 10}'
```

### Examples

```bash
# Search from English, ranked by Jev
curl -X POST localhost:8000/search -H 'Content-Type: application/json' \
  -d '{"query": "artificial intelligence in public administration", "rank": true}'

# The 28 subject areas for a federal affair, plus the APS topics
curl -X POST localhost:8000/classify -H 'Content-Type: application/json' \
  -d '{"reference": "https://openparldata.ch/item/affairs/70435",
       "taxonomies": ["curia_subject_areas", "aps_topics"]}'

# Ad-hoc topics, no training needed
curl -X POST localhost:8000/classify -H 'Content-Type: application/json' \
  -d '{"reference": "https://openparldata.ch/item/affairs/341363", "taxonomies": [],
       "custom_topics": [{"name": "Digitalisierung"}, {"name": "Covid-19"}]}'

# An uploaded PDF
curl -X POST localhost:8000/classify/upload -F file=@motion.pdf -F taxonomies=curia_subject_areas
```

## Label sets

| Id | Classes | Labelled examples | Kind |
|---|---|---|---|
| `curia_subject_areas` (default) | 28 | 59,596 federal affairs | multi-label: one yes/no probability per subject area |
| `aps_topics` | 165 topics in 22 chapters | none: zero-shot only | multi-label; chapter score = highest topic score |
| `sg_law_collection` | 10 | 6,792 St. Gallen affairs | single-label: probabilities sum to 1 |
| `tg_subject_codes` | 109 | 2,382 Thurgau affairs | single-label |
| `digitalisation` | 1 | 3,433 tagged affairs (positives only) | binary |
| `custom_topics` in the request | any | none | multi-label |

Several label sets in one request are answered in one Jev call: Jev reads the document once
and answers every question in parallel.

## Evaluate

```bash
uv run parltopics-eval subject-areas --n 300 --languages de fr it --model jev-1.13.0
uv run parltopics-eval digitalisation --n 300
```

Reports land in `evaluation_runs/<time>_<task>_<model>/report.md`. Jev answers are cached in
`evaluation_runs/cache/`, so a rerun with the same questions costs nothing. Thresholds are tuned
on a dev half and every reported number is on the test half.

### Results (18 October 2026)

**Curia Vista subject areas.** 300 federal affairs submitted 2018–2026, each classified in
German, French and Italian; 155 test affairs with 2.8 subject areas each on average.

| Model | Language | Top-1 correct | Gold in top 3 | Precision | Recall | F1 | AUC |
|---|---|---|---|---|---|---|---|
| jev-1.14.0 | de | 92.3% | 73.6% | 71.4% | 65.6% | **68.4%** | 0.951 |
| jev-1.14.0 | fr | 92.3% | 74.0% | 71.3% | 64.2% | **67.6%** | 0.946 |
| jev-1.14.0 | it | 92.9% | 74.2% | 67.9% | 68.4% | **68.1%** | 0.950 |
| jev-1.13.0 | de | 91.0% | 74.3% | 73.6% | 61.6% | 67.1% | 0.950 |
| jev-1.13.0 | fr | 91.6% | 73.1% | 70.1% | 64.9% | 67.4% | 0.948 |
| jev-1.13.0 | it | 93.5% | 74.6% | 69.7% | 65.1% | 67.3% | 0.950 |

- Baseline that always predicts the three most frequent subject areas: F1 22.1%.
- Results are the same in all three languages.
- Per subject area, the AUC is above 0.93 for most areas, but one threshold for all areas
  under-assigns some (Medien und Kommunikation: recall 30%) and over-assigns others
  (Menschenrechte, Internationales Recht: precision 28%). Per-area thresholds are the next step.
- The labels themselves are noisy: federal affairs with identical titles have exactly the same
  subject areas only 69% of the time.

**Digitalisation tag.** 300 federal affairs 2019–2023, half tagged by PolitMonitor, German texts,
jev-1.14.0, 143 test affairs: AUC 0.969. At threshold 0.5, precision 94.6% and recall 69.7%
(F1 80.3%); at the dev-tuned 0.05, precision 90.0% and recall 94.7% (F1 92.3%). The sample is
balanced; at the real share of about 5% tagged affairs, expect precision around 46% (at 0.5)
or 30% (at 0.05). Both are lower bounds: the untagged affairs Jev scores highest, such as
"NDB … Cyber" and "Smartwatches für unsere Kinder?", look like tags the editors missed.

**Cost and speed.** About 6,100 input tokens per affair for the 28 subject areas (about $77
to classify 300,000 affairs once) and 950 for the digitalisation tag (about $12). 300 affairs
took about 10 seconds at 8 parallel requests.

## Code layout

```
src/parltopics/
  config.py               settings from .env
  domain/
    models.py             shared types: affairs, documents, taxonomies, classifications
    ports.py              the interfaces between modules (Protocols)
  adapters/               one file per outside system, each implements a port
    openparldata.py       OpenParlData API: search, affairs, texts, documents
    apertus.py            Apertus (Keera gateway, OpenAI-compatible): query translation
    jev.py                TypeSafe Jev: topic probabilities and search relevance
    taxonomies.py         label sets built from the labelled data
    files.py              text from PDF, DOCX, HTML and text files
    bodies.py             parliament names from the bodies export
    labels.py             labels people gave affairs (Curia Vista, SG, TG, Zug, Zurich, PolitMonitor)
  services/               the use cases, written against the ports only
    references.py         parses pasted links and ids
    documents.py          link, upload or text -> document with named sections
    search.py             multilingual search
    classify.py           topic classification
    similar.py            similar cases: title words -> searches by hit count -> Jev ranking -> labels
  api/
    main.py               FastAPI app
    dependencies.py       wiring: which adapter implements which port
    schemas.py            request bodies
    routes/               one file per endpoint group
  web/                    the test console: index.html, styles.css, app.js (no build step)
  evaluation/
    datasets.py           labelled samples
    metrics.py            precision, recall, F1, AUC
    runner.py             cached batch classification
    cli.py                parltopics-eval
tests/                    unit tests with fake adapters, no network
```

To swap a component, write a class with the methods of its port in `domain/ports.py` and wire
it in `api/dependencies.py`. Nothing else changes.

## How the Jev questions are built

- **Multi-label sets** get one Noul per topic: "Is one of the main subjects of the parliamentary
  affair in `affair` covered by `subject_area`?" The subject area comes with its names in
  German, French, Italian and English and a short scope description. The scope descriptions
  of the 28 subject areas are hand-written in `adapters/taxonomies.py`, because the
  descriptors in the data describe the scheme before its 2012 change.
- **Single-label sets** get one Choice over all topics.
- The state is the affair: parliament, type, title, submitted text and reasoning. The Federal
  Council's answer is left out by default, because subject areas are assigned at submission.
  Long sections are cut to keep the state focused.

## Notes

- The OpenParlData search matches every word of a query and returns results newest first, not
  by relevance. That is why Apertus writes short queries and Jev can rank the merged hits.
- Full-text scopes (`texts`, `docs`, `all`) take about 10 seconds per query; `metadata`
  (titles) about 0.3 seconds.
- Labels are suggestions with probabilities. A person should be able to correct them.
- Apertus often ends its JSON with one stray `}`. The parsers read the first complete JSON object and ignore
  the rest; before this fix, about 1 in 10 translations was discarded and the request searched untranslated.
