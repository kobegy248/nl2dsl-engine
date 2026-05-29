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
