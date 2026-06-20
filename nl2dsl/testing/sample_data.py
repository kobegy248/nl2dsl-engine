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


# =============================================================================
# Bank schema (for bank domain e2e tests)
# =============================================================================

BANK_ORGS = [
    {"cd": "0100", "nm": "总行", "lvl": 1, "parent": None},
    {"cd": "0101", "nm": "北京分行", "lvl": 2, "parent": "0100"},
    {"cd": "0102", "nm": "上海分行", "lvl": 2, "parent": "0100"},
    {"cd": "0103", "nm": "深圳分行", "lvl": 2, "parent": "0100"},
    {"cd": "010101", "nm": "北京朝阳支行", "lvl": 3, "parent": "0101"},
    {"cd": "010102", "nm": "北京海淀支行", "lvl": 3, "parent": "0101"},
    {"cd": "010201", "nm": "上海浦东支行", "lvl": 3, "parent": "0102"},
    {"cd": "010202", "nm": "上海徐汇支行", "lvl": 3, "parent": "0102"},
]

BANK_CHANNELS = [
    {"cd": "01", "nm": "柜面"},
    {"cd": "02", "nm": "手机银行"},
    {"cd": "03", "nm": "网银"},
    {"cd": "04", "nm": "ATM"},
    {"cd": "05", "nm": "第三方"},
]

BANK_TXN_TYPES = [
    {"cd": "1001", "nm": "存款"},
    {"cd": "1002", "nm": "取款"},
    {"cd": "1003", "nm": "转账"},
    {"cd": "1004", "nm": "消费"},
    {"cd": "1005", "nm": "理财购买"},
]

BANK_PRODUCTS = [
    {"cd": "P001", "nm": "活期存款", "lvl1": "存款类", "lvl2": "活期", "sts": "01", "min": 0.0, "yld": 0.003},
    {"cd": "P002", "nm": "一年定期", "lvl1": "存款类", "lvl2": "定期", "sts": "01", "min": 5000.0, "yld": 0.018},
    {"cd": "P003", "nm": "三年定期", "lvl1": "存款类", "lvl2": "定期", "sts": "01", "min": 10000.0, "yld": 0.0275},
    {"cd": "P004", "nm": "稳健理财", "lvl1": "理财类", "lvl2": "稳健型", "sts": "01", "min": 10000.0, "yld": 0.035},
    {"cd": "P005", "nm": "进取理财", "lvl1": "理财类", "lvl2": "进取型", "sts": "01", "min": 50000.0, "yld": 0.055},
    {"cd": "P006", "nm": "货币基金", "lvl1": "基金类", "lvl2": "货币型", "sts": "01", "min": 1.0, "yld": 0.022},
]


def create_bank_schema(engine) -> tuple[Table, ...]:
    """Create bank domain schema."""
    metadata = MetaData()

    t_cif_base = Table(
        "t_cif_base", metadata,
        Column("cif_no", String(20), primary_key=True),
        Column("cust_nm", String(50)),
        Column("cust_sts_cd", String(2)),
        Column("cust_type_cd", String(2)),
        Column("cert_type_cd", String(2)),
        Column("risk_lvl_cd", String(2)),
        Column("reg_dt", String(10)),
        Column("mgr_emp_no", String(10)),
        Column("org_cd", String(10)),
        Column("tenant_id", String(20)),
    )

    t_acct_main = Table(
        "t_acct_main", metadata,
        Column("acct_no", String(20), primary_key=True),
        Column("cif_no", String(20)),
        Column("acct_type_cd", String(2)),
        Column("ccyc_cd", String(3)),
        Column("acct_sts_cd", String(2)),
        Column("acct_bal", Float),
        Column("avl_bal", Float),
        Column("frz_amt", Float),
        Column("open_dt", String(10)),
        Column("mat_dt", String(10)),
        Column("org_cd", String(10)),
        Column("tenant_id", String(20)),
    )

    t_txn_dtl = Table(
        "t_txn_dtl", metadata,
        Column("txn_seq_no", String(30), primary_key=True),
        Column("acct_no", String(20)),
        Column("cif_no", String(20)),
        Column("txn_dt", String(10)),
        Column("txn_type_cd", String(4)),
        Column("txn_amt", Float),
        Column("dr_cr_flg", String(1)),
        Column("chl_cd", String(2)),
        Column("rvsl_flg", String(1)),
        Column("tenant_id", String(20)),
    )

    t_org_hier = Table(
        "t_org_hier", metadata,
        Column("org_cd", String(10), primary_key=True),
        Column("org_nm", String(50)),
        Column("org_lvl", Integer),
        Column("parent_org_cd", String(10)),
    )

    t_prod_info = Table(
        "t_prod_info", metadata,
        Column("prod_cd", String(10), primary_key=True),
        Column("prod_nm", String(50)),
        Column("prod_lvl1_nm", String(20)),
        Column("prod_lvl2_nm", String(20)),
        Column("prod_sts_cd", String(2)),
        Column("min_pur_amt", Float),
        Column("exp_yld_rate", Float),
    )

    t_cust_prod_agt = Table(
        "t_cust_prod_agt", metadata,
        Column("agt_no", String(20), primary_key=True),
        Column("cif_no", String(20)),
        Column("acct_no", String(20)),
        Column("prod_cd", String(10)),
        Column("hold_amt", Float),
        Column("sign_amt", Float),
        Column("sign_dt", String(10)),
        Column("due_dt", String(10)),
        Column("agt_sts_cd", String(2)),
        Column("tenant_id", String(20)),
    )

    t_chl_mapping = Table(
        "t_chl_mapping", metadata,
        Column("chl_cd", String(2), primary_key=True),
        Column("chl_nm", String(20)),
    )

    t_txn_type_dict = Table(
        "t_txn_type_dict", metadata,
        Column("txn_type_cd", String(4), primary_key=True),
        Column("txn_type_nm", String(20)),
    )

    metadata.create_all(engine)
    return (
        t_cif_base, t_acct_main, t_txn_dtl,
        t_org_hier, t_prod_info, t_cust_prod_agt,
        t_chl_mapping, t_txn_type_dict,
    )


