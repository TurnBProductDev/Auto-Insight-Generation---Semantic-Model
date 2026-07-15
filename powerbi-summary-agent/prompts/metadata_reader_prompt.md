# Metadata Reader (Node 2)

This node is deterministic and does NOT call an LLM. It runs the DAX INFO.VIEW
functions against the semantic model and assembles structured metadata:

    EVALUATE INFO.VIEW.TABLES()
    EVALUATE INFO.VIEW.COLUMNS()
    EVALUATE INFO.VIEW.MEASURES()
    EVALUATE INFO.VIEW.RELATIONSHIPS()

From the raw results it derives:
  - tables, columns, measures, relationships
  - date_fields / numeric_fields / categorical_fields (classified by data type)

Output: outputs/model_metadata.json
