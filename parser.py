import feedparser
import requests
from bs4 import BeautifulSoup
import re
import json


class UraParser:
    """Парсер URA.RU через RSS"""
    URL = "https://ura.news/rss"

    def get_news(self):
        feed = feedparser.parse(self.URL)
        news_list = []
        for entry in feed.entries[:10]:
            title = entry.title
            link = entry.link
            description = entry.get('summary', '')
            # Попробуем получить изображение из enclosures
            enclosures = entry.get('enclosures', [])
            image_url = enclosures[0].get('href', '') if enclosures else ''
            # Если нет в enclosures, ищем в description
            if not image_url and description:
                soup = BeautifulSoup(description, 'html.parser')
                img = soup.find('img')
                if img:
                    image_url = img.get('src', '')

            news_list.append({
                "title": title,
                "link": link,
                "description": BeautifulSoup(description, 'html.parser').get_text(strip=True)[:200],
                "image": image_url,
                "source": "URA.RU"
            })
        return news_list


class E1Parser:
    """Парсер E1.RU через HTML (новости загружаются динамически, но ссылки есть в HTML)"""
    URL = "https://www.e1.ru/text/"
    BASE_URL = "https://www.e1.ru"
    NEWS_PATTERN = re.compile(
        r'/text/(gorod|incidents|criminal|realty|longread|auto|sport|health|business|politics|world)/\d{4}/\d{2}/\d{2}/\d+/'
    )

    def get_news(self):
        try:
            response = requests.get(self.URL, headers=self._headers(), timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = []
            seen_links = set()

            # Ищем все ссылки на новости
            for a in soup.find_all('a', href=True):
                href = a.get('href', '')
                if not self.NEWS_PATTERN.search(href):
                    continue
                if '/comments/' in href:
                    continue

                # Нормализуем ссылку
                if not href.startswith('http'):
                    href = self.BASE_URL + href

                if href in seen_links:
                    continue
                seen_links.add(href)

                # Заголовок
                title = a.get('title', '')
                if not title:
                    title = a.get_text(strip=True)
                if not title or len(title) < 10:
                    # Ищем заголовок в дочерних элементах
                    for tag in a.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'span', 'p']):
                        t = tag.get_text(strip=True)
                        if len(t) > 10:
                            title = t
                            break

                if not title or len(title) < 10:
                    continue

                # Изображение
                image_url = ''
                img = a.find('img')
                if img:
                    image_url = img.get('src', '') or img.get('data-src', '')
                if not image_url:
                    # Ищем изображение в родительском контейнере
                    parent = a.parent
                    if parent:
                        img = parent.find('img')
                        if img:
                            image_url = img.get('src', '') or img.get('data-src', '')

                if image_url and not image_url.startswith('http'):
                    image_url = self.BASE_URL + image_url

                # Описание — ищем в родительском контейнере
                description = ''
                parent = a.parent
                if parent:
                    for p in parent.find_all(['p', 'div', 'span']):
                        cls = ' '.join(p.get('class', []))
                        text = p.get_text(strip=True)
                        if text and text != title and len(text) > 20:
                            description = text[:200]
                            break

                news_list.append({
                    "title": title,
                    "link": href,
                    "description": description,
                    "image": image_url,
                    "source": "E1.RU"
                })

                if len(news_list) >= 10:
                    break

            return news_list

        except Exception as e:
            print(f"Error parsing E1.ru: {e}")
            return []

    def _headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
        }


