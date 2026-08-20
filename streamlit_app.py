import streamlit as st
import requests
import pandas as pd
import trueskill

# ---------------------------
# CONFIG
# ---------------------------

# First 155 matches use the original 1x behavior.
# Match 156 onward uses 2x behavior.
LEGACY_GAME_COUNT = 155
NEW_GAME_MULTIPLIER = 2

# These players still participate in TrueSkill calculations,
# but are hidden from the final leaderboard.
EXCLUDED_PLAYERS = {
    "Roberto",
    "MarioC",
    "Sebastian",
}


# ---------------------------
# TRUESKILL LOGIC
# ---------------------------

def calculate_team_trueskill(df, starting_mu=4, starting_sigma=1):
    ratings = {}

    # Special starting rating
    ratings["Charlie"] = trueskill.Rating(
        mu=5.25,
        sigma=starting_sigma
    )

    for game_index, (_, row) in enumerate(df.iterrows()):
        t1_p1 = str(row["team_1_player_left"]).strip()
        t1_p2 = str(row["team_1_player_right"]).strip()
        t2_p1 = str(row["team_2_player_left"]).strip()
        t2_p2 = str(row["team_2_player_right"]).strip()

        players = [
            t1_p1,
            t1_p2,
            t2_p1,
            t2_p2,
        ]

        # Skip incomplete rows
        if any(not player for player in players):
            continue

        # Initialize ALL players, including excluded players.
        # Their matches still affect teammates and opponents.
        for player in players:
            if player not in ratings:
                ratings[player] = trueskill.Rating(
                    mu=starting_mu,
                    sigma=starting_sigma
                )

        s1 = int(row["team_1_score"])
        s2 = int(row["team_2_score"])

        # Matches 1-155:
        # use the original 1x behavior.
        #
        # Match 156 onward:
        # process each win/loss twice.
        multiplier = (
            1
            if game_index < LEGACY_GAME_COUNT
            else NEW_GAME_MULTIPLIER
        )

        # ---------------------------
        # TEAM 1 WINS
        # ---------------------------

        for _ in range(s1 * multiplier):
            team1 = [
                ratings[t1_p1],
                ratings[t1_p2],
            ]

            team2 = [
                ratings[t2_p1],
                ratings[t2_p2],
            ]

            new_team1, new_team2 = trueskill.rate(
                [team1, team2],
                ranks=[0, 1]
            )

            ratings[t1_p1], ratings[t1_p2] = new_team1
            ratings[t2_p1], ratings[t2_p2] = new_team2

        # ---------------------------
        # TEAM 2 WINS
        # ---------------------------

        for _ in range(s2 * multiplier):
            team1 = [
                ratings[t1_p1],
                ratings[t1_p2],
            ]

            team2 = [
                ratings[t2_p1],
                ratings[t2_p2],
            ]

            new_team1, new_team2 = trueskill.rate(
                [team1, team2],
                ranks=[1, 0]
            )

            ratings[t1_p1], ratings[t1_p2] = new_team1
            ratings[t2_p1], ratings[t2_p2] = new_team2

    # Hide excluded players from the leaderboard,
    # but keep their games in all rating calculations.
    visible_ratings = {
        name: round(rating.mu, 2)
        for name, rating in ratings.items()
        if name not in EXCLUDED_PLAYERS
    }

    return pd.Series(
        visible_ratings
    ).sort_values(ascending=False)


