"""银行零售业务测试数据生成器

生成包含复杂表关系、晦涩字段命名、码值映射的银行核心系统数据，
用于测试 NL2DSL 语义层对复杂业务语义的理解和映射能力。

表结构（8张表）:
- t_cif_base:       客户主表（状态码、证件类型码、风险等级）
- t_acct_main:      账户主表（账户类型码、币种码、余额/冻结/可用分离）
- t_txn_dtl:        交易流水（交易类型码、渠道码、借贷标志、冲正标志）
- t_prod_info:      产品信息（层级类目树）
- t_cust_prod_agt:  客户产品合约（多对多桥接）
- t_org_hier:       组织机构树（自引用父子关系）
- t_chl_mapping:    渠道映射字典
- t_txn_type_dict:  交易类型字典

字段命名规则: 历史遗留缩写 + 下划线分隔，如 acct_bal, txn_amt, dr_cr_flg
"""

from __future__ import annotations

import argparse
import os
import random
import string
from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    Date,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    text,
)

random.seed(42)

# ── 码值字典 ──────────────────────────────────────────────

CERT_TYPE_MAP = {"01": "身份证", "02": "护照", "03": "军官证", "04": "港澳通行证"}
CUST_STS_MAP = {"01": "正常", "02": "冻结", "03": "睡眠", "09": "销户"}
CUST_TYPE_MAP = {"01": "个人", "02": "企业"}
RISK_LVL_MAP = {"01": "保守型", "02": "稳健型", "03": "平衡型", "04": "进取型", "05": "激进型"}

ACCT_TYPE_MAP = {"01": "活期存款", "02": "定期存款", "03": "理财产品", "04": "信用卡"}
CCYC_MAP = {"CNY": "人民币", "USD": "美元", "EUR": "欧元", "HKD": "港币"}
ACCT_STS_MAP = {"01": "正常", "02": "冻结", "03": "止付", "09": "销户"}

TXN_TYPE_MAP = {
    "1001": ("存款", "资金流入"),
    "1002": ("取款", "资金流出"),
    "1003": ("转账", "资金划转"),
    "1004": ("消费", "资金流出"),
    "1005": ("理财购买", "投资"),
    "1006": ("理财赎回", "投资回款"),
    "1007": ("利息入账", "收益"),
    "1008": ("手续费", "费用"),
    "1009": ("贷款发放", "资金流入"),
    "1010": ("贷款还款", "资金流出"),
}

CHL_MAP = {
    "01": ("柜面", "线下"),
    "02": ("手机银行", "线上"),
    "03": ("网上银行", "线上"),
    "04": ("ATM", "自助"),
    "05": ("POS", "线下"),
    "06": ("第三方支付", "线上"),
    "07": ("快捷支付", "线上"),
}

PROD_LVL1_MAP = {
    "10": "存款类",
    "20": "理财类",
    "30": "基金类",
    "40": "保险类",
}

PROD_STS_MAP = {"01": "在售", "02": "停售", "03": "售罄"}
AGT_STS_MAP = {"01": "有效", "02": "到期", "03": "提前终止"}

ORG_DATA = [
    # (org_cd, org_nm, org_lvl, sup_org_cd, org_addr)
    ("000001", "华夏银行总行", 1, None, "北京市西城区金融大街1号"),
    ("110000", "北京分行", 2, "000001", "北京市朝阳区建国路88号"),
    ("110101", "建国门支行", 3, "110000", "北京市朝阳区建国门外大街甲6号"),
    ("110102", "中关村支行", 3, "110000", "北京市海淀区中关村大街1号"),
    ("110103", "金融街支行", 3, "110000", "北京市西城区金融大街7号"),
    ("310000", "上海分行", 2, "000001", "上海市浦东新区陆家嘴环路1000号"),
    ("310101", "陆家嘴支行", 3, "310000", "上海市浦东新区陆家嘴东路166号"),
    ("310102", "张江支行", 3, "310000", "上海市浦东新区张江高科技园区科苑路88号"),
    ("310103", "虹桥支行", 3, "310000", "上海市闵行区申长路988号"),
    ("440000", "深圳分行", 2, "000001", "深圳市福田区深南大道1003号"),
    ("440101", "福田支行", 3, "440000", "深圳市福田区福华三路168号"),
    ("440102", "南山支行", 3, "440000", "深圳市南山区粤海街道科兴科学园"),
    ("440103", "罗湖支行", 3, "440000", "深圳市罗湖区深南东路5002号"),
]

