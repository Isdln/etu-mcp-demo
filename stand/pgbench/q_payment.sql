\set w_id random(1, 100)
\set d_id random(1, 10)
\set c_id random(1, 3000)
\set cents random(100, 500000)

BEGIN;

UPDATE warehouse SET w_ytd = w_ytd + :cents / 100.0 WHERE w_id = :w_id;

UPDATE district SET d_ytd = d_ytd + :cents / 100.0 WHERE d_w_id = :w_id AND d_id = :d_id;

UPDATE customer SET c_balance = c_balance - :cents / 100.0, c_ytd_payment = c_ytd_payment + :cents / 100.0, c_payment_cnt = c_payment_cnt + 1
WHERE c_w_id = :w_id AND c_d_id = :d_id AND c_id = :c_id;

INSERT INTO history (h_c_id, h_c_d_id, h_c_w_id, h_d_id, h_w_id, h_date, h_amount, h_data)
VALUES (:c_id, :d_id, :w_id, :d_id, :w_id, now(), :cents / 100.0, 'pgbench');

END;