def assign_titles(ratings_series):
    """
    Assign titles based on rankings:

    - Challenger: rank 1
    - Master: ranks 2-3
    - Gold, Silver, Bronze: divided among remaining players
    """

    titles = {}
    total_players = len(ratings_series)

    if total_players == 0:
        return titles

    # Challenger: rank 1
    if total_players >= 1:
        titles[ratings_series.index[0]] = "👑"

    # Master: ranks 2-3
    if total_players >= 2:
        titles[ratings_series.index[1]] = "💎"

    if total_players >= 3:
        titles[ratings_series.index[2]] = "💎"

    # Remaining players divided into:
    # Gold, Silver, Bronze
    remaining_players = total_players - 3

    if remaining_players > 0:
        base_count = remaining_players // 3
        remainder = remaining_players % 3

        # Extra players go to Bronze first,
        # then Silver.
        bronze_count = (
            base_count
            + (1 if remainder >= 1 else 0)
        )

        silver_count = (
            base_count
            + (1 if remainder >= 2 else 0)
        )

        gold_count = base_count

        idx = 3

        # Gold
        for _ in range(gold_count):
            if idx < total_players:
                titles[
                    ratings_series.index[idx]
                ] = "🥇"

                idx += 1

        # Silver
        for _ in range(silver_count):
            if idx < total_players:
                titles[
                    ratings_series.index[idx]
                ] = "🥈"

                idx += 1

        # Bronze
        for _ in range(bronze_count):
            if idx < total_players:
                titles[
                    ratings_series.index[idx]
                ] = "🥉"

                idx += 1

    return titles


# ---------------------------
# GOOGLE SHEETS
# ---------------------------

def get_sheet_data(
    spreadsheet_id,
    sheet_name,
    api_key
):
    """
    Fetch Google Sheets data using the public API key.
    """

    url = (
        "https://sheets.googleapis.com/v4/spreadsheets/"
        f"{spreadsheet_id}/values/{sheet_name}"
        f"?key={api_key}"
    )

    response = requests.get(
        url,
        timeout=10
    )

    response.raise_for_status()

    data = response.json()

    rows = data.get("values", [])

    if not rows:
        raise ValueError(
            "Google Sheet returned no data."
        )

    headers = rows[0]

    # Google Sheets may omit trailing blank cells.
    # Pad every row to the same number of columns.
    records = [
        row + [""] * (len(headers) - len(row))
        for row in rows[1:]
    ]

    df = pd.DataFrame(
        records,
        columns=headers
    )

    required_columns = [
        "team_1_player_left",
        "team_1_player_right",
        "team_2_player_left",
        "team_2_player_right",
        "team_1_score",
        "team_2_score",
    ]

    missing_columns = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing_columns:
        raise ValueError(
            "Missing required columns: "
            + ", ".join(missing_columns)
        )

    df["team_1_score"] = pd.to_numeric(
        df["team_1_score"],
        errors="coerce"
    )

    df["team_2_score"] = pd.to_numeric(
        df["team_2_score"],
        errors="coerce"
    )

    # Remove rows without valid scores.
    df = df.dropna(
        subset=[
            "team_1_score",
            "team_2_score",
        ]
    )

    # Reset index so the first 155 valid rows
    # are always the legacy matches.
    df = df.reset_index(drop=True)

    return df


# ---------------------------
# STREAMLIT APP
# ---------------------------

# Load credentials securely from Streamlit secrets.
SPREADSHEET_ID = st.secrets["SPREADSHEET_ID"]
SHEET_NAME = st.secrets["SHEET_NAME"]
API_KEY = st.secrets["API_KEY"]


try:
    # ---------------------------
    # FETCH DATA
    # ---------------------------

    with st.spinner(
        "Fetching data from Google Sheets..."
    ):
        df = get_sheet_data(
            SPREADSHEET_ID,
            SHEET_NAME,
            API_KEY
        )

    # ---------------------------
    # CALCULATE RATINGS
    # ---------------------------

    with st.spinner(
        "Calculating TrueSkill ratings..."
    ):
        ratings = calculate_team_trueskill(df)
        titles = assign_titles(ratings)

    # ---------------------------
    # DISPLAY RANKINGS
    # ---------------------------

    st.subheader("Player Rankings")

    ratings_df = (
        ratings
        .rename("Rating")
        .reset_index()
    )

    ratings_df.columns = [
        "Player",
        "Rating",
    ]

    ratings_df["Title"] = (
        ratings_df["Player"].map(titles)
    )

    ratings_df = ratings_df[
        [
            "Player",
            "Title",
            "Rating",
        ]
    ]

    st.dataframe(
        ratings_df,
        hide_index=True,
        use_container_width=True
    )


except Exception as e:
    st.error(
        f"Error: {str(e)}"
    )

    st.info(
        "Please check your Google Sheets "
        "credentials in Streamlit secrets."
    )
