# Benchmark: after-collisions (reps=12)

| Target | Status | Bytes | Cold s | Warm p50 | Warm p95 |
|--------|--------|-------|--------|----------|----------|
| /app/setter.html | 200 | 130,554 | 0.064 | 0.0022 | 0.0074 |
| /app/campaigns.html | 200 | 149,840 | 0.0186 | 0.0024 | 0.004 |
| /app/deliverability.html | 200 | 58,551 | 0.0067 | 0.0007 | 0.0022 |
| /app/optimise.html | 200 | 33,153 | 0.0036 | 0.0008 | 0.0015 |
| /app/lists.html | 200 | 28,762 | 0.0036 | 0.0008 | 0.0021 |
| /app/strategy.html | 200 | 69,195 | 0.0049 | 0.0008 | 0.0009 |
| /app/report.html | 200 | 14,949 | 0.0026 | 0.0007 | 0.001 |
| /app/mailboxes-hub.html | 200 | 10,101 | 0.0017 | 0.0007 | 0.002 |
| /app/infrastructure.html | 200 | 5,215 | 0.0014 | 0.0006 | 0.0008 |
| /api/collisions | 200 | 203 | 0.0007 | 0.0008 | 0.0018 |
| /api/notifications | 200 | 183,776 | 5.0122 | 0.0121 | 0.0182 |
| /api/sources?slim=1 | 200 | 51,934 | 100.3339 | 0.0047 | 0.0079 |
| /api/sources | 200 | 4,180,889 | 0.2497 | 0.2043 | 0.2171 |
| /api/campaigns-unified | 200 | 38,270 | 16.717 | 0.0045 | 0.0073 |
| /api/analytics-hub | 200 | 4,080 | 0.6259 | 0.0026 | 0.0041 |
| /api/clients | 200 | 723 | 1.1615 | 0.0009 | 0.0012 |
| /api/workspaces | 200 | 342 | 2.2149 | 0.0016 | 0.0023 |
| /api/deliverability-trends | 200 | 462 | 1.587 | 0.0018 | 0.0026 |
