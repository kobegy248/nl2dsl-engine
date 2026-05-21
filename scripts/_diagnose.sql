-- Diagnose: count rows matching each filter condition separately
SELECT
  (SELECT COUNT(*) FROM order_fact) AS total_rows,
  (SELECT COUNT(*) FROM order_fact WHERE category IN ('手机', '家电', '电脑')) AS after_category,
  (SELECT COUNT(*) FROM order_fact WHERE category IN ('手机', '家电', '电脑') AND channel IN ('线上', '线下')) AS after_channel,
  (SELECT COUNT(*) FROM order_fact WHERE category IN ('手机', '家电', '电脑') AND channel IN ('线上', '线下') AND order_amount > 1000) AS after_amount,
  (SELECT COUNT(*) FROM order_fact WHERE category IN ('手机', '家电', '电脑') AND channel IN ('线上', '线下') AND order_amount > 1000 AND region IN ('华东', '华南')) AS after_region,
  (SELECT COUNT(*) FROM order_fact WHERE category IN ('手机', '家电', '电脑') AND channel IN ('线上', '线下') AND order_amount > 1000 AND region IN ('华东', '华南') AND tenant_id = 't001') AS after_tenant;

-- Show matching rows with customer_name
SELECT of.*, cd.customer_name
FROM order_fact of
LEFT JOIN customer_dim cd ON of.customer_id = cd.customer_id
WHERE of.category IN ('手机', '家电', '电脑')
  AND of.channel IN ('线上', '线下')
  AND of.order_amount > 1000
  AND of.region IN ('华东', '华南')
  AND of.tenant_id = 't001';
