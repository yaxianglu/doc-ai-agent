# Strict Agent Evaluation Rubric

## Scoring Dimensions

Each representative dialogue should be judged on five axes:

1. **Correctness**
   - Does it answer the actual user question?
   - Does it preserve region, domain, and time window?

2. **Completeness**
   - If the user asked for data + reason + forecast + advice, does it cover all requested parts?

3. **Constraint Obedience**
   - Does it obey explicit user instructions such as `不要建议` or `先给数据`?

4. **Multi-turn Stability**
   - Does it correctly inherit scope from prior turns without drifting?

5. **Evidence Quality**
   - Are reasons tied to observed metrics, trend, peak, recent value, or forecast output?
   - Or does it fall back to generic filler?

## Harsh Scoring Rule

- `9-10`: correct, complete, stable, evidence-grounded, no obvious agent-quality embarrassment
- `7-8`: useful but still has visible genericity or control weakness
- `5-6`: partially right, but missing key requested structure or obeying poorly
- `0-4`: obvious misunderstanding, drift, or unusable answer

## Non-Negotiable Fails

Any of the following should keep a dialogue below 7:

- compare question answers only one side
- explicit `不要建议` still returns advice
- follow-up loses already established region/domain/time
- `为什么` answer contains no data-grounded reasoning
- obvious clarification when the system already has enough context to answer
