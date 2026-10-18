# Jev on Curia Vista subject areas

- Model `jev-1.13.0`, 28 subject areas, one Noul per subject area.
- 300 federal affairs submitted 2018–2026 (seed 7), title + submitted text + reasoning. Dev 145 / test 155.
- Gold: 2.77 subject areas per test affair.
- The threshold is tuned on dev (best micro-F1) and every number below is on test.

## Overall (test set)

| Language | Threshold | Micro P | Micro R | Micro F1 | Macro F1 | Exact match | Jaccard | Top-1 correct | Recall@3 | Macro AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| de | 0.75 | 73.6% | 61.6% | **67.1%** | 62.5% | 18.1% | 0.56 | 91.0% | 74.3% | 0.950 |
| fr | 0.70 | 70.1% | 64.9% | **67.4%** | 63.3% | 18.7% | 0.56 | 91.6% | 73.1% | 0.948 |
| it | 0.70 | 69.7% | 65.1% | **67.3%** | 61.9% | 18.1% | 0.56 | 93.5% | 74.6% | 0.950 |

At the default threshold 0.5 (de): micro-F1 65.0%, 3.86 predicted vs 2.77 gold labels per affair.

Baseline, always predicting the 3 most frequent subject areas (Gesundheit, Staatspolitik, Finanzwesen): micro-F1 22.1%, macro-F1 3.7%.

## Per subject area (test, de, threshold 0.75)

| Subject area | Gold | Precision | Recall | F1 | AUC |
|---|---|---|---|---|---|
| Gesundheit | 44 | 100.0% | 54.5% | 70.6% | 0.964 |
| Wirtschaft | 41 | 75.0% | 80.5% | 77.6% | 0.919 |
| Staatspolitik | 29 | 69.6% | 55.2% | 61.5% | 0.854 |
| Umwelt | 28 | 85.0% | 60.7% | 70.8% | 0.976 |
| Sicherheitspolitik | 27 | 90.5% | 70.4% | 79.2% | 0.960 |
| Finanzwesen | 26 | 78.9% | 57.7% | 66.7% | 0.945 |
| Internationale Politik | 26 | 59.3% | 61.5% | 60.4% | 0.916 |
| Soziale Fragen | 21 | 77.8% | 66.7% | 71.8% | 0.945 |
| Verkehr | 21 | 92.9% | 61.9% | 74.3% | 0.994 |
| Medien und Kommunikation | 20 | 100.0% | 25.0% | 40.0% | 0.980 |
| Migration | 18 | 100.0% | 72.2% | 83.9% | 0.995 |
| Landwirtschaft | 16 | 77.8% | 87.5% | 82.4% | 0.989 |
| Steuer | 13 | 87.5% | 53.8% | 66.7% | 0.993 |
| Energie | 11 | 100.0% | 90.9% | 95.2% | 0.999 |
| Beschäftigung und Arbeit | 11 | 70.0% | 63.6% | 66.7% | 0.948 |
| Europapolitik | 11 | 87.5% | 63.6% | 73.7% | 0.951 |
| Menschenrechte | 11 | 25.0% | 45.5% | 32.3% | 0.788 |
| Strafrecht | 10 | 77.8% | 70.0% | 73.7% | 0.981 |
| Raumplanung und Wohnungswesen | 9 | 100.0% | 22.2% | 36.4% | 0.976 |
| Internationales Recht | 8 | 31.2% | 62.5% | 41.7% | 0.942 |
| Sozialer Schutz | 7 | 100.0% | 85.7% | 92.3% | 0.994 |
| Zivilrecht | 6 | 60.0% | 50.0% | 54.5% | 0.989 |
| Wissenschaft und Forschung | 5 | 0.0% | 0.0% | 0.0% | 0.964 |
| Kultur | 4 | 100.0% | 50.0% | 66.7% | 0.994 |
| Parlament | 3 | 100.0% | 66.7% | 80.0% | 0.982 |
| Bildung | 2 | 66.7% | 100.0% | 80.0% | 1.000 |
| Recht Allgemein | 1 | 0.0% | 0.0% | 0.0% | 0.669 |
| Gerichtswesen | 1 | 33.3% | 100.0% | 50.0% | 1.000 |

## Cost

- New Jev requests: 888, input tokens: 5,425,630 (6,110 per affair), cost about $0.228.
- At this size, classifying 300,000 affairs once would cost about $77.
