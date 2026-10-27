"""DDL for the two databases: the dealership's internal DB and BMW's partner-portal DB.

Money is GBP, DECIMAL(12,2). Timestamps are naive UTC. Ids are readable prefixed strings
(C-00001 customer, L- lead, D- deal, BK- booking, J- job card, ...), so agents can quote them.
"""

INTERNAL = """
-- staff: a copy of the personas (company/personas/*.md stays the source of truth)
CREATE TABLE staff (
    staff_id VARCHAR PRIMARY KEY, name VARCHAR, role VARCHAR, department VARCHAR,
    reports_to VARCHAR, email VARCHAR UNIQUE, phone_ext INTEGER, systems VARCHAR[]);

-- crm ---------------------------------------------------------------------------
CREATE TABLE customers (
    customer_id VARCHAR PRIMARY KEY, first_name VARCHAR, last_name VARCHAR, email VARCHAR,
    phone VARCHAR, postcode VARCHAR, city VARCHAR, source VARCHAR, consent_marketing BOOLEAN,
    created_at TIMESTAMP);
CREATE TABLE leads (
    lead_id VARCHAR PRIMARY KEY, customer_id VARCHAR, assigned_to VARCHAR,
    status VARCHAR,        -- new, contacted, test_drive, quoted, won, lost
    interest VARCHAR, budget DECIMAL(12,2), source VARCHAR, created_at TIMESTAMP,
    updated_at TIMESTAMP, lost_reason VARCHAR);
CREATE TABLE test_drives (
    test_drive_id VARCHAR PRIMARY KEY, lead_id VARCHAR, stock_no VARCHAR, staff_id VARCHAR,
    scheduled_at TIMESTAMP, status VARCHAR);   -- booked, done, no_show, cancelled
CREATE TABLE activities (
    activity_id VARCHAR PRIMARY KEY, customer_id VARCHAR, staff_id VARCHAR,
    kind VARCHAR,          -- call, email, visit, note, export
    note VARCHAR, occurred_at TIMESTAMP);
CREATE TABLE customer_vehicles (
    vin VARCHAR PRIMARY KEY, reg VARCHAR, customer_id VARCHAR, model VARCHAR, fuel VARCHAR,
    year INTEGER, mileage INTEGER, warranty_until DATE, last_service DATE, next_service_due DATE);

-- dms ---------------------------------------------------------------------------
CREATE TABLE vehicles (
    stock_no VARCHAR PRIMARY KEY, vin VARCHAR, model_code VARCHAR, model VARCHAR, series VARCHAR,
    fuel VARCHAR, colour VARCHAR, year INTEGER, mileage INTEGER,
    condition VARCHAR,     -- new, used
    status VARCHAR,        -- on_order, in_transit, in_stock, reserved, sold, delivered
    list_price DECIMAL(12,2), cost_price DECIMAL(12,2), bmw_order_no VARCHAR,
    arrived_at TIMESTAMP, pdi_done BOOLEAN, reg VARCHAR);
CREATE TABLE deals (
    deal_id VARCHAR PRIMARY KEY, lead_id VARCHAR, customer_id VARCHAR, stock_no VARCHAR,
    salesperson VARCHAR,
    status VARCHAR,        -- draft, pending_approval, approved, signed, delivered, cancelled
    list_price DECIMAL(12,2), discount_pct DECIMAL(5,2), discount_amount DECIMAL(12,2),
    accessories_amount DECIMAL(12,2), trade_in_value DECIMAL(12,2), final_price DECIMAL(12,2),
    finance_product VARCHAR, created_at TIMESTAMP, signed_at TIMESTAMP, delivered_at TIMESTAMP,
    notes VARCHAR);
CREATE TABLE approvals (
    approval_id VARCHAR PRIMARY KEY,
    kind VARCHAR,          -- discount, goodwill, stock_order, warranty
    ref_id VARCHAR, requested_by VARCHAR, approver VARCHAR, amount DECIMAL(12,2),
    pct DECIMAL(5,2), reason VARCHAR,
    status VARCHAR,        -- pending, approved, rejected
    requested_at TIMESTAMP, decided_at TIMESTAMP, decision_note VARCHAR);
CREATE TABLE order_requests (
    request_id VARCHAR PRIMARY KEY, model_code VARCHAR, colour VARCHAR, customer_id VARCHAR,
    reason VARCHAR,        -- customer, stock
    requested_by VARCHAR,
    status VARCHAR,        -- pending_approval, open, ordered, cancelled
    bmw_order_no VARCHAR, stock_no VARCHAR, created_at TIMESTAMP);
CREATE TABLE invoices (
    invoice_no VARCHAR PRIMARY KEY,
    kind VARCHAR,          -- vehicle, service, parts
    ref_id VARCHAR, customer_id VARCHAR, net DECIMAL(12,2), vat DECIMAL(12,2), total DECIMAL(12,2),
    issued_at TIMESTAMP, paid_at TIMESTAMP, payment_method VARCHAR);

-- workshop ----------------------------------------------------------------------
CREATE TABLE bookings (
    booking_id VARCHAR PRIMARY KEY, customer_id VARCHAR, vin VARCHAR, date DATE,
    service_type VARCHAR,  -- service, mot, repair, diagnosis, tyres, recall, pdi
    notes VARCHAR, created_by VARCHAR,
    status VARCHAR,        -- booked, arrived, cancelled, no_show
    created_at TIMESTAMP);
CREATE TABLE job_cards (
    job_no VARCHAR PRIMARY KEY, booking_id VARCHAR, vin VARCHAR, customer_id VARCHAR,
    advisor VARCHAR, technician VARCHAR,
    status VARCHAR,        -- open, in_progress, waiting_parts, waiting_authorisation, complete, invoiced
    complaint VARCHAR, findings VARCHAR, warranty BOOLEAN, opened_at TIMESTAMP, closed_at TIMESTAMP);
CREATE TABLE job_lines (
    line_id VARCHAR PRIMARY KEY, job_no VARCHAR,
    kind VARCHAR,          -- labour, part
    description VARCHAR, part_no VARCHAR, qty DECIMAL(8,2), unit_price DECIMAL(12,2),
    authorised BOOLEAN, added_by VARCHAR, added_at TIMESTAMP);
CREATE TABLE time_entries (
    entry_id VARCHAR PRIMARY KEY, job_no VARCHAR, technician VARCHAR, hours DECIMAL(5,2),
    note VARCHAR, occurred_at TIMESTAMP);

-- parts -------------------------------------------------------------------------
CREATE TABLE parts (
    part_no VARCHAR PRIMARY KEY, description VARCHAR, category VARCHAR, fits VARCHAR,
    bin VARCHAR, qty_on_hand INTEGER, qty_reserved INTEGER, reorder_level INTEGER,
    cost DECIMAL(12,2), price DECIMAL(12,2));
CREATE TABLE parts_requests (
    request_id VARCHAR PRIMARY KEY, job_no VARCHAR, part_no VARCHAR, qty INTEGER,
    requested_by VARCHAR,
    status VARCHAR,        -- requested, issued, ordered, cancelled
    bmw_order_no VARCHAR, issued_by VARCHAR, requested_at TIMESTAMP, issued_at TIMESTAMP);
CREATE TABLE parts_movements (
    movement_id VARCHAR PRIMARY KEY, part_no VARCHAR, qty INTEGER,
    kind VARCHAR,          -- receipt, issue, counter_sale, adjustment
    ref VARCHAR, staff_id VARCHAR, occurred_at TIMESTAMP);

-- finance -----------------------------------------------------------------------
CREATE TABLE ledger (
    entry_id VARCHAR PRIMARY KEY, date DATE, account VARCHAR, description VARCHAR,
    debit DECIMAL(12,2), credit DECIMAL(12,2), ref VARCHAR);

-- mail --------------------------------------------------------------------------
CREATE TABLE messages (
    msg_id VARCHAR PRIMARY KEY, thread_id VARCHAR, from_addr VARCHAR, to_addr VARCHAR,
    cc VARCHAR, subject VARCHAR, body VARCHAR, sent_at TIMESTAMP, read_at TIMESTAMP);

-- every tool call, by whom, with what result (feeds the admin console later)
CREATE SEQUENCE audit_seq;
CREATE TABLE audit_log (
    id BIGINT DEFAULT nextval('audit_seq') PRIMARY KEY, occurred_at TIMESTAMP, actor VARCHAR,
    system VARCHAR, tool VARCHAR, args JSON, ok BOOLEAN, result_summary VARCHAR);
"""