class ItsMyCityParser:
    """Парсер itsmycity.ru"""
    URL = "https://www.itsmycity.ru/"
    BASE_URL = "https://www.itsmycity.ru"

    def get_news(self):
        try:
            response = requests.get(self.URL, headers=self._headers(), timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = []
            items = soup.select('div.card.imc-card')

            for item in items[:10]:
                # Заголовок
                title_el = item.select_one('div.card-title.imc-card-title')
                if not title_el:
                    continue
                title = title_el.get_text(strip=True)
                if not title or len(title) < 5:
                    continue

                # Ссылка — ищем <a> внутри card-body или card-img
                link = ''
                card_body = item.select_one('div.card-body.imc-card-body')
                if card_body:
                    # Ищем ссылку в заголовке или рядом
                    a_tag = card_body.find('a')
                    if a_tag:
                        link = a_tag.get('href', '')
                if not link:
                    # Пробуем найти ссылку в картинке
                    img_link = item.select_one('span.card-img.imc-card-img a')
                    if img_link:
                        link = img_link.get('href', '')
                if not link:
                    # Ищем любую ссылку в item
                    any_a = item.find('a', href=True)
                    if any_a:
                        link = any_a['href']

                if link and not link.startswith('http'):
                    link = self.BASE_URL + link

                # Изображение
                image_url = ''
                img = item.find('img')
                if img:
                    image_url = img.get('data-src', '') or img.get('src', '')
                if image_url and not image_url.startswith('http'):
                    image_url = self.BASE_URL + image_url

                # Описание — <p class="imc-card-text">
                desc_el = item.select_one('p.imc-card-text')
                description = desc_el.get_text(strip=True)[:200] if desc_el else ''

                # Дата
                date_el = item.select_one('div.imc-card-date')
                date_str = date_el.get_text(strip=True) if date_el else ''

                if title and link:
                    news_list.append({
                        "title": title,
                        "link": link,
                        "description": description,
                        "image": image_url,
                        "source": "It's My City",
                        "date": date_str
                    })

            return news_list

        except Exception as e:
            print(f"Error parsing itsmycity.ru: {e}")
            return []

    def _headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
        }


class ObltvParser:
    """Парсер obltv.ru"""
    URL = "https://obltv.ru/news/"
    BASE_URL = "https://obltv.ru"

    def get_news(self):
        try:
            response = requests.get(self.URL, headers=self._headers(), timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = []
            items = soup.select('div.moskvin-item-row')

            for item in items[:10]:
                # Заголовок и ссылка — в a.moskvin-item-title
                title_link = item.select_one('a.moskvin-item-title')
                if not title_link:
                    continue
                title = title_link.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                link = title_link.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link

                # Изображение
                image_url = ''
                img_el = item.select_one('div.moskvin-item-image')
                if img_el:
                    img = img_el.find('img')
                    if img:
                        image_url = img.get('src', '') or img.get('data-src', '')
                    else:
                        # Может быть background-image
                        style = img_el.get('style', '')
                        if 'url(' in style:
                            image_url = style.split('url(')[1].split(')')[0].strip("'\"")
                if image_url and not image_url.startswith('http'):
                    image_url = self.BASE_URL + image_url

                # Описание
                announce_el = item.select_one('div.moskvin-item-announce')
                description = announce_el.get_text(strip=True)[:200] if announce_el else ''

                # Дата
                date_el = item.select_one('div.moskvin-news-date')
                date_str = date_el.get_text(strip=True) if date_el else ''

                if title and link:
                    news_list.append({
                        "title": title,
                        "link": link,
                        "description": description,
                        "image": image_url,
                        "source": "OBLTV.RU",
                        "date": date_str
                    })

            return news_list

        except Exception as e:
            print(f"Error parsing obltv.ru: {e}")
            return []

    def _headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
        }


