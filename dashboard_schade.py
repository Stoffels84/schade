import os
from datetime import datetime
import numpy as np
import pandas as pd
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go


# -----------------------------
# CONFIG
# -----------------------------
st.set_page_config(page_title="OT Gent", layout="wide")

FILE_SCHADE = "schade met macro.xlsm"
FILE_COACHING = "Coachingslijst.xlsx"
FILE_GESPREKKEN = "Overzicht gesprekken (aangepast).xlsx"


# -----------------------------
# HELPERS
# -----------------------------
def normalize_col(s: str) -> str:
    return str(s or "").strip().lower()


def pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return first matching column name in df for given candidates (case-insensitive)."""
    norm_map = {normalize_col(c): c for c in df.columns}
    for cand in candidates:
        key = normalize_col(cand)
        if key in norm_map:
            return norm_map[key]
    return None


def to_datetime_safe(series: pd.Series) -> pd.Series:
    """Try convert to datetime. Handles Excel serials + strings."""
    s = series.copy()

    # Excel serial numbers -> datetime (pandas origin is 1899-12-30 for Excel)
    if pd.api.types.is_numeric_dtype(s):
        # Might contain non-date numeric columns; do a best effort:
        # Convert numbers in a plausible excel-date range.
        s_num = pd.to_numeric(s, errors="coerce")
        mask = s_num.between(1, 60000)  # roughly year 2064
        out = pd.Series(pd.NaT, index=s.index)
        out.loc[mask] = pd.to_datetime(s_num.loc[mask], unit="D", origin="1899-12-30", errors="coerce", utc=True)
        # Anything else try parse as string fallback
        rest = ~mask
        if rest.any():
            out.loc[rest] = pd.to_datetime(s.loc[rest].astype(str), errors="coerce", dayfirst=True, utc=True)
        return out.dt.tz_convert(None)

    # strings / mixed
    dt = pd.to_datetime(s, errors="coerce", dayfirst=True, utc=True)
    return dt.dt.tz_convert(None)


def month_label(dt: pd.Timestamp) -> str:
    return ["Jan", "Feb", "Mrt", "Apr", "Mei", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dec"][dt.month - 1]


def coaching_status_from_text(txt: str) -> str | None:
    if txt is None or (isinstance(txt, float) and np.isnan(txt)):
        return None
    t = str(txt).strip().lower()
    if "zeer goed" in t or t == "goed" or " goed" in t:
        return "good"
    if "voldoende" in t or "onvoldoende" in t:
        return "medium"
    if "slecht" in t:
        return "bad"
    return None


@st.cache_data(show_spinner=False)
def load_schade() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not os.path.exists(FILE_SCHADE):
        raise FileNotFoundError(f"Bestand niet gevonden: {FILE_SCHADE}")

    df_bron = pd.read_excel(FILE_SCHADE, sheet_name="BRON", engine="openpyxl")
    # data hastus kan ontbreken
    try:
        df_hastus = pd.read_excel(FILE_SCHADE, sheet_name="data hastus", engine="openpyxl")
    except Exception:
        df_hastus = pd.DataFrame()

    return df_bron, df_hastus


@st.cache_data(show_spinner=False)
def load_coaching() -> tuple[pd.DataFrame, pd.DataFrame]:
    if not os.path.exists(FILE_COACHING):
        raise FileNotFoundError(f"Bestand niet gevonden: {FILE_COACHING}")

    df_done = pd.read_excel(FILE_COACHING, sheet_name="Voltooide coachings", engine="openpyxl")
    df_pending = pd.read_excel(FILE_COACHING, sheet_name="Coaching", engine="openpyxl")
    return df_done, df_pending


@st.cache_data(show_spinner=False)
def load_gesprekken() -> pd.DataFrame:
    if not os.path.exists(FILE_GESPREKKEN):
        raise FileNotFoundError(f"Bestand niet gevonden: {FILE_GESPREKKEN}")
    # eerste tabblad, robuust zoals je JS
    df = pd.read_excel(FILE_GESPREKKEN, sheet_name=0, engine="openpyxl")
    return df


def apply_year_filter(df: pd.DataFrame, date_col: str | None, year_value: str) -> pd.DataFrame:
    if df is None or df.empty or not date_col:
        return df
    if year_value == "ALL":
        return df

    dt = to_datetime_safe(df[date_col])
    y = pd.to_numeric(year_value, errors="coerce")
    if pd.isna(y):
        return df

    out = df.copy()
    out["_dt"] = dt
    out = out[out["_dt"].dt.year == int(y)]
    out = out.drop(columns=["_dt"], errors="ignore")
    return out


# -----------------------------
# LOAD DATA
# -----------------------------
st.title("OT Gent")

with st.spinner("Bestanden laden..."):
    try:
        df_bron, df_hastus = load_schade()
        df_done, df_pending = load_coaching()
        df_gesprekken = load_gesprekken()
    except Exception as e:
        st.error(f"Fout bij laden: {e}")
        st.stop()

# -----------------------------
# COLUMN DETECTION (BRON)
# -----------------------------
col_datum = pick_col(df_bron, ["datum"])
col_chauffeur = pick_col(df_bron, ["volledige naam", "chauffeur", "naam", "bestuurder"])
col_voertuigtype = pick_col(df_bron, ["bus/tram", "bus/ tram", "voertuigtype", "type voertuig"])
col_voertuignr = pick_col(df_bron, ["voertuig", "voertuignummer", "voertuig nr", "busnummer", "tramnummer", "voertuignr"])
col_type = pick_col(df_bron, ["type"])
col_locatie = pick_col(df_bron, ["locatie"])
col_link = pick_col(df_bron, ["link"])
col_pnr = pick_col(df_bron, ["personeelsnr", "personeelsnummer", "personeels nr", "p-nr", "p nr"])
col_teamcoach = pick_col(df_bron, ["teamcoach"])

# Coaching kolommen (done)
col_done_pnr = pick_col(df_done, ["p-nr", "p nr", "pnr", "personeelsnr", "personeelsnummer", "P-nr"])
col_done_rating = pick_col(df_done, ["Beoordeling coaching", "beoordeling coaching"])
col_done_datum = pick_col(df_done, ["datum", "datum coaching"])

# Coaching pending (zoals jouw JS: P-nr staat vaak in kolom D maar we doen kolomnaam-robust)
col_pending_pnr = pick_col(df_pending, ["p-nr", "p nr", "pnr", "personeelsnr", "personeelsnummer", "P-nr"])
if col_pending_pnr is None and df_pending.shape[1] >= 4:
    # fallback: 4de kolom (index 3)
    col_pending_pnr = df_pending.columns[3]

# Gesprekken kolommen
col_g_nummer = pick_col(df_gesprekken, ["nummer", "personeelsnummer", "personeelsnr", "p-nr", "p nr"])
col_g_naam = pick_col(df_gesprekken, ["chauffeurnaam", "volledige naam", "naam"])
col_g_datum = pick_col(df_gesprekken, ["datum"])
col_g_onderwerp = pick_col(df_gesprekken, ["onderwerp"])
col_g_info = pick_col(df_gesprekken, ["info"])


# -----------------------------
# BUILD COACHING MAPS
# -----------------------------
coaching_map = {}  # pnr -> list of dicts {status, date}
if not df_done.empty and col_done_pnr and col_done_rating:
    temp = df_done.copy()
    if col_done_datum:
        temp["_dt"] = to_datetime_safe(temp[col_done_datum])
    else:
        temp["_dt"] = pd.NaT

    for _, r in temp.iterrows():
        p = r.get(col_done_pnr)
        status = coaching_status_from_text(r.get(col_done_rating))
        if pd.isna(p) or status is None:
            continue
        key = str(p).strip()
        coaching_map.setdefault(key, []).append(
            {"status": status, "date": r.get("_dt")}
        )

pending_set = set()
if not df_pending.empty and col_pending_pnr:
    s = df_pending[col_pending_pnr].dropna().astype(str).str.strip()
    pending_set = set([x for x in s.tolist() if x])


def primary_status(pnr: str | None) -> str | None:
    if not pnr:
        return None
    lst = coaching_map.get(str(pnr).strip(), [])
    statuses = [x["status"] for x in lst]
    if not statuses:
        return None
    if "bad" in statuses:
        return "bad"
    if "medium" in statuses:
        return "medium"
    if "good" in statuses:
        return "good"
    return None


# -----------------------------
# YEAR FILTER (sidebar)
# -----------------------------
years = []
if col_datum and not df_bron.empty:
    dt = to_datetime_safe(df_bron[col_datum])
    years = sorted([int(y) for y in dt.dropna().dt.year.unique().tolist()])

st.sidebar.markdown("### Filter")
year_value = st.sidebar.selectbox("Jaar", options=["ALL"] + [str(y) for y in years], format_func=lambda x: "Alle jaren" if x == "ALL" else x)

df_filtered = apply_year_filter(df_bron, col_datum, year_value)


# -----------------------------
# SIDEBAR NAV (grouped)
# -----------------------------
st.sidebar.markdown("### Navigatie")

group = st.sidebar.radio(
    "Groep",
    ["Schade", "Alle info chauffeur"],
    label_visibility="collapsed"
)

if group == "Schade":
    page = st.sidebar.radio(
        "Pagina",
        ["1. Dashboard", "2. Chauffeur", "3. Voertuig", "4. Locatie", "5. Coaching", "6. Analyse"],
        label_visibility="collapsed"
    )
else:
    page = st.sidebar.radio(
        "Pagina",
        ["Gesprekken"],
        label_visibility="collapsed"
    )


# -----------------------------
# COMMON STATUS BAR
# -----------------------------
colA, colB = st.columns([2, 1])
with colA:
    st.caption(
        f"Rijen (jaarfilter): **{len(df_filtered)}**"
        + (f" — Jaar: **{year_value}**" if year_value != "ALL" else " — Alle jaren")
    )
with colB:
    st.caption(f"Coachings (voltooid) unieke P-nrs: **{len(coaching_map)}** — Lopend unieke P-nrs: **{len(pending_set)}**")


# -----------------------------
# PAGES
# -----------------------------
if page == "1. Dashboard":
    st.subheader("Dashboard – Chauffeur opzoeken")

    q = st.text_input("Zoek op personeelsnr, naam of voertuig", placeholder="Personeelsnr, naam of voertuignummer...")
    if not q:
        st.info("Tip: je kunt een deel van de naam, het nummer of het voertuignummer ingeven.")
        st.stop()

    term = q.strip().lower()

    def contains(series: pd.Series) -> pd.Series:
        return series.fillna("").astype(str).str.lower().str.contains(term, na=False)

    mask = pd.Series(False, index=df_filtered.index)
    if col_chauffeur:
        mask = mask | contains(df_filtered[col_chauffeur])
    if col_pnr:
        mask = mask | contains(df_filtered[col_pnr])
    if col_voertuignr:
        mask = mask | contains(df_filtered[col_voertuignr])
    elif col_voertuigtype:
        mask = mask | contains(df_filtered[col_voertuigtype])

    results = df_filtered[mask].copy()
    if results.empty:
        st.warning("Geen resultaten gevonden binnen de gekozen jaarfilter.")
        st.stop()

    # Coaching summary for first found pnr
    if col_pnr:
        pnr = str(results.iloc[0][col_pnr]).strip() if pd.notna(results.iloc[0][col_pnr]) else ""
        naam = str(results.iloc[0][col_chauffeur]).strip() if col_chauffeur and pd.notna(results.iloc[0][col_chauffeur]) else ""
        entries = coaching_map.get(pnr, [])
        entries = sorted(entries, key=lambda x: (x["date"] is pd.NaT, x["date"] or datetime.min))
        if entries:
            st.markdown(f"#### Coachings voor **{pnr}**{(' — ' + naam) if naam else ''}")
            st.write([e["date"].strftime("%d/%m/%Y") if isinstance(e["date"], pd.Timestamp) and pd.notna(e["date"]) else "" for e in entries])
        else:
            st.caption(f"Geen coachings gevonden voor P-nr {pnr}.")

    # Display table in same order as your JS
    cols = []
    def add(c): 
        if c and c in results.columns and c not in cols:
            cols.append(c)

    add(col_datum)
    add(col_chauffeur)
    add(col_pnr)
    add(col_voertuignr)
    add(col_voertuigtype)
    add(col_type)
    add(col_locatie)
    add(col_link)

    out = results[cols].copy()

    # format date
    if col_datum in out.columns:
        out[col_datum] = to_datetime_safe(out[col_datum]).dt.strftime("%d/%m/%Y")

    # clickable link
    if col_link in out.columns:
        out[col_link] = out[col_link].apply(lambda x: f"[=> naar EAF]({x})" if pd.notna(x) and str(x).strip() else "")

    st.dataframe(out, use_container_width=True, height=520)

elif page == "2. Chauffeur":
    st.subheader("Data rond chauffeur")

    # Teamcoach filter
    selected_coach = "ALL"
    if col_teamcoach and not df_filtered.empty:
        coaches = sorted(df_filtered[col_teamcoach].dropna().astype(str).str.strip().unique().tolist())
        selected_coach = st.selectbox("Teamcoach", ["ALL"] + coaches, format_func=lambda x: "Alle teamcoaches" if x == "ALL" else x)

    limit = st.selectbox("Toon", [10, 20, 0], format_func=lambda x: "Alle chauffeurs" if x == 0 else f"Top {x}")

    df_ch = df_filtered.copy()
    if selected_coach != "ALL" and col_teamcoach:
        df_ch = df_ch[df_ch[col_teamcoach].astype(str).str.strip() == selected_coach]

    if not col_chauffeur:
        st.warning("Kolom chauffeur/naam niet gevonden in BRON.")
        st.stop()

    counts = (
        df_ch.assign(_chauffeur=df_ch[col_chauffeur].fillna("Onbekend").astype(str).str.strip())
            .groupby("_chauffeur")
            .size()
            .reset_index(name="Aantal")
            .sort_values("Aantal", ascending=False)
    )

    if limit != 0:
        counts_view = counts.head(limit)
    else:
        counts_view = counts

    st.dataframe(counts_view, use_container_width=True, height=400)

    # details selector
    st.markdown("##### Details")
    selected_name = st.selectbox("Kies chauffeur", counts["_chauffeur"].tolist()[:200] if len(counts) > 0 else [])
    if selected_name:
        df_det = df_ch[df_ch[col_chauffeur].fillna("Onbekend").astype(str).str.strip() == selected_name].copy()

        show_cols = []
        def add2(cands):
            c = pick_col(df_det, cands)
            if c and c in df_det.columns and c not in show_cols:
                show_cols.append(c)

        add2(["datum"])
        add2(["locatie"])
        add2(["bus/ tram", "bus/tram", "voertuig", "voertuigtype"])
        add2(["link"])
        add2(["personeelsnr", "personeelsnummer", "p-nr", "p nr"])
        add2(["teamcoach"])

        df_show = df_det[show_cols].copy()
        if pick_col(df_show, ["datum"]):
            c = pick_col(df_show, ["datum"])
            df_show[c] = to_datetime_safe(df_show[c]).dt.strftime("%d/%m/%Y")

        c_link = pick_col(df_show, ["link"])
        if c_link:
            df_show[c_link] = df_show[c_link].apply(lambda x: f"[=> naar EAF]({x})" if pd.notna(x) and str(x).strip() else "")

        st.dataframe(df_show, use_container_width=True, height=420)

    st.markdown("##### Schades per teamcoach")
    if not col_teamcoach:
        st.info("Geen kolom 'teamcoach' gevonden in BRON.")
    else:
        tc_counts = (
            df_ch.assign(_tc=df_ch[col_teamcoach].fillna("").astype(str).str.strip())
                .query("_tc != ''")
                .groupby("_tc")
                .size()
                .reset_index(name="Aantal schades")
                .sort_values("Aantal schades", ascending=False)
        )
        if tc_counts.empty:
            st.info("Geen teamcoach data (na filters).")
        else:
            fig = px.bar(tc_counts, x="_tc", y="Aantal schades")
            fig.update_layout(xaxis_title="Teamcoach", yaxis_title="Aantal schades", height=360)
            st.plotly_chart(fig, use_container_width=True)

elif page == "3. Voertuig":
    st.subheader("Data rond voertuig (Bus/Tram)")

    if not col_voertuigtype:
        st.warning("Kolom voertuigtype (Bus/Tram/...) niet gevonden in BRON.")
        st.stop()

    limit = st.selectbox("Toon", [10, 20, 0], format_func=lambda x: "Alle types" if x == 0 else f"Top {x}")

    df_v = df_filtered.copy()
    df_v["_type"] = df_v[col_voertuigtype].fillna("Onbekend").astype(str).str.strip()

    counts = (
        df_v.groupby("_type")
            .size()
            .reset_index(name="Aantal")
            .sort_values("Aantal", ascending=False)
    )

    counts_view = counts if limit == 0 else counts.head(limit)
    st.dataframe(counts_view, use_container_width=True, height=360)

    st.markdown("##### Details")
    selected_type = st.selectbox("Kies voertuigtype", counts["_type"].tolist()[:200] if len(counts) > 0 else [])
    if selected_type:
        df_det = df_v[df_v["_type"] == selected_type].copy()

        show_cols = []
        def add2(cands):
            c = pick_col(df_det, cands)
            if c and c in df_det.columns and c not in show_cols:
                show_cols.append(c)

        add2(["volledige naam", "chauffeur", "naam", "bestuurder"])
        add2(["datum"])
        add2(["locatie"])
        add2(["link"])
        add2(["personeelsnr", "personeelsnummer", "p-nr", "p nr"])

        df_show = df_det[show_cols].copy()
        c_date = pick_col(df_show, ["datum"])
        if c_date:
            df_show[c_date] = to_datetime_safe(df_show[c_date]).dt.strftime("%d/%m/%Y")

        c_link = pick_col(df_show, ["link"])
        if c_link:
            df_show[c_link] = df_show[c_link].apply(lambda x: f"[=> naar EAF]({x})" if pd.notna(x) and str(x).strip() else "")

        st.dataframe(df_show, use_container_width=True, height=420)

    st.markdown("##### Schades per maand en voertuigtype (gestapelde balken)")
    if not col_datum:
        st.info("Geen datumkolom gevonden.")
    else:
        temp = df_v.copy()
        temp["_dt"] = to_datetime_safe(temp[col_datum])
        temp = temp.dropna(subset=["_dt"])
        temp["_maand"] = temp["_dt"].dt.month

        pivot = (
            temp.pivot_table(index="_maand", columns="_type", values=col_voertuigtype, aggfunc="count", fill_value=0)
                .sort_index()
        )
        # Ensure 1..12
        pivot = pivot.reindex(range(1, 13), fill_value=0)

        fig = go.Figure()
        for c in pivot.columns:
            fig.add_bar(name=c, x=[month_label(pd.Timestamp(2000, m, 1)) for m in pivot.index], y=pivot[c].values)
        fig.update_layout(barmode="stack", height=420, xaxis_title="Maand", yaxis_title="Aantal schades")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("##### Tendens per voertuigtype (lijngrafiek)")
        fig2 = go.Figure()
        for c in pivot.columns:
            fig2.add_scatter(
                name=c,
                x=[month_label(pd.Timestamp(2000, m, 1)) for m in pivot.index],
                y=pivot[c].values,
                mode="lines+markers"
            )
        fig2.update_layout(height=420, xaxis_title="Maand", yaxis_title="Aantal schades")
        st.plotly_chart(fig2, use_container_width=True)

elif page == "4. Locatie":
    st.subheader("Data rond locatie")

    if not col_locatie:
        st.warning("Kolom locatie niet gevonden in BRON.")
        st.stop()

    limit = st.selectbox("Toon", [10, 20, 0], format_func=lambda x: "Alle locaties" if x == 0 else f"Top {x}")

    df_l = df_filtered.copy()
    df_l["_loc"] = df_l[col_locatie].fillna("Onbekend").astype(str).str.strip()

    counts = (
        df_l.groupby("_loc")
            .size()
            .reset_index(name="Aantal")
            .sort_values("Aantal", ascending=False)
    )
    counts_view = counts if limit == 0 else counts.head(limit)
    st.dataframe(counts_view, use_container_width=True, height=400)

    st.markdown("##### Details")
    selected_loc = st.selectbox("Kies locatie", counts["_loc"].tolist()[:200] if len(counts) > 0 else [])
    if selected_loc:
        df_det = df_l[df_l["_loc"] == selected_loc].copy()

        show_cols = []
        def add2(cands):
            c = pick_col(df_det, cands)
            if c and c in df_det.columns and c not in show_cols:
                show_cols.append(c)

        add2(["volledige naam", "chauffeur", "naam", "bestuurder"])
        add2(["datum"])
        add2(["bus/ tram", "bus/tram", "voertuig", "voertuigtype"])
        add2(["link"])
        add2(["personeelsnr", "personeelsnummer", "p-nr", "p nr"])

        df_show = df_det[show_cols].copy()
        c_date = pick_col(df_show, ["datum"])
        if c_date:
            df_show[c_date] = to_datetime_safe(df_show[c_date]).dt.strftime("%d/%m/%Y")

        c_link = pick_col(df_show, ["link"])
        if c_link:
            df_show[c_link] = df_show[c_link].apply(lambda x: f"[=> naar EAF]({x})" if pd.notna(x) and str(x).strip() else "")

        st.dataframe(df_show, use_container_width=True, height=420)

elif page == "5. Coaching":
    st.subheader("Coaching – vergelijkingen")

    # ruwe counts
    pending_raw = int(df_pending.shape[0]) if df_pending is not None else 0
    done_raw = int(df_done.shape[0]) if df_done is not None else 0

    # pnr set in schade
    damage_pnr_set = set()
    if col_pnr and not df_bron.empty:
        damage_pnr_set = set(df_bron[col_pnr].dropna().astype(str).str.strip().tolist())

    done_pnr_set = set(coaching_map.keys())

    pending_in_damage = len([p for p in pending_set if p in damage_pnr_set])
    done_in_damage = len([p for p in done_pnr_set if p in damage_pnr_set])

    st.markdown(
        f"""
