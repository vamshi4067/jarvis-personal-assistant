"""Bounded report-only page reading, with boilerplate removal and redirect checks."""
from datetime import datetime, timezone
from io import BytesIO
import re
from urllib.parse import urljoin


def readable_page(url):
    import httpx
    from lxml import html
    from openjarvis.security.ssrf import check_ssrf
    current=url;data=b'';kind='';encoding='utf-8'
    with httpx.Client(timeout=25,follow_redirects=False,headers={'User-Agent':'Mozilla/5.0 (compatible; JarvisResearch/1.0)'}) as client:
        for _ in range(6):
            reason=check_ssrf(current)
            if reason:raise ValueError('The source address is not permitted.')
            with client.stream('GET',current) as response:
                if response.status_code in (301,302,303,307,308):
                    location=response.headers.get('location')
                    if not location:raise ValueError('The source redirect has no destination.')
                    current=urljoin(current,location);continue
                response.raise_for_status();kind=response.headers.get('content-type','').lower();encoding=response.encoding or 'utf-8'
                if not any(t in kind for t in ('text/','application/pdf','application/xhtml+xml')):
                    raise ValueError('The source is not a supported document.')
                chunks=[];size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>2_000_000:raise ValueError('The source exceeds the report reading limit.')
                    chunks.append(chunk)
                data=b''.join(chunks);break
        else:raise ValueError('The source redirected too many times.')
    if 'application/pdf' in kind:
        import pdfplumber
        with pdfplumber.open(BytesIO(data)) as pdf:
            text='\n'.join(page.extract_text() or '' for page in pdf.pages[:3])
        method='first 3 PDF pages'
    elif 'html' in kind:
        doc=html.fromstring(data.decode(encoding,errors='replace'))
        for node in doc.xpath('//script|//style|//nav|//header|//footer|//aside|//form|//noscript|//svg'):
            node.drop_tree()
        main=doc.xpath('//main|//article|//*[@role="main"]')
        root=max(main,key=lambda n:len(n.text_content())) if main else doc
        text=root.text_content();method='main article text' if main else 'page text without navigation'
    else:text=data.decode(encoding,errors='replace');method='plain text'
    text=re.sub(r'\s+',' ',text).strip()
    if len(text)<150:raise ValueError('The source did not contain enough readable evidence.')
    return text[:10000],{'url':current,'retrieved':datetime.now(timezone.utc).isoformat(),'method':method,'truncated':len(text)>10000}


class ResearchWeb:
    def __init__(self,search):self.search=search
    def execute(self,**params):
        from openjarvis.core.types import ToolResult
        query=str(params.get('query','')).strip()
        if not re.fullmatch(r'https?://\S+',query):return self.search.execute(**params)
        try:
            text,metadata=readable_page(query)
            return ToolResult(tool_name='web_search',success=True,content=text,metadata=metadata)
        except Exception:
            return ToolResult(tool_name='web_search',success=False,content='The source could not be read within the report limits.')
