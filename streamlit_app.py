import math
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

# Optional (touch-zoom, layered charts)
try:
    import altair as alt
    ALT_AVAILABLE = True
except Exception:
    ALT_AVAILABLE = False

# ----------------------------
# Page & Session
# ----------------------------
st.set_page_config(
    page_title="🔥 FIRE Tax + FI Planner 2025",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Mobile-friendly CSS
st.markdown("""
<style>
.block-container { padding-top: 0.6rem; padding-bottom: 0.6rem; }
@media (max-width: 640px) {
  .stDataFrame { font-size: 0.9rem; }
  .stMetric { font-size: 0.9rem; }
}
[data-baseweb="radio"] label, [data-baseweb="checkbox"] label { line-height: 1.2rem; }
</style>
""", unsafe_allow_html=True)

if "sim" not in st.session_state:
    st.session_state["sim"] = None

# =========================
# ---- Tax Settings ----
# =========================
FEDERAL_BRACKETS_2025_SINGLE = [
    (0, 0.10), (11925, 0.12), (48475, 0.22),
    (103350, 0.24), (197300, 0.32), (250525, 0.35), (626350, 0.37),
]
FEDERAL_BRACKETS_2025_MARRIED = [
    (0, 0.10), (23850, 0.12), (96950, 0.22),
    (206700, 0.24), (394600, 0.32), (501050, 0.35), (752600, 0.37),
]
VIRGINIA_BRACKETS_2025 = [(0, 0.02), (3000, 0.03), (5000, 0.05), (17000, 0.0575)]
STANDARD_DEDUCTION_2025_SINGLE = 15000
STANDARD_DEDUCTION_2025_MARRIED = 30000

# =========================
# ---- Helpers ----
# =========================
def calculate_tax(taxable_income: float, brackets: list[tuple[int, float]]) -> float:
    if taxable_income <= 0: return 0.0
    tax = 0.0
    n = len(brackets)
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i + 1][0] if i + 1 < n else float('inf')
        if taxable_income <= start: break
        span = min(taxable_income, end) - start
        if span > 0: tax += span * rate
    return max(tax, 0.0)

def money(x): return f"${x:,.0f}"
def pct(x):   return f"{x:.1%}"

def normalize_return(r):
    if r is None: return 0.0
    try: r_float = float(r)
    except Exception: return 0.0
    if r_float > 1.5: r_float = r_float / 100.0  # interpret 30 -> 0.30
    return max(-0.90, min(2.00, r_float))        # clamp [-90%, +200%]

def inflate_expense(base_expense: float, cpi: float, years: int) -> float:
    return base_expense * ((1.0 + cpi) ** max(0, years))

def format_eta_decimal(eta_years):
    """Always show a decimal number of years (one decimal)."""
    if eta_years is None:
        return "> capped horizon"
    return f"{eta_years:.1f} years"

def marginal_rate_for(brackets, taxable):
    if taxable <= 0: return 0.0
    n = len(brackets)
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i+1][0] if i+1 < n else float('inf')
        if start < taxable <= end:
            return rate
    return brackets[-1][1]

def bracket_slices(brackets, taxable):
    rows = []
    n = len(brackets)
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i+1][0] if i+1 < n else float('inf')
        if taxable <= start:
            break
        span = min(taxable, end) - start
        tax  = max(0.0, span * rate)
        rows.append({"from": start, "to": min(taxable, end), "rate": rate, "span": span, "tax": tax})
    return rows

def recompute_tax_with_override(base_gross, pension_contrib, filing, contributions, override_key=None, override_value=None):
    contribs = dict(contributions)
    if override_key is not None:
        contribs[override_key] = override_value

    std_ded = STANDARD_DEDUCTION_2025_SINGLE if filing == "Single" else STANDARD_DEDUCTION_2025_MARRIED
    fed_br = FEDERAL_BRACKETS_2025_SINGLE if filing == "Single" else FEDERAL_BRACKETS_2025_MARRIED

    agi = base_gross - pension_contrib
    agi_reducing_accounts = [
        "403(b) Traditional", "457(b) Traditional",
        "401(a) Employee", "Solo 401(k) Employee",
        "SEP IRA", "SIMPLE IRA", "Traditional IRA", "HSA", "FSA"
    ]
    for acct in agi_reducing_accounts:
        agi -= contribs.get(acct, 0)
    agi -= min(contribs.get("529 Plan", 0), 4000)

    taxable = max(agi - std_ded, 0)
    fed = calculate_tax(taxable, fed_br)
    sta = calculate_tax(taxable, VIRGINIA_BRACKETS_2025)
    return taxable, fed, sta, fed + sta

# =========================
# ---- App ----
# =========================
st.title("🔥 FIRE Tax + FI Planner 2025 (Federal + Virginia) 🔥")

with st.expander("Assumptions", expanded=False):
    st.markdown(
        "- 2025 **federal** & **Virginia** tax brackets (start-of-bracket).\n"
        "- Uses the **standard deduction** by filing status.\n"
        "- Virginia 529 deduction capped at **$4,000**.\n"
        "- **SWR** drives FI targets (you control the %).\n"
        "- **Years until retirement = Target age − Current age**.\n"
        "- Simplified model: ignores credits/phaseouts, SS/Medicare, LTCG/qualified dividends, NIIT, etc."
    )

# ---- Sidebar Inputs ----
st.sidebar.header("Filing Status")
filing_status = st.sidebar.selectbox("Select Filing Status", ["Single", "Married Filing Jointly"])

st.sidebar.header("Income & Expenses")
gross_salary = st.sidebar.number_input("Gross Salary ($)", value=150000, step=1000)
pension_percent = st.sidebar.slider("Pension Contribution (% of Salary)", 0, 20, 5) / 100
annual_expenses = st.sidebar.number_input("Annual Expenses ($)", value=45000, step=1000)

# SWR
swr_percent = st.sidebar.number_input("Safe Withdrawal Rate (%)", min_value=2.0, max_value=7.0, value=4.0, step=0.1)
swr = swr_percent / 100.0

# Inflation controls
st.sidebar.header("Inflation")
inflation_percent = st.sidebar.number_input("Annual CPI (%)", min_value=0.0, max_value=10.0, value=3.0, step=0.1)
inflation = inflation_percent / 100.0
expense_inflation_on = st.sidebar.checkbox(
    "Inflate expenses by CPI for nominal FI targets", value=False,
    help="When ON, FI guide-lines (Lean/Full/Chubby/Obese) use expenses inflated to the snapshot horizon."
)

# Horizon + cap
st.sidebar.header("Retirement Horizon")
current_age = st.sidebar.number_input("Current age", value=40, step=1, min_value=0)
target_age = st.sidebar.number_input("Target retirement age", value=58, step=1, min_value=0)
years_until_ret = max(1, int(round(target_age - current_age)))

