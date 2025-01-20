import os
import csv
import json
import logging
import requests
from bs4 import BeautifulSoup
from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
from concurrent.futures import ThreadPoolExecutor, as_completed
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

CACHE_DIR = "cached_pages"
RESULTS_FILE = "results.json"

CAPTCHA_KEYWORDS = [
    "captcha", "verify you are human", "cloudflare", "please solve",
    "robot verification", "verify your identity", "are you a robot",
    "security check", "access denied", "recaptcha", "protection by", "bot protection"
]

MAX_WORKERS = 20


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
        logging.info(f"Капча на сайте {url} решена успешно. Ответ: {solution}")
        return solution
    logging.error(f"Ошибка решения капчи на сайте {url}: {solver.error_code}")
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
    """Сохраняет HTML в кэшш."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    file_path = os.path.join(CACHE_DIR, f"{domain.replace('.', '_')}.html")
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(html)
    logging.info(f"HTML страницы {domain} сохранен в {file_path}.")


def init_selenium_driver():
    """Инициализирует WebDriver для Selenium."""
    options = Options()
    options.headless = True  
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    return driver


def process_site_with_selenium(domain: str, api_key: str) -> dict:
    """Обрабатывает сайт с использованием Selenium."""
    result = {"domain": domain, "cms": None, "captcha": None, "error": None, "html_cached": False}
    
    driver = init_selenium_driver()

    for scheme in ["http", "https"]:
        url = f"{scheme}://{domain}"
        logging.info(f"Проверка сайта с Selenium: {url}.")
        try:
            driver.get(url)
            driver.implicitly_wait(10)  
            
            html = driver.page_source
            
            if contains_captcha(html):
                logging.info(f"На сайте {domain} найдена капча.")
                result["captcha"] = True
                soup = BeautifulSoup(html, "html.parser")
                site_key = soup.find("div", attrs={"data-sitekey": True})
                if site_key:
                    solve_recaptcha(api_key, site_key["data-sitekey"], url)

            else:
                result["captcha"] = False  

            result["cms"] = identify_cms(html)
            cache_html(domain, html)
            result["html_cached"] = True
            return result

        except Exception as e:
            logging.warning(f"Ошибка при работе с Selenium {url}: {e}")
            result["error"] = str(e)
            error_html = f"Ошибка: {e}\nURL: {url}"
            cache_html(domain, error_html)
            result["html_cached"] = False
            result["captcha"] = None  
            return result
        finally:
            driver.quit()

    result["error"] = "HTTP и HTTPS недоступны"
    result["captcha"] = None  
    return result


def process_site(domain: str, api_key: str) -> dict:
    """Обрабатывает сайт: проверяет капчу, определяет CMS, сохраняет HTML даже при ошибках."""
    result = {"domain": domain, "cms": None, "captcha": None, "error": None, "html_cached": False}

    for scheme in ["http", "https"]:
        url = f"{scheme}://{domain}"
        logging.info(f"Проверка сайта {url}.")
        try:
            response = requests.get(url, timeout=10, verify=False)

            if response.status_code >= 400:
                logging.warning(f"Сайт {domain} вернул ошибку {response.status_code}: {response.reason}")
                result["error"] = f"{response.status_code} {response.reason}"
                html = response.text
                cache_html(domain, html)  
                result["html_cached"] = True
                result["captcha"] = None  
                return result

            html = response.text

            if contains_captcha(html):
                logging.info(f"На сайте {domain} найдена капча.")
                result["captcha"] = True
                soup = BeautifulSoup(html, "html.parser")
                site_key = soup.find("div", attrs={"data-sitekey": True})
                if site_key:
                    solve_recaptcha(api_key, site_key["data-sitekey"], url)
            else:
                result["captcha"] = False  

            result["cms"] = identify_cms(html)
            cache_html(domain, html)
            result["html_cached"] = True
            return result

        except requests.RequestException as e:
            logging.warning(f"Ошибка запроса {url}: {e}")
            result["error"] = str(e)
            cache_html(domain, f"Ошибка: {e}") 
            result["html_cached"] = True
            result["captcha"] = None  
            return result

    result["error"] = "HTTP и HTTPS недоступны"
    result["captcha"] = None
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
    csv_file = "top-1m.csv"
    api_key = "224f03d7fc94f5c109770e0b57e2290f" 
    
    domains = load_domains_from_csv(csv_file)
    if domains:
        process_sites(domains[:10], api_key)