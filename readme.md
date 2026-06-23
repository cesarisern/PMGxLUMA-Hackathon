✦ To test the functionality in this project, you can run the core Python
  scripts directly from your terminal. Based on the file structure and
  the headers of the scripts, here is the recommended workflow:

  1. Initial Setup
  Ensure you have the required dependencies and environment variables
  configured:

    # Install dependencies
    `pip install -r requirements.txt`
    # Configure environment (copy and fill in your API keys)
    `cp .env.example .env`

  2. Phase 1: Data Acquisition
  Run fetch_feeds.py to gather the necessary data (brand info, campaign
  context, trends, and locations). This script saves data to the data/
  directory and populates the database.

   * Interactive Mode: Follow the prompts for URL and campaign info.

   `python fetch_feeds.py`

   * Cached Mode (for quick testing): Use local files if you've already
     run it once.

   `python fetch_feeds.py --cached`

  3. Phase 2: Content Generation
  Once the data is fetched and stored in the database (db.py), you can
  generate the localized audio ads.

   * Generate All Ads:

   `python generate_audio.py`
   
   
   * Test with just a few locations to save API credits and time.

   `python generate_audio.py --limit 3`

  4. Database Inspection (Optional)
  Since the project uses a database (db.py), you might want to check the
  stored runs. If there's a CLI interface in db.py, you can use it to
  verify that data is being stored correctly between steps.

  ---

  Summary of Scripts
  ┌───────────────────┬───────────────────────────────────────────────┐
  │ Script            │ Purpose                                       │
  ├───────────────────┼───────────────────────────────────────────────┤
  │ fetch_feeds.py    │ Scrapes/fetches the 4 core data feeds (Brand, │
  │                   │ Context, Trends, Locations).                  │
  │ generate_audio.py │ Uses Audiostack to create localized audio     │
  │                   │ files based on the fetched data.              │
  │ db.py             │ Handles SQLite storage for runs and generated │
  │                   │ content.                                      │
  │ generate_image.py │ For visual asset generation.                  │
  └───────────────────┴─────────────────────────────────