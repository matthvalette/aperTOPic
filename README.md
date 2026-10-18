# Hack Apertus Liebefeld — aperTOPic

OpenParlData: Topic classification for Swiss parliaments with Apertus

Submissions must use the v1.5 Apertus model family.
The submission must comply with the [HackApertus T&C](https://hackapertus.ch/terms-and-conditions).

## 🎯 The Challenge

# Context and Background

OpenParlData.ch collects parliamentary data from 90 Swiss federal, cantonal and municipal parliaments and makes it accessible through a single open API. It currently provides access to more than 300,000 political affairs and 900,000 documents in German, French, Italian and — to a tiny extent — Romansh. While this creates a common basis for accessing and analysing parliamentary information across Switzerland, the data is currently primarily searchable through full-text search. A number of parliaments, organisations and research projects have developed their own approaches to organising affairs by topic, but these are typically designed for specific use cases, use different classification schemes and often rely on manual tagging. There is therefore a need for a shared, accessible approach to topic classification that builds on the data provided by OpenParlData.ch.

# Problem Description

Today there is no common way to turn this large body of parliamentary information into topic-based results. Existing topic classifications are fragmented across parliaments and projects, differ in structure and are often created manually for a specific purpose — so a classification created for one use case cannot easily be reused for another. At the same time, full-text search requires users to anticipate the terminology in the underlying documents and repeat it across languages. The result: even seemingly straightforward questions about a topic across parliaments require substantial manual work — identifying relevant affairs, interpreting them, and assigning topic labels by hand. The data is available, but its thematic structure is not reusable as a shared resource.

# Main Objective

Develop an open and reusable classification service for Swiss parliamentary data, based on Apertus and OpenParlData. The service processes parliamentary affairs — titles, texts and associated documents — in German, French, Italian and Romansh, and automatically returns either topics from a standard two-level classification (such as the Année Politique Suisse scheme) or ad-hoc topics defined by users (such as "digitalisation" or "Covid-19"). The approach is validated through a practical use case with Digital Administration Switzerland (DVS), automatically identifying digitalisation-related affairs across the OpenParlData dataset as an alternative to the current manual process.

## 🔧 Resources & Tools

Check our resources & tools page for detailed information:
[https://hackapertus.notion.site/liebefeld-resources-tools](https://hackapertus.notion.site/liebefeld-resources-tools)

| Models           | URL                                      |
|------------------|------------------------------------------|
| Apertus v1.5 8B  | [huggingface.co/swiss-ai/Apertus-v1.5-8B](https://huggingface.co/swiss-ai/Apertus-v1.5-8B)  |
| Apertus v1.5 70B | [huggingface.co/swiss-ai/Apertus-v1.5-70B](https://huggingface.co/swiss-ai/Apertus-v1.5-70B) |

## The structure

Keep the files and directories as shown below — don't rename or move them.

| Path | What it is |
| --- | --- |
| `README.md` | The challenge description and submission requirements |
| `technical_report.md` | The deeper write-up: architecture, evaluation, limitations |
| `LICENSE` | Apache-2.0 |
| `src/` | Your code |

## Environment

- Include instructions for running the project in your technical report.
- Use the following environment variables:
```
LLM_NAME — name and version of the model
LLM_BASE_URL — endpoint base URL
LLM_API_KEY — your API key
```

## 📦 Submission Requirements & Deliverables

The submission must:
1. follow the template repo and include all prerequisite files and definitions
2. run end-to-end when judges try to run it

### Git repo (URL)
- Create your repo from this template (**Use this template**).
- Keep the layout as it is: don't rename or move its files.
- Set the repo to PUBLIC (Settings --> Collaborators --> Manage Visibility)
- Submit the URL of YOUR Git repo.

### Technical Report (pdf)
- Update [technical_report.md](technical_report.md) in this repository with all the details for your submission.
- Upload a pdf of your technical report to the root of the repo, named as `TeamName_Report.pdf`.
- Format: pdf, max. 6 pages w/o references
- Submit the pdf of the technical report.

### Demo video (URL)
- Max. 2 min demo video of your prototype
- Add the link to the **Demo** field at the top of [technical_report.md](technical_report.md)
- Submit the URL of the video.

## ⚖️ Judging Criteria

Each challenge has its own criteria, listed in its challenge description.

The main jury scores every submission on 6 dimensions (relevant for Top 6 teams):
1. **Purposeful use of AI**
2. **Technical rigour**
3. **Value, cost & scalability**
4. **Sovereign deployability**
5. **Implementation feasibility**
6. **Pitch & presentation**

Each dimension is scored from 0 to 5.

## Getting started



## License

All Hack Apertus projects are open-sourced. Please check our Terms & Conditions for specific licensing details (6. What you build is open source): https://hackapertus.ch/terms-and-conditions

## Support

### FAQ
💡 https://hackapertus.ch/faq

### Contact

💬 In case you have questions, join the conversation on Discord. Alternatively, send an email to “hello@hackapertus.ch”.
