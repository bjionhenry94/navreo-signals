# Benchmark: after-sources (reps=10)

| Target | Status | Bytes | Cold s | Warm p50 | Warm p95 |
|--------|--------|-------|--------|----------|----------|
| /app/setter.html | 200 | 130,554 | 0.1364 | 0.0088 | 0.0224 |
| /app/campaigns.html | 200 | 149,840 | 0.0491 | 0.0049 | 0.0146 |
| /app/deliverability.html | 200 | 58,556 | 0.0214 | 0.0042 | 0.007 |
| /app/optimise.html | 200 | 33,153 | 0.0141 | 0.003 | 0.0045 |
| /app/lists.html | 200 | 28,762 | 0.0114 | 0.0031 | 0.0039 |
| /app/strategy.html | 200 | 69,195 | 0.0223 | 0.0037 | 0.0376 |
| /app/report.html | 200 | 14,949 | 0.0121 | 0.0032 | 0.0043 |
| /app/mailboxes-hub.html | 200 | 10,101 | 0.0064 | 0.0019 | 0.0032 |
| /app/infrastructure.html | 200 | 5,215 | 0.0037 | 0.0018 | 0.0036 |
| /api/collisions | 200 | 203 | 6.2194 | 0.0031 | 0.005 |
| /api/notifications | 200 | 183,776 | 2.868 | 0.1927 | 0.453 |
| /api/sources?slim=1 | 200 | 51,934 | 0.0222 | 0.0186 | 0.0445 |
| /api/sources | 200 | 51,934 | 0.0471 | 0.0141 | 0.018 |
| /api/campaigns-unified | 200 | 38,270 | 10.2002 | 0.0086 | 0.0252 |
| /api/analytics-hub | 200 | 4,080 | 0.97 | 0.0018 | 0.0027 |
| /api/clients | 200 | 723 | 1.6512 | 0.0012 | 0.0028 |
| /api/workspaces | 200 | 342 | 1.9293 | 0.0009 | 0.0018 |
| /api/deliverability-trends | 200 | 464 | 2.1285 | 0.0042 | 0.0141 |
