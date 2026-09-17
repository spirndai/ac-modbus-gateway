#!/usr/bin/python3
import psycopg2
from psycopg2 import sql
import os


def init_timezone(conn):
    # store local time instead of UTC so now() matches wall-clock readings
    cur = conn.cursor()
    cur.execute("SELECT current_database()")
    dbname = cur.fetchone()[0]
    cur.execute(
        sql.SQL("ALTER DATABASE {} SET timezone TO 'Asia/Shanghai'").format(
            sql.Identifier(dbname))
    )
    conn.commit()
    cur.close()


def init_table(conn, name, ddl):
    cur = conn.cursor()
    cur.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = %s)",
        (name,))
    if not cur.fetchone()[0]:
        cur.execute(ddl)
        conn.commit()
    cur.close()


def init_db(conn):
    init_timezone(conn)
    # parsed messages, identical ones are stored only once
    init_table(conn, "modbusmsg", '''
        CREATE TABLE modbusmsg (
            id SERIAL PRIMARY KEY,
            msg JSONB);
        CREATE INDEX idx_msg_hash ON modbusmsg USING HASH (msg);''')
    # one row per occurrence of a message
    init_table(conn, "modbustime", '''
        CREATE TABLE modbustime (
            id SERIAL PRIMARY KEY,
            insert_time TIMESTAMP DEFAULT (CURRENT_TIMESTAMP),
            msg_id INTEGER);
        CREATE INDEX idx_msg_time ON modbustime (insert_time);''')
    # last known IP of each device, used to send control commands
    init_table(conn, "modbusclient", '''
        CREATE TABLE modbusclient (
            device_id INT UNIQUE,
            ipaddr VARCHAR(50));''')
