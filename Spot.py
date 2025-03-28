import os
from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from typing import List, Dict
import json
import requests
import re
load_dotenv()
print(f"SPOTIPY_CLIENT_ID: {os.getenv('SPOTIPY_CLIENT_ID')}")
print(f"SPOTIPY_CLIENT_SECRET: {os.getenv('SPOTIPY_CLIENT_SECRET')}")
class SpotifyPlaylistGenerator:
    def __init__(self):
        self.sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
            client_id=os.getenv('SPOTIPY_CLIENT_ID'),
            client_secret=os.getenv('SPOTIPY_CLIENT_SECRET'),
            redirect_uri='http://localhost:8888/callback',
            scope='playlist-modify-public playlist-modify-private'
        ))
        self.ollama_url = "http://localhost:11434/api/generate"
        self.model = "llama3"
    def create_playlist_from_prompt(self, prompt: str, playlist_name: str = None, track_count: int = 20, preferred_artists=None) -> str:
        try:
            # Initialize preferred_artists if None
            if preferred_artists is None:
                preferred_artists = []

            user = self.sp.current_user()
            if not playlist_name:
                playlist_name = f"AI Generated: {prompt[:50]}..."
            playlist = self.sp.user_playlist_create(
                user['id'],
                playlist_name,
                public=True,
                description=f"AI-generated playlist based on prompt: {prompt}"
            )
            common_languages = ["tamil", "hindi", "telugu", "kannada", "malayalam", 
                              "korean", "japanese", "chinese", "spanish", "french", 
                              "german", "italian", "portuguese", "russian", "arabic"]
            language_specified = None
            for language in common_languages:
                if language.lower() in prompt.lower():
                    language_specified = language
                    break
            search_terms = self._generate_search_terms(prompt)
            track_uris = []
            unique_songs = set()
            language_market_map = {
                "tamil": "IN",
                "hindi": "IN",
                "telugu": "IN",
                "kannada": "IN", 
                "malayalam": "IN",
                "korean": "KR",
                "japanese": "JP",
                "chinese": "CN",
                "spanish": "ES",
            }
            market = None
            for language, market_code in language_market_map.items():
                if language.lower() in prompt.lower():
                    market = market_code
                    break
            llm_terms = self._get_llm_music_terms(prompt)
            
            # Define variables that were missing
            artist_count = {}
            max_songs_per_artist = 2
            min_popularity = 10
            term_tracks = {}
            
            # Use a smaller set of high-quality search terms
            core_search_terms = [prompt]  # Start with just the original prompt
            
            # Add preferred artist search terms
            if preferred_artists:
                for artist in preferred_artists:
                    core_search_terms.append(f"artist:{artist}")
                    if language_specified:
                        core_search_terms.append(f"artist:{artist} {language_specified}")
            
            # Add 1-2 most relevant LLM terms to core terms
            if llm_terms and len(llm_terms) > 0:
                core_search_terms.extend(llm_terms[:2])  # Just use top 2 terms from LLM
            
            if language_specified:
                core_search_terms.append(f"{language_specified} {prompt}")  # Add language-specific version
            
            # Use a quality threshold - stop after finding low-quality matches
            consecutive_empty_searches = 0
            max_empty_searches = 3  # Stop after 3 searches with no results
            
            search_iteration = 0
            max_iterations = 10  # Reduced from 15
            
            print(f"Using core search terms: {core_search_terms}")
            
            while len(track_uris) < track_count and search_iteration < max_iterations and consecutive_empty_searches < max_empty_searches:
                # Use only our core terms first, then fall back to other terms if needed
                if search_iteration < len(core_search_terms):
                    current_term = core_search_terms[search_iteration]
                else:
                    # After exhausting core terms, use the rest
                    remaining_index = search_iteration - len(core_search_terms)
                    if remaining_index < len(search_terms):
                        current_term = search_terms[remaining_index]
                    else:
                        # We've exhausted all terms
                        break
                    
                search_iteration += 1
                print(f"Searching for: {current_term}")
                
                if market:
                    results = self.sp.search(q=current_term, type='track', limit=30, market=market)
                else:
                    results = self.sp.search(q=current_term, type='track', limit=30)
                if results['tracks']['items']:
                    term_matches = 0
                    
                    for track in results['tracks']['items']:
                        if len(track_uris) >= track_count:
                            break
                        
                        artist_name = track['artists'][0]['name'].lower()
                        track_name = track['name'].lower()
                        
                        # Simplify artist limit check
                        if artist_count.get(artist_name, 0) >= max_songs_per_artist:
                            continue
                        
                        # Simple popularity check - only filter extremely unpopular tracks
                        if track['popularity'] < min_popularity:
                            continue
                        
                        # Keep only the basic similarity check
                        song_id = f"{artist_name}:{track_name}"
                        similar_song_exists = False
                        simplified_name = self._simplify_track_name(track_name)
                        
                        for existing_id in unique_songs:
                            existing_artist, existing_track = existing_id.split(':', 1)
                            # Only check similarity if it's the same artist
                            if existing_artist == artist_name:
                                existing_simplified = self._simplify_track_name(existing_track)
                                # Simple similarity check - only catch obvious duplicates
                                if simplified_name == existing_simplified:
                                    similar_song_exists = True
                                    break
                        
                        if song_id not in unique_songs and not similar_song_exists:
                            track_uris.append(track['uri'])
                            unique_songs.add(song_id)
                            artist_count[artist_name] = artist_count.get(artist_name, 0) + 1
                            
                            # Track which search terms are yielding good results
                            if current_term not in term_tracks:
                                term_tracks[current_term] = []
                            term_tracks[current_term].append(track['uri'])
                            term_matches += 1
                            
                            print(f"Added: {artist_name} - {track_name}")
                        
                        if preferred_artists and artist_name in [a.lower() for a in preferred_artists]:
                            # Prioritize tracks by preferred artists by giving them extra weight
                            max_songs_per_artist = 4  # Allow more songs from preferred artists
                            # Skip popularity check for preferred artists
                            pass  # Skip the popularity check
                        
                    if term_matches == 0:
                        consecutive_empty_searches += 1
                        print(f"No relevant tracks found for '{current_term}' ({consecutive_empty_searches}/{max_empty_searches})")
                    else:
                        consecutive_empty_searches = 0  # Reset counter when we find tracks
                else:
                    consecutive_empty_searches += 1
                    print(f"No tracks found for '{current_term}' ({consecutive_empty_searches}/{max_empty_searches})")
            
            # Add a note about partial playlist if we couldn't find enough tracks
            if len(track_uris) < track_count:
                print(f"Could only find {len(track_uris)} relevant tracks out of {track_count} requested")
                if playlist:
                    # Update the description to note this is a partial playlist
                    self.sp.playlist_change_details(
                        playlist['id'],
                        description=f"AI-generated playlist based on prompt: {prompt} (Found {len(track_uris)} relevant tracks)"
                    )
            
            print(f"Total tracks found: {len(track_uris)}")
            if track_uris:
                for i in range(0, len(track_uris), 100):
                    batch = track_uris[i:min(i+100, len(track_uris))]
                    if batch:
                        self.sp.playlist_add_items(playlist['id'], batch)
                        print(f"Added batch of {len(batch)} tracks")
            return playlist['external_urls']['spotify']
        except Exception as e:
            print(f"Error creating playlist: {str(e)}")
            return None
    def _generate_search_terms(self, prompt: str) -> List[str]:
        common_languages = ["tamil", "hindi", "telugu", "kannada", "malayalam", 
                            "korean", "japanese", "chinese", "spanish", "french", 
                            "german", "italian", "portuguese", "russian", "arabic"]
        language_specified = None
        for language in common_languages:
            if language.lower() in prompt.lower():
                language_specified = language
                break
        llm_terms = self._get_llm_music_terms(prompt)
        search_terms = [prompt]
        if language_specified:
            for i, term in enumerate(llm_terms):
                if language_specified.lower() not in term.lower():
                    llm_terms[i] = f"{language_specified} {term}"
            search_terms.append(f"{language_specified} music")
            search_terms.append(f"{language_specified} songs")
        search_terms.extend(llm_terms)
        return search_terms
    def _get_llm_music_terms(self, prompt: str) -> List[str]:
        try:
            system_prompt = """
            You are a music expert assistant that helps create Spotify playlists.
            Given a user's description, generate 5-8 relevant search terms that would find songs matching that vibe.
            IMPORTANT: If the user specifies a language (like Tamil, Korean, Spanish, etc.), 
            ALWAYS include that language name in EVERY search term.
            Include genre terms, emotional qualities, era/time period if relevant, and artist types and lyrics that would match.
            Return ONLY a JSON array with a "terms" key containing an array of strings.
            For example: {"terms": ["indie pop 2010s", "melancholic guitar", "summer nostalgia", "beach vibes", "sunset driving"]}
            For language-specific requests like "Tamil 90's hits", make sure every term includes "Tamil" like:
            {"terms": ["Tamil 90s hits", "Tamil film songs 1990s", "Tamil pop 90s", "classic Tamil tracks", "Tamil nostalgic 1990s"]}
            """
            payload = {
                "model": self.model,
                "prompt": f"{system_prompt}\nUser: Generate music search terms for this playlist idea: {prompt}\nAssistant:",
                "stream": False
            }
            response = requests.post(self.ollama_url, json=payload)
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "")
                try:
                    cleaned_text = response_text
                    if "```json" in response_text:
                        cleaned_text = response_text.split("```json")[1].split("```")[0].strip()
                    elif "```" in response_text:
                        cleaned_text = response_text.split("```")[1].split("```")[0].strip()
                    response_json = json.loads(cleaned_text)
                    terms = response_json.get("terms", [])
                    if terms:
                        print(f"Generated search terms: {terms}")
                        return terms
                except json.JSONDecodeError:
                    print("Failed to parse JSON from LLM response, using basic search")
                    print(f"Raw response: {response_text}")
            return [prompt, "instrumental", f"{prompt} music", f"{prompt} songs"]
        except Exception as e:
            print(f"Error using LLM for search terms: {str(e)}")
            return [prompt, "instrumental", f"{prompt} music", f"{prompt} songs"]
    def _simplify_track_name(self, track_name: str) -> str:
        simplified = track_name.lower()
        simplified = re.sub(r'\([^)]*\)', '', simplified)
        simplified = re.sub(r'\[[^\]]*\]', '', simplified)
        simplified = re.sub(r'".*?"', '', simplified)
        simplified = re.sub(r'\'.*?\'', '', simplified)
        indicators = ['remaster', 'version', 'edit', 'mix', 'radio', 'remix', 
                     'mono', 'stereo', 'feat', 'ft.', 'live', 'acoustic',
                     'extended', 'original', 'bonus', 'deluxe', 'single']
        for indicator in indicators:
            simplified = simplified.replace(indicator, '')
        simplified = re.sub(r'[-_:,;./\\]', ' ', simplified)
        simplified = re.sub(r'\s+', ' ', simplified).strip()
        return simplified
    def _similarity_score(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings using a simple algorithm."""
        # Convert both strings to lowercase and remove extra spaces
        str1 = ' '.join(str1.lower().split())
        str2 = ' '.join(str2.lower().split())
        
        # If the strings are identical, return 1.0
        if str1 == str2:
            return 1.0
        
        # If one string contains the other entirely, high similarity
        if str1 in str2 or str2 in str1:
            return 0.9
        
        # Otherwise, calculate word overlap
        words1 = set(str1.split())
        words2 = set(str2.split())
        
        # Calculate Jaccard similarity coefficient
        intersection = len(words1.intersection(words2))
        union = len(words1.union(words2))
        
        if union == 0:
            return 0.0
        
        return intersection / union
def main():
    generator = SpotifyPlaylistGenerator()
    
    # Structured input collection
    print("Create your playlist by filling in the following criteria:")
    
    # Language selection
    language = input("Language (e.g., English, Tamil, Korean, leave blank for no preference): ").strip()
    
    # Decade selection
    decade = input("Decade (e.g., 80s, 90s, 2000s, leave blank for no preference): ").strip()
    
    # Genre selection
    genre = input("Genre (e.g., Rock, Pop, Hip Hop, R&B, leave blank for no preference): ").strip()
    
    # Mood/Vibe selection
    mood = input("Mood/Vibe (e.g., Chill, Energetic, Romantic, Sad, leave blank for no preference): ").strip()
    
    # Preferred artists - NEW
    artists = input("Preferred artists (comma-separated, e.g., MC Frontalot, MC Chris, leave blank for no preference): ").strip()
    preferred_artists = [artist.strip() for artist in artists.split(',')] if artists else []
    
    # Construct a structured prompt from the inputs
    prompt_parts = []
    if language and language.lower() != "english":
        prompt_parts.append(language)
    if decade:
        prompt_parts.append(f"{decade} music")
    if genre:
        prompt_parts.append(genre)
    if mood:
        prompt_parts.append(mood)
    
    # Create the complete prompt
    prompt = " ".join(prompt_parts)
    if not prompt:
        prompt = "diverse popular music"  # Default if no criteria specified
        
    # Add artist preference to the structured prompt if provided
    if preferred_artists:
        print(f"Will prioritize tracks by: {', '.join(preferred_artists)}")
        
    # Get playlist length
    try:
        track_count = int(input("\nHow many tracks would you like in your playlist? (default: 20): ") or "20")
    except ValueError:
        print("Invalid input, using default of 20 tracks.")
        track_count = 20
    
    # Create playlist name based on criteria
    parts = [p for p in [language, decade, genre, mood] if p]
    playlist_name = "AI Generated: " + " ".join(parts) if parts else f"AI Generated: {prompt}"
    
    print(f"\nCreating playlist: \"{playlist_name}\"")
    playlist_url = generator.create_playlist_from_prompt(prompt, playlist_name=playlist_name, 
                                                        track_count=track_count, 
                                                        preferred_artists=preferred_artists)
    
    if playlist_url:
        print(f"Playlist created successfully! URL: {playlist_url}")
    else:
        print("Failed to create playlist.")
if __name__ == "__main__":
    main()
