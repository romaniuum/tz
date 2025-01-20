import os
import csv
import logging
import json
from bs4 import BeautifulSoup
from anticaptchaofficial.recaptchav2proxyless import recaptchaV2Proxyless
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
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
    """Сохраняет HTML в кэш."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    file_path = os.path.join(CACHE_DIR, f"{domain.replace('.', '_')}.html")
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(html)
    logging.info(f"HTML страницы {domain} сохранен в {file_path}.")


def init_undetected_driver():
    """Инициализирует undetected-chromedriver для обхода Cloudflare."""
    options = uc.ChromeOptions()
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-logging")
    options.add_argument("--disable-blink-features=AutomationControlled")
    cache_dir = os.path.join(os.getenv("APPDATA", ""), "undetected_chromedriver", "undetected")
    
    
    if os.path.exists(cache_dir):
        try:
            for file in os.listdir(cache_dir):
                file_path = os.path.join(cache_dir, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)
        except Exception as e:
            logging.warning(f"Не удалось очистить кэш драйвера: {e}")

    driver = uc.Chrome(options=options, use_subprocess=True)
    return driver


def process_site_with_selenium(domain: str, api_key: str) -> dict:
    """Обрабатывает сайт с помощью Selenium, решает капчу и определяет CMS."""
    result = {"domain": domain, "captcha": None, "error": None, "html_cached": False, "cms": ""}
    driver = init_undetected_driver()

    try:
        for scheme in ["http", "https"]:
            url = f"{scheme}://{domain}"
            logging.info(f"Проверка сайта с Selenium: {url}.")
            try:
                driver.get(url)
                driver.implicitly_wait(10)

                html = driver.page_source
                if contains_captcha(html):
                    logging.info(f"На сайте {domain} найдена капча. Попытка решения.")
                    soup = BeautifulSoup(html, "html.parser")
                    site_key = soup.find("div", attrs={"data-sitekey": True})
                    if site_key:
                        solution = solve_recaptcha(api_key, site_key["data-sitekey"], url)
                        if solution:
                            driver.execute_script(
                                """
                                document.querySelector('[name=\"g-recaptcha-response\"]').style.display = 'block';
                                document.querySelector('[name=\"g-recaptcha-response\"]').value = arguments[0];
                                """,
                                solution,
                            )
                            submit_button = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                            if submit_button:
                                submit_button.click()
                            logging.info(f"Капча на сайте {domain} решена.")
                    result["captcha"] = True
                else:
                    result["captcha"] = False

                result["cms"] = identify_cms(html)
                cache_html(domain, html)
                result["html_cached"] = True
                return result

            except Exception as e:
                logging.warning(f"Ошибка при обработке {url}: {e}")
                result["error"] = str(e)
                cache_html(domain, f"Ошибка: {e}")  

    finally:
        driver.quit()

    result["error"] = "HTTP и HTTPS недоступны"
    return result


def process_sites(domains: list, api_key: str):
    """Обрабатывает несколько доменов параллельно и сохраняет результаты."""
    with open(RESULTS_FILE, "w", encoding="utf-8") as file:
        file.write("[")  

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(process_site_with_selenium, domain, api_key): domain for domain in domains}

            for i, future in enumerate(as_completed(futures)):
                domain = futures[future]
                try:
                    result = future.result()
                    json.dump(result, file, ensure_ascii=False, indent=4)
                    if i < len(futures) - 1:
                        file.write(",\n")
                except Exception as e:
                    logging.error(f"Ошибка при обработке {domain}: {e}")
        
        file.write("]")
    logging.info(f"Результаты сохранены в {RESULTS_FILE}.")


if __name__ == "__main__":
    csv_file = "example.csv"
    api_key = "224f03d7fc94f5c109770e0b57e2290f"

    domains = load_domains_from_csv(csv_file)
    if domains:
        process_sites(domains[:100], api_key)
