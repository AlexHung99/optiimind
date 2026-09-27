"""Read public HTML pages as bounded, plain-text evidence for local models."""

from html.parser import HTMLParser
import gzip
import http.client
import ipaddress
import re
import socket
from urllib.parse import urljoin, urlsplit, urlunsplit


MAX_DOWNLOAD = 1024 * 1024
MAX_TEXT = 12000
PAGE_CHARS = 1400
MAX_REDIRECTS = 3
URL_PATTERN = re.compile(r'https?://[^\s<>"\'`，。；：！？、（）【】《》]+', re.I)
SKIP_TAGS = {'script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header', 'aside', 'form'}
BLOCK_TAGS = {'p', 'div', 'section', 'article', 'main', 'h1', 'h2', 'h3', 'h4',
              'h5', 'h6', 'li', 'br', 'blockquote', 'pre', 'tr', 'td', 'dt', 'dd'}


class AuthenticationRequired(ValueError):
    """The page requires the user to sign in before its content can be read."""


def extract_urls(text, limit=2):
    """Keep only distinct links, excluding punctuation normally adjacent to prose."""
    result = []
    for match in URL_PATTERN.finditer(text):
        url = match.group().rstrip('.,;:!?)]}。，；：！？）】》')
        if url not in result:
            result.append(url)
        if len(result) >= limit:
            break
    return result


def _public_target(url):
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        raise ValueError('網址長度無效。')
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
        port = parts.port
    except ValueError as error:
        raise ValueError('網址格式無效。') from error
    if parts.scheme.lower() not in ('http', 'https') or not host or parts.username or parts.password:
        raise ValueError('僅支援公開的 HTTP／HTTPS 網址。')
    default_port = 443 if parts.scheme.lower() == 'https' else 80
    if port not in (None, default_port):
        raise ValueError('網址不可使用非標準連接埠。')
    if any(ord(character) < 32 for character in url):
        raise ValueError('網址含無效字元。')
    try:
        addresses = socket.getaddrinfo(host, default_port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError) as error:
        raise ValueError('無法解析網址的主機名稱。') from error
    for _family, _type, _proto, _name, address in addresses:
        if ipaddress.ip_address(address[0]).is_global:
            path = urlunsplit((parts.scheme.lower(), parts.netloc, parts.path or '/', parts.query, ''))
            return path, host, default_port, address[0]
    raise ValueError('僅可讀取公開網頁，不能連線至本機或私人網路。')


def _download(url):
    for _redirect in range(MAX_REDIRECTS + 1):
        current, host, port, address = _public_target(url)
        parts = urlsplit(current)
        connection_type = http.client.HTTPSConnection if parts.scheme == 'https' else http.client.HTTPConnection
        connection = connection_type(host, port, timeout=10)
        # Pin the already-validated public address; TLS still verifies the URL hostname.
        connection._create_connection = lambda _target, timeout, source_address=None: socket.create_connection(
            (address, port), timeout, source_address)
        try:
            target = (parts.path or '/') + (('?' + parts.query) if parts.query else '')
            connection.request('GET', target, headers={
                'User-Agent': 'OptiChat/1.3 (+https://optiimind.com/Tools/optiichat/)',
                'Accept': 'text/html,application/xhtml+xml,text/plain;q=0.8',
                'Accept-Encoding': 'gzip, identity'})
            response = connection.getresponse()
            if response.status in (301, 302, 303, 307, 308):
                location = response.getheader('Location')
                if not location:
                    raise ValueError('網頁轉址缺少目標網址。')
                url = urljoin(current, location)
                continue
            if response.status in (401, 403):
                raise AuthenticationRequired(f'網頁要求登入或授權（HTTP {response.status}）。')
            if response.status != 200:
                raise ValueError(f'網頁回應 HTTP {response.status}。')
            content_type = response.getheader('Content-Type', '').lower()
            if not any(content_type.startswith(kind) for kind in
                       ('text/html', 'application/xhtml+xml', 'text/plain')):
                raise ValueError('此連結不是可讀取的網頁文字。')
            data = response.read(MAX_DOWNLOAD + 1)
            if len(data) > MAX_DOWNLOAD:
                raise ValueError('網頁超過 1 MB 下載上限。')
            encoding = response.getheader('Content-Encoding', '').lower()
            if encoding == 'gzip':
                from io import BytesIO
                with gzip.GzipFile(fileobj=BytesIO(data)) as stream:
                    data = stream.read(MAX_DOWNLOAD + 1)
                if len(data) > MAX_DOWNLOAD:
                    raise ValueError('網頁解壓後超過 1 MB 上限。')
            elif encoding not in ('', 'identity'):
                raise ValueError('網頁使用不支援的壓縮格式。')
            charset = re.search(r'charset\s*=\s*["\']?([\w.-]+)', content_type)
            codec = charset.group(1) if charset else 'utf-8'
            try:
                return current, data.decode(codec, errors='replace'), content_type
            except LookupError as error:
                raise ValueError('網頁使用不支援的文字編碼。') from error
        finally:
            connection.close()
    raise ValueError('網頁轉址次數過多。')


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ''
        self.description = ''
        self._title = False
        self._skip_tag = None
        self._skip_depth = 0
        self._main = 0
        self.all_text = []
        self.main_text = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag in SKIP_TAGS:
            self._skip_tag = tag
            self._skip_depth = 1
            return
        if tag == 'meta' and attrs.get('name', '').lower() == 'description':
            self.description = attrs.get('content', '').strip()[:500]
        if tag == 'title':
            self._title = True
        if tag == 'main' or tag == 'article':
            self._main += 1
        if tag in BLOCK_TAGS:
            self.all_text.append('\n')
            if self._main:
                self.main_text.append('\n')

    def handle_endtag(self, tag):
        if self._skip_tag:
            if tag == self._skip_tag:
                self._skip_depth -= 1
                if not self._skip_depth:
                    self._skip_tag = None
            return
        if tag == 'title':
            self._title = False
        if tag in BLOCK_TAGS:
            self.all_text.append('\n')
            if self._main:
                self.main_text.append('\n')
        if tag in ('main', 'article') and self._main:
            self._main -= 1

    def handle_data(self, data):
        if self._skip_tag:
            return
        if self._title:
            self.title += data
            return
        self.all_text.append(data + ' ')
        if self._main:
            self.main_text.append(data + ' ')


