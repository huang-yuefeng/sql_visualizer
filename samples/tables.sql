-- Sample database tables for testing SQL field extraction

CREATE TABLE users (
    user_id INT PRIMARY KEY,
    username VARCHAR(50) NOT NULL,
    email VARCHAR(100),
    age INT,
    status VARCHAR(20) DEFAULT 'active',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP,
    score DECIMAL(10,2)
);

CREATE TABLE orders (
    order_id INT PRIMARY KEY,
    user_id INT NOT NULL,
    product_id INT,
    amount DECIMAL(10,2) NOT NULL,
    quantity INT DEFAULT 1,
    order_status VARCHAR(20),
    order_date DATE,
    shipped_date DATE,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE products (
    product_id INT PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    category VARCHAR(50),
    price DECIMAL(10,2),
    stock INT,
    rating DECIMAL(3,2),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE TABLE payments (
    payment_id INT PRIMARY KEY,
    order_id INT NOT NULL,
    payment_method VARCHAR(30),
    amount DECIMAL(10,2),
    payment_date TIMESTAMP,
    status VARCHAR(20),
    transaction_id VARCHAR(100)
);

CREATE TABLE logs (
    log_id INT PRIMARY KEY,
    table_name VARCHAR(50),
    operation VARCHAR(10),
    record_id INT,
    old_value TEXT,
    new_value TEXT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    changed_by INT
);
