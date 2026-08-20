"""학교 홈페이지(wsu.ac.kr) 크롤링용 HTTP 헬퍼 — 인증서 체인 보정.

문제
    학교 서버가 잎 인증서만 보내고, 그것을 서명한 중간 인증서
    (Sectigo Public Server Authentication CA DV R36)를 함께 보내지 않는다.
    브라우저는 인증서의 AIA 필드를 보고 중간 인증서를 스스로 내려받아 체인을
    잇지만 requests 에는 그 기능이 없어, 검증이
    'unable to get local issuer certificate' 로 실패한다.
    브라우저에서는 멀쩡히 열리는데 코드에서만 막히는 이유가 이것이다.

    실측 이력
      2026-08-04  학교가 인증서 갱신, 중간 인증서 누락 시작
      2026-08-12  학식 크롤 실패 확인 → dining.py 에 verify=False 폴백 추가
      2026-08-20  관리자 문서 크롤도 동일 원인으로 실패 확인

해결
    누락된 중간 인증서(wsu_intermediate.pem)를 certifi 번들 뒤에 붙인 파일을
    만들어 verify 로 넘긴다. 검증을 끄는 것이 아니라 빠진 고리를 채우는 것이라
    중간자 공격에 대한 보호가 그대로 유지된다.
    중간 인증서 유효기간은 2036-03-21 까지다.

    학교가 서버 설정을 바로잡으면 이 번들이 있어도 정상 동작하므로
    되돌릴 필요가 없다.

    쓰는 법
      get()          requests 로 가져올 때
      ssl_context()  urllib.request.urlopen(context=...) 로 가져올 때
      install()      서버 기동 때 한 번 — 이 둘을 안 거치는 코드(직접 requests.get 하는
                     곳, 서드파티 라이브러리 내부 요청)까지 환경변수로 함께 덮는다.
                     app.server.create_app() 에서 부르고 있다.
"""
from __future__ import annotations

import atexit
import os
import tempfile

import certifi
import requests

_INTERMEDIATE = os.path.join(os.path.dirname(__file__), "wsu_intermediate.pem")
_bundle_path: str | None = None

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)


def ca_bundle() -> str:
    """certifi + 학교 중간 인증서를 합친 번들 경로. 최초 1회만 만든다."""
    global _bundle_path
    if _bundle_path and os.path.exists(_bundle_path):
        return _bundle_path

    data = open(certifi.where(), "rb").read()
    if os.path.exists(_INTERMEDIATE):
        data += b"\n" + open(_INTERMEDIATE, "rb").read()
    else:
        print(f"[http_client] 중간 인증서 파일 없음: {_INTERMEDIATE}")

    fd, path = tempfile.mkstemp(prefix="wsu_ca_", suffix=".pem")
    with os.fdopen(fd, "wb") as f:
        f.write(data)
    atexit.register(lambda: os.path.exists(path) and os.remove(path))
    _bundle_path = path
    return path


def ssl_context():
    """urllib.request.urlopen(context=...) 용. requests 가 아닌 경로에서 쓴다."""
    import ssl
    return ssl.create_default_context(cafile=ca_bundle())


def install() -> None:
    """보정 번들을 프로세스 전체의 기본 CA 로 심는다. 서버 기동 때 한 번 부른다.

    get()·ssl_context() 를 거치지 않는 코드까지 한꺼번에 살리기 위한 것이다.
    requests 는 REQUESTS_CA_BUNDLE, urllib·ssl 은 SSL_CERT_FILE 을 기본값으로 읽으므로
    (requests 는 요청마다, ssl 은 create_default_context 마다 다시 읽는다)
    나중에 임포트되는 모듈이나 서드파티 라이브러리의 요청에도 그대로 적용된다.
    학교 서버 말고 다른 사이트 요청은 certifi 번들 부분이 그대로 처리하므로 영향이 없다.

    이미 환경변수가 지정돼 있으면 건드리지 않는다 — 배포 환경이 사내 CA 등을 넘겼을 때
    그쪽이 우선이다. verify=... 를 명시한 호출(get() 포함)도 환경변수보다 우선한다.
    """
    path = ca_bundle()
    for key in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
        os.environ.setdefault(key, path)


def get(url: str, *, timeout: int = 20, headers: dict | None = None,
        allow_insecure_fallback: bool = True, **kw) -> requests.Response:
    """보정된 번들로 GET. 그래도 검증이 실패하면(체인이 또 바뀐 경우) 경고 후 재시도.

    폴백은 공개된 안내 페이지를 읽기만 하는 경로에서만 의미가 있다.
    로그인·개인정보가 오가는 요청에는 allow_insecure_fallback=False 로 호출할 것.
    """
    h = {"User-Agent": USER_AGENT}
    if headers:
        h.update(headers)
    try:
        return requests.get(url, timeout=timeout, headers=h, verify=ca_bundle(), **kw)
    except requests.exceptions.SSLError as e:
        if not allow_insecure_fallback:
            raise
        # 번들로도 안 되면 체인이 또 바뀐 것이다. 원인을 로그로 남기고 한 번 더 시도한다.
        print(f"[http_client] 보정 번들로도 검증 실패 → 검증 없이 재시도: {url} ({e.__class__.__name__})")
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        return requests.get(url, timeout=timeout, headers=h, verify=False, **kw)