- 📄 Lopend – ruwe rijen (coachingslijst): **{pending_raw}**
- 🔵 Lopend (in schadelijst): **{pending_in_damage}**
- 📄 Voltooid – ruwe rijen (coachingslijst): **{done_raw}**
- 🟡 Voltooid (in schadelijst): **{done_in_damage}**
"""
    )

    # High damage without coaching (jaarfilter)
    st.markdown("##### P-nrs > 2 schades zonder coaching (jaarfilter)")
    if not col_pnr:
        st.info("Geen personeelsnummer kolom gevonden in BRON.")
    else:
        temp = df_filtered.copy()
        temp["_pnr"] = temp[col_pnr].fillna("").astype(str).str.strip()
        temp = temp[temp["_pnr"] != ""]
        grp = temp.groupby("_pnr").size().reset_index(name="Schades")
        grp = grp[grp["Schades"] > 2].copy()
        grp["Heeft coaching"] = grp["_pnr"].apply(lambda p: ("Ja" if (p in coaching_map or p in pending_set) else "Nee"))
        grp = grp[grp["Heeft coaching"] == "Nee"].sort_values("Schades", ascending=False)

        if grp.empty:
            st.success("Geen P-nrs gevonden die > 2 schades hebben en geen coaching.")
        else:
            st.dataframe(grp.rename(columns={"_pnr": "P-nr"}), use_container_width=True, height=420)

elif page == "6. Analyse":
    st.subheader("Analyse")

    if df_filtered.empty:
        st.info("Geen gegevens (na filters).")
        st.stop()

    st.markdown(f"#### 1. Totaal schades\nTotaal aantal schades (jaarfilter): **{len(df_filtered)}**")

    st.markdown("#### 2. Histogram — aantal schades per medewerker")
    if not col_pnr:
        st.info("Geen P-nr/personeelsnummer kolom gevonden.")
    else:
        damage_per = (
            df_filtered.assign(_pnr=df_filtered[col_pnr].fillna("").astype(str).str.strip())
                .query("_pnr != ''")
                .groupby("_pnr")
                .size()
        )

        # hastus all employees list
        if not df_hastus.empty:
            col_h_pnr = pick_col(df_hastus, ["p-nr", "pnr", "personeelsnr", "personeelsnummer", "p nr"])
            if col_h_pnr:
                all_h = pd.to_numeric(df_hastus[col_h_pnr], errors="coerce").dropna().astype(int).astype(str).tolist()
                damages_all = [int(damage_per.get(p, 0)) for p in all_h]
            else:
                damages_all = damage_per.values.tolist()
        else:
            damages_all = damage_per.values.tolist()

        if len(damages_all) == 0:
            st.info("Geen P-nrs gevonden.")
        else:
            median = float(np.median(damages_all))
            median_rounded = int(round(median))

            freq = pd.Series(damages_all).value_counts().sort_index()
            hist_df = freq.reset_index()
            hist_df.columns = ["Schades", "Aantal medewerkers"]

            fig = px.bar(hist_df, x="Schades", y="Aantal medewerkers")
            fig.add_vline(x=median_rounded, line_dash="dash")
            fig.update_layout(height=420)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f"Mediaan ≈ {median:.2f} (lijn op {median_rounded})")

    st.markdown("#### 3. Verdeling P-nrs per 10.000-tal (Hastus)")
    if df_hastus.empty:
        st.info('Geen P-nr gegevens gevonden in tabblad "data hastus".')
    else:
        col_h_pnr = pick_col(df_hastus, ["p-nr", "pnr", "personeelsnr", "personeelsnummer", "p nr"])
        if not col_h_pnr:
            st.info('Kolom P-nr niet gevonden in "data hastus".')
        else:
            pnrs = pd.to_numeric(df_hastus[col_h_pnr], errors="coerce").dropna().astype(int)
            st.write(f'Totaal P-nrs in "data hastus": **{len(pnrs)}**')

            bin_size = 10000
            bins = (pnrs // bin_size) * bin_size
            dist = bins.value_counts().sort_index().reset_index()
            dist.columns = ["BinStart", "Aantal P-nrs"]
            dist["Range"] = dist["BinStart"].apply(lambda x: f"{x}–{x+bin_size-1}")

            fig = px.bar(dist, x="Range", y="Aantal P-nrs")
            fig.update_layout(height=360, xaxis_tickangle=45)
            st.plotly_chart(fig, use_container_width=True)

elif page == "Gesprekken":
    st.subheader("Gesprekken")
    st.caption("Overzicht uit Overzicht gesprekken (aangepast).xlsx (respecteert de jaarfilter).")

    df_g = df_gesprekken.copy()

    # apply year filter on gesprekken
    if col_g_datum:
        df_g["_dt"] = to_datetime_safe(df_g[col_g_datum])
        if year_value != "ALL":
            df_g = df_g[df_g["_dt"].dt.year == int(year_value)]
    else:
        df_g["_dt"] = pd.NaT

    col1, col2 = st.columns([3, 1])
    with col1:
        q = st.text_input("Zoek personeelsnr of naam", placeholder="Zoek personeelsnr of naam...")
    with col2:
        reset = st.button("Reset")

    if reset:
        q = ""
        st.rerun()

    if q:
        term = q.strip().lower()
        mask = pd.Series(False, index=df_g.index)
        if col_g_nummer:
            mask = mask | df_g[col_g_nummer].fillna("").astype(str).str.lower().str.contains(term, na=False)
        if col_g_naam:
            mask = mask | df_g[col_g_naam].fillna("").astype(str).str.lower().str.contains(term, na=False)
        df_g = df_g[mask]

    # format date
    if col_g_datum:
        df_g[col_g_datum] = df_g["_dt"].dt.strftime("%d/%m/%Y")

    show_cols = []
    for c in [col_g_nummer, col_g_naam, col_g_datum, col_g_onderwerp, col_g_info]:
        if c and c in df_g.columns and c not in show_cols:
            show_cols.append(c)

    st.caption(f"Resultaten: {len(df_g)}")
    st.dataframe(df_g[show_cols], use_container_width=True, height=560)