FIRST_NAMES = ["伟", "芳", "娜", "敏", "静", "丽", "强", "磊", "军", "洋",
               "勇", "艳", "杰", "娟", "涛", "明", "超", "秀", "霞", "平",
               "刚", "桂英", "秀英", "华", "建国", "建军", "国华", "建平"]
LAST_NAMES = ["王", "李", "张", "刘", "陈", "杨", "黄", "赵", "吴", "周",
              "徐", "孙", "马", "朱", "胡", "郭", "何", "高", "林", "罗"]


def _gen_name() -> str:
    return random.choice(LAST_NAMES) + random.choice(FIRST_NAMES)


def _gen_mobile() -> str:
    prefixes = ["138", "139", "136", "137", "135", "150", "151", "152", "157", "158", "159", "182", "183", "187", "188"]
    return random.choice(prefixes) + "".join(random.choices(string.digits, k=8))


def _gen_cert_no(cert_type: str) -> str:
    if cert_type == "01":  # 身份证
        areas = ["110101", "310101", "440304", "500101", "510107", "330106", "320106", "420106"]
        area = random.choice(areas)
        year = random.randint(1960, 2005)
        month = random.randint(1, 12)
        day = random.randint(1, 28)
        seq = "".join(random.choices(string.digits, k=3))
        base = f"{area}{year:04d}{month:02d}{day:02d}{seq}"
        # 简化的校验位（非真实）
        return base + str(random.randint(0, 9))
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=12))


def _random_date(start: datetime, end: datetime) -> datetime:
    delta = end - start
    return start + timedelta(days=random.randint(0, delta.days))