def insert_bank_orgs(conn, t_org_hier: Table) -> None:
    records = [
        {"org_cd": o["cd"], "org_nm": o["nm"], "org_lvl": o["lvl"], "parent_org_cd": o["parent"]}
        for o in BANK_ORGS
    ]
    conn.execute(insert(t_org_hier), records)
    conn.commit()


def insert_bank_channels(conn, t_chl_mapping: Table) -> None:
    records = [
        {"chl_cd": c["cd"], "chl_nm": c["nm"]}
        for c in BANK_CHANNELS
    ]
    conn.execute(insert(t_chl_mapping), records)
    conn.commit()


def insert_bank_txn_types(conn, t_txn_type_dict: Table) -> None:
    records = [
        {"txn_type_cd": t["cd"], "txn_type_nm": t["nm"]}
        for t in BANK_TXN_TYPES
    ]
    conn.execute(insert(t_txn_type_dict), records)
    conn.commit()


def insert_bank_products(conn, t_prod_info: Table) -> None:
    records = [
        {
            "prod_cd": p["cd"], "prod_nm": p["nm"], "prod_lvl1_nm": p["lvl1"],
            "prod_lvl2_nm": p["lvl2"], "prod_sts_cd": p["sts"],
            "min_pur_amt": p["min"], "exp_yld_rate": p["yld"],
        }
        for p in BANK_PRODUCTS
    ]
    conn.execute(insert(t_prod_info), records)
    conn.commit()


def insert_bank_customers(conn, t_cif_base: Table) -> None:
    """Insert 10 bank customers with varied attributes."""
    names = ["王一", "李二", "张三", "赵四", "钱五", "孙六", "周七", "吴八", "郑九", "冯十"]
    risk_levels = ["01", "02", "03", "04", "05"]
    cust_types = ["01", "02"]  # 个人/企业
    cust_statuses = ["01", "01", "01", "01", "01", "02", "03", "01", "01", "09"]  # 多数正常
    cert_types = ["01", "01", "01", "02", "01", "01", "03", "01", "04", "01"]
    orgs = ["010101", "010102", "010201", "010202", "010101", "0103", "010201", "010102", "010202", "0103"]
    managers = ["M001", "M002", "M003", "M001", "M004", "M002", "M003", "M001", "M004", "M002"]

    records = []
    for i, name in enumerate(names):
        reg_dt = (datetime(2023, 1, 1) + timedelta(days=i * 30)).strftime("%Y-%m-%d")
        records.append({
            "cif_no": f"C{1001 + i:05d}",
            "cust_nm": name,
            "cust_sts_cd": cust_statuses[i],
            "cust_type_cd": cust_types[i % 2],
            "cert_type_cd": cert_types[i],
            "risk_lvl_cd": risk_levels[i % 5],
            "reg_dt": reg_dt,
            "mgr_emp_no": managers[i],
            "org_cd": orgs[i],
            "tenant_id": "t001",
        })
    conn.execute(insert(t_cif_base), records)
    conn.commit()


def insert_bank_accounts(conn, t_acct_main: Table) -> None:
    """Insert ~15 accounts for 10 customers."""
    acct_types = ["01", "02", "03"]  # 活期/定期/理财
    cccys = ["CNY", "USD"]
    acct_statuses = ["01", "01", "01", "01", "02", "03", "01", "01", "01", "09",
                     "01", "01", "02", "01", "01"]

    records = []
    for i in range(15):
        cif_idx = i % 10
        cif_no = f"C{1001 + cif_idx:05d}"
        acct_type = acct_types[i % 3]
        bal = round(random.uniform(1000, 500000), 2)
        frz = round(bal * random.uniform(0, 0.3), 2) if random.random() > 0.7 else 0.0
        avl = round(bal - frz, 2)
        open_dt = (datetime(2023, 3, 1) + timedelta(days=i * 20)).strftime("%Y-%m-%d")
        mat_dt = (datetime(2025, 1, 1) + timedelta(days=i * 45)).strftime("%Y-%m-%d") if acct_type == "02" else None
        records.append({
            "acct_no": f"A{6001 + i:08d}",
            "cif_no": cif_no,
            "acct_type_cd": acct_type,
            "ccyc_cd": cccys[i % 2],
            "acct_sts_cd": acct_statuses[i],
            "acct_bal": bal,
            "avl_bal": avl,
            "frz_amt": frz,
            "open_dt": open_dt,
            "mat_dt": mat_dt,
            "org_cd": f"010{i % 3 + 1}01" if i < 12 else "0103",
            "tenant_id": "t001",
        })
    conn.execute(insert(t_acct_main), records)
    conn.commit()


