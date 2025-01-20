from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.chrome.options import Options

# Инициализация драйвера с явными опциями
chrome_options = Options()
chrome_options.add_argument("--no-sandbox")
chrome_options.add_argument("--disable-dev-shm-usage")

# Установка драйвера Chrome
driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)

# Открытие страницы
driver.get("https://www.google.com")

# Закрытие драйвера
driver.quit()