def create_schema(engine) -> dict[str, Table]:
    """创建所有表，返回表名到 Table 对象的映射。"""
    metadata = MetaData()

    t_cif_base = Table(
        "t_cif_base", metadata,
        Column("cif_no", String(20), primary_key=True),
        Column("cust_nm", String(50)),
        Column("cert_type_cd", String(2)),
        Column("cert_no", String(30)),
        Column("cust_sts_cd", String(2)),
        Column("cust_type_cd", String(2)),
        Column("mobile_no", String(15)),
        Column("reg_dt", Date),
        Column("risk_lvl_cd", String(2)),
        Column("mgr_emp_no", String(10)),
    )

    t_acct_main = Table(
        "t_acct_main", metadata,
        Column("acct_no", String(25), primary_key=True),
        Column("cif_no", String(20), ForeignKey("t_cif_base.cif_no")),
        Column("acct_type_cd", String(2)),
        Column("ccyc_cd", String(3)),
        Column("acct_sts_cd", String(2)),
        Column("acct_bal", Float),
        Column("frz_amt", Float),
        Column("avl_bal", Float),
        Column("open_dt", Date),
        Column("mat_dt", Date, nullable=True),
        Column("int_rate", Float, nullable=True),
    )

    t_txn_dtl = Table(
        "t_txn_dtl", metadata,
        Column("txn_seq_no", String(32), primary_key=True),
        Column("acct_no", String(25), ForeignKey("t_acct_main.acct_no")),
        Column("txn_dt", Date),
        Column("txn_tm", String(6)),
        Column("txn_type_cd", String(4)),
        Column("dr_cr_flg", String(1)),  # 1=借(出), 2=贷(入)
        Column("txn_amt", Float),
        Column("txn_ccyc_cd", String(3)),
        Column("acct_bal_af", Float),
        Column("opp_acct_no", String(25), nullable=True),
        Column("opp_acct_nm", String(50), nullable=True),
        Column("chl_cd", String(2)),
        Column("txn_rmk", String(200), nullable=True),
        Column("rvsl_flg", String(1)),  # 0=正常, 1=已冲正
        Column("rvsl_rel_no", String(32), nullable=True),
    )

    t_prod_info = Table(
        "t_prod_info", metadata,
        Column("prod_cd", String(10), primary_key=True),
        Column("prod_nm", String(100)),
        Column("prod_lvl1_cd", String(2)),
        Column("prod_lvl1_nm", String(50)),
        Column("prod_lvl2_cd", String(4)),
        Column("prod_lvl2_nm", String(50)),
        Column("prod_sts_cd", String(2)),
        Column("min_pur_amt", Float),
        Column("exp_yld_rate", Float),
        Column("risk_lvl_cd", String(2)),
    )

    t_cust_prod_agt = Table(
        "t_cust_prod_agt", metadata,
        Column("agt_no", String(20), primary_key=True),
        Column("cif_no", String(20), ForeignKey("t_cif_base.cif_no")),
        Column("prod_cd", String(10), ForeignKey("t_prod_info.prod_cd")),
        Column("acct_no", String(25), ForeignKey("t_acct_main.acct_no")),
        Column("agt_sts_cd", String(2)),
        Column("sign_dt", Date),
        Column("due_dt", Date),
        Column("hold_amt", Float),
        Column("sign_amt", Float),
    )

    t_org_hier = Table(
        "t_org_hier", metadata,
        Column("org_cd", String(10), primary_key=True),
        Column("org_nm", String(100)),
        Column("org_lvl", Integer),
        Column("sup_org_cd", String(10), nullable=True),
        Column("org_addr", String(200)),
    )

    t_chl_mapping = Table(
        "t_chl_mapping", metadata,
        Column("chl_cd", String(2), primary_key=True),
        Column("chl_nm", String(50)),
        Column("chl_type", String(20)),
    )

    t_txn_type_dict = Table(
        "t_txn_type_dict", metadata,
        Column("txn_type_cd", String(4), primary_key=True),
        Column("txn_type_nm", String(50)),
        Column("txn_type_cls", String(20)),
    )

    metadata.create_all(engine)
    return {
        "t_cif_base": t_cif_base,
        "t_acct_main": t_acct_main,
        "t_txn_dtl": t_txn_dtl,
        "t_prod_info": t_prod_info,
        "t_cust_prod_agt": t_cust_prod_agt,
        "t_org_hier": t_org_hier,
        "t_chl_mapping": t_chl_mapping,
        "t_txn_type_dict": t_txn_type_dict,
    }


def insert_dicts(conn, tables: dict[str, Table]) -> None:
    """插入码值字典表（渠道、交易类型）。"""
    chl_records = [
        {"chl_cd": k, "chl_nm": v[0], "chl_type": v[1]}
        for k, v in CHL_MAP.items()
    ]
    conn.execute(insert(tables["t_chl_mapping"]), chl_records)

    txn_type_records = [
        {"txn_type_cd": k, "txn_type_nm": v[0], "txn_type_cls": v[1]}
        for k, v in TXN_TYPE_MAP.items()
    ]
    conn.execute(insert(tables["t_txn_type_dict"]), txn_type_records)
    conn.commit()


def insert_org(conn, tables: dict[str, Table]) -> None:
    """插入组织机构树。"""
    records = [
        {
            "org_cd": cd,
            "org_nm": nm,
            "org_lvl": lvl,
            "sup_org_cd": sup,
            "org_addr": addr,
        }
        for cd, nm, lvl, sup, addr in ORG_DATA
    ]
    conn.execute(insert(tables["t_org_hier"]), records)
    conn.commit()


