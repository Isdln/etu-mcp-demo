\set w_id random(1, 100)
\set d_id random(1, 10)
\set c_id random(1, 3000)

SELECT coalesce(max(o_id), -1) AS last_o_id FROM orders
WHERE o_w_id = :w_id AND o_d_id = :d_id AND o_c_id = :c_id \gset

SELECT ol_i_id, ol_supply_w_id, ol_quantity, ol_amount, ol_delivery_d FROM order_line
WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = :last_o_id
ORDER BY ol_number;