st.sidebar.header("Horizon Limit")
sim_until_age = st.sidebar.number_input(
    "Show results until age", value=65, min_value=max(current_age + 1, 1), step=1,
    help="Simulation and charts will stop at this age."
)

# Portfolio-level default return (everything else)
default_return_all_else = 0.08   # 8%

# ===========================================
# ---- Accounts (Core vs More, with Crypto) --
# ===========================================
st.sidebar.header("Choose Accounts to Contribute To")
with st.sidebar.container():
    st.markdown("**Core account types**")
    core_accounts = {
        "Brokerage": st.checkbox("Brokerage", value=False),
        "Crypto": st.checkbox("Crypto", value=True),
        "Traditional IRA": st.checkbox("Traditional IRA", value=True),
        "Roth IRA": st.checkbox("Roth IRA", value=True),
        "457(b) Traditional": st.checkbox("457(b) Traditional", value=True),
        "457(b) Roth": st.checkbox("457(b) Roth", value=False),
        "403(b) Traditional": st.checkbox("403(b) Traditional", value=True),
        "403(b) Roth": st.checkbox("403(b) Roth", value=True),
    }
with st.sidebar.expander("More account types (optional)"):
    more_accounts = {
        "401(a) Employee": st.checkbox("401(a) Employee Contribution", value=False),
        "401(a) Employer": st.checkbox("401(a) Employer Contribution", value=False),
        "Solo 401(k) Employee": st.checkbox("Solo 401(k) Employee Contribution", value=False),
        "Solo 401(k) Employer": st.checkbox("Solo 401(k) Employer Contribution", value=False),
        "SEP IRA": st.checkbox("SEP IRA", value=False),
        "SIMPLE IRA": st.checkbox("SIMPLE IRA", value=False),
        "HSA": st.checkbox("HSA", value=False),
        "FSA": st.checkbox("FSA", value=False),
        "529 Plan": st.checkbox("529 Plan", value=False),
        "ESA": st.checkbox("ESA", value=False),
    }

# Contributions (defaults)
st.sidebar.header("Annual Contributions ($/year)")
contributions = {}
for account, enabled in {**core_accounts, **more_accounts}.items():
    if enabled:
        key = ("core_" if account in core_accounts else "more_") + account
        default_val = 0
        if account == "457(b) Traditional": default_val = 15000
        if account == "403(b) Traditional": default_val = 23500
        if account == "Crypto":             default_val = 15000
        if account == "Roth IRA":           default_val = 5000
        contributions[account] = st.sidebar.number_input(
            f"{account} Contribution ($)", value=default_val, step=500, key=key
        )

# 2025 limit hints (warnings only)
with st.sidebar.expander("Contribution limit tips (2025 — edit if needed)"):
    hints = {
        "IRA (Traditional/Roth) combined": st.number_input("IRA annual limit ($)", value=7000, step=500, key="hint_ira"),
        "457(b) employee deferral": st.number_input("457(b) annual limit ($)", value=23500, step=500, key="hint_457"),
        "403(b) employee deferral": st.number_input("403(b) annual limit ($)", value=23500, step=500, key="hint_403"),
        "HSA (family)": st.number_input("HSA annual limit ($)", value=8550, step=50, key="hint_hsa"),
        "FSA (health)": st.number_input("FSA annual limit ($)", value=3300, step=50, key="hint_fsa"),
        "415(c) overall DC limit": st.number_input("Overall DC limit (§415c) ($)", value=70000, step=1000, key="hint_415c"),
        "529 (VA deduction hint)": st.number_input("VA 529 deductible amount used ($)", value=4000, step=500, key="hint_529"),
    }
    st.caption("These are non-blocking warnings; catch-ups vary by age & plan.")

# ==============================================
# ---- Granular Balances & Per-Account Returns --
# ==============================================
st.sidebar.header("Granular balances & returns (optional)")
granular_mode = st.sidebar.checkbox("Enable granular balances & per-account returns", value=True)

ALL_ACCOUNTS = list(core_accounts.keys()) + list(more_accounts.keys())
account_start_balances = {}
account_returns = {}

DEFAULT_BALANCES = {
    "Crypto": 250_000,
    "403(b) Traditional": 176_000,
    "403(b) Roth": 28_000,
    "457(b) Traditional": 112_000,
    "457(b) Roth": 300,
    "Traditional IRA": 67_000,
    "Roth IRA": 123_000,
}
DEFAULT_RETURNS = {"Crypto": 0.20}  # others default to 8%

default_total_investments = sum(DEFAULT_BALANCES.values())
current_investments = st.sidebar.number_input(
    "Current Total Investment Value ($)", value=default_total_investments, step=1000
)
default_granular_selection = list(DEFAULT_BALANCES.keys())

if granular_mode:
    st.sidebar.caption("Specify starting balances & returns for selected accounts. Remainder → 'Other Investments'.")
    chosen_accounts = st.sidebar.multiselect(
        "Accounts with explicit starting balance & return",
        options=ALL_ACCOUNTS,
        default=default_granular_selection
    )
    for acct in chosen_accounts:
        start_default = DEFAULT_BALANCES.get(acct, 0.0)
        ret_default = DEFAULT_RETURNS.get(acct, default_return_all_else)
        account_start_balances[acct] = st.sidebar.number_input(
            f"{acct} starting balance ($)", min_value=0.0, value=float(start_default), step=1000.0, key=f"bal_{acct}"
        )
        account_returns[acct] = st.sidebar.number_input(
            f"{acct} expected annual return (%)",
            min_value=-50.0, max_value=50.0,
            value=round(ret_default * 100, 1),
            step=0.5, key=f"ret_{acct}"
        ) / 100.0

    with st.sidebar.expander("Set returns for additional accounts (no starting balances)"):
        for acct in [a for a in ALL_ACCOUNTS if a not in chosen_accounts]:
            if st.checkbox(f"Set return for {acct}", key=f"setret_{acct}"):
                account_returns[acct] = st.number_input(
                    f"{acct} expected annual return (%)",
                    min_value=-50.0, max_value=50.0,
                    value=round(default_return_all_else * 100, 1),
                    step=0.5, key=f"ret_only_{acct}"
                ) / 100.0

    specified_total = sum(account_start_balances.values())
    other_start = max(current_investments - specified_total, 0.0)
    other_return = st.sidebar.number_input(
        "Other Investments expected annual return (%)",
        min_value=-50.0, max_value=50.0,
        value=round(default_return_all_else * 100, 1),
        step=0.5, key="ret_other"
    ) / 100.0
