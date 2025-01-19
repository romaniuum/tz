import os
import csv
import json
import logging
import requests
from bs4 import BeautifulSoup
from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
from concurrent.futures import ThreadPoolExecutor, as_completed

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

CACHE_DIR = "cached_pages"
RESULTS_FILE = "results.json"

CAPTCHA_KEYWORDS = [
    "captcha", "verify you are human", "cloudflare", "please solve",
    "robot verification", "verify your identity", "are you a robot",
    "security check", "access denied", "recaptcha", "protection by", "bot protection"
]

MAX_WORKERS = 10


def load_domains_from_csv(csv_file: str) -> list:
    """Загружает список доменов из CSV файла."""
    domains = []
    with open(csv_file, "r", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        for row in reader:
            domain = row.get("Domain", "").strip()
            if domain:
                domains.append(domain)
    logging.info(f"Загружено {len(domains)} доменов.")
    return domains


def contains_captcha(html: str) -> bool:
    """Проверяет HTML на наличие капчи."""
    text = BeautifulSoup(html, "html.parser").get_text().lower()
    return any(keyword in text for keyword in CAPTCHA_KEYWORDS)


def solve_recaptcha(api_key: str, site_key: str, url: str) -> str:
    """Решает капчу с помощью Anti-Captcha API."""
    solver = recaptchaV2Proxyless()
    solver.set_key(api_key)
    solver.set_website_url(url)
    solver.set_website_key(site_key)
    
    solution = solver.solve_and_return_solution()
    if solution:
        logging.info("Капча решена успешно.")
        return solution
    logging.error(f"Ошибка решения капчи: {solver.error_code}")
    return ""


def identify_cms(html: str) -> str:
    """Определяет CMS сайта по ключевым фразам в HTML."""
    cms_signatures = {
        "WordPress": ["wp-content", "wordpress"],
        "Drupal": ["drupal"],
        "Joomla": ["joomla"],
        "Shopify": ["shopify"],
        "Squarespace": ["squarespace"],
        "Wix": ["wix"],
        "Magento": ["magento"],
        "PrestaShop": ["prestashop"],
        "Blogger": ["blogger"],
    }
    
    for cms, keywords in cms_signatures.items():
        if any(keyword in html for keyword in keywords):
            return cms
    return "Самопис"


def cache_html(domain: str, html: str):
    """Сохраняет HTML страницу в кэш."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    file_path = os.path.join(CACHE_DIR, f"{domain.replace('.', '_')}.html")
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(html)
    logging.info(f"HTML страницы {domain} сохранен в {file_path}.")


def process_site(domain: str, api_key: str) -> dict:
    """Обрабатывает сайт: проверяет капчу, определяет CMS, сохраняет HTML."""
    result = {"domain": domain, "cms": None, "captcha": False, "error": None}
    
    for scheme in ["http", "https"]:
        url = f"{scheme}://{domain}"
        logging.info(f"Проверка сайта {url}.")
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            html = response.text

            if contains_captcha(html):
                logging.info(f"На сайте {domain} найдена капча.")
                result["captcha"] = True
                soup = BeautifulSoup(html, "html.parser")
                site_key = soup.find("div", attrs={"data-sitekey": True})
                if site_key:
                    solve_recaptcha(api_key, site_key["data-sitekey"], url)

            result["cms"] = identify_cms(html)
            cache_html(domain, html)
            return result

        except requests.RequestException as e:
            logging.warning(f"Ошибка запроса {url}: {e}")
            result["error"] = str(e)
            return result
    
    result["error"] = "HTTP и HTTPS недоступны"
    return result


def process_sites(domains: list, api_key: str):
    """Обрабатывает несколько доменов параллельно и сохраняет результаты в файл."""
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(process_site, domain, api_key): domain for domain in domains}
        
        for future in as_completed(futures):
            domain = futures[future]
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                logging.error(f"Ошибка при обработке {domain}: {e}")

    with open(RESULTS_FILE, "w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=4)
    logging.info(f"Результаты сохранены в {RESULTS_FILE}.")


if __name__ == "__main__":
    csv_file = "top_domains.csv"
    api_key = "224f03d7fc94f5c109770e0b57e2290f"
    
    domains = load_domains_from_csv(csv_file)
    if domains:
        process_sites(domains[:10], api_key)
