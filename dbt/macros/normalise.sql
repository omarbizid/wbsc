{# Matching keys used for duplicate detection. Documented in docs/data_dictionary.md. #}

{% macro company_key(col) -%}
    regexp_replace(
        regexp_replace(lower({{ col }}), '\m(group|holdings|uk|limited|ltd|plc|llp|inc|technologies|technology)\M', '', 'g'),
        '[^a-z0-9]', '', 'g')
{%- endmacro %}

{# Lowercase, punctuation removed, work-arrangement / location / contract noise removed.
   Bracketed text is KEPT: "Data Scientist (Economist)" is a different job. #}
{% macro title_key(col) -%}
    btrim(regexp_replace(
        regexp_replace(lower({{ col }}),
            '\m(hybrid|remote|london|uk|united kingdom|fte|permanent|contract|\d+\s*months?)\M', ' ', 'g'),
        '[^a-z0-9]+', ' ', 'g'))
{%- endmacro %}

{# Words that describe level, not the job. Titles differing only in these are different jobs. #}
{% macro level_words_regex() -%}
    '^(senior|sr|snr|junior|jr|lead|principal|staff|head|manager|director|vp|intern|graduate|grad|associate|mid|i|ii|iii|iv|v|chief)$'
{%- endmacro %}
