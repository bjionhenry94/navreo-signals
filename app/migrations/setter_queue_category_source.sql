-- Uncategorised-intake ship 2026-07-20: records WHO resolved a queue row's
-- category. "manual" = the recategorise dropdown (authoritative - nothing
-- automated may overwrite it); "auto" = the poll's late-category
-- auto-resolve. NULL = the row arrived already categorised at intake.
alter table setter_queue add column if not exists category_source text;
