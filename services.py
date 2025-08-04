import os, httpx, json
from dotenv import load_dotenv
from fastapi import status, HTTPException
import requests
import json_repair
from bs4 import BeautifulSoup
from pprint import pprint
from urllib.parse import urljoin, urlparse
import a2a.types as a2a_types

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
    async def audit_page_with_ai(cls, url, api_key, webhook_url, task_id):
        html, _ = cls.fetch_html(url)
        if not html:
            return
        
        soup = BeautifulSoup(html, 'html.parser')

        lines = str(soup).splitlines()

        chunks = []
        for i in range(0, len(lines), 800):
            chunk = "\n".join(lines[i:i+800])
            chunks.append(chunk)
            

        print(f"Will send request to AI {len(chunks)} time(s)")

        reports = []

        for chunk in chunks:
            prompt = cls.create_seo_audit_prompt(chunk)

            report = await cls.send_request_to_ai(prompt, api_key, webhook_url=webhook_url, task_id=task_id)

            reports.append(report)


        final_report_prompt = cls.get_final_report_prompt(reports)

        final_report = await cls.send_request_to_ai(prompt=final_report_prompt, api_key=api_key, webhook_url=webhook_url, task_id=task_id)

        return final_report
    

    @classmethod
    async def audit_multiple_pages_with_ai(cls, links, api_key, webhook_url, task_id):
        #send links to ai to check which ones to scrape and which ones to exclude for seo purposes
        print("deduping links.....")
        links_prompt = cls.deduplicate_links_prompt(links)

        result: str = await cls.send_request_to_ai(prompt=links_prompt, api_key=api_key, webhook_url=webhook_url, task_id=task_id)

        de_duped_links = result.split(",")

        print("deduped links: ", de_duped_links)

        collated_reports = []

        print("auditing pages....")
        for link in de_duped_links:
            print("LINK: ", link)

            page_report = await cls.audit_page_with_ai(url=link, api_key=api_key, webhook_url=webhook_url, task_id=task_id)

            collated_reports.append(page_report)

        # audit_result =  "\n".join(collated_reports)
        # join collated reports with ai
        print("collating reports...")
        collated_reports_prompt = cls.get_final_report_prompt(collated_reports)

        collated_reports_result = await cls.send_request_to_ai(prompt=collated_reports_prompt, api_key=api_key, webhook_url=webhook_url, task_id=task_id)

        return collated_reports_result
    
        
    def deduplicate_links_prompt(links):
        return f"""
            You are an expert SEO analyst specializing in technical site audits. Your task is to analyze a list of URLs and identify a minimal set of unique page templates for an SEO audit.

            Follow these rules for deduplication:
            1.  **Identify URL Patterns:** Group URLs that follow the same structural pattern. For example, `/hotels/lagos`, `/hotels/kaduna`, and `/hotels/abuja` all share the `/hotels/[location]` pattern.
            2.  **Keep One Representative:** From each group of patterns, keep only ONE representative URL. It doesn't matter which one you keep.
            3.  **Handle Query Parameters:** For URLs with query parameters (e.g., `/search?q=item1`), keep only the base path (`/search`).
            4.  **Remove Exact Duplicates:** If the same exact URL appears multiple times, keep only one.

            **Example:**

            Input Links:
            [
                "https://domain.com/",
                "https://domain.com/about",
                "https://domain.com/about",
                "https://domain.com/hotels/lagos",
                "https://domain.com/hotels/kaduna",
                "https://domain.com/blog/post-1",
                "https://domain.com/blog/post-2",
                "https://domain.com/search?q=hotels",
                "https://domain.com/search?q=flights"
            ]

            Ideal Output JSON:
            [
                "https://domain.com/",
                "https://domain.com/about",
                "https://domain.com/hotels/lagos",
                "https://domain.com/blog/post-1",
                "https://domain.com/search"
            ]

            ---

            Now, perform this task on the following list of links:
            {links}

            Return the final list of deduplicated links as a comma separated string, with no other text or explanation.
        """
    
    def get_final_report_prompt(reports: list):
        return f"""
            As an SEO expert, summarize the list of SEO audit reports below, into one comprehensive report. 

            {reports}

            return your result as a string summarizing the faults(if any), or highlighting improvements. If there are none, commend the SEO done on the website
        """

    
    def create_seo_audit_prompt(html):
        return f"""
            You are an SEO expert. Based on the HTML content below, give an SEO audit of the page. 
            Look for missing meta tags, bad title structure, heading tag issues, alt tags, page speed concerns, or other common problems.

            HTML content:
            {html}

            return your result as a string summarizing the faults(if any), or highlighting improvements. If there are none, commend the SEO done on the website
            Your result should be a SHORT summary.
        """

    # Step 3: Send to LLM
    async def send_request_to_ai(prompt, api_key, webhook_url, task_id=None):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                request_headers = {
                    "X-AGENT-API-KEY": api_key,
                    "X-MODEL": TELEX_AI_MODEL
                }

                request_body = {
                    "model": TELEX_AI_MODEL,
                    "messages": [
                        {
                        "role": "system",
                        "content": prompt
                        }
                    ],
                    "stream": False
                }

                print("sending ai request...")

                response = await client.post(
                    TELEX_AI_URL, 
                    headers=request_headers,
                    json=request_body,
                    timeout=45.0
                )

                response.raise_for_status()
                
                res = response.json().get("data", {}).get("choices", None)[0].get("message", None)
                reply = res.get("content", "not available")

                return reply

        except Exception as e:
            print(e)
            # send webhook error response
            async with httpx.AsyncClient() as client:
                headers = {"X-TELEX-API-KEY": api_key}
                error = a2a_types.InternalError(
                    message=str(e)
                )
                response = a2a_types.JSONRPCErrorResponse(
                    error=error,
                    id=task_id or "not provided"
                )
                error_is_sent = await client.post(webhook_url, headers=headers,  json=response.model_dump(exclude_none=True, mode="json"))
                pprint(error_is_sent.json())
        

    def is_internal_link(base_url, link):
        # Only follow internal links (same domain)
        parsed_base = urlparse(base_url)
        parsed_link = urlparse(link)
        return parsed_link.netloc == "" or parsed_link.netloc == parsed_base.netloc

    @classmethod
    async def discover_links(cls, start_url, max_pages=10):
        visited = set()
        to_visit = [start_url]
        discovered_links = []

        while to_visit and len(visited) < max_pages:
            current_url = to_visit.pop(0)
            if current_url in visited:
                continue

            try:
                response = requests.get(current_url, timeout=10)
                if 'text/html' not in response.headers.get('Content-Type', ''):
                    continue

                soup = BeautifulSoup(response.text, 'html.parser')
                visited.add(current_url)
                discovered_links.append(current_url)

                for tag in soup.find_all('a', href=True):
                    href = tag['href']
                    absolute_link = urljoin(current_url, href)
                    if (
                        cls.is_internal_link(start_url, absolute_link)
                        and absolute_link not in visited
                        and absolute_link.startswith(("http://", "https://"))
                    ):
                        to_visit.append(absolute_link)

            except requests.RequestException as e:
                print(f"Failed to fetch {current_url}: {e}")

        return list(set(discovered_links))