---
name: database-id-bigint
description: Use _string_id_to_bigint when creating new IDs for database inserts. Ensures deterministic bigint primary keys from string IDs. Use when adding new tables, insert logic, or any code that supplies id for rows.
---

# Database ID: Use _string_id_to_bigint

## Rule

When creating a new id for a new (or existing) database table in this project, **always** derive the numeric id from a string id using `_string_id_to_bigint(string_id)` instead of auto-increment or random IDs.

- **Input**: A stable string id (e.g. `f"{entity}_{slug}"`, or an external id like `item.id`).
- **Output**: Use the returned `int` as the row’s `id` (bigint) on insert.

This keeps IDs deterministic, reproducible, and consistent across environments.

## Import

- **General / news / story / pipeline code**:  
  `from backend.storage.news_articles_save import _string_id_to_bigint`
- **Macro-related storage** (macro_* tables):  
  `from backend.storage.macro_id_utils import _string_id_to_bigint`  
  (and use the same module’s string-id helpers, e.g. `macro_raw_string_id`, when they exist.)

## Usage pattern

```python
# 1. Define a stable string id (e.g. from domain key)
string_id = f"my_entity_{source_id}"  # or use an existing *_string_id() helper

# 2. Convert to bigint for the database
db_id = _string_id_to_bigint(string_id)

# 3. Use db_id in insert
row = {"id": db_id, "other_col": ...}
```

## Do not

- Rely on database auto-increment/serial for new tables when the row has a natural string key.
- Generate random UUIDs or random ints for `id` when a deterministic string key exists.
- Reimplement hashing; use the existing `_string_id_to_bigint` so all tables share the same scheme.
