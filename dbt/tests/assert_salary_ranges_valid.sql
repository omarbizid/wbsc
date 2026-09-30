-- Salaries must be positive, min <= max, and always carry a currency.
select posting_id, salary_min, salary_max, salary_currency
from {{ ref('dim_postings') }}
where salary_min <= 0 or salary_max <= 0
   or salary_min > salary_max
   or (has_salary and salary_currency is null)