def insert_products(conn, tables: dict[str, Table]) -> list[dict]:
    """插入产品信息，返回产品列表。"""
    products = []
    prod_id = 1

    lvl2_data = [
        # (lvl1_cd, lvl2_cd, lvl2_nm, count, base_name, min_amt, rate_range, risk)
        ("10", "1001", "活期存款", 2, "活期", 0, (0.002, 0.0035), "01"),
        ("10", "1002", "定期存款", 4, "定期", 5000, (0.015, 0.025), "01"),
        ("10", "1003", "大额存单", 3, "大额存单", 200000, (0.02, 0.03), "01"),
        ("20", "2001", "固收理财", 4, "稳健理财", 10000, (0.03, 0.045), "02"),
        ("20", "2002", "混合理财", 3, "混合优选", 50000, (0.04, 0.065), "03"),
        ("20", "2003", "权益理财", 2, "权益精选", 100000, (0.05, 0.08), "04"),
        ("30", "3001", "货币基金", 2, "货币基金", 1, (0.015, 0.025), "01"),
        ("30", "3002", "债券基金", 3, "债券增强", 1000, (0.025, 0.04), "02"),
        ("30", "3003", "股票基金", 2, "股票精选", 1000, (0.06, 0.12), "04"),
        ("40", "4001", "寿险产品", 2, "终身寿险", 5000, (0.025, 0.035), "02"),
        ("40", "4002", "年金产品", 2, "养老年金", 10000, (0.03, 0.04), "03"),
    ]

    for lvl1_cd, lvl2_cd, lvl2_nm, count, base_name, min_amt, rate_range, risk in lvl2_data:
        for i in range(count):
            prod_cd = f"P{prod_id:05d}"
            prod_nm = f"{base_name}{i+1}号"
            rate = round(random.uniform(*rate_range), 4)
            sts = random.choices(
                list(PROD_STS_MAP.keys()),
                weights=[0.6, 0.2, 0.2],
            )[0]
            products.append({
                "prod_cd": prod_cd,
                "prod_nm": prod_nm,
                "prod_lvl1_cd": lvl1_cd,
                "prod_lvl1_nm": PROD_LVL1_MAP[lvl1_cd],
                "prod_lvl2_cd": lvl2_cd,
                "prod_lvl2_nm": lvl2_nm,
                "prod_sts_cd": sts,
                "min_pur_amt": float(min_amt),
                "exp_yld_rate": rate,
                "risk_lvl_cd": risk,
            })
            prod_id += 1

    conn.execute(insert(tables["t_prod_info"]), products)
    conn.commit()
    return products


def insert_customers(
    conn, tables: dict[str, Table], num_customers: int = 100,
) -> list[dict]:
    """插入客户主表，返回客户列表。"""
    customers = []
    branch_orgs = [o for o in ORG_DATA if o[2] == 3]  # 只取支行
    mgr_prefix = "E"

    for i in range(num_customers):
        cif_no = f"C{100000 + i:08d}"
        cert_type = random.choices(
            list(CERT_TYPE_MAP.keys()),
            weights=[0.9, 0.04, 0.03, 0.03],
        )[0]
        cust_sts = random.choices(
            list(CUST_STS_MAP.keys()),
            weights=[0.85, 0.05, 0.05, 0.05],
        )[0]
        cust_type = random.choices(
            list(CUST_TYPE_MAP.keys()),
            weights=[0.95, 0.05],
        )[0]
        risk = random.choices(
            list(RISK_LVL_MAP.keys()),
            weights=[0.15, 0.30, 0.30, 0.15, 0.10],
        )[0]
        org = random.choice(branch_orgs)
        mgr_no = f"{mgr_prefix}{org[0][:2]}{random.randint(100, 999):03d}"

        reg_dt = _random_date(datetime(2018, 1, 1), datetime(2024, 6, 30))

        customers.append({
            "cif_no": cif_no,
            "cust_nm": _gen_name(),
            "cert_type_cd": cert_type,
            "cert_no": _gen_cert_no(cert_type),
            "cust_sts_cd": cust_sts,
            "cust_type_cd": cust_type,
            "mobile_no": _gen_mobile(),
            "reg_dt": reg_dt.date(),
            "risk_lvl_cd": risk,
            "mgr_emp_no": mgr_no,
        })

    conn.execute(insert(tables["t_cif_base"]), customers)
    conn.commit()
    return customers


