# Deal Score v2 shadow evaluation

`daily-median-v2` runs beside the production Deal Score but cannot send or suppress alerts. It
exists to test whether reducing correlated intraday samples produces a more trustworthy baseline.

## Method

- Keep the current observation outside both baselines.
- Group prior observations by calendar day in `America/Sao_Paulo`.
- Replace all prices in each day with one exact-Decimal median.
- Use the latest timestamp from that day as the representative observation time.
- Run the existing percentiles, confidence, trend, recent-drop, weights, and classifications over
  those daily representatives.
- Persist the result in `deal_score_shadow`; never read it in the alert engine or formatter.

The production v1 keeps its latest 500 raw observations. V2 can load up to 8,000 raw observations,
which covers roughly 500 days at the current 16 checks/day before daily reduction.

## Thirty-day review

Start the review clock at the first persisted shadow row. Do not promote v2 automatically. After
30 complete days, compare:

1. v1 versus v2 score availability and confidence;
2. mean and maximum absolute score difference;
3. classification agreement;
4. how often each version crossed the route's notification threshold;
5. candidate alerts that humans judged useful or noisy;
6. performance and database growth.

The earliest valid review time can be queried without exposing routes:

```sql
SELECT MIN(evaluated_at) AS shadow_started_at,
       MIN(evaluated_at) + INTERVAL '30 days' AS earliest_review_at,
       COUNT(*) AS evaluations
FROM deal_score_shadow
WHERE version = 'daily-median-v2';
```

Promotion, weight changes, confidence changes, or alert-policy changes require a separate product
decision and PR after the review.