PORTAL = """
CREATE TABLE dealers (dealer_no VARCHAR PRIMARY KEY, name VARCHAR, city VARCHAR);
CREATE TABLE portal_users (
    user_id VARCHAR PRIMARY KEY, dealer_no VARCHAR, email VARCHAR UNIQUE, name VARCHAR,
    portal_role VARCHAR,   -- dealer_admin, sales_ordering, parts_ordering, aftersales, technician, finance
    active BOOLEAN, mfa_enabled BOOLEAN, last_login TIMESTAMP);
CREATE TABLE models (
    model_code VARCHAR PRIMARY KEY, series VARCHAR, name VARCHAR, fuel VARCHAR, body VARCHAR,
    base_price DECIMAL(12,2), dealer_cost DECIMAL(12,2), lead_time_weeks INTEGER);
CREATE TABLE car_orders (
    order_no VARCHAR PRIMARY KEY, dealer_no VARCHAR, model_code VARCHAR, colour VARCHAR,
    options VARCHAR[], order_type VARCHAR,  -- customer, stock
    customer_ref VARCHAR, ordered_by VARCHAR, ordered_at TIMESTAMP,
    status VARCHAR,        -- confirmed, in_production, shipped, delivered, cancelled
    production_week VARCHAR, eta DATE, vin VARCHAR, invoice_amount DECIMAL(12,2));
CREATE TABLE parts_catalog (
    part_no VARCHAR PRIMARY KEY, description VARCHAR, category VARCHAR, fits VARCHAR,
    dealer_price DECIMAL(12,2), retail_price DECIMAL(12,2), central_stock INTEGER);
CREATE TABLE parts_orders (
    order_no VARCHAR PRIMARY KEY, dealer_no VARCHAR,
    kind VARCHAR,          -- stock, vor
    job_ref VARCHAR, ordered_by VARCHAR, ordered_at TIMESTAMP,
    status VARCHAR,        -- confirmed, dispatched, delivered
    eta TIMESTAMP, total DECIMAL(12,2));
CREATE TABLE parts_order_lines (
    order_no VARCHAR, part_no VARCHAR, qty INTEGER, unit_price DECIMAL(12,2));
CREATE TABLE warranty_claims (
    claim_no VARCHAR PRIMARY KEY, dealer_no VARCHAR, vin VARCHAR, job_ref VARCHAR,
    description VARCHAR, labour_hours DECIMAL(5,2), parts_amount DECIMAL(12,2),
    amount DECIMAL(12,2), submitted_by VARCHAR, submitted_at TIMESTAMP,
    status VARCHAR,        -- submitted, approved, rejected, paid
    decided_at TIMESTAMP, decision_note VARCHAR);
CREATE TABLE recalls (
    recall_code VARCHAR PRIMARY KEY, title VARCHAR, models VARCHAR, remedy VARCHAR,
    labour_hours DECIMAL(5,2), issued_at DATE);
CREATE TABLE recall_vins (recall_code VARCHAR, vin VARCHAR, completed_at TIMESTAMP);
CREATE TABLE bulletins (
    bulletin_no VARCHAR PRIMARY KEY, title VARCHAR, models VARCHAR, symptom VARCHAR,
    fix VARCHAR, issued_at DATE);
CREATE SEQUENCE access_seq;
CREATE TABLE portal_access_log (
    id BIGINT DEFAULT nextval('access_seq') PRIMARY KEY, occurred_at TIMESTAMP, actor VARCHAR,
    system VARCHAR, tool VARCHAR, args JSON, ok BOOLEAN, result_summary VARCHAR);
"""
