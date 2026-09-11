\set w_id random(1, 100)
\set d_id random(1, 10)

BEGIN;

SELECT coalesce(min(no_o_id), -1) AS no_o_id FROM new_order WHERE no_w_id = :w_id AND no_d_id = :d_id \gset

DELETE FROM new_order WHERE no_w_id = :w_id AND no_d_id = :d_id AND no_o_id = :no_o_id;

UPDATE orders SET o_carrier_id = 1 + (random() * 9)::int WHERE o_w_id = :w_id AND o_d_id = :d_id AND o_id = :no_o_id;

UPDATE order_line SET ol_delivery_d = now() WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = :no_o_id;

UPDATE customer SET c_balance = c_balance + coalesce( (SELECT sum(ol_amount) FROM order_line WHERE ol_w_id = :w_id AND ol_d_id = :d_id AND ol_o_id = :no_o_id), 0), c_delivery_cnt = c_delivery_cnt + 1
WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = coalesce((SELECT o_c_id FROM orders WHERE o_w_id = :w_id AND o_d_id = :d_id AND o_id = :no_o_id), -1);

END;