import requests
import json
import sys
import time
import csv
import os
import hashlib
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def get_oauth_token(client_id, client_secret):
    """
    Get OAuth token from osu! API
    """
    url = "https://osu.ppy.sh/oauth/token"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/x-www-form-urlencoded"
    }

    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "grant_type": "client_credentials",
        "scope": "public"
    }

    response = requests.post(url, headers=headers, data=data)

    if response.status_code == 200:
        token_data = response.json()
        return token_data["access_token"]
    else:
        print(f"Error getting OAuth token: {response.status_code}")
        print(response.text)
        sys.exit(1)

def get_user_scores(token, user, type="recent", params=None):
    """
    Get scores for a specific user from osu! API
    """
    url = f"https://osu.ppy.sh/api/v2/users/{user}/scores/{type}"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # Initialize query parameters
    query_params = {"limit": 1000}

    # Add any additional parameters
    if params:
        query_params.update(params)

    response = requests.get(url, headers=headers, params=query_params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error getting scores for user {user}: {response.status_code}")
        print(response.text)
        return None

def generate_score_hash(score_data):
    """
    Generate a unique hash for a score to prevent duplicates
    
    Can work with either a score API response or a CSV row
    """
    # Extract the necessary fields, handling both API response and CSV row
    score_id = str(score_data.get('id', ''))
    user_id = str(score_data.get('user_id', ''))
    beatmap_id = str(score_data.get('beatmap_id', ''))
    created_at = str(score_data.get('created_at', ''))
    
    # Create a string with the most important identifying information
    unique_string = f"{score_id}{user_id}{beatmap_id}{created_at}"
    
    # Generate a hash
    return hashlib.md5(unique_string.encode()).hexdigest()

def load_existing_scores(output_file):
    """
    Load existing scores from CSV to prevent duplicates
    """
    existing_hashes = set()
    score_ids = set()

    if os.path.isfile(output_file) and os.path.getsize(output_file) > 0:
        try:
            with open(output_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Add score ID to our set for a simpler duplicate check
                    if 'id' in row and row['id']:
                        score_ids.add(str(row['id']))
                    
                    # Also create a hash for more robust checking
                    score_hash = generate_score_hash(row)
                    existing_hashes.add(score_hash)
            
            print(f"Successfully loaded {len(existing_hashes)} existing scores from {output_file}")
        except Exception as e:
            print(f"Warning: Could not read existing scores: {e}")

    return existing_hashes, score_ids

def process_scores(scores_data, output_file, existing_hashes, existing_ids):
    """
    Process scores and append them to CSV,
    avoiding duplicates using the hash set and ID set
    """
    # Extract scores from the response
    if not scores_data or not isinstance(scores_data, list) or len(scores_data) == 0:
        print("No valid scores data found")
        return 0, [], []

    # Find scores that aren't duplicates
    new_scores = []
    new_hashes = set()
    new_ids = set()

    for score in scores_data:
        # Get the score ID for a quick check
        score_id = str(score.get('id', ''))
        
        # Skip if we've already seen this ID
        if score_id in existing_ids:
            continue
            
        # Generate a hash for more thorough checking
        score_hash = generate_score_hash(score)
        
        # If neither the ID nor hash exists, it's a new score
        if score_hash not in existing_hashes:
            new_scores.append(score)
            new_hashes.add(score_hash)
            new_ids.add(score_id)

    if not new_scores:
        print("No new scores found")
        return 0, [], []

    # Prepare scores for CSV
    all_fields = set()
    flat_scores = []

    for score in new_scores:
        flat_score = {}

        # Process each field in the score
        for key, value in score.items():
            if isinstance(value, dict):
                # Flatten nested dictionaries
                for subkey, subvalue in value.items():
                    flat_key = f"{key}_{subkey}"
                    flat_score[flat_key] = subvalue
                    all_fields.add(flat_key)
            elif key == "mods" and isinstance(value, list):
                # Extract mod acronyms
                mod_list = [mod.get("acronym", "") for mod in value if isinstance(mod, dict) and "acronym" in mod]
                flat_score["mods"] = ",".join(mod_list)
                all_fields.add("mods")
            else:
                flat_score[key] = value
                all_fields.add(key)

        flat_scores.append(flat_score)

    # Check if the file exists to determine if we need to write headers
    file_exists = os.path.isfile(output_file) and os.path.getsize(output_file) > 0

    # Get existing headers if file exists
    existing_fields = []
    if file_exists:
        try:
            with open(output_file, 'r', newline='', encoding='utf-8') as f:
                reader = csv.reader(f)
                existing_fields = next(reader)  # Get header row
        except Exception as e:
            print(f"Warning: Could not read existing headers: {e}")

    # Combine existing fields with new fields
    if existing_fields:
        all_fields.update(existing_fields)

    # Append to CSV
    with open(output_file, 'a', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=sorted(all_fields))
        if not file_exists:
            writer.writeheader()
        writer.writerows(flat_scores)

    print(f"Added {len(flat_scores)} new scores to {output_file}")
    return len(flat_scores), new_hashes, new_ids

def main():
    # Load credentials from .env file
    client_id = os.getenv('OSU_CLIENT_ID')
    client_secret = os.getenv('OSU_CLIENT_SECRET')
    output_file = os.getenv('CSV_OUTPUT_FILE', 'scores.csv')
    
    # Get polling interval from env or default to 10 seconds
    try:
        poll_interval = int(os.getenv('POLL_INTERVAL', '10'))
    except ValueError:
        poll_interval = 10
        print(f"Warning: Invalid POLL_INTERVAL in .env, using default of {poll_interval} seconds")

    # Parse user IDs from environment variable
    users_str = os.getenv('USER_IDS', '14852499')
    try:
        users = [int(uid.strip()) for uid in users_str.split(',')]
    except ValueError:
        print("Error: User IDs in .env file must be integers separated by commas")
        sys.exit(1)

    # Fallback to command line arguments if provided
    if len(sys.argv) > 1:
        client_id = sys.argv[1]
        client_secret = sys.argv[2]
        output_file = sys.argv[3] if len(sys.argv) > 3 else output_file

        # Parse user IDs if provided
        if len(sys.argv) > 4:
            try:
                users = [int(uid.strip()) for uid in sys.argv[4].split(',')]
            except ValueError:
                print("Error: User IDs must be integers separated by commas")
                sys.exit(1)

    # Load existing scores to prevent duplicates
    print(f"Loading existing scores from {output_file}...")
    existing_hashes, existing_ids = load_existing_scores(output_file)
    print(f"Loaded {len(existing_hashes)} existing score hashes")

    # Get initial token
    print(f"Starting to monitor scores for users: {users}")
    print(f"Results will be saved to: {output_file}")
    print(f"Polling every {poll_interval} seconds")
    token = get_oauth_token(client_id, client_secret)

    try:
        total_scores_added = 0

        while True:
            for user_id in users:
                print(f"Getting scores for user {user_id}...")
                scores = get_user_scores(token, user_id)
                
                if scores:
                    added, new_hashes, new_ids = process_scores(scores, output_file, existing_hashes, existing_ids)

                    # Update our hash set and ID set with new scores
                    existing_hashes.update(new_hashes)
                    existing_ids.update(new_ids)
                    total_scores_added += added

                    if added > 0:
                        print(f"Total scores tracked so far: {total_scores_added}")

            # Sleep before next poll
            print(f"Waiting {poll_interval} seconds for next poll...")
            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\nMonitoring stopped by user")
        print(f"Total scores tracked: {total_scores_added}")

    except Exception as e:
        print(f"Error: {e}")
        # Try to refresh token on error
        try:
            print("Attempting to refresh OAuth token...")
            token = get_oauth_token(client_id, client_secret)
        except:
            print("Could not refresh token. Exiting.")
            sys.exit(1)

if __name__ == "__main__":
    main()
