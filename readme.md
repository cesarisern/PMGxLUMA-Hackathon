# PMGxLUMA Hackathon Local UI

Local full-stack wizard for running the existing feed pipeline and AudioStack generation.

## Run locally

### Terminal 1 (API)

```bash
cd api && ../.venv/bin/uvicorn server:app --reload --port 8002
```

### Terminal 2 (UI)

```bash
cd ui && npm run dev
```

## Health check

`GET http://127.0.0.1:8002/health`


✦ To test the functionality in this project, you can run the core Python
  scripts directly from your terminal. Based on the file structure and
  the headers of the scripts, here is the recommended workflow:

  1. Initial Setup
  Ensure you have the required dependencies and environment variables
  configured:

    # System dependency — ffmpeg must be installed before running video generation
    # macOS:
    `brew install ffmpeg`
    # Ubuntu/Debian:
    `apt install ffmpeg`

    # Install Python dependencies
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

  4. Image generation
  
  `python generate_image.py`

    If you've already run context.py and generated an output json for the context, this should pick it up automatically.

    You can also test by entering the context after the script - this will take precedence over the json as an input.

    `python generate_image.py "Nike advert for the world cup - highlight how Nike is supporting women and girls' sport participation with sponsored soccer camps across the US this summer"`

  5. Video generation

  Pass the image URL printed by generate_image.py. One 9:16 MP4 is produced
  per audio version, with captions burned in. Outputs are saved to data/videos/.

  `python generate_video_from_image.py <image_url>`


    ## For testing only
    Very simple mock UI to test the queries. To run: 

    `cd PMGxLUMA-Hackathon/test_frontend`
    `python server.py`
    # then open 
    `http://localhost:8765`