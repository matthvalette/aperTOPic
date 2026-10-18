"""Prompt templates for Curia Vista → APS topic mapping.

German-language prompts (source labels are predominantly German; Apertus is
multilingual). The full 165-topic APS list is embedded in the system prompt.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ApsTopic:
    """One APS topic entry."""

    code: str
    domain_de: str
    domain_fr: str
    chapter_de: str
    chapter_fr: str
    topic_de: str
    topic_fr: str


def format_aps_list(topics: list[ApsTopic]) -> str:
    """Render the APS topic list compactly for inclusion in the prompt."""
    lines = []
    for t in topics:
        lines.append(f"{t.code}\t{t.topic_de} ({t.chapter_de} > {t.domain_de})")
    return "\n".join(lines)


_FEW_SHOT_EXAMPLES = [
    {
        "label_de": "Gesundheit",
        "label_fr": "Santé",
        "label_it": "Salute",
        "affair_count": 10273,
        "response": {
            "primary": ["5.1.1"],
            "secondary": [
                "5.1.2", "5.1.3", "5.1.4", "5.1.5", "5.1.6", "5.1.7", "5.1.8",
                "5.2.1", "5.2.4", "5.2.5",
            ],
        },
    },
    {
        "label_de": "Landwirtschaft",
        "label_fr": "Agriculture",
        "label_it": "Agricoltura",
        "affair_count": 3894,
        "response": {
            "primary": ["8.4.1"],
            "secondary": [
                "8.4.2", "8.4.3", "8.4.4", "8.4.5", "8.4.6", "8.4.7", "8.4.8",
                "8.4.9", "8.4.10", "8.4.11", "8.4.12",
            ],
        },
    },
    {
        "label_de": "Staatspolitik",
        "label_fr": "Politique d'Etat",
        "label_it": "Politica nazionale",
        "affair_count": 8855,
        "response": {
            "primary": ["1.1.1", "1.1.2", "1.2.7"],
            "secondary": [
                "1.1.3", "1.1.4", "1.2.1", "1.2.2", "1.2.3", "1.2.4", "1.2.5",
                "1.2.6", "1.2.8", "1.2.9", "1.2.10", "1.2.11", "1.2.12",
                "2.1.7",
            ],
        },
    },
]


def _format_few_shot(example: dict) -> str:
    """Render one few-shot example."""
    import json as _json

    labels = [f'DE: "{example["label_de"]}"']
    if example.get("label_fr"):
        labels.append(f'FR: "{example["label_fr"]}"')
    if example.get("label_it"):
        labels.append(f'IT: "{example["label_it"]}"')
    label_str = ", ".join(labels)
    response_str = _json.dumps(example["response"], ensure_ascii=False)
    return (
        f"BEISPIEL-EINGABE:\n"
        f"Quell-Label: {label_str}\n"
        f"Anzahl Geschäfte: {example['affair_count']}\n\n"
        f"BEISPIEL-ANTWORT:\n{response_str}"
    )


def build_mapping_prompt(
    source_scheme: str,
    source_label_de: str,
    source_label_fr: str | None,
    source_label_it: str | None,
    affair_count: int,
    aps_topics: list[ApsTopic],
    sample_titles: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build chat messages for a single source-label → APS mapping request.

    Parameters
    ----------
    source_scheme
        Identifier of the source classification, e.g. ``curia_vista_subject_areas``.
    source_label_de
        German label (required).
    source_label_fr
        French label, if available.
    source_label_it
        Italian label, if available.
    affair_count
        Number of affairs carrying this label (helps the model judge breadth).
    aps_topics
        Full list of APS topics.
    sample_titles
        Optional affair titles carrying this label, for context.

    Returns
    -------
    list of dict
        OpenAI chat-format messages.
    """
    aps_list = format_aps_list(aps_topics)

    labels = [f'DE: "{source_label_de}"']
    if source_label_fr:
        labels.append(f'FR: "{source_label_fr}"')
    if source_label_it:
        labels.append(f'IT: "{source_label_it}"')
    label_str = ", ".join(labels)

    titles_block = ""
    if sample_titles:
        sample = "\n".join(f"- {t}" for t in sample_titles[:5])
        titles_block = f"\n\nBeispiel-Geschäfte mit diesem Label:\n{sample}"

    few_shots = "\n\n---\n\n".join(_format_few_shot(e) for e in _FEW_SHOT_EXAMPLES)

    system = (
        "Du bist ein Experte für Schweizer Politik und klassifizierst "
        "parlamentarische Geschäfte in das Themenschema der Année Politique "
        "Suisse (APS). Das APS-Schema hat 8 Domänen, 22 Kapitel und 165 Topics. "
        "Jedes Topic hat einen Code im Format D.C.T (Domäne.Kapitel.Topic).\n\n"
        "WICHTIG:\n"
        "- Breite Quell-Labels (z.B. 'Wirtschaft', 'Gesundheit') decken VIELE "
        "APS-Topics ab. Zögere nicht, 10–20 Secondary-Codes zu vergeben, wenn "
        "das sachlich gerechtfertigt ist.\n"
        "- Achte auf die DOMÄNE: 'Staatspolitik' gehört zu Domäne 1 "
        "(Akteure und Institutionen), NICHT zu Domäne 8 (Wirtschaft). "
        "'Gesundheit' gehört zu Domäne 5.\n"
        "- Gib immer mindestens 1 Primary-Code zurück."
    )

    user = f"""Hier ist die vollständige Liste der 165 APS-Topics (Code<TAB>Topic (Kapitel > Domäne)):

{aps_list}

---

{few_shots}

---

JETZT DEINE AUFGABE:

Quell-Schema: {source_scheme}
Quell-Label: {label_str}
Anzahl Geschäfte mit diesem Label: {affair_count}{titles_block}

AUFGABE:
Bestimme, welche APS-Topics diesem Quell-Label zugeordnet werden können.

- "primary": 1 bis 5 APS-Topics, die inhaltlich am besten passen. Ein Geschäft
  mit diesem Quell-Label würde typischerweise unter einem dieser Topics fallen.
- "secondary": 0 bis 20 weitere APS-Topics, die ebenfalls plausibel abgedeckt
  werden, aber nicht zentral sind. Bei breiten Labels (viele Geschäfte) sind
  viele Secondaries erwartet.
- Alle übrigen APS-Topics gelten als nicht relevant und werden NICHT aufgelistet.

REGELN:
1. Antworte ausschliesslich mit einem validen JSON-Objekt.
2. Verwende nur APS-Codes aus der obigen Liste. Keine erfundenen Codes.
3. Wenn kein APS-Topic passt, gib leere Listen zurück.
4. Keine Erklärungen, kein Kommentar — nur JSON.

ANTWORTFORMAT:
{{"primary": ["X.Y.Z", ...], "secondary": ["X.Y.Z", ...]}}"""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def build_reverse_prompt(
    aps_topic: ApsTopic,
    candidate_source_labels: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Build prompt to find which source label(s) cover a given APS topic.

    Used during the coverage pass when an APS topic is orphaned.

    Parameters
    ----------
    aps_topic
        The uncovered APS topic.
    candidate_source_labels
        List of dicts with keys ``id``, ``label_de``, ``label_fr``, ``label_it``
        representing source labels that could potentially cover this APS topic.
    """
    lines = []
    for s in candidate_source_labels:
        labels = [f'DE: "{s["label_de"]}"']
        if s.get("label_fr"):
            labels.append(f'FR: "{s["label_fr"]}"')
        if s.get("label_it"):
            labels.append(f'IT: "{s["label_it"]}"')
        lines.append(f'{s["id"]}: ' + ", ".join(labels))
    candidates_block = "\n".join(lines)

    system = (
        "Du bist ein Experte für Schweizer Politik und klassifizierst "
        "parlamentarische Geschäfte."
    )

    user = f"""APS-Topic: {aps_topic.code} "{aps_topic.topic_de}"
(Kapitel: {aps_topic.chapter_de}, Domäne: {aps_topic.domain_de})

Kandidaten-Quell-Labels (Curia Vista und kantonale Schemata):

{candidates_block}

AUFGABE:
Welche dieser Quell-Labels würden Geschäfte enthalten, die unter das obige
APS-Topic fallen? Liste die IDs der passenden Quell-Labels auf.

Antworte ausschliesslich mit einem validen JSON-Objekt:
{{"covering_source_ids": ["ID1", "ID2", ...], "relevance": ["primary", "secondary", ...]}}

Die Listen müssen gleich lang sein: covering_source_ids[i] hat relevance[i].
Wenn kein Quell-Label passt, gib leere Listen zurück."""

    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
