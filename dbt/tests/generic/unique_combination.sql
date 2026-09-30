{% test dbt_utils_free_unique_combination(model, columns) %}
{# Rows that repeat the same combination of columns (no package dependency needed). #}
select {{ columns | join(', ') }}, count(*) as n
from {{ model }}
group by {{ columns | join(', ') }}
having count(*) > 1
{% endtest %}