def insert_bank_transactions(conn, t_txn_dtl: Table) -> None:
    """Insert ~50 transaction records."""
    txn_types = ["1001", "1002", "1003", "1004", "1005"]
    channels = ["01", "02", "03", "04", "05"]
    base_dt = datetime(2024, 6, 1)

    records = []
    for i in range(50):
        acct_idx = i % 15
        cif_idx = acct_idx % 10
        acct_no = f"A{6001 + acct_idx:08d}"
        cif_no = f"C{1001 + cif_idx:05d}"
        txn_type = txn_types[i % 5]
        # dr_cr: 1=借/出, 2=贷/入
        dr_cr = "2" if txn_type in ("1001", "1005") else "1"
        amt = round(random.uniform(100, 50000), 2)
        txn_dt = (base_dt + timedelta(days=i % 30)).strftime("%Y-%m-%d")
        records.append({
            "txn_seq_no": f"TXN{20240601 + i:010d}",
            "acct_no": acct_no,
            "cif_no": cif_no,
            "txn_dt": txn_dt,
            "txn_type_cd": txn_type,
            "txn_amt": amt,
            "dr_cr_flg": dr_cr,
            "chl_cd": channels[i % 5],
            "rvsl_flg": "1" if i % 20 == 0 else "0",
            "tenant_id": "t001",
        })
    conn.execute(insert(t_txn_dtl), records)
    conn.commit()


def insert_bank_agreements(conn, t_cust_prod_agt: Table) -> None:
    """Insert ~12 product agreements."""
    prod_cds = ["P001", "P002", "P004", "P005", "P006"]
    records = []
    for i in range(12):
        cif_idx = i % 8
        acct_idx = i % 12
        prod = BANK_PRODUCTS[i % len(BANK_PRODUCTS)]
        hold = round(random.uniform(5000, 200000), 2)
        sign = round(hold * random.uniform(0.8, 1.2), 2)
        sign_dt = (datetime(2024, 1, 1) + timedelta(days=i * 15)).strftime("%Y-%m-%d")
        due_dt = (datetime(2024, 12, 31) + timedelta(days=i * 10)).strftime("%Y-%m-%d")
        records.append({
            "agt_no": f"AGT{9001 + i:06d}",
            "cif_no": f"C{1001 + cif_idx:05d}",
            "acct_no": f"A{6001 + acct_idx:08d}",
            "prod_cd": prod_cds[i % 5],
            "hold_amt": hold,
            "sign_amt": sign,
            "sign_dt": sign_dt,
            "due_dt": due_dt,
            "agt_sts_cd": "01" if i < 10 else "02",
            "tenant_id": "t001",
        })
    conn.execute(insert(t_cust_prod_agt), records)
    conn.commit()


