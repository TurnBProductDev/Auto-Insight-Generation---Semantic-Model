# DAX Validator (Node 6)

This node is deterministic and does NOT call an LLM. For each generated query it
checks, against the model metadata:
  - every referenced table exists
  - every referenced column exists
  - every referenced measure exists
  - the query has exactly one EVALUATE
  - breakdown queries use a row limit (TOPN)

Invalid queries are marked "skipped" with a reason and excluded from execution;
valid queries continue. Output: outputs/validated_dax_queries.json
