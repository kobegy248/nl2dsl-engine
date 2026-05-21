"""Mock data generator for end-to-end tests.

Generates realistic e-commerce/retail business data for NL2DSL testing.
Now includes: orders, products, customers, suppliers, regions, dates,
warehouses, and inventory snapshots.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy import (
    Column, Float, Integer, MetaData, String, Table, create_engine, insert,
)
from sqlalchemy.pool import StaticPool

# Fixed seed for reproducible data
random.seed(42)

# --- Products (10 items, covering 4 categories & key brands) ---
PRODUCTS = [
    {"name": "iPhone 15 Pro", "brand": "苹果", "category": "手机", "price": 7999.0},
    {"name": "华为 Mate 60 Pro", "brand": "华为", "category": "手机", "price": 6999.0},
    {"name": "小米 14", "brand": "小米", "category": "手机", "price": 3999.0},
    {"name": "MacBook Pro 14", "brand": "苹果", "category": "电脑", "price": 14999.0},
    {"name": "联想 ThinkPad X1", "brand": "联想", "category": "电脑", "price": 9999.0},
    {"name": "海尔冰箱 500L", "brand": "海尔", "category": "家电", "price": 3999.0},
    {"name": "美的空调 1.5匹", "brand": "美的", "category": "家电", "price": 2699.0},
    {"name": "索尼电视 65寸", "brand": "索尼", "category": "家电", "price": 5999.0},
    {"name": "Nike Air Max", "brand": "Nike", "category": "服饰", "price": 899.0},
    {"name": "优衣库羽绒服", "brand": "优衣库", "category": "服饰", "price": 499.0},
]

# --- Regions ---
REGIONS = [
    {"name": "华东", "code": "HD"},
    {"name": "华南", "code": "HN"},
    {"name": "华北", "code": "HB"},
    {"name": "西南", "code": "XN"},
]

# --- Channels ---
CHANNELS = [
    {"name": "线上", "code": "online"},
    {"name": "线下", "code": "offline"},
    {"name": "分销", "code": "distribute"},
]

# --- Customer types ---
CUSTOMER_TYPES = [
    {"name": "新客", "code": "new"},
    {"name": "老客", "code": "old"},
    {"name": "VIP", "code": "vip"},
]

# --- Suppliers ---
SUPPLIERS = [
    {"name": "上海生鲜供应链有限公司", "type": "批发商", "region": "华东", "contact": "王经理", "credit": "A", "years": 8},
    {"name": "深圳电子元器件有限公司", "type": "制造商", "region": "华南", "contact": "李总监", "credit": "A", "years": 5},
    {"name": "北京冷链物流有限公司", "type": "物流商", "region": "华北", "contact": "张主管", "credit": "B", "years": 3},
    {"name": "杭州纺织服装有限公司", "type": "制造商", "region": "华东", "contact": "刘经理", "credit": "B", "years": 6},
    {"name": "成都食品饮料有限公司", "type": "代理商", "region": "西南", "contact": "陈总监", "credit": "C", "years": 2},
    {"name": "广州日用百货有限公司", "type": "批发商", "region": "华南", "contact": "赵经理", "credit": "A", "years": 10},
    {"name": "武汉家电制造有限公司", "type": "制造商", "region": "华北", "contact": "孙主管", "credit": "B", "years": 4},
    {"name": "南京数码科技有限公司", "type": "代理商", "region": "华东", "contact": "周总监", "credit": "A", "years": 7},
]

# --- Warehouses ---
WAREHOUSES = [
    {"name": "华东中心仓", "type": "中心仓", "region": "华东", "region_code": "HD", "capacity": 50000, "status": "运营中"},
    {"name": "华南中心仓", "type": "中心仓", "region": "华南", "region_code": "HN", "capacity": 45000, "status": "运营中"},
    {"name": "华北中心仓", "type": "中心仓", "region": "华北", "region_code": "HB", "capacity": 40000, "status": "运营中"},
    {"name": "西南中心仓", "type": "中心仓", "region": "西南", "region_code": "XN", "capacity": 35000, "status": "运营中"},
    {"name": "华东前置仓-杭州", "type": "前置仓", "region": "华东", "region_code": "HD", "capacity": 8000, "status": "运营中"},
    {"name": "华南前置仓-深圳", "type": "前置仓", "region": "华南", "region_code": "HN", "capacity": 6000, "status": "运营中"},
]


def _generate_order_no(idx: int) -> str:
    return f"ORD{datetime.now().strftime('%Y%m%d')}{idx:06d}"


def create_schema(engine) -> tuple[Table, ...]:
    """Create full retail e-commerce schema."""
    metadata = MetaData()

    region_dim = Table(
        "region_dim", metadata,
        Column("region_code", String(10), primary_key=True),
        Column("region_name", String(20)),
        Column("province", String(50)),
        Column("city", String(50)),
        Column("tier_level", String(20)),
        Column("population_millions", Float),
    )

    date_dim = Table(
        "date_dim", metadata,
        Column("date_id", Integer, primary_key=True),
        Column("full_date", String(20)),
        Column("year", Integer),
        Column("month", Integer),
        Column("quarter", String(10)),
        Column("day_of_week", Integer),
        Column("is_weekend", Integer),
        Column("is_holiday", Integer),
        Column("fiscal_year", Integer),
    )

    supplier_dim = Table(
        "supplier_dim", metadata,
        Column("supplier_id", Integer, primary_key=True),
        Column("supplier_name", String(100)),
        Column("supplier_type", String(50)),
        Column("region", String(20)),
        Column("contact_name", String(50)),
        Column("credit_rating", String(10)),
        Column("cooperation_years", Integer),
    )

    product_dim = Table(
        "product_dim", metadata,
        Column("product_id", Integer, primary_key=True),
        Column("product_name", String(100)),
        Column("brand", String(50)),
        Column("category", String(50)),
        Column("price", Float),
        Column("supplier_id", Integer),
    )

    customer_dim = Table(
        "customer_dim", metadata,
        Column("customer_id", Integer, primary_key=True),
        Column("customer_name", String(50)),
        Column("customer_type", String(20)),
        Column("register_date", String(20)),
        Column("region", String(20)),
    )

    warehouse_dim = Table(
        "warehouse_dim", metadata,
        Column("warehouse_id", Integer, primary_key=True),
        Column("warehouse_name", String(100)),
        Column("warehouse_type", String(50)),
        Column("region", String(20)),
        Column("region_code", String(10)),
        Column("capacity", Integer),
        Column("status", String(20)),
    )

    order_fact = Table(
        "order_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("order_no", String(50)),
        Column("product_id", Integer),
        Column("product_name", String(100)),
        Column("brand", String(50)),
        Column("category", String(50)),
        Column("region", String(20)),
        Column("region_code", String(10)),
        Column("channel", String(20)),
        Column("channel_code", String(20)),
        Column("customer_id", Integer),
        Column("customer_type", String(20)),
        Column("order_amount", Float),
        Column("discount_amount", Float),
        Column("pay_amount", Float),
        Column("quantity", Integer),
        Column("order_date", String(20)),
        Column("date_id", Integer),
        Column("tenant_id", String(20)),
    )

    inventory_fact = Table(
        "inventory_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("product_id", Integer),
        Column("product_name", String(100)),
        Column("brand", String(50)),
        Column("category", String(50)),
        Column("warehouse_id", Integer),
        Column("warehouse_name", String(100)),
        Column("warehouse_type", String(50)),
        Column("region", String(20)),
        Column("region_code", String(10)),
        Column("date_id", Integer),
        Column("date_str", String(20)),
        Column("stock_quantity", Integer),
        Column("available_quantity", Integer),
        Column("reserved_quantity", Integer),
        Column("avg_daily_sales", Integer),
        Column("days_of_supply", Integer),
        Column("tenant_id", String(20)),
    )

    metadata.create_all(engine)
    return (
        order_fact, product_dim, customer_dim,
        supplier_dim, region_dim, date_dim,
        warehouse_dim, inventory_fact,
    )


def insert_regions(conn, region_dim: Table) -> None:
    """Insert region dimension data."""
    records = [
        {"region_code": "HD", "region_name": "华东", "province": "浙江/江苏/上海", "city": "杭州", "tier_level": "新一线", "population_millions": 100.0},
        {"region_code": "HN", "region_name": "华南", "province": "广东", "city": "深圳", "tier_level": "一线", "population_millions": 120.0},
        {"region_code": "HB", "region_name": "华北", "province": "北京", "city": "北京", "tier_level": "一线", "population_millions": 85.0},
        {"region_code": "XN", "region_name": "西南", "province": "四川", "city": "成都", "tier_level": "新一线", "population_millions": 95.0},
    ]
    conn.execute(insert(region_dim), records)
    conn.commit()


def insert_dates(conn, date_dim: Table) -> None:
    """Insert date dimension for Jan 2024."""
    base = datetime(2024, 1, 1)
    records = []
    for i in range(31):
        d = base + timedelta(days=i)
        dow = d.isoweekday()  # 1=Mon ... 7=Sun
        records.append({
            "date_id": int(d.strftime("%Y%m%d")),
            "full_date": d.strftime("%Y-%m-%d"),
            "year": 2024,
            "month": 1,
            "quarter": "Q1",
            "day_of_week": dow,
            "is_weekend": 1 if dow in (6, 7) else 0,
            "is_holiday": 1 if d.strftime("%Y-%m-%d") == "2024-01-01" else 0,
            "fiscal_year": 2024,
        })
    conn.execute(insert(date_dim), records)
    conn.commit()


def insert_suppliers(conn, supplier_dim: Table) -> None:
    """Insert supplier dimension data (8 suppliers)."""
    records = [
        {
            "supplier_id": i + 1,
            "supplier_name": s["name"],
            "supplier_type": s["type"],
            "region": s["region"],
            "contact_name": s["contact"],
            "credit_rating": s["credit"],
            "cooperation_years": s["years"],
        }
        for i, s in enumerate(SUPPLIERS)
    ]
    conn.execute(insert(supplier_dim), records)
    conn.commit()


def insert_products(conn, product_dim: Table) -> None:
    """Insert product dimension data (10 products)."""
    records = [
        {
            "product_id": i + 1,
            "product_name": p["name"],
            "brand": p["brand"],
            "category": p["category"],
            "price": p["price"],
            "supplier_id": (i % 8) + 1,
        }
        for i, p in enumerate(PRODUCTS)
    ]
    conn.execute(insert(product_dim), records)
    conn.commit()


def insert_customers(conn, customer_dim: Table) -> None:
    """Insert customer dimension data (5 customers)."""
    names = ["张三", "李四", "王五", "赵六", "孙七"]
    regions = ["华东", "华南", "华北", "西南", "华东"]
    records = []
    for i, name in enumerate(names):
        c_type = random.choice(CUSTOMER_TYPES)
        days_back = random.randint(30, 365)
        reg_date = (datetime(2024, 1, 1) - timedelta(days=days_back)).strftime("%Y-%m-%d")
        records.append({
            "customer_id": i + 1,
            "customer_name": name,
            "customer_type": c_type["name"],
            "register_date": reg_date,
            "region": regions[i],
        })
    conn.execute(insert(customer_dim), records)
    conn.commit()


def insert_warehouses(conn, warehouse_dim: Table) -> None:
    """Insert warehouse dimension data (6 warehouses)."""
    records = [
        {
            "warehouse_id": i + 1,
            "warehouse_name": w["name"],
            "warehouse_type": w["type"],
            "region": w["region"],
            "region_code": w["region_code"],
            "capacity": w["capacity"],
            "status": w["status"],
        }
        for i, w in enumerate(WAREHOUSES)
    ]
    conn.execute(insert(warehouse_dim), records)
    conn.commit()


def insert_orders(conn, order_fact: Table, num_orders: int = 50) -> None:
    """Insert order fact data (default 50 orders)."""
    base_date = datetime(2024, 1, 1)
    records = []

    region_weights = [0.30, 0.25, 0.25, 0.20]
    channel_weights = [0.50, 0.30, 0.20]
    tenant_weights = [0.60, 0.40]

    for i in range(num_orders):
        product = random.choices(PRODUCTS, weights=[
            0.12 if p["category"] == "手机" else
            0.08 if p["category"] == "电脑" else
            0.07 if p["category"] == "家电" else
            0.05
            for p in PRODUCTS
        ])[0]

        region = random.choices(REGIONS, weights=region_weights)[0]
        channel = random.choices(CHANNELS, weights=channel_weights)[0]
        tenant_id = "t001" if random.random() < 0.6 else "t002"

        day_offset = random.randint(0, 30)
        order_date = (base_date + timedelta(days=day_offset)).strftime("%Y-%m-%d")

        price = product["price"]
        quantity = random.randint(1, 5) if product["category"] != "服饰" else random.randint(1, 10)
        order_amount = round(price * quantity, 2)
        discount_rate = random.choice([0, 0.05, 0.10, 0.15, 0.20])
        discount_amount = round(order_amount * discount_rate, 2)
        pay_amount = round(order_amount - discount_amount, 2)

        records.append({
            "id": i + 1,
            "order_no": _generate_order_no(i),
            "product_id": PRODUCTS.index(product) + 1,
            "product_name": product["name"],
            "brand": product["brand"],
            "category": product["category"],
            "region": region["name"],
            "region_code": region["code"],
            "channel": channel["name"],
            "channel_code": channel["code"],
            "customer_id": random.randint(1, 5),
            "customer_type": random.choice(CUSTOMER_TYPES)["name"],
            "order_amount": order_amount,
            "discount_amount": discount_amount,
            "pay_amount": pay_amount,
            "quantity": quantity,
            "order_date": order_date,
            "date_id": int(order_date.replace("-", "")),
            "tenant_id": tenant_id,
        })

    conn.execute(insert(order_fact), records)
    conn.commit()


def insert_inventory(conn, inventory_fact: Table) -> None:
    """Insert inventory fact data: 10 products x 6 warehouses = 60 rows."""
    records = []
    date_id = 20240131
    for w_idx, wh in enumerate(WAREHOUSES):
        for p_idx, prod in enumerate(PRODUCTS):
            stock = random.randint(20, 500)
            reserved = random.randint(0, min(50, stock))
            available = stock - reserved
            avg_daily = random.randint(1, 20)
            dos = stock // avg_daily if avg_daily > 0 else 0
            records.append({
                "id": w_idx * len(PRODUCTS) + p_idx + 1,
                "product_id": p_idx + 1,
                "product_name": prod["name"],
                "brand": prod["brand"],
                "category": prod["category"],
                "warehouse_id": w_idx + 1,
                "warehouse_name": wh["name"],
                "warehouse_type": wh["type"],
                "region": wh["region"],
                "region_code": wh["region_code"],
                "date_id": date_id,
                "date_str": "2024-01-31",
                "stock_quantity": stock,
                "available_quantity": available,
                "reserved_quantity": reserved,
                "avg_daily_sales": avg_daily,
                "days_of_supply": dos,
                "tenant_id": "t001" if random.random() < 0.6 else "t002",
            })
    conn.execute(insert(inventory_fact), records)
    conn.commit()


def create_mock_database(db_url: str = "sqlite:///:memory:"):
    """Create a complete mock database with full retail schema and data.

    Returns:
        (engine, order_fact, product_dim, customer_dim,
         supplier_dim, region_dim, date_dim,
         warehouse_dim, inventory_fact)
    """
    if db_url == "sqlite:///:memory:":
        engine = create_engine(
            db_url,
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
    else:
        engine = create_engine(db_url)

    (
        order_fact, product_dim, customer_dim,
        supplier_dim, region_dim, date_dim,
        warehouse_dim, inventory_fact,
    ) = create_schema(engine)

    with engine.connect() as conn:
        insert_regions(conn, region_dim)
        insert_dates(conn, date_dim)
        insert_suppliers(conn, supplier_dim)
        insert_warehouses(conn, warehouse_dim)
        insert_products(conn, product_dim)
        insert_customers(conn, customer_dim)
        insert_orders(conn, order_fact, num_orders=50)
        insert_inventory(conn, inventory_fact)

    return (
        engine, order_fact, product_dim, customer_dim,
        supplier_dim, region_dim, date_dim,
        warehouse_dim, inventory_fact,
    )


def get_summary_stats(engine, order_fact: Table):
    """Print summary statistics for verification."""
    from sqlalchemy import func as sa_func, select as sa_select

    with engine.connect() as conn:
        result = conn.execute(sa_select(sa_func.sum(order_fact.c.pay_amount)))
        total_sales = result.scalar()

        result = conn.execute(sa_select(sa_func.count()).select_from(order_fact))
        total_orders = result.scalar()

        result = conn.execute(
            sa_select(order_fact.c.region, sa_func.count())
            .group_by(order_fact.c.region)
        )
        by_region = dict(result.fetchall())

        result = conn.execute(
            sa_select(order_fact.c.category, sa_func.count())
            .group_by(order_fact.c.category)
        )
        by_category = dict(result.fetchall())

    return {
        "total_sales": round(total_sales or 0, 2),
        "total_orders": total_orders,
        "by_region": by_region,
        "by_category": by_category,
    }


if __name__ == "__main__":
    (
        engine, order_fact, product_dim, customer_dim,
        supplier_dim, region_dim, date_dim,
        warehouse_dim, inventory_fact,
    ) = create_mock_database()
    stats = get_summary_stats(engine, order_fact)
    print("Mock database created successfully!")
    print(f"  Total orders: {stats['total_orders']}")
    print(f"  Total sales: {stats['total_sales']:,.2f}")
    print(f"  By region: {stats['by_region']}")
    print(f"  By category: {stats['by_category']}")
