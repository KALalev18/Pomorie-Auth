{# HMAC-SHA256 pseudonym, identical to pomorie.privacy.pseudonym(value, purpose). #}
{% macro pseudonym(column, purpose) -%}
    encode(hmac('{{ purpose }}:' || {{ column }}::text, '{{ var("pseudonym_key") }}', 'sha256'), 'hex')
{%- endmacro %}
