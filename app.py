import re
from urllib.parse import quote_plus
import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
    'Accept-Language': 'en-IN,en;q=0.9',
}

AMAZON_HEADERS = {
    **HEADERS,
    'User-Agent': (
        'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
    ),
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
}

app = Flask(__name__)

# ✅ EMPTY_RESULT DEFINITION - MUST BE HERE
EMPTY_RESULT = {
    'price': 0,
    'price_display': '',
    'name': '',
    'product_url': '',
    'search_url': '',
}

def _abs_url(base: str, href: str) -> str:
    if not href:
        return ''
    if href.startswith('http'):
        return href
    return f'{base.rstrip("/")}/{href.lstrip("/")}'

def _to_int_price(value) -> int:
    try:
        if not value or value == '0':
            return 0
        cleaned = str(value).replace(' ', '').replace('INR', '').replace(',', '')
        cleaned = cleaned.replace('₹', '').replace('Rs.', '').replace('Rs', '')
        return int(float(cleaned))
    except (TypeError, ValueError):
        return 0

def _decode_myntra_path(path: str) -> str:
    return path.encode('utf-8').decode('unicode_escape')

def flipkart(name: str) -> dict:
    query = quote_plus(name)
    search_url = f'https://www.flipkart.com/search?q={query}'
    result = {**EMPTY_RESULT, 'search_url': search_url}

    try:
        res = requests.get(search_url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(res.text, 'html.parser')

        links = [
            a for a in soup.select('a[href*="/p/"]')
            if a.get_text(strip=True)
        ]
        prices = [el.get_text(strip=True) for el in soup.select('.hZ3P6w')]

        for link, price_text in zip(links, prices):
            title = link.get_text(strip=True)
            if name.lower() not in title.lower():
                continue

            href = link.get('href', '')
            result.update({
                'name': title,
                'price_display': price_text,
                'price': _to_int_price(price_text),
                'product_url': _abs_url('https://www.flipkart.com', href),
            })
            return result

        if links and prices:
            link = links[0]
            href = link.get('href', '')
            result.update({
                'name': link.get_text(strip=True),
                'price_display': prices[0],
                'price': _to_int_price(prices[0]),
                'product_url': _abs_url('https://www.flipkart.com', href),
            })
    except Exception:
        pass

    return result

def _amazon_title(card) -> str:
    parts = [s.get_text(strip=True) for s in card.select('h2 span') if s.get_text(strip=True)]
    if parts:
        return ' '.join(parts)
    title_el = card.select_one('h2 a span, h2 span, h2 a')
    return title_el.get_text(strip=True) if title_el else ''

def _amazon_product_url(card) -> str:
    asin = card.get('data-asin', '').strip()
    if asin:
        return f'https://www.amazon.in/dp/{asin}'

    for link in card.select('a[href]'):
        href = link.get('href', '')
        if '/dp/' in href or '/gp/' in href:
            return _abs_url('https://www.amazon.in', href)

    link_el = card.select_one('h2 a')
    if link_el and link_el.get('href'):
        return _abs_url('https://www.amazon.in', link_el.get('href', ''))
    return ''

def _amazon_card_data(card) -> dict:
    title = _amazon_title(card)
    price_el = card.select_one('.a-price .a-offscreen, .a-price-whole')
    price_text = price_el.get_text(strip=True) if price_el else ''
    return {
        'name': title,
        'price_display': price_text,
        'price': _to_int_price(price_text),
        'product_url': _amazon_product_url(card),
    }

def amazon(name: str) -> dict:
    query = quote_plus(name)
    search_url = f'https://www.amazon.in/s?k={query}'
    result = {**EMPTY_RESULT, 'search_url': search_url}

    try:
        res = requests.get(search_url, headers=AMAZON_HEADERS, timeout=20)
        if res.status_code != 200 or 's-search-result' not in res.text:
            return result

        soup = BeautifulSoup(res.text, 'html.parser')
        cards = soup.select('[data-component-type="s-search-result"]')
        fallback = None
        for card in cards:
            data = _amazon_card_data(card)
            if not data['name'] or data['price'] <= 0:
                continue
            if fallback is None:
                fallback = data
            if name.lower() in data['name'].lower():
                result.update(data)
                return result

        if fallback:
            result.update(fallback)
    except Exception:
        pass

    return result

def myntra(name: str) -> dict:
    query = quote_plus(name)
    search_url = f'https://www.myntra.com/{name.split()[0].lower()}?rawQuery={query}'
    result = {**EMPTY_RESULT, 'search_url': search_url}

    try:
        res = requests.get(search_url, headers=HEADERS, timeout=20)
        text = res.text

        names = re.findall(r'"productName":"([^"]+)"', text)
        prices = re.findall(r'"price":(\d+)', text)
        paths = re.findall(r'"landingPageUrl":"([^"]+)"', text)

        for product_name, price_text, path in zip(names, prices, paths):
            if name.lower() not in product_name.lower():
                continue

            product_path = _decode_myntra_path(path)
            result.update({
                'name': product_name,
                'price_display': f'Rs. {price_text}',
                'price': _to_int_price(price_text),
                'product_url': _abs_url('https://www.myntra.com', product_path),
            })
            return result

        if names and prices and paths:
            product_path = _decode_myntra_path(paths[0])
            result.update({
                'name': names[0],
                'price_display': f'Rs. {prices[0]}',
                'price': _to_int_price(prices[0]),
                'product_url': _abs_url('https://www.myntra.com', product_path),
            })
    except Exception:
        pass

    return result

def _site_payload(prefix: str, data: dict) -> dict:
    return {
        f'{prefix}_price': data['price'],
        f'{prefix}_price_display': data['price_display'],
        f'{prefix}_name': data['name'],
        f'{prefix}_url': data['search_url'],
        f'{prefix}_product_url': data['product_url'],
    }

def search_all(name: str) -> dict:
    flipkart_data = flipkart(name)
    amazon_data = amazon(name)
    myntra_data = myntra(name)

    sites = [
        ('flipkart', flipkart_data),
        ('amazon', amazon_data),
        ('myntra', myntra_data),
    ]

    available = [(label, data) for label, data in sites if data['price'] > 0]
    best_price = min(data['price'] for _, data in available) if available else 0

    best_label = ''
    best_name = ''
    best_url = ''
    best_product_url = ''

    if best_price > 0:
        for label, data in available:
            if data['price'] == best_price:
                best_label = label
                best_name = data['name']
                best_url = data['search_url']
                best_product_url = data['product_url']
                break

    payload = {
        'query': name,
        'best_price': best_price,
        'best_label': best_label,
        'best_name': best_name,
        'best_url': best_url,
        'best_product_url': best_product_url,
        'results': [
            {
                'store': label.capitalize(),
                'name': data['name'],
                'price': data['price'],
                'price_display': data['price_display'] or ('Not found' if data['price'] == 0 else str(data['price'])),
                'search_url': data['search_url'],
                'product_url': data['product_url'],
            }
            for label, data in sites
        ],
    }

    for label, data in sites:
        payload.update(_site_payload(label, data))

    return payload

@app.get('/')
def index():
    return render_template('index.html')

@app.post('/search')
def search():
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    if not name:
        return jsonify({'error': 'Product name is required'}), 400

    try:
        return jsonify(search_all(name))
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)