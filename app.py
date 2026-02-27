# ============================================================
#  Strava Running Analyser  –  Streamlit app  v4
# ============================================================

import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime, timedelta
from stravalib import Client

try:
    from dotenv import load_dotenv
    import pathlib
    load_dotenv(dotenv_path=pathlib.Path(__file__).parent / ".env")
except ImportError:
    pass

# ============================================================
# CONFIGURATION
# ============================================================

CLIENT_ID     = os.environ.get("STRAVA_CLIENT_ID") or st.secrets.get("STRAVA_CLIENT_ID")
CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET") or st.secrets.get("STRAVA_CLIENT_SECRET")
REDIRECT_URI = "https://hr-zone-compiler-gp.streamlit.app"


ZONE_COLORS = {
    "Z1": "#74c7ec",
    "Z2": "#89dceb",
    "Z3": "#a6e3a1",
    "Z4": "#fab387",
    "Z5": "#f38ba8",
}

RUNNING_TYPES = {"Run", "TrailRun", "VirtualRun"}


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def classify_zone(hr):
    if hr is None or (isinstance(hr, float) and pd.isna(hr)):
        return None
    for zone, (lo, hi) in HR_ZONES.items():
        if lo <= hr <= hi:
            return zone
    return None


def to_float(val):
    """Safely extract a float from stravalib quantity objects."""
    if val is None:
        return None
    try:
        return float(val.magnitude if hasattr(val, 'magnitude') else val)
    except Exception:
        return None


def to_seconds(val):
    """Safely extract seconds from a stravalib Duration or timedelta."""
    if val is None:
        return None
    if hasattr(val, 'seconds'):
        return val.seconds
    if hasattr(val, 'total_seconds'):
        return val.total_seconds()
    try:
        return int(val)
    except Exception:
        return None


def get_auth_url(client):
    return client.authorization_url(
        client_id    = CLIENT_ID,
        redirect_uri = REDIRECT_URI,
        scope        = ["activity:read_all"],
    )


def exchange_token(client, code):
    return client.exchange_code_for_token(
        client_id     = CLIENT_ID,
        client_secret = CLIENT_SECRET,
        code          = code,
    )


# ============================================================
# DATA FETCHING
# ============================================================

@st.cache_data(ttl=600, show_spinner="Fetching activities...")
def fetch_activities(_client, start_date, end_date):
    start_dt = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
    end_dt   = datetime(end_date.year,   end_date.month,   end_date.day,   23, 59, 59)

    acts = list(_client.get_activities(after=start_dt, before=end_dt))

    rows = []
    for a in acts:
        sport = a.sport_type.root if hasattr(a.sport_type, 'root') else str(a.sport_type)
        if sport not in RUNNING_TYPES:
            continue

        secs = to_seconds(a.moving_time)
        dist = to_float(a.distance)

        rows.append({
            "id"          : str(a.id),
            "date"        : a.start_date_local.strftime("%Y-%m-%d %H:%M") if a.start_date_local else None,
            "sport_type"  : sport,
            "distance_km" : round(dist / 1000, 2) if dist else None,
            "duration_min": round(secs / 60, 1)   if secs else None,
            "elevation_m" : to_float(a.total_elevation_gain),
            "avg_hr"      : to_float(a.average_heartrate),
        })

    return pd.DataFrame(rows)


@st.cache_data(ttl=600, show_spinner=False)
def fetch_hr_zones(_client, act_id):
    """
    Fetch HR stream for one activity.
    Returns dict {Z1: pct, Z2: pct, ...} or empty dict if no HR data.
    """
    try:
        streams = _client.get_activity_streams(
            activity_id = int(act_id),
            types       = ["heartrate", "time"],
            resolution  = "high",
        )
    except Exception:
        return {}

    if "heartrate" not in streams:
        return {}

    hr_values = streams["heartrate"].data
    total     = len(hr_values)
    if total == 0:
        return {}

    counts = {z: 0 for z in HR_ZONES}
    for hr in hr_values:
        z = classify_zone(hr)
        if z:
            counts[z] += 1

    return {z: round(counts[z] / total * 100, 1) for z in HR_ZONES}


# ============================================================
# SESSION STATE
# ============================================================

if "token"    not in st.session_state: st.session_state.token    = None
if "client"   not in st.session_state: st.session_state.client   = Client()
if "zones_df" not in st.session_state: st.session_state.zones_df = None
if "df"       not in st.session_state: st.session_state.df       = None

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title = "HR Zone compiler",
    page_icon  = "🏃",
    layout     = "wide",
)
st.title("🏃❤️ HR Zone compiler by G.Pastore")
st.subheader("Instructions")
st.markdown("This app fetches your uploaded activities in a selected date range. It computes the % of time spent in each Heart Rate Zone.")

# ============================================================
# AUTHENTICATION
# ============================================================

client = st.session_state.client