def insert_accounts(
    conn, tables: dict[str, Table], customers: list[dict],
) -> list[dict]:
    """插入账户主表，返回账户列表。"""
    accounts = []
    acct_idx = 1

    for cust in customers:
        if cust["cust_sts_cd"] != "01":  # 非正常的客户账户少
            num_accts = random.randint(0, 1)
        else:
            num_accts = random.randint(1, 4)

        for _ in range(num_accts):
            acct_type = random.choices(
                list(ACCT_TYPE_MAP.keys()),
                weights=[0.5, 0.25, 0.2, 0.05],
            )[0]
            ccyc = random.choices(
                list(CCYC_MAP.keys()),
                weights=[0.92, 0.05, 0.02, 0.01],
            )[0]
            acct_sts = random.choices(
                list(ACCT_STS_MAP.keys()),
                weights=[0.88, 0.05, 0.04, 0.03],
            )[0]

            # 余额分布: 大部分人小额，少数人大额
            if random.random() < 0.7:
                bal = round(random.uniform(100, 50000), 2)
            elif random.random() < 0.9:
                bal = round(random.uniform(50000, 500000), 2)
            else:
                bal = round(random.uniform(500000, 5000000), 2)

            frz = 0.0
            if acct_sts == "02":  # 冻结
                frz = round(bal * random.uniform(0.3, 1.0), 2)
            elif acct_sts == "03":  # 止付
                frz = round(bal * random.uniform(0.1, 0.5), 2)

            avl = round(bal - frz, 2)

            open_dt = _random_date(
                datetime(2019, 1, 1),
                datetime(2024, 6, 30),
            )
            mat_dt = None
            int_rate = None
            if acct_type == "02":  # 定期
                mat_dt = (open_dt + timedelta(days=random.choice([90, 180, 365, 730, 1095]))).date()
                int_rate = round(random.uniform(0.015, 0.025), 4)
            elif acct_type == "03":  # 理财
                mat_dt = (open_dt + timedelta(days=random.choice([90, 180, 365]))).date()
                int_rate = round(random.uniform(0.03, 0.06), 4)

            acct_no = f"{random.choice(['6222', '6228', '6217'])}{random.randint(100000000000, 999999999999):012d}"
            accounts.append({
                "acct_no": acct_no,
                "cif_no": cust["cif_no"],
                "acct_type_cd": acct_type,
                "ccyc_cd": ccyc,
                "acct_sts_cd": acct_sts,
                "acct_bal": bal,
                "frz_amt": frz,
                "avl_bal": avl,
                "open_dt": open_dt.date(),
                "mat_dt": mat_dt,
                "int_rate": int_rate,
            })
            acct_idx += 1

    conn.execute(insert(tables["t_acct_main"]), accounts)
    conn.commit()
    return accounts


