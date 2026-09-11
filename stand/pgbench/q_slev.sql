\set w_id random(1, 100)
\set d_id random(1, 10)
\set threshold random(10, 20)

SELECT d_next_o_id AS next_o FROM district
WHERE d_w_id = :w_id AND d_id = :d_id \gset

SELECT count(DISTINCT s.s_i_id) FROM order_line ol
JOIN stock s ON s.s_w_id = :w_id AND s.s_i_id = ol.ol_i_id
WHERE ol.ol_w_id = :w_id AND ol.ol_d_id = :d_id AND ol.ol_o_id BETWEEN :next_o - 20 AND :next_o - 1 AND s.s_quantity < :threshold;