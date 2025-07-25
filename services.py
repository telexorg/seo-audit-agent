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