def insert_transactions(
    conn, tables: dict[str, Table], accounts: list[dict],
    num_txns: int = 2000,
) -> list[dict]:
    """插入交易流水。"""
    txns = []
    active_accounts = [a for a in accounts if a["acct_sts_cd"] == "01"]
    if not active_accounts:
        return []

    base_date = datetime(2024, 1, 1)

    for i in range(num_txns):
        acct = random.choice(active_accounts)
        day_offset = random.randint(0, 180)
        txn_dt = (base_date + timedelta(days=day_offset)).date()
        txn_tm = f"{random.randint(0, 23):02d}{random.randint(0, 59):02d}{random.randint(0, 59):02d}"

        txn_type = random.choices(
            list(TXN_TYPE_MAP.keys()),
            weights=[0.20, 0.15, 0.20, 0.15, 0.08, 0.05, 0.05, 0.05, 0.04, 0.03],
        )[0]

        # 借贷方向
        txn_cls = TXN_TYPE_MAP[txn_type][1]
        if txn_cls in ("资金流入", "收益", "投资回款"):
            dr_cr = "2"
        elif txn_cls in ("资金流出", "费用"):
            dr_cr = "1"
        else:  # 资金划转
            dr_cr = random.choice(["1", "2"])

        # 交易金额分布
        if random.random() < 0.6:
            amt = round(random.uniform(10, 5000), 2)
        elif random.random() < 0.85:
            amt = round(random.uniform(5000, 50000), 2)
        else:
            amt = round(random.uniform(50000, 200000), 2)

        bal_af = round(acct["avl_bal"] + (amt if dr_cr == "2" else -amt), 2)
        bal_af = max(bal_af, 0)

        chl = random.choices(
            list(CHL_MAP.keys()),
            weights=[0.15, 0.30, 0.15, 0.10, 0.10, 0.12, 0.08],
        )[0]

        rvsl = "0"
        rvsl_rel = None
        # 少量冲正交易（模拟原交易+冲正交易对）
        if random.random() < 0.02 and i > 0:
            rvsl = "1"
            rvsl_rel = txns[-1]["txn_seq_no"] if txns else None

        txn_seq = f"TXN{txn_dt.strftime('%Y%m%d')}{i+1:08d}"
        txns.append({
            "txn_seq_no": txn_seq,
            "acct_no": acct["acct_no"],
            "txn_dt": txn_dt,
            "txn_tm": txn_tm,
            "txn_type_cd": txn_type,
            "dr_cr_flg": dr_cr,
            "txn_amt": amt,
            "txn_ccyc_cd": acct["ccyc_cd"],
            "acct_bal_af": bal_af,
            "opp_acct_no": None,
            "opp_acct_nm": None,
            "chl_cd": chl,
            "txn_rmk": None,
            "rvsl_flg": rvsl,
            "rvsl_rel_no": rvsl_rel,
        })

    conn.execute(insert(tables["t_txn_dtl"]), txns)
    conn.commit()
    return txns


def insert_agreements(
    conn, tables: dict[str, Table],
    customers: list[dict], accounts: list[dict], products: list[dict],
) -> list[dict]:
    """插入客户产品合约（多对多桥接）。"""
    agts = []
    active_custs = [c for c in customers if c["cust_sts_cd"] == "01"]
    acct_map = {a["cif_no"]: a for a in accounts if a["acct_sts_cd"] == "01"}
    valid_prods = [p for p in products if p["prod_sts_cd"] in ("01", "03")]

    agt_idx = 1
    for cust in active_custs:
        if cust["cif_no"] not in acct_map:
            continue
        acct = acct_map[cust["cif_no"]]
        num_agts = random.randint(0, 3)
        chosen_prods = random.sample(valid_prods, min(num_agts, len(valid_prods)))

        for prod in chosen_prods:
            sign_dt = _random_date(datetime(2023, 1, 1), datetime(2024, 6, 30))
            due_days = random.choice([90, 180, 365, 730])
            due_dt = (sign_dt + timedelta(days=due_days)).date()

            sign_amt = round(random.uniform(prod["min_pur_amt"], prod["min_pur_amt"] * 20), 2)
            hold_amt = sign_amt if datetime.now().date() < due_dt else 0

            agt_sts = random.choices(
                list(AGT_STS_MAP.keys()),
                weights=[0.8, 0.15, 0.05],
            )[0]

            agts.append({
                "agt_no": f"AGT{agt_idx:010d}",
                "cif_no": cust["cif_no"],
                "prod_cd": prod["prod_cd"],
                "acct_no": acct["acct_no"],
                "agt_sts_cd": agt_sts,
                "sign_dt": sign_dt.date(),
                "due_dt": due_dt,
                "hold_amt": hold_amt,
                "sign_amt": sign_amt,
            })
            agt_idx += 1

    conn.execute(insert(tables["t_cust_prod_agt"]), agts)
    conn.commit()
    return agts


