import os
import openai
import json
import logging
import csv
from datetime import datetime
from urllib.parse import urlparse, urlunparse
from linkedin_jobs_scraper import LinkedinScraper
from linkedin_jobs_scraper.events import Events, EventData, EventMetrics
from linkedin_jobs_scraper.query import Query, QueryOptions, QueryFilters
from linkedin_jobs_scraper.filters import RelevanceFilters, TimeFilters, TypeFilters, ExperienceLevelFilters, \
    OnSiteOrRemoteFilters, SalaryBaseFilters
from selenium import webdriver
from selenium.webdriver.common.by import By
import pickle
import time

# Load config
def load_config():
    try:
        with open('config.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(
            "config.json not found. Please create it based on config.sample.json"
        )
    except json.JSONDecodeError:
        raise ValueError("config.json is not valid JSON")

# Load config and set OpenAI key
config = load_config()
openai.api_key = config['openai']['api_key']

def ask_chatgpt(question):
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are ChatGPT, a helpful assistant for my job search."},
            {"role": "user", "content": question},
        ]
    )
    return response.choices[0].message.content

# ChatGPT question template
chatgpt_question_template = """
    Help me decide if this job description matches my resume keywords, and extract only 5 most important tech related keywords from the job description, the years of experience required, and the salary range.
    Job description: %s
    My resume: %s
    Only answer in JSON in pure text without markdown formatting:
    {
        "match": "Yes" or "No",
        "keywords": ["keyword1", "keyword2", "keyword3"],
        "years of experience": "1-3 years" or NA if not specified,
        "salary": "100,000-150,000" or NA if not specified
    }
    """

# Get resume keywords from config
resume_keywords = config['resume_keywords']

# Change root logger level (default is WARN)
logging.basicConfig(level=logging.INFO)

def manual_login_and_save_cookies():
    chrome_options = webdriver.ChromeOptions()
    driver = webdriver.Chrome(options=chrome_options)

    driver.get("https://www.linkedin.com/login")
    input("Please log in manually, complete any verification, and press Enter here when done.")
    # Save cookies after manual login
    with open("linkedin_cookies.pkl", "wb") as f:
        pickle.dump(driver.get_cookies(), f)
    print("Cookies saved successfully.")

def load_cookies():
    if os.path.exists("linkedin_cookies.pkl"):
        with open("linkedin_cookies.pkl", "rb") as f:
            cookies = pickle.load(f)
            return cookies
    return None

# Add this function to create a new CSV file with headers
def create_or_load_csv():
    filename = "jobs.csv"
    existing_links = set()

    if os.path.exists(filename):
        with open(filename, 'r', newline='', encoding='utf-8') as csvfile:
            reader = csv.reader(csvfile)
            next(reader)  # Skip header
            existing_links = set(row[3] for row in reader)  # Assuming link is the 4th column
    else:
        with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(['Title', 'Company', 'Date', 'Location', 'Link', 'Match', 'Keywords', 'Years of Experience', 'Salary'])

    return filename, existing_links

# Create or load the CSV file and get existing links
csv_filename, existing_links = create_or_load_csv()

def remove_url_parameters(url):
    parsed = urlparse(url)
    clean_url = urlunparse(parsed._replace(query='', fragment=''))
    return clean_url.rstrip('/')

# Fired once for each successfully processed job
def on_data(data: EventData):
    # Clean the URL by removing parameters
    clean_link = remove_url_parameters(data.link)

    if clean_link in existing_links:
        print(f"[SKIPPED] Job already exists: {clean_link}")
        return

    # print('[ON_DATA]', data.title, data.company, data.company_link, data.location, data.date, clean_link, len(data.description))
    question = chatgpt_question_template % (data.description, resume_keywords)
    answer = ask_chatgpt(question)
    answer_json = json.loads(answer)

    # Write to CSV
    with open(csv_filename, 'a', newline='', encoding='utf-8') as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow([
            data.title.replace('"', '').replace('with verification', ''),
            data.company,
            data.date if data.date != '' and data.date != 'None' else datetime.now().strftime('%Y-%m-%d'),
            data.location,
            clean_link,
            answer_json['match'],
            ', '.join(answer_json['keywords']),
            answer_json['years of experience'],
            answer_json['salary']
        ])

    # Add the new clean link to existing_links
    existing_links.add(clean_link)

# Fired once for each page (25 jobs)
def on_metrics(metrics: EventMetrics):
    print('[ON_METRICS]', str(metrics))

def on_error(error):
    print('[ON_ERROR]', error)

def on_end():
    print('[ON_END]')


def main():
    # Initialize the Chrome driver


    # Try to load cookies or perform manual login
    cookies = load_cookies()
    if not cookies:
        manual_login_and_save_cookies()

    # Initialize the scraper with the cookie
    scraper = LinkedinScraper(
        chrome_executable_path=None,
        chrome_binary_location=None,
        chrome_options=None,
        headless=False,
        max_workers=1,
        slow_mo=1,
        page_load_timeout=40,
        cookies=cookies
    )

    # Add event listeners
    scraper.on(Events.DATA, on_data)
    scraper.on(Events.ERROR, on_error)
    scraper.on(Events.END, on_end)

    queries = [
        Query(
            query='Software Engineer',
            options=QueryOptions(
                locations=['Vancouver, BC, Canada'],
                apply_link=False,
                skip_promoted_jobs=False,
                page_offset=0,
                limit=500,
                filters=QueryFilters(
                    relevance=RelevanceFilters.RELEVANT,
                    time=TimeFilters.WEEK,
                )
            )
        ),
    ]

    scraper.run(queries)

if __name__ == "__main__":
    main()
