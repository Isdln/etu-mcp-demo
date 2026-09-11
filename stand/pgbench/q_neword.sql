\set w_id random(1, 100)
\set d_id random(1, 10)
\set c_id random(1, 3000)
\set ol_cnt random(5, 15)

BEGIN;

SELECT w_tax FROM warehouse WHERE w_id = :w_id;

SELECT c_discount, c_last, c_credit FROM customer WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id;

UPDATE district SET d_next_o_id = d_next_o_id + 1 WHERE d_w_id = :w_id AND d_id = :d_id RETURNING d_next_o_id, d_tax \gset

INSERT INTO orders (o_id, o_d_id, o_w_id, o_c_id, o_entry_d, o_ol_cnt, o_all_local)
VALUES (:d_next_o_id, :d_id, :w_id, :c_id, now(), :ol_cnt, 1);

INSERT INTO new_order (no_o_id, no_d_id, no_w_id)
VALUES (:d_next_o_id, :d_id, :w_id);

INSERT INTO order_line (ol_o_id, ol_d_id, ol_w_id, ol_number, ol_i_id, ol_supply_w_id, ol_quantity, ol_amount, ol_dist_info)
SELECT :d_next_o_id, :d_id, :w_id, g, (random() * 99999)::int + 1, :w_id, 5, (random() * 100)::numeric(6,2), left(md5(g::text), 24) FROM generate_series(1, :ol_cnt) g;

UPDATE stock SET s_quantity = CASE WHEN s_quantity > 10 THEN s_quantity - 1 ELSE s_quantity + 90 END, s_ytd = s_ytd + 1, s_order_cnt = s_order_cnt + 1
WHERE s_w_id = :w_id AND s_i_id IN (SELECT ol_i_id FROM order_line WHERE ol_o_id = :d_next_o_id AND ol_d_id = :d_id AND ol_w_id = :w_id);

END;