class JustMediaParser:
    """Парсер justmedia.ru"""
    URL = "https://justmedia.ru/news/"
    BASE_URL = "https://justmedia.ru"

    def get_news(self):
        try:
            response = requests.get(self.URL, headers=self._headers(), timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = []
            items = soup.select('div.news-one')

            for item in items[:10]:
                # Заголовок и ссылка
                title_a = item.select_one('p.news-one__desc a')
                if not title_a:
                    continue
                title = title_a.get_text(strip=True)
                if not title or len(title) < 5:
                    continue
                link = title_a.get('href', '')
                if link and not link.startswith('http'):
                    link = self.BASE_URL + link

                # Изображение
                image_url = ''
                img = item.select_one('img')
                if img:
                    image_url = img.get('src', '')
                if image_url and not image_url.startswith('http'):
                    image_url = self.BASE_URL + image_url

                # Описание
                desc_el = item.select_one('p.news-one__dop')
                description = desc_el.get_text(strip=True)[:200] if desc_el else ''

                # Дата
                date_el = item.select_one('p.news-one__date')
                date_str = date_el.get_text(strip=True) if date_el else ''

                if title and link:
                    news_list.append({
                        "title": title,
                        "link": link,
                        "description": description,
                        "image": image_url,
                        "source": "JustMedia",
                        "date": date_str
                    })

            return news_list

        except Exception as e:
            print(f"Error parsing justmedia.ru: {e}")
            return []

    def _headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
        }


class RU66Parser:
    """Парсер 66.RU через HTML"""
    URL = "https://www.66.ru/news/"
    BASE_URL = "https://www.66.ru"

    def get_news(self):
        try:
            response = requests.get(self.URL, headers=self._headers(), timeout=10)
            response.raise_for_status()
            response.encoding = 'utf-8'
            soup = BeautifulSoup(response.text, 'html.parser')

            news_list = []
            items = soup.select('div.section_item')

            for item in items[:10]:
                # Заголовок и ссылка
                title_tag = item.select_one('a.section_item-body-link')
                if not title_tag:
                    title_tag = item.select_one('h2.section_item-body-title')
                if not title_tag:
                    continue

                link = title_tag.get('href', '')
                if not link.startswith('http'):
                    link = self.BASE_URL + link

                title_el = item.select_one('h2.section_item-body-title')
                title = title_el.get_text(strip=True) if title_el else title_tag.get_text(strip=True)

                if not title or len(title) < 5:
                    continue

                # Изображение
                image_url = ''
                img = item.select_one('img.section_item-picture')
                if img:
                    image_url = img.get('src', '') or img.get('data-src', '')
                if image_url and not image_url.startswith('http'):
                    image_url = self.BASE_URL + image_url

                # Описание
                description = ''
                body = item.select_one('div.section_item-body')
                if body:
                    # Ищем текст описания (div после h2)
                    for div in body.find_all('div', recursive=False):
                        text = div.get_text(strip=True)
                        if text and text != title and len(text) > 20:
                            description = text[:200]
                            break
                    if not description:
                        # Ищем в span или p
                        for tag in body.find_all(['p', 'span']):
                            text = tag.get_text(strip=True)
                            if text and text != title and len(text) > 20:
                                description = text[:200]
                                break

                news_list.append({
                    "title": title,
                    "link": link,
                    "description": description,
                    "image": image_url,
                    "source": "66.RU"
                })

            return news_list

        except Exception as e:
            print(f"Error parsing 66.ru: {e}")
            return []

    def _headers(self):
        return {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.5',
        }


if __name__ == "__main__":
    parsers = [
        ("URA.RU", UraParser()),
        ("E1.RU", E1Parser()),
        ("66.RU", RU66Parser()),
        ("OBLTV.RU", ObltvParser()),
        ("JustMedia", JustMediaParser()),
    ]

    for name, parser in parsers:
        print("\n" + "=" * 60)
        print(f"--- {name} NEWS ---")
        print("=" * 60)
        try:
            news_list = parser.get_news()
            if not news_list:
                print("  (нет новостей)")
            for i, news in enumerate(news_list[:5], 1):
                print(f"\n{i}. {news['title']}")
                print(f"   Link: {news['link']}")
                img = news.get('image', '')
                print(f"   Image: {img[:80] if img else 'N/A'}")
                print(f"   Desc: {news['description'][:100]}")
        except Exception as e:
            print(f"  ERROR: {e}")
