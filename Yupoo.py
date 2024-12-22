import os
import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from concurrent.futures import ThreadPoolExecutor
import re
import time
import csv

def sanitize_folder_name(name):
    """Replace invalid characters for folder names."""
    return "".join(c if c.isalnum() or c in (' ', '_') else "_" for c in name).strip()

def get_category_title(soup):
    """Extract the category title from the crumbs section."""
    crumbs = soup.find("div", class_="yupoo-crumbs categories__box-right-header")
    if crumbs:
        category_title_tag = crumbs.find("a", class_="yupoo-crumbs-span", title=True)
        if category_title_tag:
            return category_title_tag["title"].strip()
    return "Unknown_Category"

def get_total_pages(soup):
    """Extract the total number of pages from the pagination form or set to 1 if not present."""
    pagination_form = soup.find("form", class_="pagination__jumpwrap")
    if pagination_form:
        # Search for the total pages in Chinese (e.g., "共2页")
        total_pages_text = pagination_form.find("span", string=re.compile(r"共\d+页"))
        if total_pages_text:
            # Extract number using regex
            match = re.search(r"共(\d+)页", total_pages_text.string.strip())
            if match:
                return int(match.group(1))
    # Default to 1 page if no pagination info is found
    return 1

def download_image(image_detail, session):
    """Download a single image and save it to the specified path."""
    image_url, save_path = image_detail
    headers = {"Referer": "https://wangxia1984.x.yupoo.com/"}
    retries = 3  # Retry 3 times before skipping
    for attempt in range(retries):
        try:
            with session.get(image_url, headers=headers, stream=True, timeout=120) as img_response:  # Set timeout to 2 minutes
                img_response.raise_for_status()
                with open(save_path, "wb") as file:
                    for chunk in img_response.iter_content(chunk_size=8192):
                        file.write(chunk)
                print(f"Downloaded: {save_path}")
                return  # Exit loop if download is successful
        except (requests.RequestException, requests.exceptions.Timeout) as e:
            print(f"Attempt {attempt + 1} failed for {image_url}: {e}")
            time.sleep(2)  # Backoff before retry
    print(f"Skipping failed or corrupt download: {image_url}")

def download_images_from_album(link, album_title, session, base_folder):
    album_folder = os.path.join(base_folder, sanitize_folder_name(album_title))
    os.makedirs(album_folder, exist_ok=True)

    print(f"Fetching album '{album_title}' metadata...")
    try:
        response = session.get(link)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Failed to fetch album URL: {e}")
        return

    soup = BeautifulSoup(response.text, "html.parser")
    total_pages = get_total_pages(soup)  # Use get_total_pages to determine the total pages
    print(f"Total pages in album '{album_title}': {total_pages}")

    for page in range(1, total_pages + 1):
        print(f"Fetching album '{album_title}', page {page}")
        try:
            response = session.get(f"{link}&page={page}")
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Failed to fetch URL for page {page}: {e}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        image_cards = soup.find_all("div", class_="showalbum__children image__main")
        if not image_cards:
            print(f"No images found on page {page}.")
            continue

        image_details = []
        for card in image_cards:
            img_tag = card.find("img", {"data-origin-src": True})
            title_tag = card.find("h3", {"title": True})
            if img_tag and title_tag:
                image_url = img_tag["data-origin-src"]
                image_name = title_tag["title"]

                if image_url.startswith("//"):
                    image_url = "https:" + image_url
                    print(image_url)

                image_name = sanitize_folder_name(f"{page}_{image_name}")
                image_name += ".jpg"
                image_details.append((image_url, os.path.join(album_folder, image_name)))
                # print(image_details)
        print(f"Starting downloads for album '{album_title}', page {page}...")
        with ThreadPoolExecutor(max_workers=8) as executor:
            executor.map(lambda img: download_image(img, session), image_details)

    print(f"All pages of album '{album_title}' have been processed.")

def download_images_from_yupoo_main():
    input_file = "input.csv"
    try:
        with open(input_file, "r", encoding="utf-8") as csv_file:
            reader = csv.DictReader(csv_file)
            links = [row["URL"] for row in reader if "URL" in row]
    except FileNotFoundError:
        print(f"Input file '{input_file}' not found.")
        return
    except KeyError:
        print("Input CSV file must have a column named 'URL'.")
        return

    session = requests.Session()
    retries = Retry(total=5, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount("https://", HTTPAdapter(max_retries=retries))

    for base_url in links:
        base_url = base_url.strip()
        base_domain = re.match(r"https://[^/]+", base_url).group(0)  # Extract base domain from URL

        print(f"Fetching main category page: {base_url}")
        try:
            response = session.get(base_url)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Failed to fetch main category page: {e}")
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        total_pages = get_total_pages(soup)
        print(f"Total number of pages in the category: {total_pages}")

        category_title = get_category_title(soup)
        base_folder = os.path.join("Images", sanitize_folder_name(category_title))
        os.makedirs(base_folder, exist_ok=True)

        for page in range(1, total_pages + 1):
            print(f"Processing page {page}...")
            page_url = f"{base_url}?page={page}"
            try:
                page_response = session.get(page_url)
                page_response.raise_for_status()
            except requests.RequestException as e:
                print(f"Failed to fetch page {page}: {e}")
                continue

            page_soup = BeautifulSoup(page_response.text, "html.parser")
            albums = page_soup.find_all("a", class_="album__main")
            if not albums:
                print(f"No albums found on page {page}.")
                continue

            for album in albums:
                album_title = album.get("title", "Untitled").strip()
                album_link = album["href"]
                # Ensure the album link uses the correct base URL
                if album_link.startswith("/"):
                    album_link = f"{base_domain}{album_link}"
                download_images_from_album(album_link, album_title, session, base_folder)

    print("All images from all categories downloaded successfully.")

# Run the script
if __name__ == "__main__":
    download_images_from_yupoo_main()