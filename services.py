import os, httpx
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin, urlparse

# Load environment variables from .env file
load_dotenv()

TELEX_API_KEY = os.getenv('TELEX_API_KEY')
TELEX_API_URL = os.getenv('TELEX_API_URL')

class AgentService:

    def scrape_business_info(url):
        def fetch_soup(target_url):
            try:
                response = requests.get(target_url, timeout=10)
                response.raise_for_status()
                return BeautifulSoup(response.text, 'html.parser'), response.text
            except Exception as e:
                print(f"Error fetching {target_url}: {e}")
                return None, ""

        soup, raw_html = fetch_soup(url)

        if not soup:
            return None

        data = {
            "url": url,
            "about": "",
            "contact_info": {
                "emails": [],
                "phone_numbers": [],
                "social_links": [],
                "contact_page": ""
            }
        }

        # Step 1: Look for contact page link
        contact_page_url = None
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True).lower()
            if 'contact us' in text or text == 'contact':
                contact_page_url = urljoin(url, a['href'])
                data['contact_info']['contact_page'] = contact_page_url
                break

        # Step 2: Load contact page if available
        if contact_page_url:
            contact_soup, raw_html = fetch_soup(contact_page_url)
            if not contact_soup:
                contact_soup = soup  # fallback to main page
        else:
            contact_soup = soup

        # Step 3: Extract about section from the main page only
        about_keywords = ['about', 'who we are', 'our story', 'mission', 'vision']
        for section in soup.find_all(['section', 'div', 'p', 'article']):
            text = section.get_text(strip=True).lower()
            if any(keyword in text for keyword in about_keywords):
                data['about'] = section.get_text(strip=True)
                break

        # Step 4: Extract emails
        data['contact_info']['emails'] = list(set(re.findall(
            r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+',
            raw_html
        )))

        # Step 5: Extract phone numbers using improved logic
        text_content = contact_soup.get_text(separator=' ', strip=True)

        # Keywords that often appear near phone numbers
        phone_keywords = ['phone', 'whatsapp', 'call us', 'tel', 'contact']
        nearby_numbers = []

        # Primary pattern: Look for numbers near keywords like "Phone", "WhatsApp", etc.
        for match in re.finditer(
            rf"(?:{'|'.join(phone_keywords)})[^:{{0,20}}][:–\s]?\s*(\+?\(?\d[\d\s().\-]{{7,}}\d)",
            text_content,
            flags=re.IGNORECASE
        ):
            number = match.group(1)
            nearby_numbers.append(number.strip())

        # Fallback pattern: Match general phone-like strings more conservatively
        fallback_numbers = re.findall(
            r'(?:(?:\+\d{1,3}[\s.-]?)?\(?\d{2,4}\)?[\s.-]?)?\d{3,4}[\s.-]?\d{3,4}[\s.-]?\d{0,4}',
            text_content
        )

        # Filter out too-short fragments or obviously invalid matches
        cleaned_fallbacks = [num.strip() for num in fallback_numbers if len(re.sub(r'\D', '', num)) >= 9]

        # Merge and deduplicate
        all_numbers = list(set(nearby_numbers + cleaned_fallbacks))

        data['contact_info']['phone_numbers'] = list(set(all_numbers))

        # Step 6: Extract social links
        social_domains = ['facebook.com', 'twitter.com', 'linkedin.com', 'instagram.com']
        for a in soup.find_all('a', href=True):
            href = a['href']
            if any(domain in href for domain in social_domains):
                data['contact_info']['social_links'].append(href)

        return data
    

    import os, httpx
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import urljoin

# Load environment variables from .env file
load_dotenv()

TELEX_API_KEY = os.getenv('TELEX_API_KEY')
TELEX_API_URL = os.getenv('TELEX_API_URL')

class AgentService:
    def fetch_html(url):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text, response.url
        except Exception as e:
            print(f"Error fetching URL: {e}")
            return None, None

    @classmethod
    def audit_page(cls, url):
        html, final_url = cls.fetch_html(url)
        if not html:
            return

        soup = BeautifulSoup(html, 'lxml')
        report = {}

        # Title tag
        title_tag = soup.title.string.strip() if soup.title else ''
        report['Title'] = {
            'content': title_tag,
            'length': len(title_tag),
            'status': 'OK' if 10 <= len(title_tag) <= 70 else 'Too short/long or missing'
        }

        # Meta description
        desc = soup.find('meta', attrs={'name': 'description'})
        desc_content = desc['content'].strip() if desc and 'content' in desc.attrs else ''
        report['Meta Description'] = {
            'content': desc_content,
            'length': len(desc_content),
            'status': 'OK' if 50 <= len(desc_content) <= 160 else 'Too short/long or missing'
        }

        # H1 tags
        h1_tags = soup.find_all('h1')
        report['H1 Tags'] = {
            'count': len(h1_tags),
            'content': [h.get_text(strip=True) for h in h1_tags],
            'status': 'OK' if len(h1_tags) == 1 else 'Should have exactly 1'
        }

        # Images with missing alt attributes
        images = soup.find_all('img')
        missing_alts = [img.get('src') for img in images if not img.get('alt')]
        report['Images without alt'] = {
            'count': len(missing_alts),
            'examples': missing_alts[:5]
        }

        # Canonical tag
        canonical = soup.find('link', rel='canonical')
        report['Canonical'] = canonical['href'] if canonical and 'href' in canonical.attrs else 'Missing'

        # Mobile responsive (viewport tag)
        viewport = soup.find('meta', attrs={'name': 'viewport'})
        report['Mobile Responsive'] = 'Yes' if viewport else 'No (missing viewport tag)'

        # Robots.txt check
        base = f"{urlparse(final_url).scheme}://{urlparse(final_url).netloc}"
        robots_url = urljoin(base, "/robots.txt")
        robots_ok = requests.get(robots_url).status_code == 200
        report['robots.txt'] = 'Present' if robots_ok else 'Missing'

        # Sitemap check
        sitemap_url = urljoin(base, "/sitemap.xml")
        sitemap_ok = requests.get(sitemap_url).status_code == 200
        report['sitemap.xml'] = 'Present' if sitemap_ok else 'Missing'

        return report