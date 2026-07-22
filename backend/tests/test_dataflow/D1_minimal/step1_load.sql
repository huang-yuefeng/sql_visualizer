CREATE TABLE IF NOT EXISTS orders (
    id BIGINT PRIMARY KEY,
    amount DECIMAL(18,2),
    status VARCHAR(50),
    created_at TIMESTAMP
);
INSERT INTO orders (id, amount, status, created_at) VALUES (1, 100.00, 'PENDING', NOW());
