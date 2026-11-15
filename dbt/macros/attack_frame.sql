{#- Coordinates seen by the team of the row (docs/product.md, section 2): x_att = distance from its own goal line,
    y_att > 45.33 is its left. Thirds and lanes of the same section. -#}
{% macro x_att(team, x) -%}
    (case when {{ team }} = 'HOME' then {{ x }} else {{ var('pitch_length') }} - {{ x }} end)
{%- endmacro %}

{% macro y_att(team, y) -%}
    (case when {{ team }} = 'HOME' then {{ y }} else {{ var('pitch_width') }} - {{ y }} end)
{%- endmacro %}

{% macro third(x_att) -%}
    (case when {{ x_att }} < 35 then 'own' when {{ x_att }} < 70 then 'middle' when {{ x_att }} >= 70 then 'final' end)
{%- endmacro %}

{% macro lane(y_att) -%}
    (case when {{ y_att }} > 45.33 then 'left' when {{ y_att }} < 22.67 then 'right' when {{ y_att }} is not null then 'centre' end)
{%- endmacro %}
