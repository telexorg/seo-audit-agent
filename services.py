import os, httpx, json
from dotenv import load_dotenv
from fastapi import status, HTTPException
import requests
import json_repair
from bs4 import BeautifulSoup
from pprint import pprint
from urllib.parse import urljoin, urlparse

# Load environment variables from .env file
load_dotenv()

TELEX_API_KEY = os.getenv('TELEX_API_KEY')
TELEX_API_URL = os.getenv('TELEX_API_URL')
TELEX_AI_URL = os.getenv('TELEX_AI_URL')
TELEX_AI_MODEL = os.getenv('TELEX_AI_MODEL')

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
    
    @classmethod
    async def audit_page_with_ai(cls, url, api_key):
        html, final_url = cls.fetch_html(url)
        if not html:
            return
        
        soup = BeautifulSoup(html, 'html.parser')

        html = str(soup)
        lines = html.splitlines()[:400]
        first_500_lines = "\n".join(lines)

        prompt = cls.create_prompt(first_500_lines)

        report = await cls.ai_seo_analysis(prompt, api_key)

        return report

    
    @classmethod
    async def audit_page_with_ai_old(cls, url, api_key):
        html, final_url = cls.fetch_html(url)
        if not html:
            return
        
        soup = BeautifulSoup(html, 'html.parser')

        # 2. Find all <div> tags
        tags_to_chunk = ['div']
        div_tags = soup.body.find_all(tags_to_chunk)

        # 3. Extract the text from each <div> to create chunks
        chunks = [str(div) for div in div_tags]
        print(chunks[0])

        prompt = cls.create_prompt(chunks[0])

        report = await cls.ai_seo_analysis(prompt, api_key)

        return report
    
    def create_prompt(html):
        return f"""
            You are an SEO expert. Based on the HTML content below, give an SEO audit of the page. 
            Look for missing meta tags, bad title structure, heading tag issues, alt tags, page speed concerns, or other common problems.

            HTML content:
            {html}

            return your result as a string summarizing the faults(if any), or highlighting improvements. If there are none, commend the SEO done on the website
        """

    # Step 3: Send to LLM
    async def ai_seo_analysis(prompt, api_key):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                request_headers = {
                    "X-AGENT-API-KEY": api_key,
                    "X-MODEL": "google/gemini-2.5-flash-lite"
                    # "X-MODEL": TELEX_AI_MODEL
                }

                request_body = {
                    "model": "google/gemini-2.5-flash-lite",
                    "messages": [
                        {
                        "role": "system",
                        "content": prompt
                        }
                    ],
                    "stream": False
                }

                print("sending request...")

                response = await client.post(
                    TELEX_AI_URL, 
                    headers=request_headers,
                    json=request_body,
                    timeout=45.0
                )

                response.raise_for_status()
                
                res = response.json().get("data", {}).get("choices", None)[0].get("message", None)
                reply = res.get("content", "not available")

                print("REPLY:")

                return reply

        except (KeyError, IndexError, json.JSONDecodeError, Exception) as e:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=e)