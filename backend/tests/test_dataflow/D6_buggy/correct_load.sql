CREATE TABLE transactions (
    id BIGINT,
    amount DECIMAL(18,2),
    fee DECIMAL(18,2),
    status VARCHAR(50)
);
INSERT INTO transactions VALUES (1, 100.00, 5.00, 'COMPLETED');
