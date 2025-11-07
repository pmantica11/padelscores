import streamlit as st
import requests
import pandas as pd
import trueskill

# ---------------------------
# ELO / TrueSkill LOGIC
# ---------------------------
def calculate_team_trueskill(df, starting_mu=4, starting_sigma=1):
    ratings = {}
    for _, row in df.iterrows():
        t1_p1, t1_p2 = row['team_1_player_left'], row['team_1_player_right']
        t2_p1, t2_p2 = row['team_2_player_left'], row['team_2_player_right']

        # Initialize players if not seen before
        for p in [t1_p1, t1_p2, t2_p1, t2_p2]:
            if p not in ratings:
                ratings[p] = trueskill.Rating(mu=starting_mu, sigma=starting_sigma)

        s1, s2 = row['team_1_score'], row['team_2_score']

        # Process each individual game
        for _ in range(s1):  # Team 1 wins
            team1 = [ratings[t1_p1], ratings[t1_p2]]
            team2 = [ratings[t2_p1], ratings[t2_p2]]
            new_team1, new_team2 = trueskill.rate([team1, team2], ranks=[0, 1])
            ratings[t1_p1], ratings[t1_p2] = new_team1
            ratings[t2_p1], ratings[t2_p2] = new_team2

        for _ in range(s2):  # Team 2 wins
            team1 = [ratings[t1_p1], ratings[t1_p2]]
            team2 = [ratings[t2_p1], ratings[t2_p2]]
            new_team1, new_team2 = trueskill.rate([team1, team2], ranks=[1, 0])
            ratings[t1_p1], ratings[t1_p2] = new_team1
            ratings[t2_p1], ratings[t2_p2] = new_team2

    ratings = {name: round(rating.mu, 2) for name, rating in ratings.items()}
    series = pd.Series(ratings).sort_values(ascending=False)
    return series


def get_sheet_data(spreadsheet_id, sheet_name, api_key):
    """Fetch Google Sheets data using the public API key."""
    url = f"https://sheets.googleapis.com/v4/spreadsheets/{spreadsheet_id}/values/{sheet_name}?key={api_key}"
    response = requests.get(url)
    response.raise_for_status()
    data = response.json()

    rows = data.get("values", [])
    headers = rows[0]
    records = rows[1:]
    df = pd.DataFrame(records, columns=headers)

    df["team_1_score"] = pd.to_numeric(df["team_1_score"])
    df["team_2_score"] = pd.to_numeric(df["team_2_score"])

    return df


# ---------------------------
# STREAMLIT APP
# ---------------------------
st.title("🏓 TrueSkill Player Rankings")

# Load credentials securely from Streamlit secrets
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
SHEET_NAME = st.secrets["SHEET_NAME"]
API_KEY = st.secrets["API_KEY"]

# Fetch and calculate ratings
try:
    with st.spinner("Fetching data from Google Sheets..."):
        df = get_sheet_data(SPREADSHEET_ID, SHEET_NAME, API_KEY)

    with st.spinner("Calculating TrueSkill ratings..."):
        ratings = calculate_team_trueskill(df)

    st.success(f"✅ Loaded {len(df)} matches and calculated ratings for {len(ratings)} players!")

    # Display ratings
    st.subheader("Player Rankings")
    ratings_df = ratings.reset_index()
    ratings_df.columns = ['Player', 'TrueSkill Rating']
    ratings_df.index = ratings_df.index + 1
    st.dataframe(ratings_df, use_container_width=True)

    if st.button("🔄 Refresh Data"):
        st.rerun()

except Exception as e:
    st.error(f"Error: {str(e)}")
    st.info("Please check your Google Sheets credentials in Streamlit secrets.")
