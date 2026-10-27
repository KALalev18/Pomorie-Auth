select
    d::date as date_key,
    extract(isoyear from d)::int as iso_year,
    extract(month from d)::int as month_number,
    to_char(d, 'YYYY-MM') as year_month_label,
    extract(isodow from d)::int as iso_weekday,
    extract(isodow from d) in (6, 7) as is_weekend,
    -- Pomorie's tourist season drives report volume (see the generator's summer factor).
    extract(month from d) between 6 and 9 as is_summer_season
from generate_series('2026-01-01'::date, '2027-12-31'::date, interval '1 day') as d