def _clean_text(parts):
    lines = [re.sub(r'\s+', ' ', line).strip() for line in ''.join(parts).splitlines()]
    return '\n'.join(line for line in lines if line)


def format_webpage(final_url, source, content_type, page=1, page_count=1):
    """Extract one bounded portion from HTML or plain text, including provenance."""
    try:
        page = int(page)
    except (TypeError, ValueError) as error:
        raise ValueError('網頁頁碼必須是正整數。') from error
    if page < 1:
        raise ValueError('網頁頁碼必須是正整數。')
    if not isinstance(page_count, int) or not 1 <= page_count <= 3:
        raise ValueError('網頁讀取頁數無效。')
    if content_type.startswith('text/plain'):
        title, description, body = '', '', source.strip()
    else:
        parser = _TextParser()
        parser.feed(source)
        title, description = parser.title.strip(), parser.description
        main = _clean_text(parser.main_text)
        body = main if len(main) >= 100 else _clean_text(parser.all_text)
        login_path = re.search(r'/(?:login|log-in|signin|sign-in|authorize)(?:/|\?|$)',
                               urlsplit(final_url).path, re.I)
        password_form = re.search(r'<input\b[^>]*\btype\s*=\s*["\']?password\b', source, re.I)
        if login_path or (password_form and len(body) < 1500):
            raise AuthenticationRequired('此網頁顯示登入畫面，請先登入再讀取。')
    if not body:
        raise ValueError('網頁沒有可讀取的文字；可能需要 JavaScript 才會顯示內容。')
    clipped = len(body) > MAX_TEXT
    body = body[:MAX_TEXT]
    pages = max(1, (len(body) + PAGE_CHARS - 1) // PAGE_CHARS)
    if page > pages:
        raise ValueError(f'此網頁僅有 {pages} 頁文字。')
    last_page = min(pages, page + page_count - 1)
    chunk = body[(page-1)*PAGE_CHARS:last_page*PAGE_CHARS]
    header = [f'來源：{final_url}']
    if title:
        header.append(f'標題：{title[:180]}')
    if description:
        header.append(f'描述：{description}')
    header.append(f'網頁文字：第 {page}' + (f'–{last_page}' if last_page != page else '')
                  + f'/{pages} 頁' + ('；超過 12,000 字的部分未讀取' if clipped else ''))
    return '\n'.join(header) + '\n' + chunk


def fetch_webpage(url, page=1, page_count=1):
    """Read a public page without browser cookies; raise if sign-in is required."""
    try:
        final_url, source, content_type = _download(url)
    except (OSError, http.client.HTTPException) as error:
        raise ValueError('無法連線至此網頁：' + str(error)) from error
    return format_webpage(final_url, source, content_type, page, page_count)