else:
    chosen_accounts = []
    specified_total = 0.0
    other_start = current_investments
    other_return = default_return_all_else

# =========================
# ---- Run Simulation ----
# =========================
clicked = st.sidebar.button("🚀 Run / Update FIRE Simulation")

if clicked:
    # Taxes / cash flow
    pension_contribution = gross_salary * pension_percent
    agi = gross_salary - pension_contribution
    agi_reducing_accounts = [
        "403(b) Traditional", "457(b) Traditional",
        "401(a) Employee", "Solo 401(k) Employee",
        "SEP IRA", "SIMPLE IRA", "Traditional IRA", "HSA", "FSA"
    ]
    employer_funded_accounts = ["401(a) Employer"]
    for acct in agi_reducing_accounts:
        agi -= contributions.get(acct, 0)
    va_529_deduction = min(contributions.get("529 Plan", 0), 4000)
    agi -= va_529_deduction

    std_ded = STANDARD_DEDUCTION_2025_SINGLE if filing_status=="Single" else STANDARD_DEDUCTION_2025_MARRIED
    taxable_income = max(agi - std_ded, 0)
    federal_tax = calculate_tax(taxable_income, FEDERAL_BRACKETS_2025_SINGLE if filing_status=="Single" else FEDERAL_BRACKETS_2025_MARRIED)
    state_tax = calculate_tax(taxable_income, VIRGINIA_BRACKETS_2025)
    total_tax = federal_tax + state_tax

    effective_tax_rate = (total_tax / gross_salary) if gross_salary > 0 else 0.0
    after_tax_income = gross_salary - pension_contribution - total_tax

    total_savings = sum(contributions.values())
    pre_tax_sum = sum(contributions.get(a, 0) for a in agi_reducing_accounts) + va_529_deduction
    employer_sum = sum(contributions.get(a, 0) for a in employer_funded_accounts)
    post_tax_savings = total_savings - pre_tax_sum - employer_sum
    disposable_income = after_tax_income - post_tax_savings

    # Warnings
    warn_msgs = []
    ira_total = contributions.get("Traditional IRA", 0) + contributions.get("Roth IRA", 0)
    if ira_total > hints["IRA (Traditional/Roth) combined"]:
        warn_msgs.append(f"IRA combined {money(ira_total)} > {money(hints['IRA (Traditional/Roth) combined'])}")
    def over(a, b, key, label):
        t = contributions.get(a, 0) + contributions.get(b, 0)
        if t > hints[key]: warn_msgs.append(f"{label} {money(t)} > {money(hints[key])}")
    over("457(b) Traditional", "457(b) Roth", "457(b) employee deferral", "457(b)")
    over("403(b) Traditional", "403(b) Roth", "403(b) employee deferral", "403(b)")
    if post_tax_savings > after_tax_income:
        warn_msgs.append("Post-tax savings > after-tax income (negative disposable).")

    # Portfolio build
    portfolio = {}
    if other_start > 0:
        portfolio["Other Investments"] = {"balance": other_start, "return": normalize_return(other_return)}
    for acct, bal in account_start_balances.items():
        if bal > 0:
            r = account_returns.get(acct, default_return_all_else)
            portfolio[acct] = {"balance": bal, "return": normalize_return(r)}
    for acct in contributions.keys():
        if acct not in portfolio:
            r = account_returns.get(acct, default_return_all_else)
            portfolio[acct] = {"balance": 0.0, "return": normalize_return(r)}
    annual_contribs = {acct: contributions.get(acct, 0.0) for acct in portfolio.keys()}

    # Record per-account history for charts
    account_history = {acct: [] for acct in portfolio.keys()}

    # FI targets (real baseline)
    if swr <= 0:
        st.error("Safe Withdrawal Rate must be > 0%."); st.stop()
    base_full_fi    = annual_expenses / swr
    base_lean_fi    = (annual_expenses * 0.75) / swr
    base_chubby_fi  = (annual_expenses * 1.20) / swr
    base_fat_fi     = (annual_expenses * 1.50) / swr
    base_obese_fi   = (annual_expenses * 2.00) / swr
    base_barista_fi = (annual_expenses * 0.50) / swr
    base_flamingo_fi = 0.50 * base_full_fi
    coast_fi_target  = base_full_fi / ((1 + default_return_all_else) ** years_until_ret) if default_return_all_else > -1 else math.inf

    milestone_defs = [
        ("Coast FI", coast_fi_target),
        ("Flamingo FI (50% of FI #)", base_flamingo_fi),
        ("Barista FI (covers ~50% of expenses)", base_barista_fi),
        ("Lean FI (75% Expenses)", base_lean_fi),
        ("Chubby FI (~120% Expenses)", base_chubby_fi),
        ("Full FI (100% Expenses)", base_full_fi),
        ("Fat FI (150% Expenses)", base_fat_fi),
        ("Obese FI (200% Expenses)", base_obese_fi),
    ]

    # Sim loop with age cap + fractional milestone ETAs
    sim_years = max(1, min(50, int(sim_until_age - current_age)))
    years, balances = [], []
    milestone_eta = {name: (0.0 if sum(b["balance"] for b in portfolio.values()) >= target else None)
                     for name, target in milestone_defs}
    snapshot_at_ret = None
    full_fi_first_year = None
    snapshot_full_fi = None
    snapshot_5yr = None
    snapshot_10yr = None

    for year in range(1, sim_years + 1):
        prev_total = sum(b["balance"] for b in portfolio.values())
        # grow & contribute
        for acct in portfolio:
            r = portfolio[acct]["return"]
            portfolio[acct]["balance"] = portfolio[acct]["balance"] * (1 + r) + annual_contribs.get(acct, 0.0)
        total_balance = sum(b["balance"] for b in portfolio.values())

        # record per-account balances after this year
        for acct in portfolio:
            account_history[acct].append(portfolio[acct]["balance"])

        years.append(year); balances.append(total_balance)

        if year == 5:  snapshot_5yr  = {acct: portfolio[acct]["balance"] for acct in portfolio}
        if year == 10: snapshot_10yr = {acct: portfolio[acct]["balance"] for acct in portfolio}

        if full_fi_first_year is None and total_balance >= base_full_fi:
            full_fi_first_year = year
            snapshot_full_fi = {acct: portfolio[acct]["balance"] for acct in portfolio}

        # fractional crossing time
        span = max(total_balance - prev_total, 1e-9)
        for name, target in milestone_defs:
            if milestone_eta[name] is None and prev_total < target <= total_balance:
                frac = (target - prev_total) / span
                milestone_eta[name] = (year - 1) + frac

        if year == years_until_ret:
            snapshot_at_ret = {acct: portfolio[acct]["balance"] for acct in portfolio}
    if snapshot_at_ret is None:
        snapshot_at_ret = {acct: portfolio[acct]["balance"] for acct in portfolio}

    # Real (today's $) series
    deflator = [(1.0 + inflation) ** y for y in years]
    real_balances = [b / d for b, d in zip(balances, deflator)]

    def discount_snapshot(snap_dict, t_years):
        if snap_dict is None: return None
        return {k: v / ((1.0 + inflation) ** t_years) for k, v in snap_dict.items()}

    real_snapshot_at_ret = discount_snapshot(snapshot_at_ret, min(years_until_ret, sim_years))
    real_snapshot_full_fi = discount_snapshot(snapshot_full_fi, full_fi_first_year) if full_fi_first_year else None
    real_snapshot_5yr  = discount_snapshot(snapshot_5yr, 5)   if snapshot_5yr  else None
    real_snapshot_10yr = discount_snapshot(snapshot_10yr, 10) if snapshot_10yr else None

    # Save to session state
    st.session_state["sim"] = dict(
        # cash/tax
        agi=agi, taxable_income=taxable_income, federal_tax=federal_tax, state_tax=state_tax,
        total_tax=total_tax, effective_tax_rate=effective_tax_rate, after_tax_income=after_tax_income,
        total_savings=total_savings, employer_sum=employer_sum, post_tax_savings=post_tax_savings,
        disposable_income=disposable_income, pension_contribution=pension_contribution, warn_msgs=warn_msgs,
        # series
        years=years, balances=balances, real_balances=real_balances, sim_years=sim_years,
        # targets (real baseline)
        base_full_fi=base_full_fi, base_lean_fi=base_lean_fi, base_chubby_fi=base_chubby_fi,
        base_fat_fi=base_fat_fi, base_obese_fi=base_obese_fi,
        base_barista_fi=base_barista_fi, base_flamingo_fi=base_flamingo_fi, coast_fi_target=coast_fi_target,
        # snapshots nominal + real
        snapshot_at_ret=snapshot_at_ret, snapshot_full_fi=snapshot_full_fi,
        snapshot_5yr=snapshot_5yr, snapshot_10yr=snapshot_10yr,
        real_snapshot_at_ret=real_snapshot_at_ret, real_snapshot_full_fi=real_snapshot_full_fi,
        real_snapshot_5yr=real_snapshot_5yr, real_snapshot_10yr=real_snapshot_10yr,
        # milestone ETAs (decimal years)
        milestone_defs=milestone_defs, milestone_eta=milestone_eta,
        full_fi_first_year=full_fi_first_year,
        # per-account history for stacked chart
        account_history=account_history, accounts=list(account_history.keys()),
        # meta
        swr_percent=swr_percent, swr=swr, annual_expenses=annual_expenses,
        years_until_ret=years_until_ret, inflation=inflation, inflation_percent=inflation_percent,
        expense_inflation_on=expense_inflation_on, sim_until_age=sim_until_age
    )

