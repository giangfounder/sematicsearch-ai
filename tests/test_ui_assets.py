import re


def test_ui_build_and_cache_headers(client):
    response = client.get('/')
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-cache'
    html = response.text
    assert 'type="module"' in html
    assert len(html) < 3000
    assets = re.findall(r'(?:src|href)="(/assets/[^\"]+\.(?:js|css))"', html)
    assert len(assets) >= 2
    for path in assets:
        asset = client.get(path)
        assert asset.status_code == 200
        assert asset.headers['cache-control'] == 'public, max-age=31536000, immutable'
        assert asset.headers.get('content-encoding') == 'gzip'
    assert client.get('/assets/nonexistent.js').status_code == 404


def test_auth_responses_are_not_cached(client):
    assert client.get('/v1/auth/config').headers['cache-control'] == 'no-store'
    assert client.get('/v1/auth/me').headers['cache-control'] == 'no-store'
