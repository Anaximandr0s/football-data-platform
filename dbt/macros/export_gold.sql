{#- on-run-end: copy each Gold table that was built to <gold_export_root>/<table>.parquet (MinIO bucket gold).
    Off by default; `make gold` turns it on with --vars "{export_gold: true}". -#}
{% macro export_gold(results) %}
  {%- if var('export_gold') and execute -%}
    {%- for r in results if r.node.resource_type == 'model' and 'marts' in r.node.fqn and r.status == 'success' -%}
      {%- set target_file = var('gold_export_root') ~ '/' ~ r.node.name ~ '.parquet' -%}
      {%- do run_query("copy (select * from " ~ r.node.relation_name ~ ") to '" ~ target_file ~ "' (format parquet)") -%}
      {{ log("exported " ~ r.node.name ~ " -> " ~ target_file, info=True) }}
    {%- endfor -%}
  {%- endif -%}
{% endmacro %}