query_params = st.query_params
if "code" in query_params and st.session_state.token is None:
    with st.spinner("Authenticating with Strava..."):
        try:
            token = exchange_token(client, query_params["code"])
            st.session_state.token = token
            client.access_token    = token["access_token"]
            st.query_params.clear()
            st.rerun()
        except Exception as e:
            st.error(f"Authentication failed: {e}")

if st.session_state.token is None:
    st.info("Connect your Strava account to get started.")
    auth_url = get_auth_url(client)
    st.markdown(
        f'<a href="{auth_url}" target="_self">'
        f'<button style="background:#fc4c02;color:white;padding:12px 32px;'
        f'border:none;border-radius:6px;font-size:18px;cursor:pointer;font-weight:bold;">'
        f'🔗 Connect with Strava</button></a>',
        unsafe_allow_html=True,
    )
    st.stop()

client.access_token = st.session_state.token["access_token"]

try:
    athlete = client.get_athlete()
    st.sidebar.success(f"✅ **{athlete.firstname} {athlete.lastname}**")
except Exception:
    st.sidebar.warning("Could not fetch athlete info.")

if st.sidebar.button("🔓 Log out"):
    st.session_state.token    = None
    st.session_state.client   = Client()
    st.session_state.zones_df = None
    st.rerun()


# ============================================================
# SIDEBAR — DATE RANGE & LOAD
# ============================================================

st.sidebar.header("📅 Date range")
start_date = st.sidebar.date_input("Start date", value=date.today() - timedelta(days=30))
end_date   = st.sidebar.date_input("End date",   value=date.today())

if start_date > end_date:
    st.sidebar.error("Start date must be before end date.")
    st.stop()

st.sidebar.header("❤️ HR Zone boundaries (bpm)")
st.sidebar.caption("Set the UPPER limit of each zone. Z1 always starts at 0, Z5 ends at 220.")

z1_max = st.sidebar.number_input("Z1 upper limit", min_value=100, max_value=220, value=153, step=1)
z2_max = st.sidebar.number_input("Z2 upper limit", min_value=100, max_value=220, value=162, step=1)
z3_max = st.sidebar.number_input("Z3 upper limit", min_value=100, max_value=220, value=171, step=1)
z4_max = st.sidebar.number_input("Z4 upper limit", min_value=100, max_value=220, value=181, step=1)

# Validate they are in increasing order
if not (z1_max < z2_max < z3_max < z4_max):
    st.sidebar.error("Zone limits must be in increasing order: Z1 < Z2 < Z3 < Z4.")
    st.stop()

# Override the global HR_ZONES with user values
HR_ZONES = {
    "Z1": (0,         z1_max),
    "Z2": (z1_max+1,  z2_max),
    "Z3": (z2_max+1,  z3_max),
    "Z4": (z3_max+1,  z4_max),
    "Z5": (z4_max+1,  220),
}

if st.sidebar.button("🔄 Load activities", type="primary"):
    fetch_activities.clear()
    fetch_hr_zones.clear()
    st.session_state.zones_df = None
    st.session_state.df       = fetch_activities(client, start_date, end_date)


# ============================================================
# FETCH ACTIVITIES
# ============================================================

if st.session_state.df is None:
    st.info("👈 Set a date range and press **Load activities** to begin.")
    st.stop()

df = st.session_state.df

if df.empty:
    st.warning("No running activities found in the selected date range.")
    st.stop()

st.subheader(f"Found **{len(df)}** running activities")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Total distance",  f"{df['distance_km'].sum():.1f} km")
c2.metric("Total time",      f"{df['duration_min'].sum():.0f} min")
c3.metric("Total D+",        f"{df['elevation_m'].sum():.0f} m")
c4.metric("Avg heart rate",
          f"{df['avg_hr'].mean():.0f} bpm" if df['avg_hr'].notna().any() else "N/A")

st.divider()


# ============================================================
# FETCH HR ZONE STREAMS FOR ALL ACTIVITIES
# ============================================================

if st.session_state.zones_df is None:
    progress_bar = st.progress(0, text="Fetching HR streams...")
    zone_rows = []
    for i, act_id in enumerate(df["id"]):
        pct = fetch_hr_zones(client, act_id)
        zone_rows.append({"id": act_id, **pct})
        progress_bar.progress(
            (i + 1) / len(df),
            text=f"Fetching HR streams... {i + 1}/{len(df)}"
        )
    progress_bar.empty()
    st.session_state.zones_df = pd.DataFrame(zone_rows)

zones_df = st.session_state.zones_df
full_df  = df.merge(zones_df, on="id", how="left")


# ============================================================
# 1. ACTIVITY TABLE
# ============================================================

st.subheader("📋 Activity log")

display_cols = ["date", "sport_type", "distance_km", "duration_min",
                "elevation_m", "avg_hr", "Z1", "Z2", "Z3", "Z4", "Z5"]