def create_bank_database(db_path: str, num_customers: int = 100, num_txns: int = 2000) -> str:
    """创建完整的银行测试数据库。

    Returns:
        数据库文件路径
    """
    engine = create_engine(f"sqlite:///{db_path}")
    tables = create_schema(engine)

    with engine.connect() as conn:
        insert_dicts(conn, tables)
        insert_org(conn, tables)
        products = insert_products(conn, tables)
        customers = insert_customers(conn, tables, num_customers)
        accounts = insert_accounts(conn, tables, customers)
        insert_transactions(conn, tables, accounts, num_txns)
        insert_agreements(conn, tables, customers, accounts, products)

    print(f"Bank test database created at: {db_path}")
    print(f"  Tables: {len(tables)}")
    print(f"  Customers: {num_customers}")
    print(f"  Accounts: {len(accounts)}")
    print(f"  Transactions: {num_txns}")
    print(f"  Products: {len(products)}")
    print(f"  Agreements: {len(insert_agreements.__code__.co_consts)}")
    return db_path


def print_stats(db_path: str) -> None:
    """打印数据库统计信息。"""
    engine = create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        for tbl in [
            "t_cif_base", "t_acct_main", "t_txn_dtl",
            "t_prod_info", "t_cust_prod_agt", "t_org_hier",
        ]:
            result = conn.execute(text(f"SELECT COUNT(*) FROM {tbl}"))
            count = result.scalar()
            print(f"  {tbl}: {count} rows")

        # 资产分布
        print("\n  -- 账户资产分布 --")
        result = conn.execute(text("""
            SELECT acct_type_cd, COUNT(*) as cnt,
                   ROUND(SUM(acct_bal), 2) as total_bal,
                   ROUND(AVG(acct_bal), 2) as avg_bal
            FROM t_acct_main
            WHERE acct_sts_cd = '01'
            GROUP BY acct_type_cd
        """))
        for row in result.fetchall():
            type_nm = ACCT_TYPE_MAP.get(row[0], row[0])
            print(f"    {type_nm}: {row[1]} 户, 总余额 {row[2]:,.2f}, 户均 {row[3]:,.2f}")

        # 交易类型分布
        print("\n  -- 近半年交易类型分布 (TOP 5) --")
        result = conn.execute(text("""
            SELECT txn_type_cd, COUNT(*) as cnt, ROUND(SUM(txn_amt), 2) as total
            FROM t_txn_dtl
            WHERE rvsl_flg = '0'
            GROUP BY txn_type_cd
            ORDER BY cnt DESC
            LIMIT 5
        """))
        for row in result.fetchall():
            type_nm = TXN_TYPE_MAP.get(row[0], (row[0], ""))[0]
            print(f"    {type_nm}: {row[1]} 笔, 金额 {row[2]:,.2f}")

        # 产品持有分布
        print("\n  -- 产品签约分布 --")
        result = conn.execute(text("""
            SELECT p.prod_lvl2_nm, COUNT(*) as cnt, ROUND(SUM(a.hold_amt), 2) as total
            FROM t_cust_prod_agt a
            JOIN t_prod_info p ON a.prod_cd = p.prod_cd
            WHERE a.agt_sts_cd = '01'
            GROUP BY p.prod_lvl2_nm
            ORDER BY total DESC
        """))
        for row in result.fetchall():
            print(f"    {row[0]}: {row[1]} 笔, 持有 {row[2]:,.2f}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate bank retail test database")
    parser.add_argument("--db-path", default="bank_test.db", help="Output SQLite database path")
    parser.add_argument("--customers", type=int, default=100, help="Number of customers")
    parser.add_argument("--transactions", type=int, default=2000, help="Number of transactions")
    parser.add_argument("--stats", action="store_true", help="Print statistics after generation")
    args = parser.parse_args()

    db_path = create_bank_database(args.db_path, args.customers, args.transactions)

    if args.stats:
        print("\nStatistics:")
        print_stats(db_path)
