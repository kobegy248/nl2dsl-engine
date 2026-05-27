"""Seed ecommerce mock data into the default SQLite database."""

from __future__ import annotations

import random
from pathlib import Path

from sqlalchemy import create_engine, MetaData, Table, Column, Integer, String, Float, insert, text

from nl2dsl.config import settings


def seed():
    """Create tables and insert mock data if empty."""
    db = create_engine(settings.db_url, echo=False)

    metadata = MetaData()

    Table(
        "order_fact",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("product_id", Integer),
        Column("product_name", String),
        Column("brand", String),
        Column("category", String),
        Column("region", String),
        Column("region_code", String),
        Column("channel", String),
        Column("customer_id", Integer),
        Column("customer_type", String),
        Column("order_amount", Float),
        Column("discount_amount", Float),
        Column("pay_amount", Float),
        Column("quantity", Integer),
        Column("order_date", String),
        Column("tenant_id", String),
    )

    Table(
        "product_dim",
        metadata,
        Column("product_id", Integer, primary_key=True),
        Column("product_name", String),
        Column("brand", String),
        Column("category", String),
        Column("price", Float),
    )

    Table(
        "customer_dim",
        metadata,
        Column("customer_id", Integer, primary_key=True),
        Column("customer_name", String),
        Column("customer_type", String),
        Column("register_date", String),
        Column("region", String),
    )

    metadata.create_all(db)

    with db.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM order_fact"))
        count = result.scalar()
        if count == 0:
            # Insert products
            products = [
                {"product_id": 1, "product_name": "iPhone 15 Pro", "brand": "苹果", "category": "手机", "price": 7999.0},
                {"product_id": 2, "product_name": "华为 Mate 60 Pro", "brand": "华为", "category": "手机", "price": 6999.0},
                {"product_id": 3, "product_name": "小米 14", "brand": "小米", "category": "手机", "price": 3999.0},
                {"product_id": 4, "product_name": "联想拯救者 Y9000P", "brand": "联想", "category": "电脑", "price": 8999.0},
                {"product_id": 5, "product_name": "MacBook Pro 14", "brand": "苹果", "category": "电脑", "price": 14999.0},
                {"product_id": 6, "product_name": "海尔冰箱 500L", "brand": "海尔", "category": "家电", "price": 3999.0},
                {"product_id": 7, "product_name": "美的空调 1.5匹", "brand": "美的", "category": "家电", "price": 2699.0},
                {"product_id": 8, "product_name": "Nike Air Max", "brand": "Nike", "category": "服饰", "price": 899.0},
                {"product_id": 9, "product_name": "索尼电视 65寸", "brand": "索尼", "category": "家电", "price": 5999.0},
                {"product_id": 10, "product_name": "优衣库羽绒服", "brand": "优衣库", "category": "服饰", "price": 499.0},
            ]
            conn.execute(insert(metadata.tables["product_dim"]), products)

            # Insert customers
            customers = [
                {"customer_id": 1, "customer_name": "张三", "customer_type": "VIP", "register_date": "2023-01-15", "region": "华东"},
                {"customer_id": 2, "customer_name": "李四", "customer_type": "老客", "register_date": "2023-03-20", "region": "华东"},
                {"customer_id": 3, "customer_name": "王五", "customer_type": "新客", "register_date": "2024-01-05", "region": "华南"},
                {"customer_id": 4, "customer_name": "赵六", "customer_type": "VIP", "register_date": "2022-08-10", "region": "华北"},
                {"customer_id": 5, "customer_name": "孙七", "customer_type": "老客", "register_date": "2023-06-18", "region": "西南"},
            ]
            conn.execute(insert(metadata.tables["customer_dim"]), customers)

            # Insert orders
            random.seed(42)
            regions = ["华东", "华南", "华北", "西南"]
            order_records = []
            for i in range(50):
                pid = random.randint(1, 10)
                cid = random.randint(1, 5)
                region = regions[i % 4]
                qty = random.randint(1, 5)
                price = products[pid - 1]["price"]
                amount = round(price * qty, 2)
                discount = round(amount * random.choice([0, 0.05, 0.10, 0.15]), 2)
                order_records.append({
                    "id": i + 1,
                    "product_id": pid,
                    "product_name": products[pid - 1]["product_name"],
                    "brand": products[pid - 1]["brand"],
                    "category": products[pid - 1]["category"],
                    "region": region,
                    "region_code": region[:2],
                    "channel": random.choice(["线上", "线下", "分销"]),
                    "customer_id": cid,
                    "customer_type": random.choice(["VIP", "老客", "新客"]),
                    "order_amount": amount,
                    "discount_amount": discount,
                    "pay_amount": round(amount - discount, 2),
                    "quantity": qty,
                    "order_date": f"2024-01-{random.randint(1, 31):02d}",
                    "tenant_id": "t001" if random.random() < 0.6 else "t002",
                })
            conn.execute(insert(metadata.tables["order_fact"]), order_records)
            conn.commit()
            print("Mock ecommerce data seeded successfully.")
        else:
            print(f"order_fact already has {count} rows, skipping seed.")


if __name__ == "__main__":
    seed()