# =========================
# ---- Show Results (Two Tabs) ----
# =========================
sim = st.session_state["sim"]
if not sim:
    st.info("Set your inputs and tap **🚀 Run / Update FIRE Simulation**.")
else:
    tax_tab, retire_tab = st.tabs(["Tax Planning", "Retirement Planning"])

    # ---------- TAX PLANNING ----------
    with tax_tab:
        st.subheader("📋 Tax Summary")
        c1, c2, c3 = st.columns(3)
        c1.metric("AGI", money(sim["agi"]))
        c2.metric("Total Taxes", money(sim["total_tax"]))
        c3.metric("Effective Tax Rate", pct(sim["effective_tax_rate"]))

        c1.metric("After-Tax Income", money(sim["after_tax_income"]))
        c2.metric("Annual Savings (total)", money(sim["total_savings"]))
        c3.metric("Disposable ($)", money(sim["disposable_income"]))

        for msg in sim["warn_msgs"]:
            st.warning(msg)

        # --- Contribution Impact: cash-flow stacked bars (side-by-side) ---
        st.subheader("📊 Contribution Impact (cash-flow breakdown)")

        std_ded = STANDARD_DEDUCTION_2025_SINGLE if filing_status == "Single" else STANDARD_DEDUCTION_2025_MARRIED
        baseline_pension = sim["pension_contribution"]
        base_agi = gross_salary - baseline_pension
        base_taxable_income = max(base_agi - std_ded, 0)
        base_fed = calculate_tax(base_taxable_income, FEDERAL_BRACKETS_2025_SINGLE if filing_status=="Single" else FEDERAL_BRACKETS_2025_MARRIED)
        base_state = calculate_tax(base_taxable_income, VIRGINIA_BRACKETS_2025)
        base_tax_total = base_fed + base_state
        base_pre_tax_stack = baseline_pension
        base_post_tax_savings = 0.0
        base_disposable = max(0.0, gross_salary - base_pre_tax_stack - base_tax_total - base_post_tax_savings)

        agi_reducing_accounts = [
            "403(b) Traditional","457(b) Traditional","401(a) Employee","Solo 401(k) Employee",
            "SEP IRA","SIMPLE IRA","Traditional IRA","HSA","FSA"
        ]
        with_pre_tax_elective = sum(contributions.get(a, 0.0) for a in agi_reducing_accounts)
        with_pre_tax_stack = baseline_pension + with_pre_tax_elective
        with_fed = sim["federal_tax"]
        with_state = sim["state_tax"]
        with_tax_total = with_fed + with_state
        with_post_tax_savings = sim["post_tax_savings"]
        with_disposable = max(0.0, gross_salary - with_pre_tax_stack - with_tax_total - with_post_tax_savings)

        order = [
            "Pre-tax (pension + elective)",
            "Federal tax",
            "State tax",
            "Post-tax savings",
            "Disposable income"
        ]
        bars = [
            {"Scenario": "No contributions", "Component": order[0], "Amount": base_pre_tax_stack},
            {"Scenario": "No contributions", "Component": order[1], "Amount": base_fed},
            {"Scenario": "No contributions", "Component": order[2], "Amount": base_state},
            {"Scenario": "No contributions", "Component": order[3], "Amount": base_post_tax_savings},
            {"Scenario": "No contributions", "Component": order[4], "Amount": base_disposable},
            {"Scenario": "With contributions", "Component": order[0], "Amount": with_pre_tax_stack},
            {"Scenario": "With contributions", "Component": order[1], "Amount": with_fed},
            {"Scenario": "With contributions", "Component": order[2], "Amount": with_state},
            {"Scenario": "With contributions", "Component": order[3], "Amount": with_post_tax_savings},
            {"Scenario": "With contributions", "Component": order[4], "Amount": with_disposable},
        ]
        impact_df = pd.DataFrame(bars)

        if ALT_AVAILABLE:
            chart = (
                alt.Chart(impact_df)
                .mark_bar()
                .encode(
                    x=alt.X("Scenario:N", title=None),
                    y=alt.Y("Amount:Q", title="Annual $, stacks to gross salary", stack="zero", axis=alt.Axis(format="~s")),
                    color=alt.Color("Component:N", sort=order, legend=alt.Legend(orient="bottom")),
                    order=alt.Order("Component:N", sort="ascending"),
                    tooltip=[alt.Tooltip("Scenario:N"), alt.Tooltip("Component:N"), alt.Tooltip("Amount:Q", format="$,.0f")],
                )
                .properties(height=260)
            )
            st.altair_chart(chart, use_container_width=True)
        else:
            import numpy as np
            scenarios = ["No contributions", "With contributions"]
            fig, ax = plt.subplots(figsize=(6, 3.2))
            x = np.arange(len(scenarios))
            bottoms = np.zeros(len(scenarios))
            for comp in order:
                y = []
                for sc in scenarios:
                    amt = impact_df[(impact_df["Scenario"]==sc) & (impact_df["Component"]==comp)]["Amount"].sum()
                    y.append(amt)
                ax.bar(x, y, bottom=bottoms, label=comp)
                bottoms += np.array(y)
            ax.set_xticks(x); ax.set_xticklabels(scenarios)
            ax.set_ylabel("Annual $")
            ax.yaxis.set_major_formatter(ticker.StrMethodFormatter("${x:,.0f}"))
            ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2)
            st.pyplot(fig, clear_figure=True)

        # --- Marginal rates & bracket viz (collapsible) ---
        with st.expander("Bracket visualizer & marginal rates", expanded=False):
            fed_marg = marginal_rate_for(
                FEDERAL_BRACKETS_2025_SINGLE if filing_status=="Single" else FEDERAL_BRACKETS_2025_MARRIED,
                sim["taxable_income"]
            )
            va_marg  = marginal_rate_for(VIRGINIA_BRACKETS_2025, sim["taxable_income"])
            combined_simple = fed_marg + va_marg

            c1, c2, c3 = st.columns(3)
            c1.metric("Federal marginal rate", pct(fed_marg))
            c2.metric("Virginia marginal rate", pct(va_marg))
            c3.metric("Combined (simple)", pct(combined_simple))

            fed_slices = bracket_slices(
                FEDERAL_BRACKETS_2025_SINGLE if filing_status=="Single" else FEDERAL_BRACKETS_2025_MARRIED,
                sim["taxable_income"]
            )
            va_slices  = bracket_slices(VIRGINIA_BRACKETS_2025, sim["taxable_income"])

            fed_df = pd.DataFrame([{"System":"Federal","Bracket Start": r["from"], "Span": r["span"], "Tax": r["tax"], "Rate": r["rate"]} for r in fed_slices])
            va_df  = pd.DataFrame([{"System":"Virginia","Bracket Start": r["from"], "Span": r["span"], "Tax": r["tax"], "Rate": r["rate"]} for r in va_slices])
            stack_df = pd.concat([fed_df, va_df], ignore_index=True)

            if ALT_AVAILABLE and len(stack_df):
                chart = (
                    alt.Chart(stack_df)
                      .mark_bar()
                      .encode(
                          x=alt.X("Bracket Start:Q", title="Taxable income slice start ($)", axis=alt.Axis(format="~s")),
                          y=alt.Y("Span:Q", title="Amount taxed in slice ($)", axis=alt.Axis(format="~s")),
                          color=alt.Color("Rate:Q", scale=alt.Scale(scheme="blues"), legend=alt.Legend(format=".0%")),
                          column=alt.Column("System:N", header=alt.Header(title=None)),
                          tooltip=[
                              "System:N",
                              alt.Tooltip("Bracket Start:Q", title="Slice start", format="$,.0f"),
                              alt.Tooltip("Span:Q", title="Slice amount", format="$,.0f"),
                              alt.Tooltip("Rate:Q", title="Rate", format=".0%"),
                              alt.Tooltip("Tax:Q", title="Tax on slice", format="$,.0f"),
                          ],
                      )
                      .properties(height=220)
                )
                st.altair_chart(chart, use_container_width=True)
            else:
                st.dataframe(stack_df, use_container_width=True)

        # --- Waterfall Gross → AGI → Taxable (collapsible) ---
        with st.expander("Income path: Gross → AGI → Taxable", expanded=False):
            gross = gross_salary
            pension = sim["pension_contribution"]
            agi_reductions = sum(contributions.get(a,0) for a in [
                "403(b) Traditional","457(b) Traditional","401(a) Employee","Solo 401(k) Employee",
                "SEP IRA","SIMPLE IRA","Traditional IRA","HSA","FSA"
            ]) + min(contributions.get("529 Plan",0), 4000)
            std_ded = STANDARD_DEDUCTION_2025_SINGLE if filing_status=="Single" else STANDARD_DEDUCTION_2025_MARRIED

            wf = pd.DataFrame([
                {"Step":"Gross salary","Amount": gross},
                {"Step":"− Pension","Amount": -pension},
                {"Step":"− AGI reductions","Amount": -agi_reductions},
                {"Step":"= AGI","Amount": gross - pension - agi_reductions},
                {"Step":"− Standard deduction","Amount": -std_ded},
                {"Step":"= Taxable income","Amount": sim["taxable_income"]},
            ])

            if ALT_AVAILABLE:
                wf["idx"] = range(len(wf))
                bars = alt.Chart(wf).mark_bar().encode(
                    x=alt.X("idx:N", title=None, axis=alt.Axis(labels=False)),
                    y=alt.Y("Amount:Q", title="Δ amount ($)", axis=alt.Axis(format="~s")),
                    color=alt.Color("Amount:Q", legend=None, scale=alt.Scale(range=["#fca5a5","#93c5fd"])),
                    tooltip=[alt.Tooltip("Step:N"), alt.Tooltip("Amount:Q", format="$,.0f")]
                ).properties(height=220)
                labels = alt.Chart(wf).mark_text(dy=-10).encode(x="idx:N", y="Amount:Q", text="Step:N")
                st.altair_chart(bars + labels, use_container_width=True)
            else:
                st.dataframe(wf, use_container_width=True)

        # --- Which contributions saved the most tax? ---
        with st.expander("Which contributions saved you the most tax?", expanded=False):
            impact_rows = []
            pension = sim["pension_contribution"]
            pre_tax_like = [
                "403(b) Traditional","457(b) Traditional",
                "401(a) Employee","Solo 401(k) Employee",
                "SEP IRA","SIMPLE IRA","Traditional IRA","HSA","FSA"
            ]
            for acct in pre_tax_like + ["529 Plan"]:
                amt = contributions.get(acct, 0.0)
                if amt <= 0: continue
                _, _, _, tot2 = recompute_tax_with_override(
                    base_gross=gross_salary,
                    pension_contrib=pension,
                    filing=filing_status,
                    contributions=contributions,
                    override_key=acct,
                    override_value=0.0
                )
                delta_tax = tot2 - sim["total_tax"]
                impact_rows.append({"Account": acct, "Your contribution": money(amt), "Estimated tax saved": money(delta_tax)})
            if impact_rows:
                imp_df = pd.DataFrame(impact_rows)
                imp_df["_sort"] = imp_df["Estimated tax saved"].replace({r'[$,]':''}, regex=True).astype(float)
                imp_df = imp_df.sort_values(by="_sort", ascending=False).drop(columns=["_sort"])
                st.dataframe(imp_df, use_container_width=True)
                st.caption("Method: turn each contribution OFF (one at a time), recompute taxes, and show the resulting increase. "
                           "Approximate; ignores credits/phaseouts and employer match effects.")
            else:
                st.info("No AGI-reducing contributions detected for this analysis.")

    # ---------- RETIREMENT PLANNING ----------
    with retire_tab:
        st.subheader("🏁 FI Milestones (ordered by time)")
        ordered = []
        ordered_names = [
            "Coast FI",
            "Flamingo FI (50% of FI #)",
            "Barista FI (covers ~50% of expenses)",
            "Lean FI (75% Expenses)",
            "Chubby FI (~120% Expenses)",
            "Full FI (100% Expenses)",
            "Fat FI (150% Expenses)",
            "Obese FI (200% Expenses)",
        ]
        for name in ordered_names:
            eta = sim["milestone_eta"].get(name)
            if eta is not None and eta > sim["sim_years"] + 1e-6:
                eta = None
            display = format_eta_decimal(eta if eta is not None else None)
            sort_key = 10**9 if eta is None else eta
            ordered.append((name, display, sort_key))
        ordered.sort(key=lambda x: x[2])
        st.table(pd.DataFrame([(n, d) for n, d, _ in ordered], columns=["Milestone", "ETA (years)"]))

        with st.expander("What the milestones mean", expanded=False):
            st.markdown(f"""
- **Coast FI**: Invested today grows to **Full FI** by ~**{sim['years_until_ret']} years** with **no new contributions**.
- **Barista FI**: Portfolio supports **~50%** of expenses at your SWR; rest from part-time/lower-pay work.
- **Flamingo FI**: Build **~50%** of your Full FI number, then **downshift**; compounding finishes the job.
- **Lean FI**: Supports **75%** of expenses.
- **Full FI**: Supports **100%** of expenses.
- **Chubby FI**: **~120%** of expenses (extra cushion).
- **Fat FI**: **150%** of expenses (lux/cushion).
- **Obese FI**: **200%** of expenses (very large margin).
""")

        # ---- Growth chart ----
        st.subheader("📈 Investment Growth Over Time")
        chart_units = st.radio(
            "Chart units", ["Nominal ($ at future dates)", "Real (today's $)"],
            index=1, horizontal=True, key="chart_units_mode"
        )
        use_real = (chart_units == "Real (today's $)")
        logy = st.checkbox("Log scale (Y)", value=False, key="logy")

        show_guides = st.checkbox("Show FI guide lines (Lean / Full / Chubby / Obese)", value=True)
        show_markers = st.checkbox("Show milestone markers", value=True)
        show_stacked = st.checkbox("Show per-account stacked area (advanced)", value=False,
                                   help="See what actually drives growth (composition over time).")

        guide_year = min(sim["years_until_ret"], sim["sim_years"])

        main_df = pd.DataFrame({
            "Year": sim["years"],
            "Nominal": sim["balances"],
            "Real": sim["real_balances"],
        })
        y_field = "Real" if use_real else "Nominal"

        if ALT_AVAILABLE and len(main_df) > 0:
            y_scale = alt.Scale(type='log') if logy else alt.Scale()
            base = alt.Chart(main_df).mark_line().encode(
                x=alt.X("Year:Q", title="Years from today", scale=alt.Scale(domain=(0, sim['sim_years']))),
                y=alt.Y(f"{y_field}:Q", title="Portfolio Value ($)", scale=y_scale, axis=alt.Axis(format="~s")),
                tooltip=[alt.Tooltip("Year:Q"), alt.Tooltip(f"{y_field}:Q", title="Value", format="$.2s")]
            ).properties(height=340).interactive()

            layers = []

            # Shading 0–5y and 5–10y
            shade_rows = []
            if sim["sim_years"] >= 5:  shade_rows.append({"x0": 0, "x1": 5})
            if sim["sim_years"] >= 10: shade_rows.append({"x0": 5, "x1": 10})
            if shade_rows:
                shade_df = pd.DataFrame(shade_rows)
                shades = alt.Chart(shade_df).mark_rect(opacity=0.08).encode(
                    x="x0:Q", x2="x1:Q", y=alt.value(0), y2=alt.value(1),
                ).properties(height=340)
                layers.append(shades)

            # Main line
            layers.append(base)

            # --- Milestone markers (clean, non-overlapping labels) ---
            if show_markers and "milestone_eta" in sim:
                names_ordered = ordered_names
                mdata = []
                for name in names_ordered:
                    eta = sim["milestone_eta"].get(name)
                    if eta is None or eta <= 0 or eta > sim["sim_years"]:
                        continue
                    lo_idx = max(0, int(eta) - 1)
                    hi_idx = min(len(main_df) - 1, int(eta))
                    lo_y = main_df[y_field].iloc[lo_idx]
                    hi_y = main_df[y_field].iloc[hi_idx]
                    frac = eta - int(eta)
                    val = lo_y + (hi_y - lo_y) * frac
                    mdata.append({"Year": float(eta), "Value": float(val), "Milestone": name, "ETA": float(f"{eta:.1f}")})

                if mdata:
                    mdf = pd.DataFrame(mdata).sort_values("Year")
                    picked = []
                    gap_x = 1.2
                    gap_y_ratio = 0.10
                    for row in mdf.itertuples(index=False):
                        if picked:
                            prev = picked[-1]
                            close_x = (row.Year - prev["Year"]) < gap_x
                            close_y = abs(row.Value - prev["Value"]) < (prev["Value"] * gap_y_ratio)
                            if close_x and close_y:
                                continue
                        picked.append({"Year": row.Year, "Value": row.Value, "Milestone": row.Milestone, "ETA": row.ETA})
                    pick_df = pd.DataFrame(picked)

                    points = alt.Chart(mdf).mark_point(size=55, filled=True, opacity=0.6).encode(
                        x="Year:Q",
                        y=alt.Y("Value:Q", scale=y_scale),
                        tooltip=["Milestone:N", alt.Tooltip("ETA:Q", title="ETA (yrs)", format=".1f"),
                                 alt.Tooltip("Value:Q", format="$.2s")]
                    )
                    labels = alt.Chart(pick_df).mark_text(dy=-8, fontSize=10, stroke="black", strokeWidth=0.5).encode(
                        x="Year:Q", y=alt.Y("Value:Q", scale=y_scale), text=alt.Text("Milestone:N")
                    )
                    eta_labels = alt.Chart(pick_df).mark_text(dy=8, fontSize=9).encode(
                        x="Year:Q", y=alt.Y("Value:Q", scale=y_scale), text=alt.Text("ETA:Q", format=".1f")
                    )
                    layers += [points, labels, eta_labels]

            # Guide lines
            if show_guides:
                if use_real:
                    full_line   = sim["base_full_fi"]
                    chubby_line = sim["base_chubby_fi"]
                    lean_line   = sim["base_lean_fi"]
                    obese_line  = sim["base_obese_fi"]
                    caption = " (real)"
                else:
                    if sim["expense_inflation_on"]:
                        inflated_exp = inflate_expense(sim["annual_expenses"], sim["inflation"], guide_year)
                    else:
                        inflated_exp = sim["annual_expenses"]
                    full_line   = inflated_exp / sim["swr"]
                    chubby_line = (inflated_exp * 1.20) / sim["swr"]
                    lean_line   = (inflated_exp * 0.75) / sim["swr"]
                    obese_line  = (inflated_exp * 2.00) / sim["swr"]
                    caption = f" (nominal @ ~{guide_year}y; infl {'ON' if sim['expense_inflation_on'] else 'OFF'})"
                rules_df = pd.DataFrame({
                    "Label": [f"Lean{caption}", f"Full{caption}", f"Chubby{caption}", f"Obese{caption}"],
                    "Y":     [lean_line,        full_line,        chubby_line,        obese_line]
                })
                rules = alt.Chart(rules_df).mark_rule(strokeDash=[6,4]).encode(
                    y=alt.Y("Y:Q", scale=y_scale),
                    tooltip=["Label:N", alt.Tooltip("Y:Q", title="Target", format="$.2s")]
                )
                layers.append(rules)

            st.altair_chart(alt.layer(*layers), use_container_width=True)

            # Stacked per-account area (separate chart)
            if show_stacked and "account_history" in sim and sim["account_history"]:
                acct_df_rows = []
                years_list = sim["years"]
                defl = [(1.0 + sim["inflation"]) ** y for y in years_list]
                for acct, series in sim["account_history"].items():
                    for i, val in enumerate(series):
                        y = years_list[i]
                        amt = (val / defl[i]) if use_real else val
                        acct_df_rows.append({"Year": y, "Account": acct, "Amount": amt})
                acct_df = pd.DataFrame(acct_df_rows)

                y_scale2 = alt.Scale(type='log') if logy else alt.Scale()
                area = alt.Chart(acct_df).mark_area(opacity=0.55).encode(
                    x=alt.X("Year:Q", title="Years from today", scale=alt.Scale(domain=(0, sim["sim_years"]))),
                    y=alt.Y("sum(Amount):Q", title="Portfolio Value ($)", scale=y_scale2, axis=alt.Axis(format="~s")),
                    color=alt.Color("Account:N", legend=alt.Legend(title="Account")),
                    tooltip=[alt.Tooltip("Year:Q"),
                             alt.Tooltip("Account:N"),
                             alt.Tooltip("sum(Amount):Q", title="Amount", format="$.2s")]
                ).properties(height=340).interactive()

                st.caption("Per-account composition")
                st.altair_chart(area, use_container_width=True)

        else:
            # Matplotlib fallback
            fig2, ax2 = plt.subplots()
            years = sim["years"]
            series = sim["real_balances"] if use_real else sim["balances"]
            if years and series:
                ax2.plot(years, series, label="Projected Portfolio Value")
                if logy: ax2.set_yscale('log')
                for h in [5, 10]:
                    if h <= sim["sim_years"]:
                        ax2.axvline(h, linestyle=':', alpha=0.35)
                # milestone dots
                if "milestone_eta" in sim:
                    for name, eta in sim["milestone_eta"].items():
                        if eta is None or eta <= 0 or eta > sim["sim_years"]: continue
                        i0 = max(0, int(eta) - 1)
                        i1 = min(len(series) - 1, int(eta))
                        y0, y1 = series[i0], series[i1]
                        val = y0 + (y1 - y0) * (eta - int(eta))
                        ax2.scatter([eta], [val], s=40, zorder=5)
                ax2.set_xlim(0, sim["sim_years"])
                ax2.yaxis.set_major_formatter(
                    ticker.FuncFormatter(lambda x, _: f'${int(x/1000)}k' if x < 1_000_000 else f'${x/1_000_000:.1f}M')
                )
                ax2.set_xlabel("Years from today"); ax2.set_ylabel("Portfolio Value ($)")
                ax2.legend()
            else:
                ax2.text(0.5, 0.5, "No data to plot", ha='center', va='center')
            st.pyplot(fig2)

        # ---- Snapshots & Buckets ----
        st.subheader("📌 Snapshot & Buckets")
        default_label = f"Retirement horizon (~{sim['years_until_ret']} years)"
        fi_label = "First year you reach Full FI"
        five_label = "5 years from today"
        ten_label  = "10 years from today"

        options = []
        if sim.get("snapshot_5yr") and 5  <= sim["sim_years"]: options.append(five_label)
        if sim.get("snapshot_10yr") and 10 <= sim["sim_years"]: options.append(ten_label)
        options += [default_label, fi_label]

        snapshot_choice = st.radio(
            "Balance snapshot at",
            options,
            index=options.index(default_label) if default_label in options else 0,
            key="snapshot_choice",
        )

        if snapshot_choice == five_label and sim.get("snapshot_5yr"):
            snapshot_to_use = sim["snapshot_5yr"]; snapshot_year_text = "(~5 years)"; guide_year = 5
        elif snapshot_choice == ten_label and sim.get("snapshot_10yr"):
            snapshot_to_use = sim["snapshot_10yr"]; snapshot_year_text = "(~10 years)"; guide_year = 10
        elif snapshot_choice == fi_label and sim.get("snapshot_full_fi") is not None:
            snapshot_to_use = sim["snapshot_full_fi"]; snapshot_year_text = f"(year {st.session_state['sim']['full_fi_first_year']})"; guide_year = st.session_state["sim"]["full_fi_first_year"] or sim["years_until_ret"]
        else:
            if snapshot_choice == fi_label and sim.get("snapshot_full_fi") is None:
                st.info("You do not reach Full FI within the capped horizon. Showing retirement-horizon snapshot instead.")
            snapshot_to_use = sim["snapshot_at_ret"]; snapshot_year_text = f"(~{sim['years_until_ret']} years)"; guide_year = sim["years_until_ret"]

        if snapshot_choice == five_label and sim.get("real_snapshot_5yr"):
            real_snapshot = sim["real_snapshot_5yr"]
        elif snapshot_choice == ten_label and sim.get("real_snapshot_10yr"):
            real_snapshot = sim["real_snapshot_10yr"]
        elif snapshot_choice == fi_label and sim.get("real_snapshot_full_fi") is not None:
            real_snapshot = sim["real_snapshot_full_fi"]
        else:
            real_snapshot = sim["real_snapshot_at_ret"]

        def tax_bucket(acct_name: str) -> str:
            roth = {"Roth IRA", "403(b) Roth", "457(b) Roth"}
            traditional = {
                "Traditional IRA", "403(b) Traditional", "457(b) Traditional",
                "401(a) Employee", "401(a) Employer", "Solo 401(k) Employee",
                "Solo 401(k) Employer", "SEP IRA", "SIMPLE IRA"
            }
            hsa = {"HSA"}; education = {"529 Plan", "ESA"}
            taxable = {"Brokerage", "Crypto", "Other Investments"}
            if acct_name in roth: return "Roth (tax-free withdrawals, rules apply)"
            if acct_name in traditional: return "Traditional / Pre-tax (taxable withdrawals)"
            if acct_name in hsa: return "HSA (triple-advantaged, med. rules)"
            if acct_name in education: return "Education (529/ESA)"
            if acct_name in taxable: return "Taxable / Non-advantaged"
            return "Other / Unclassified"

        bucket_sums, bucket_sums_real = {}, {}
        for acct, bal in snapshot_to_use.items():
            b = tax_bucket(acct); bucket_sums[b] = bucket_sums.get(b, 0.0) + bal
        for acct, bal in real_snapshot.items():
            b = tax_bucket(acct); bucket_sums_real[b] = bucket_sums_real.get(b, 0.0) + bal

        with st.expander(f"Projected Balances by Tax Bucket {snapshot_year_text}", expanded=True):
            bucket_rows = []
            for b in sorted(set(bucket_sums) | set(bucket_sums_real)):
                bucket_rows.append({
                    "Bucket": b,
                    "Projected Balance (Nominal)": money(bucket_sums.get(b, 0.0)),
                    "Projected Balance (Real)":    money(bucket_sums_real.get(b, 0.0)),
                })
            st.dataframe(pd.DataFrame(bucket_rows), use_container_width=True)

        with st.expander(f"Per-Account Balances {snapshot_year_text}", expanded=False):
            acct_rows = []
            for acct in sorted(set(snapshot_to_use.keys()) | set(real_snapshot.keys())):
                acct_rows.append({
                    "Account": acct, "Bucket": tax_bucket(acct),
                    "Nominal": money(snapshot_to_use.get(acct, 0.0)),
                    "Real":    money(real_snapshot.get(acct, 0.0)),
                })
            st.dataframe(pd.DataFrame(acct_rows), use_container_width=True)

        # ---- Total Assets Summary (Nominal vs Real) ----
        st.subheader("🧮 Total Assets Summary")
        total_nominal = sum(snapshot_to_use.values())
        total_real = sum(real_snapshot.values())
        c1, c2 = st.columns(2)
        c1.metric("Total Assets (Nominal)", money(total_nominal))
        c2.metric("Total Assets (Real, today's $)", money(total_real))

        if ALT_AVAILABLE:
            sum_df = pd.DataFrame({"Type": ["Nominal", "Real"], "Amount": [total_nominal, total_real]})
            bar = alt.Chart(sum_df).mark_bar().encode(
                x=alt.X("Type:N", title=""),
                y=alt.Y("Amount:Q", title="Total", axis=alt.Axis(format="~s")),
                tooltip=[alt.Tooltip("Type:N"), alt.Tooltip("Amount:Q", title="Total", format="$.2s")]
            ).properties(height=220)
            st.altair_chart(bar, use_container_width=True)

        # ---- NEW: Income you could draw from the portfolio ----
        st.subheader("💸 Income You Could Draw")
        st.caption("Pick withdrawal rates to preview sustainable income from this snapshot.")

        # robust defaults so widget never crashes
        wrate_options = [2.5, 3.0, 3.5, 4.0, 4.5, 5.0, 6.0]
        _default_wr = {round(float(sim['swr_percent']), 1), 3.0, 4.0, 5.0}
        default_wrates = [w for w in sorted(_default_wr) if w in wrate_options] or [4.0]
        wrates = st.multiselect(
            "Withdrawal rates",
            options=wrate_options,
            default=default_wrates,
            help="All results shown for both Nominal and Real (today’s $)."
        )

        if wrates:
            income_rows = []
            # expense baseline for coverage %
            if snapshot_choice in (five_label, ten_label) and sim["expense_inflation_on"]:
                horizon = 5 if snapshot_choice == five_label else 10
                exp_nominal = inflate_expense(sim["annual_expenses"], sim["inflation"], horizon)
            elif snapshot_choice == fi_label and sim.get("full_fi_first_year"):
                exp_nominal = inflate_expense(sim["annual_expenses"], sim["inflation"], int(sim["full_fi_first_year"]))
            elif snapshot_choice == default_label and sim["expense_inflation_on"]:
                exp_nominal = inflate_expense(sim["annual_expenses"], sim["inflation"], sim["years_until_ret"])
            else:
                exp_nominal = sim["annual_expenses"]
            exp_real = sim["annual_expenses"]  # real baseline

            for r in sorted(set(wrates)):
                r_dec = r / 100.0
                inc_nom = total_nominal * r_dec
                inc_real = total_real * r_dec
                coverage_nom = (inc_nom / exp_nominal) if exp_nominal > 0 else 0.0
                coverage_real = (inc_real / exp_real) if exp_real > 0 else 0.0
                income_rows.append({
                    "Withdrawal Rate": f"{r:.1f}%",
                    "Annual Income (Nominal)": money(inc_nom),
                    "Covers Expenses (Nominal)": f"{coverage_nom*100:.0f}%",
                    "Annual Income (Real)": money(inc_real),
                    "Covers Expenses (Real)": f"{coverage_real*100:.0f}%"
                })
            st.table(pd.DataFrame(income_rows))