# Only show zone cols that exist (activities without HR will be missing them)
display_cols = [c for c in display_cols if c in full_df.columns]

st.dataframe(full_df[display_cols], use_container_width=True, hide_index=True)
st.divider()


# ============================================================
# 2. WEEKLY DISTANCE
# ============================================================

st.subheader("📈 Weekly distance (km)")

weekly_df       = full_df.copy()
weekly_df["week"] = pd.to_datetime(weekly_df["date"]).dt.to_period("W").apply(
    lambda r: r.start_time
)
weekly = weekly_df.groupby("week")["distance_km"].sum().reset_index()

fig_weekly = px.bar(
    weekly, x="week", y="distance_km",
    labels={"week": "Week", "distance_km": "Distance (km)"},
    color_discrete_sequence=["#fc4c02"],
)
fig_weekly.update_layout(showlegend=False)
st.plotly_chart(fig_weekly, use_container_width=True)
st.divider()


# ============================================================
# 3. AVERAGE % TIME IN EACH ZONE ACROSS ALL ACTIVITIES
# ============================================================

st.subheader("❤️ Average % time in each HR zone (all activities)")

zone_cols  = [z for z in ["Z1", "Z2", "Z3", "Z4", "Z5"] if z in full_df.columns]
zone_means = full_df[zone_cols].mean().reset_index()
zone_means.columns = ["zone", "avg_pct"]

fig_zones = px.bar(
    zone_means, x="zone", y="avg_pct",
    color="zone", color_discrete_map=ZONE_COLORS,
    labels={"zone": "HR Zone", "avg_pct": "Avg % of activity time"},
    text="avg_pct",
)
fig_zones.update_traces(texttemplate="%{text:.1f}%", textposition="outside")
fig_zones.update_layout(showlegend=False, yaxis_range=[0, 100])
st.plotly_chart(fig_zones, use_container_width=True)
st.divider()


# ============================================================
# 4. PER-ACTIVITY HR ZONE BREAKDOWN
# ============================================================

st.subheader("🔍 Per-activity HR zone breakdown")

activity_options = {
    f"{row['date']}  —  {row['distance_km']} km  ({row['sport_type']})": row["id"]
    for _, row in full_df.sort_values("date", ascending=False).iterrows()
}

selected_label = st.selectbox("Choose an activity", list(activity_options.keys()))
selected_id    = activity_options[selected_label]
sel            = full_df[full_df["id"] == selected_id].iloc[0]

act_zone_data  = {z: sel.get(z, 0) or 0 for z in zone_cols}
has_hr         = any(v > 0 for v in act_zone_data.values())

left, right = st.columns([3, 1])

with left:
    if not has_hr:
        st.warning("No HR stream data for this activity.")
    else:
        zone_plot_df = pd.DataFrame({
            "zone": list(act_zone_data.keys()),
            "pct" : list(act_zone_data.values()),
        })
        fig_donut = go.Figure(go.Pie(
            labels        = zone_plot_df["zone"],
            values        = zone_plot_df["pct"],
            hole          = 0.55,
            marker        = dict(colors=[ZONE_COLORS[z] for z in zone_plot_df["zone"]]),
            textinfo      = "label+percent",
            hovertemplate = "<b>%{label}</b><br>%{value:.1f}%<extra></extra>",
        ))
        fig_donut.update_layout(showlegend=True, margin=dict(t=20, b=20, l=20, r=20))
        st.plotly_chart(fig_donut, use_container_width=True)

with right:
    st.markdown("### 📌 Details")
    st.markdown(f"**Date**")
    st.markdown(f"{sel['date']}")
    st.markdown("---")
    st.markdown(f"**Distance**")
    st.markdown(f"{sel['distance_km']} km")
    st.markdown("---")
    st.markdown(f"**Duration**")
    st.markdown(f"{sel['duration_min']} min")
    st.markdown("---")
    st.markdown(f"**Elevation gain**")
    st.markdown(f"{sel['elevation_m']:.0f} m")
    if sel['avg_hr']:
        st.markdown("---")
        st.markdown(f"**Avg HR**")
        st.markdown(f"{sel['avg_hr']:.0f} bpm")

st.divider()


# ============================================================
# 5. DOWNLOAD BUTTON  (large, full width, Strava orange)
# ============================================================

st.markdown(
    """
    <style>
    div.stDownloadButton > button {
        width: 100%;
        padding: 20px;
        font-size: 22px;
        font-weight: bold;
        background-color: #fc4c02;
        color: white;
        border: none;
        border-radius: 8px;
        cursor: pointer;
    }
    div.stDownloadButton > button:hover {
        background-color: #e04000;
        color: white;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

csv = full_df.to_csv(index=False).encode("utf-8")
st.download_button(
    label     = "⬇️  Download full activity log as CSV",
    data      = csv,
    file_name = f"strava_runs_{start_date}_{end_date}.csv",
    mime      = "text/csv",
)




