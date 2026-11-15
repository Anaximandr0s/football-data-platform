{#- Where a Silver table is read from. One place to change if the way DuckDB reads Silver changes. -#}
{% macro silver_table(name) %}
  {%- if var('silver_reader') == 'iceberg' -%}
    iceberg_scan('{{ var("silver_warehouse") }}/{{ var("silver_namespace") }}/{{ name }}')
  {%- elif var('silver_reader') == 'parquet' -%}
    read_parquet('{{ var("silver_parquet_root") }}/{{ name }}/*.parquet')
  {%- else -%}
    {{ exceptions.raise_compiler_error("silver_reader must be 'iceberg' or 'parquet'") }}
  {%- endif -%}
{% endmacro %}
