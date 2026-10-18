# Jev on Curia Vista subject areas

- Model `jev-1.14.0`, 28 subject areas, one Noul per subject area.
- 300 federal affairs submitted 2018–2026 (seed 7), title + submitted text + reasoning. Dev 145 / test 155.
- Gold: 2.77 subject areas per test affair.
- The threshold is tuned on dev (best micro-F1) and every number below is on test.

## Overall (test set)

| Language | Threshold | Micro P | Micro R | Micro F1 | Macro F1 | Exact match | Jaccard | Top-1 correct | Recall@3 | Macro AUC |
|---|---|---|---|---|---|---|---|---|---|---|
| de | 0.75 | 71.4% | 65.6% | **68.4%** | 63.6% | 18.7% | 0.57 | 92.3% | 73.6% | 0.951 |
| fr | 0.75 | 71.3% | 64.2% | **67.6%** | 62.8% | 20.0% | 0.57 | 92.3% | 74.0% | 0.946 |
| it | 0.70 | 67.9% | 68.4% | **68.1%** | 63.6% | 17.4% | 0.57 | 92.9% | 74.2% | 0.950 |

At the default threshold 0.5 (de): micro-F1 64.6%, 4.15 predicted vs 2.77 gold labels per affair.

Baseline, always predicting the 3 most frequent subject areas (Gesundheit, Staatspolitik, Finanzwesen): micro-F1 22.1%, macro-F1 3.7%.

## Per subject area (test, de, threshold 0.75)

| Subject area | Gold | Precision | Recall | F1 | AUC |
|---|---|---|---|---|---|
| Gesundheit | 44 | 96.2% | 56.8% | 71.4% | 0.965 |
| Wirtschaft | 41 | 73.9% | 82.9% | 78.2% | 0.920 |
| Staatspolitik | 29 | 75.0% | 62.1% | 67.9% | 0.859 |
| Umwelt | 28 | 86.4% | 67.9% | 76.0% | 0.976 |
| Sicherheitspolitik | 27 | 87.5% | 77.8% | 82.4% | 0.955 |
| Finanzwesen | 26 | 77.3% | 65.4% | 70.8% | 0.942 |
| Internationale Politik | 26 | 63.0% | 65.4% | 64.2% | 0.918 |
| Soziale Fragen | 21 | 78.9% | 71.4% | 75.0% | 0.940 |
| Verkehr | 21 | 92.9% | 61.9% | 74.3% | 0.994 |
| Medien und Kommunikation | 20 | 85.7% | 30.0% | 44.4% | 0.979 |
| Migration | 18 | 100.0% | 77.8% | 87.5% | 0.995 |
| Landwirtschaft | 16 | 82.4% | 87.5% | 84.8% | 0.991 |
| Steuer | 13 | 80.0% | 61.5% | 69.6% | 0.993 |
| Energie | 11 | 100.0% | 90.9% | 95.2% | 0.999 |
| Beschäftigung und Arbeit | 11 | 63.6% | 63.6% | 63.6% | 0.961 |
| Europapolitik | 11 | 77.8% | 63.6% | 70.0% | 0.947 |
| Menschenrechte | 11 | 28.0% | 63.6% | 38.9% | 0.793 |
| Strafrecht | 10 | 58.3% | 70.0% | 63.6% | 0.980 |
| Raumplanung und Wohnungswesen | 9 | 100.0% | 33.3% | 50.0% | 0.970 |
| Internationales Recht | 8 | 27.8% | 62.5% | 38.5% | 0.934 |
| Sozialer Schutz | 7 | 100.0% | 71.4% | 83.3% | 0.991 |
| Zivilrecht | 6 | 60.0% | 50.0% | 54.5% | 0.990 |
| Wissenschaft und Forschung | 5 | 0.0% | 0.0% | 0.0% | 0.967 |
| Kultur | 4 | 100.0% | 50.0% | 66.7% | 0.995 |
| Parlament | 3 | 100.0% | 66.7% | 80.0% | 0.998 |
| Bildung | 2 | 66.7% | 100.0% | 80.0% | 0.997 |
| Recht Allgemein | 1 | 0.0% | 0.0% | 0.0% | 0.695 |
| Gerichtswesen | 1 | 33.3% | 100.0% | 50.0% | 0.994 |

## Cost

- New Jev requests: 900, input tokens: 5,499,507 (6,111 per affair), cost about $0.231.
- At this size, classifying 300,000 affairs once would cost about $77.
