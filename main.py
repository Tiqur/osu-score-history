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

def get_scores(token, ruleset="osu", params=None):
    """
    Get scores from osu! API
    """
    url = "https://osu.ppy.sh/api/v2/scores"

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Authorization": f"Bearer {token}"
    }

    # Initialize query parameters with ruleset
    query_params = {"ruleset": ruleset}

    # Add any additional parameters
    if params:
        query_params.update(params)

    response = requests.get(url, headers=headers, params=query_params)

    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error getting scores: {response.status_code}")
        print(response.text)
        return None

def generate_score_hash(score):
    """
    Generate a unique hash for a score to prevent duplicates
    """
    # Create a string with the most important identifying information
    unique_string = f"{score.get('id', '')}{score.get('user_id', '')}{score.get('beatmap_id', '')}{score.get('created_at', '')}"
    
    # Generate a hash
    return hashlib.md5(unique_string.encode()).hexdigest()

def load_existing_scores(output_file):
    """
    Load existing scores from CSV to prevent duplicates
    """
    existing_hashes = set()
    
    if os.path.isfile(output_file) and os.path.getsize(output_file) > 0:
        try:
            with open(output_file, 'r', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Create a hash from the stored data
                    unique_string = f"{row.get('id', '')}{row.get('user_id', '')}{row.get('beatmap_id', '')}{row.get('created_at', '')}"
                    score_hash = hashlib.md5(unique_string.encode()).hexdigest()
                    existing_hashes.add(score_hash)
        except Exception as e:
            print(f"Warning: Could not read existing scores: {e}")
    
    return existing_hashes

def process_scores_for_users(scores_data, users, output_file, existing_hashes):
    """
    Process scores and append those from target users to CSV,
    avoiding duplicates using the hash set
    """
    # Convert users to a set for O(1) lookup
    user_set = set(users)
    
    # Extract scores from the response
    if isinstance(scores_data, dict) and 'scores' in scores_data:
        scores = scores_data['scores']
    else:
        scores = scores_data
    
    if not scores or not isinstance(scores, list) or len(scores) == 0:
        print("No valid scores data found")
        return 0, []
    
    # Find scores that match our users and aren't duplicates
    matching_scores = []
    new_hashes = set()
    
    for score in scores:
        if score.get('user_id') in user_set:
            score_hash = generate_score_hash(score)
            if score_hash not in existing_hashes:
                matching_scores.append(score)
                new_hashes.add(score_hash)
    
    if not matching_scores:
        print("No new scores found for tracked users")
        return 0, []
    
    # Prepare scores for CSV
    all_fields = set()
    flat_scores = []
    
    for score in matching_scores:
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
    
    # Append to CSV
    with open(output_file, 'a', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=sorted(all_fields))
        if not file_exists:
            writer.writeheader()
        writer.writerows(flat_scores)
    
    print(f"Added {len(flat_scores)} new scores from tracked users to {output_file}")
    return len(flat_scores), new_hashes

def main():
    # Load credentials from .env file
    client_id = os.getenv('OSU_CLIENT_ID') 
    client_secret = os.getenv('OSU_CLIENT_SECRET')
    output_file = os.getenv('CSV_OUTPUT_FILE', 'scores.csv')
    
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
    existing_hashes = load_existing_scores(output_file)
    print(f"Loaded {len(existing_hashes)} existing score hashes")
    
    # Get initial token
    print(f"Starting to monitor scores for users: {users}")
    print(f"Results will be saved to: {output_file}")
    token = get_oauth_token(client_id, client_secret)

    try:
        total_scores_added = 0

        while True:
            scores = get_scores(token)
            if scores:
                added, new_hashes = process_scores_for_users(scores, users, output_file, existing_hashes)
                
                # Update our hash set with new scores
                existing_hashes.update(new_hashes)
                total_scores_added += added
                
                if added > 0:
                    print(f"Total scores tracked so far: {total_scores_added}")
            
            # Sleep for 5 seconds before next poll
            print("Waiting 5 seconds for next poll...")
            time.sleep(5)
            
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