def create_mock_bank_database(db_url: str = "sqlite:///:memory:"):
    """Create a complete mock bank database with full schema and data.

    Returns:
        (engine, t_cif_base, t_acct_main, t_txn_dtl,
         t_org_hier, t_prod_info, t_cust_prod_agt,
         t_chl_mapping, t_txn_type_dict)
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
        t_cif_base, t_acct_main, t_txn_dtl,
        t_org_hier, t_prod_info, t_cust_prod_agt,
        t_chl_mapping, t_txn_type_dict,
    ) = create_bank_schema(engine)

    with engine.connect() as conn:
        insert_bank_orgs(conn, t_org_hier)
        insert_bank_channels(conn, t_chl_mapping)
        insert_bank_txn_types(conn, t_txn_type_dict)
        insert_bank_products(conn, t_prod_info)
        insert_bank_customers(conn, t_cif_base)
        insert_bank_accounts(conn, t_acct_main)
        insert_bank_transactions(conn, t_txn_dtl)
        insert_bank_agreements(conn, t_cust_prod_agt)

    return (
        engine, t_cif_base, t_acct_main, t_txn_dtl,
        t_org_hier, t_prod_info, t_cust_prod_agt,
        t_chl_mapping, t_txn_type_dict,
    )


# =============================================================================
# Supply Chain / Logistics schema (for supply chain domain e2e tests)
# =============================================================================

SC_REGIONS = [
    {"name": "华东", "code": "HD", "province": "浙江/江苏/上海"},
    {"name": "华南", "code": "HN", "province": "广东/福建"},
    {"name": "华北", "code": "HB", "province": "北京/天津/河北"},
    {"name": "西南", "code": "XN", "province": "四川/重庆"},
    {"name": "东北", "code": "DB", "province": "辽宁/吉林"},
    {"name": "西北", "code": "XB", "province": "陕西/甘肃"},
    {"name": "华中", "code": "HZ", "province": "湖北/湖南"},
]

SC_SUPPLIERS = [
    {"id": 1, "name": "深圳精密电子有限公司", "type": "零部件", "region": "华南", "contact": "李经理", "phone": "13800138001", "bank": "6222021234567890001", "credit": "A", "years": 8},
    {"id": 2, "name": "上海化工原料集团", "type": "原材料", "region": "华东", "contact": "王总监", "phone": "13900139002", "bank": "6222021234567890002", "credit": "A", "years": 12},
    {"id": 3, "name": "北京机械制造股份公司", "type": "零部件", "region": "华北", "contact": "张主管", "phone": "13700137003", "bank": "6222021234567890003", "credit": "B", "years": 5},
    {"id": 4, "name": "成都包装材料厂", "type": "包装", "region": "西南", "contact": "陈经理", "phone": "13600136004", "bank": "6222021234567890004", "credit": "B", "years": 6},
    {"id": 5, "name": "武汉五金制品有限公司", "type": "原材料", "region": "华中", "contact": "赵总监", "phone": "13500135005", "bank": "6222021234567890005", "credit": "C", "years": 3},
    {"id": 6, "name": "杭州电子元器件厂", "type": "零部件", "region": "华东", "contact": "孙经理", "phone": "13400134006", "bank": "6222021234567890006", "credit": "A", "years": 10},
    {"id": 7, "name": "广州塑料制品集团", "type": "包装", "region": "华南", "contact": "周主管", "phone": "13300133007", "bank": "6222021234567890007", "credit": "B", "years": 7},
    {"id": 8, "name": "沈阳金属材料有限公司", "type": "原材料", "region": "东北", "contact": "吴总监", "phone": "13200132008", "bank": "6222021234567890008", "credit": "C", "years": 4},
    {"id": 9, "name": "西安半导体科技公司", "type": "零部件", "region": "西北", "contact": "郑经理", "phone": "13100131009", "bank": "6222021234567890009", "credit": "A", "years": 9},
    {"id": 10, "name": "南京机械设备厂", "type": "零部件", "region": "华东", "contact": "钱主管", "phone": "13000130010", "bank": "6222021234567890010", "credit": "B", "years": 6},
    {"id": 11, "name": "天津化工有限公司", "type": "原材料", "region": "华北", "contact": "冯总监", "phone": "12900129011", "bank": "6222021234567890011", "credit": "A", "years": 11},
    {"id": 12, "name": "重庆包装材料公司", "type": "包装", "region": "西南", "contact": "何经理", "phone": "12800128012", "bank": "6222021234567890012", "credit": "C", "years": 2},
    {"id": 13, "name": "青岛五金工具厂", "type": "原材料", "region": "华东", "contact": "林主管", "phone": "12700127013", "bank": "6222021234567890013", "credit": "B", "years": 5},
    {"id": 14, "name": "东莞电子有限公司", "type": "零部件", "region": "华南", "contact": "黄总监", "phone": "12600126014", "bank": "6222021234567890014", "credit": "A", "years": 8},
    {"id": 15, "name": "长沙塑料制品厂", "type": "包装", "region": "华中", "contact": "徐经理", "phone": "12500125015", "bank": "6222021234567890015", "credit": "B", "years": 4},
    {"id": 16, "name": "大连机械制造公司", "type": "零部件", "region": "东北", "contact": "马主管", "phone": "12400124016", "bank": "6222021234567890016", "credit": "C", "years": 3},
    {"id": 17, "name": "苏州化工材料厂", "type": "原材料", "region": "华东", "contact": "朱总监", "phone": "12300123017", "bank": "6222021234567890017", "credit": "A", "years": 9},
    {"id": 18, "name": "昆明包装材料公司", "type": "包装", "region": "西南", "contact": "胡经理", "phone": "12200122018", "bank": "6222021234567890018", "credit": "B", "years": 5},
    {"id": 19, "name": "合肥电子元器件厂", "type": "零部件", "region": "华中", "contact": "郭主管", "phone": "12100121019", "bank": "6222021234567890019", "credit": "A", "years": 7},
    {"id": 20, "name": "兰州金属材料有限公司", "type": "原材料", "region": "西北", "contact": "高总监", "phone": "12000120020", "bank": "6222021234567890020", "credit": "C", "years": 4},
]

SC_MATERIALS = [
    {"id": 1, "name": "CPU芯片i7-13700K", "category": "电子", "unit": "片", "spec": "16核24线程"},
    {"id": 2, "name": "DDR5内存条32GB", "category": "电子", "unit": "条", "spec": "5600MHz"},
    {"id": 3, "name": "固态硬盘1TB", "category": "电子", "unit": "个", "spec": "NVMe PCIe4.0"},
    {"id": 4, "name": "液晶显示屏15.6寸", "category": "电子", "unit": "片", "spec": "IPS 1920x1080"},
    {"id": 5, "name": "电源适配器120W", "category": "电子", "unit": "个", "spec": "Type-C PD"},
    {"id": 6, "name": "铝合金型材6063", "category": "机械", "unit": "kg", "spec": "T5状态"},
    {"id": 7, "name": "不锈钢螺丝M6", "category": "机械", "unit": "千个", "spec": "304不锈钢"},
    {"id": 8, "name": "轴承6204", "category": "机械", "unit": "个", "spec": "深沟球轴承"},
    {"id": 9, "name": "齿轮模组", "category": "机械", "unit": "套", "spec": "减速比1:10"},
    {"id": 10, "name": "液压油ISO VG46", "category": "化工", "unit": "L", "spec": "抗磨液压油"},
    {"id": 11, "name": "环氧树脂AB胶", "category": "化工", "unit": "kg", "spec": "双组分"},
    {"id": 12, "name": "防锈润滑剂", "category": "化工", "unit": "瓶", "spec": "500ml喷雾"},
    {"id": 13, "name": "纸箱五层瓦楞", "category": "包装", "unit": "个", "spec": "400x300x200mm"},
    {"id": 14, "name": "PE气泡膜", "category": "包装", "unit": "卷", "spec": "宽50cm"},
    {"id": 15, "name": "防静电袋", "category": "包装", "unit": "百个", "spec": "150x200mm"},
    {"id": 16, "name": "铜导线BV2.5", "category": "五金", "unit": "米", "spec": "国标纯铜"},
    {"id": 17, "name": "PVC线槽", "category": "五金", "unit": "米", "spec": "宽40x高25"},
    {"id": 18, "name": "接线端子", "category": "五金", "unit": "百个", "spec": "UK2.5B"},
    {"id": 19, "name": "散热片铝型材", "category": "电子", "unit": "片", "spec": "100x50x10mm"},
    {"id": 20, "name": "连接器Type-C", "category": "电子", "unit": "百个", "spec": "USB3.2"},
    {"id": 21, "name": "橡胶密封圈", "category": "机械", "unit": "百个", "spec": "NBR材质"},
    {"id": 22, "name": "润滑脂", "category": "化工", "unit": "kg", "spec": "锂基脂NLGI2"},
    {"id": 23, "name": "木托盘", "category": "包装", "unit": "个", "spec": "1200x1000mm"},
    {"id": 24, "name": "镀锌钢板", "category": "五金", "unit": "kg", "spec": "Q235B"},
    {"id": 25, "name": "LED灯珠", "category": "电子", "unit": "千个", "spec": "SMD2835"},
    {"id": 26, "name": "继电器24V", "category": "电子", "unit": "个", "spec": "5A/250VAC"},
    {"id": 27, "name": "弹簧", "category": "机械", "unit": "百个", "spec": "压缩弹簧"},
    {"id": 28, "name": "清洗剂", "category": "化工", "unit": "L", "spec": "工业除油剂"},
    {"id": 29, "name": "缠绕膜", "category": "包装", "unit": "卷", "spec": "宽50cmx长300m"},
    {"id": 30, "name": "螺栓M8", "category": "五金", "unit": "千个", "spec": "8.8级镀锌"},
    {"id": 31, "name": "电容100uF", "category": "电子", "unit": "百个", "spec": "铝电解电容"},
    {"id": 32, "name": "电阻10K", "category": "电子", "unit": "千个", "spec": "1%精度"},
    {"id": 33, "name": "齿轮油", "category": "化工", "unit": "L", "spec": "GL-5 80W-90"},
    {"id": 34, "name": "泡沫板", "category": "包装", "unit": "张", "spec": "1000x1000x50mm"},
    {"id": 35, "name": "角钢", "category": "五金", "unit": "米", "spec": "40x40x4mm"},
    {"id": 36, "name": "PCB电路板", "category": "电子", "unit": "片", "spec": "FR4双层"},
    {"id": 37, "name": "电机", "category": "机械", "unit": "台", "spec": "AC220V 1.5kW"},
    {"id": 38, "name": "导热硅脂", "category": "化工", "unit": "g", "spec": "高导热系数"},
    {"id": 39, "name": "标签纸", "category": "包装", "unit": "卷", "spec": "热敏纸80x60"},
    {"id": 40, "name": "焊锡丝", "category": "五金", "unit": "kg", "spec": "Sn63Pb37"},
    {"id": 41, "name": "晶振", "category": "电子", "unit": "百个", "spec": "8MHz"},
    {"id": 42, "name": "气缸", "category": "机械", "unit": "个", "spec": "SC63x50"},
    {"id": 43, "name": "脱模剂", "category": "化工", "unit": "L", "spec": "水性"},
    {"id": 44, "name": "真空袋", "category": "包装", "unit": "百个", "spec": "PE材质"},
    {"id": 45, "name": "铝箔胶带", "category": "五金", "unit": "卷", "spec": "宽50mm"},
    {"id": 46, "name": "变压器", "category": "电子", "unit": "个", "spec": "220V/12V"},
    {"id": 47, "name": "链条", "category": "机械", "unit": "米", "spec": "08B-1"},
    {"id": 48, "name": "稀释剂", "category": "化工", "unit": "L", "spec": "通用型"},
    {"id": 49, "name": "打包带", "category": "包装", "unit": "卷", "spec": "PP带宽16mm"},
    {"id": 50, "name": "钢丝", "category": "五金", "unit": "kg", "spec": "304不锈钢"},
]

SC_WAREHOUSES = [
    {"id": 1, "name": "上海中心仓", "type": "中心仓", "region": "华东", "region_code": "HD", "capacity": 100000},
    {"id": 2, "name": "广州中心仓", "type": "中心仓", "region": "华南", "region_code": "HN", "capacity": 90000},
    {"id": 3, "name": "北京中心仓", "type": "中心仓", "region": "华北", "region_code": "HB", "capacity": 80000},
    {"id": 4, "name": "成都中心仓", "type": "中心仓", "region": "西南", "region_code": "XN", "capacity": 70000},
    {"id": 5, "name": "武汉中心仓", "type": "中心仓", "region": "华中", "region_code": "HZ", "capacity": 60000},
    {"id": 6, "name": "沈阳中心仓", "type": "中心仓", "region": "东北", "region_code": "DB", "capacity": 50000},
    {"id": 7, "name": "西安中心仓", "type": "中心仓", "region": "西北", "region_code": "XB", "capacity": 45000},
    {"id": 8, "name": "杭州区域仓", "type": "区域仓", "region": "华东", "region_code": "HD", "capacity": 30000},
    {"id": 9, "name": "深圳区域仓", "type": "区域仓", "region": "华南", "region_code": "HN", "capacity": 25000},
    {"id": 10, "name": "天津区域仓", "type": "区域仓", "region": "华北", "region_code": "HB", "capacity": 20000},
    {"id": 11, "name": "重庆区域仓", "type": "区域仓", "region": "西南", "region_code": "XN", "capacity": 18000},
    {"id": 12, "name": "南京前置仓", "type": "前置仓", "region": "华东", "region_code": "HD", "capacity": 8000},
    {"id": 13, "name": "东莞前置仓", "type": "前置仓", "region": "华南", "region_code": "HN", "capacity": 6000},
    {"id": 14, "name": "青岛前置仓", "type": "前置仓", "region": "华东", "region_code": "HD", "capacity": 5000},
    {"id": 15, "name": "郑州前置仓", "type": "前置仓", "region": "华中", "region_code": "HZ", "capacity": 4000},
]

SC_CARRIERS = [
    {"id": 1, "name": "顺丰速运", "mode": "公路", "region": "华东"},
    {"id": 2, "name": "中通快递", "mode": "公路", "region": "华南"},
    {"id": 3, "name": "德邦物流", "mode": "公路", "region": "华北"},
    {"id": 4, "name": "中国邮政", "mode": "公路", "region": "华中"},
    {"id": 5, "name": "京东物流", "mode": "公路", "region": "华东"},
    {"id": 6, "name": "中铁快运", "mode": "铁路", "region": "华北"},
    {"id": 7, "name": "南方航空货运", "mode": "航空", "region": "华南"},
    {"id": 8, "name": "中远海运", "mode": "海运", "region": "华东"},
    {"id": 9, "name": "圆通速递", "mode": "公路", "region": "西南"},
    {"id": 10, "name": "韵达快递", "mode": "公路", "region": "华东"},
]

SC_ORDER_STATUS = ["待确认", "已发货", "在途", "已入库", "已取消"]
SC_DELIVERY_STATUS = ["待发货", "运输中", "已签收", "异常"]


def create_supply_chain_schema(engine) -> tuple[Table, ...]:
    """Create supply chain domain schema with 9 tables."""
    metadata = MetaData()

    supplier_dim = Table(
        "supplier_dim", metadata,
        Column("supplier_id", Integer, primary_key=True),
        Column("supplier_name", String(100)),
        Column("supplier_type", String(50)),
        Column("region", String(20)),
        Column("contact_name", String(50)),
        Column("contact_phone", String(20)),
        Column("bank_account", String(30)),
        Column("credit_rating", String(10)),
        Column("cooperation_years", Integer),
    )

    material_dim = Table(
        "material_dim", metadata,
        Column("material_id", Integer, primary_key=True),
        Column("material_name", String(100)),
        Column("material_category", String(50)),
        Column("unit", String(20)),
        Column("specification", String(100)),
    )

    warehouse_dim = Table(
        "warehouse_dim", metadata,
        Column("warehouse_id", Integer, primary_key=True),
        Column("warehouse_name", String(100)),
        Column("warehouse_type", String(50)),
        Column("region", String(20)),
        Column("region_code", String(10)),
        Column("capacity", Integer),
    )

    carrier_dim = Table(
        "carrier_dim", metadata,
        Column("carrier_id", Integer, primary_key=True),
        Column("carrier_name", String(50)),
        Column("transport_mode", String(20)),
        Column("region", String(20)),
    )

    region_dim = Table(
        "region_dim", metadata,
        Column("region_code", String(10), primary_key=True),
        Column("region_name", String(20)),
        Column("province", String(100)),
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
    )

    purchase_fact = Table(
        "purchase_fact", metadata,
        Column("purchase_id", Integer, primary_key=True),
        Column("purchase_no", String(50)),
        Column("supplier_id", Integer),
        Column("material_id", Integer),
        Column("warehouse_id", Integer),
        Column("region_code", String(10)),
        Column("quantity", Integer),
        Column("unit_price", Float),
        Column("order_amount", Float),
        Column("received_qty", Integer),
        Column("purchase_date", String(20)),
        Column("expected_date", String(20)),
        Column("actual_date", String(20)),
        Column("order_status", String(20)),
        Column("on_time", Integer),
        Column("lead_time_days", Integer),
        Column("date_id", Integer),
        Column("tenant_id", String(20)),
    )

    inventory_fact = Table(
        "inventory_fact", metadata,
        Column("id", Integer, primary_key=True),
        Column("material_id", Integer),
        Column("material_name", String(100)),
        Column("material_category", String(50)),
        Column("warehouse_id", Integer),
        Column("warehouse_name", String(100)),
        Column("warehouse_type", String(50)),
        Column("region", String(20)),
        Column("region_code", String(10)),
        Column("stock_quantity", Integer),
        Column("available_quantity", Integer),
        Column("reserved_quantity", Integer),
        Column("avg_daily_usage", Integer),
        Column("days_of_supply", Integer),
        Column("stock_amount", Float),
        Column("date_id", Integer),
        Column("tenant_id", String(20)),
    )

    shipment_fact = Table(
        "shipment_fact", metadata,
        Column("shipment_id", Integer, primary_key=True),
        Column("purchase_id", Integer),
        Column("carrier_id", Integer),
        Column("material_id", Integer),
        Column("from_warehouse_id", Integer),
        Column("to_warehouse_id", Integer),
        Column("from_warehouse_name", String(100)),
        Column("to_warehouse_name", String(100)),
        Column("from_region_code", String(10)),
        Column("to_region_code", String(10)),
        Column("region_code", String(10)),
        Column("ship_quantity", Integer),
        Column("shipping_cost", Float),
        Column("ship_date", String(20)),
        Column("delivery_date", String(20)),
        Column("delivery_status", String(20)),
        Column("transport_mode", String(20)),
        Column("date_id", Integer),
        Column("tenant_id", String(20)),
    )

    metadata.create_all(engine)
    return (
        supplier_dim, material_dim, warehouse_dim,
        carrier_dim, region_dim, date_dim,
        purchase_fact, inventory_fact, shipment_fact,
    )


def insert_sc_regions(conn, region_dim: Table) -> None:
    records = [
        {"region_code": r["code"], "region_name": r["name"], "province": r["province"]}
        for r in SC_REGIONS
    ]
    conn.execute(insert(region_dim), records)
    conn.commit()


def insert_sc_dates(conn, date_dim: Table) -> None:
    base = datetime(2024, 4, 1)
    records = []
    for i in range(90):  # 2024-04-01 to 2024-06-29
        d = base + timedelta(days=i)
        dow = d.isoweekday()
        records.append({
            "date_id": int(d.strftime("%Y%m%d")),
            "full_date": d.strftime("%Y-%m-%d"),
            "year": 2024,
            "month": d.month,
            "quarter": f"Q{(d.month - 1) // 3 + 1}",
            "day_of_week": dow,
            "is_weekend": 1 if dow in (6, 7) else 0,
            "is_holiday": 1 if d.strftime("%Y-%m-%d") in ("2024-05-01", "2024-05-02", "2024-05-03", "2024-06-10") else 0,
        })
    conn.execute(insert(date_dim), records)
    conn.commit()


def insert_sc_suppliers(conn, supplier_dim: Table) -> None:
    records = [
        {
            "supplier_id": s["id"],
            "supplier_name": s["name"],
            "supplier_type": s["type"],
            "region": s["region"],
            "contact_name": s["contact"],
            "contact_phone": s["phone"],
            "bank_account": s["bank"],
            "credit_rating": s["credit"],
            "cooperation_years": s["years"],
        }
        for s in SC_SUPPLIERS
    ]
    conn.execute(insert(supplier_dim), records)
    conn.commit()


def insert_sc_materials(conn, material_dim: Table) -> None:
    records = [
        {
            "material_id": m["id"],
            "material_name": m["name"],
            "material_category": m["category"],
            "unit": m["unit"],
            "specification": m["spec"],
        }
        for m in SC_MATERIALS
    ]
    conn.execute(insert(material_dim), records)
    conn.commit()


def insert_sc_warehouses(conn, warehouse_dim: Table) -> None:
    records = [
        {
            "warehouse_id": w["id"],
            "warehouse_name": w["name"],
            "warehouse_type": w["type"],
            "region": w["region"],
            "region_code": w["region_code"],
            "capacity": w["capacity"],
        }
        for w in SC_WAREHOUSES
    ]
    conn.execute(insert(warehouse_dim), records)
    conn.commit()


def insert_sc_carriers(conn, carrier_dim: Table) -> None:
    records = [
        {
            "carrier_id": c["id"],
            "carrier_name": c["name"],
            "transport_mode": c["mode"],
            "region": c["region"],
        }
        for c in SC_CARRIERS
    ]
    conn.execute(insert(carrier_dim), records)
    conn.commit()


def insert_sc_purchase(conn, purchase_fact: Table, num_records: int = 200) -> None:
    """Insert purchase order fact data."""
    records = []
    base_date = datetime(2024, 4, 1)

    for i in range(num_records):
        supplier = random.choice(SC_SUPPLIERS)
        material = random.choice(SC_MATERIALS)
        warehouse = random.choice(SC_WAREHOUSES)

        # 关联性：某些供应商偏好某些物料类别
        if supplier["type"] == "电子" and material["category"] != "电子":
            material = random.choice([m for m in SC_MATERIALS if m["category"] == "电子"])
        elif supplier["type"] == "机械" and material["category"] != "机械":
            material = random.choice([m for m in SC_MATERIALS if m["category"] == "机械"])

        quantity = random.randint(10, 1000)
        unit_price = round(random.uniform(1.0, 5000.0), 2)
        order_amount = round(quantity * unit_price, 2)

        day_offset = random.randint(0, 89)
        purchase_date = base_date + timedelta(days=day_offset)
        expected_days = random.randint(3, 15)
        expected_date = purchase_date + timedelta(days=expected_days)
        actual_delay = random.randint(-2, 5)  # -2 = early, 5 = late
        actual_date = expected_date + timedelta(days=actual_delay)

        on_time = 1 if actual_delay <= 0 else 0
        lead_time = (actual_date - purchase_date).days
        order_status = random.choice(SC_ORDER_STATUS)
        received_qty = quantity if order_status == "已入库" else random.randint(0, quantity)

        tenant_id = "t001" if random.random() < 0.7 else "t002"

        records.append({
            "purchase_id": i + 1,
            "purchase_no": f"PO{20240401 + i:010d}",
            "supplier_id": supplier["id"],
            "material_id": material["id"],
            "warehouse_id": warehouse["id"],
            "region_code": warehouse["region_code"],
            "quantity": quantity,
            "unit_price": unit_price,
            "order_amount": order_amount,
            "received_qty": received_qty,
            "purchase_date": purchase_date.strftime("%Y-%m-%d"),
            "expected_date": expected_date.strftime("%Y-%m-%d"),
            "actual_date": actual_date.strftime("%Y-%m-%d"),
            "order_status": order_status,
            "on_time": on_time,
            "lead_time_days": lead_time,
            "date_id": int(purchase_date.strftime("%Y%m%d")),
            "tenant_id": tenant_id,
        })

    conn.execute(insert(purchase_fact), records)
    conn.commit()


def insert_sc_inventory(conn, inventory_fact: Table) -> None:
    """Insert inventory fact data: 50 materials x 15 warehouses = 750 rows."""
    records = []
    date_id = 20240630

    for w_idx, wh in enumerate(SC_WAREHOUSES):
        for m_idx, mat in enumerate(SC_MATERIALS):
            stock = random.randint(50, 5000)
            reserved = random.randint(0, min(200, stock))
            available = stock - reserved
            avg_daily = random.randint(1, 50)
            dos = stock // avg_daily if avg_daily > 0 else 0
            unit_price = round(random.uniform(1.0, 5000.0), 2)
            stock_amount = round(stock * unit_price, 2)

            records.append({
                "id": w_idx * len(SC_MATERIALS) + m_idx + 1,
                "material_id": mat["id"],
                "material_name": mat["name"],
                "material_category": mat["category"],
                "warehouse_id": wh["id"],
                "warehouse_name": wh["name"],
                "warehouse_type": wh["type"],
                "region": wh["region"],
                "region_code": wh["region_code"],
                "stock_quantity": stock,
                "available_quantity": available,
                "reserved_quantity": reserved,
                "avg_daily_usage": avg_daily,
                "days_of_supply": dos,
                "stock_amount": stock_amount,
                "date_id": date_id,
                "tenant_id": "t001" if random.random() < 0.7 else "t002",
            })

    conn.execute(insert(inventory_fact), records)
    conn.commit()


def insert_sc_shipment(conn, shipment_fact: Table, num_records: int = 180) -> None:
    """Insert shipment fact data."""
    records = []
    base_date = datetime(2024, 4, 1)

    for i in range(num_records):
        purchase_id = (i % 200) + 1
        carrier = random.choice(SC_CARRIERS)
        material = random.choice(SC_MATERIALS)

        from_wh = random.choice(SC_WAREHOUSES)
        to_wh = random.choice([w for w in SC_WAREHOUSES if w["id"] != from_wh["id"]])

        ship_qty = random.randint(10, 500)
        shipping_cost = round(ship_qty * random.uniform(0.5, 5.0), 2)

        day_offset = random.randint(0, 89)
        ship_date = base_date + timedelta(days=day_offset)
        transit_days = random.randint(1, 10)
        delivery_date = ship_date + timedelta(days=transit_days)

        delivery_status = random.choice(SC_DELIVERY_STATUS)
        tenant_id = "t001" if random.random() < 0.7 else "t002"

        records.append({
            "shipment_id": i + 1,
            "purchase_id": purchase_id,
            "carrier_id": carrier["id"],
            "material_id": material["id"],
            "from_warehouse_id": from_wh["id"],
            "to_warehouse_id": to_wh["id"],
            "from_warehouse_name": from_wh["name"],
            "to_warehouse_name": to_wh["name"],
            "from_region_code": from_wh["region_code"],
            "to_region_code": to_wh["region_code"],
            "region_code": from_wh["region_code"],
            "ship_quantity": ship_qty,
            "shipping_cost": shipping_cost,
            "ship_date": ship_date.strftime("%Y-%m-%d"),
            "delivery_date": delivery_date.strftime("%Y-%m-%d"),
            "delivery_status": delivery_status,
            "transport_mode": carrier["mode"],
            "date_id": int(ship_date.strftime("%Y%m%d")),
            "tenant_id": tenant_id,
        })

    conn.execute(insert(shipment_fact), records)
    conn.commit()


def create_mock_supply_chain_database(db_url: str = "sqlite:///:memory:"):
    """Create a complete supply chain mock database with full schema and data.

    Returns:
        (engine, supplier_dim_sc, material_dim, warehouse_dim_sc,
         carrier_dim, region_dim_sc, date_dim_sc,
         purchase_fact, inventory_fact_sc, shipment_fact)
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
        supplier_dim, material_dim, warehouse_dim,
        carrier_dim, region_dim, date_dim,
        purchase_fact, inventory_fact, shipment_fact,
    ) = create_supply_chain_schema(engine)

    with engine.connect() as conn:
        insert_sc_regions(conn, region_dim)
        insert_sc_dates(conn, date_dim)
        insert_sc_suppliers(conn, supplier_dim)
        insert_sc_materials(conn, material_dim)
        insert_sc_warehouses(conn, warehouse_dim)
        insert_sc_carriers(conn, carrier_dim)
        insert_sc_purchase(conn, purchase_fact, num_records=200)
        insert_sc_inventory(conn, inventory_fact)
        insert_sc_shipment(conn, shipment_fact, num_records=180)

    return (
        engine, supplier_dim, material_dim, warehouse_dim,
        carrier_dim, region_dim, date_dim,
        purchase_fact, inventory_fact, shipment_fact,
    )


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
