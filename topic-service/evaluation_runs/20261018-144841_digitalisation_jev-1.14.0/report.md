# Jev on the PolitMonitor “Digitalisierung” tag

- Model `jev-1.14.0`, one Noul, German texts of federal affairs 2019–2023.
- 150 tagged and 150 untagged affairs; dev 157 / test 143.
- Untagged affairs count as negatives, but editors miss some, so precision is a lower bound.

| Threshold | Precision | Recall | F1 | Accuracy | AUC |
|---|---|---|---|---|---|
| 0.50 | 94.6% | 69.7% | **80.3%** | 81.8% | 0.969 |
| 0.05 (tuned on dev) | 90.0% | 94.7% | **92.3%** | 91.6% | 0.969 |

Confusion at 0.05: {'tp': 72, 'fp': 8, 'fn': 4, 'tn': 59}.

Untagged affairs Jev scores highest (candidates for missed tags): 23.7917 (0.91), 22.7585 (0.90), 23.3404 (0.56), 20.3317 (0.18), 23.4183 (0.12), 21.7629 (0.07), 21.7426 (0.06), 20.3420 (0.06)

## Cost

- New Jev requests: 300, input tokens: 285,917 (953 per affair), cost about $0.012.
- At this size, classifying 300,000 affairs once would cost about $12.
