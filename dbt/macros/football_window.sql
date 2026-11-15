{#- The football window of a second (docs/product.md, section 2; the same rule as clock.window_index in the app and,
    in step 6, Spark Streaming). Windows restart at each kick-off: with size 300, 0..8 then 9 (45+) in the first half,
    10..18 then 19 (90+) in the second; with size 900, 0..2, 3, 4..6, 7. -#}
{% macro football_window(ts, period, p1_start, p2_start, size) -%}
    {%- set regular = 2700 // size -%}
    (case when {{ period }} = 2
          then {{ regular + 1 }} + least(greatest({{ ts }} - {{ p2_start }}, 0) // {{ size }}, {{ regular }})
          else least(greatest({{ ts }} - {{ p1_start }}, 0) // {{ size }}, {{ regular }}) end)
{%- endmacro %}
